// V2 E2E : chiffrement scellé vers la clé publique du serveur (libsodium,
// même primitive que PHP ext-sodium — zéro crypto maison).
// Le contenu chiffré ne quitte le téléphone qu'illisible pour les relais ;
import sodium from 'libsodium-wrappers';

import { canonicalBytes, checksumOf, type MeshBundle } from './mesh-sdk';

export const SEAL_ALG = 'nacl-sealed-box' as const;

/** Chemin de la clé publique E2E du serveur. */
export const MESH_KEY_PATH = '/v1/mesh/key';

let ready: Promise<void> | null = null;

function ensureReady(): Promise<void> {
  ready ??= sodium.ready.then(() => undefined);
  return ready;
}

export interface SealKey {
  algorithm: string;
  public_key: string; // base64
}

/** Récupère la clé publique E2E (503 = chiffrement non configuré côté serveur). */
export async function fetchSealKey(apiUrl: string): Promise<SealKey | null> {
  try {
    const res = await fetch(`${apiUrl}${MESH_KEY_PATH}`);
    if (!res.ok) return null;
    const data = (await res.json()) as SealKey;
    return data.algorithm === SEAL_ALG && data.public_key ? data : null;
  } catch {
    return null;
  }
}

/** Scelle un message texte vers le serveur. Retourne l'enveloppe base64. */
export async function sealMessage(message: string, serverPublicKeyB64: string): Promise<string> {
  await ensureReady();
  // Variante ORIGINAL explicite : le défaut libsodium (URLSAFE sans padding)
  // est incompatible avec base64_decode() de PHP.
  const box = sodium.crypto_box_seal(
    sodium.from_string(message),
    sodium.from_base64(serverPublicKeyB64, sodium.base64_variants.ORIGINAL),
  );
  return sodium.to_base64(box, sodium.base64_variants.ORIGINAL);
}

// V2 signatures nœuds : Ed25519 (libsodium, zéro crypto maison).
// La signature couvre les octets canoniques (canonicalBytes dans mesh-sdk) :
// exactement le `raw` du checksum, moins le champ `signature` lui-même
// (auto-exclusion), AVEC `node_pubkey` (lie le contenu à la clé annoncée).
// Même forme côté relai (mesh_verify.py) et Laravel (MeshSignature.php).

export const SIGN_ALG = 'ed25519' as const;

export interface NodeSigningKey {
  /** Clé publique Ed25519, base64 standard (44 car.) — posée dans `node_pubkey`. */
  publicKeyB64: string;
  /** Clé secrète 64 o. (seed || pubkey), base64 standard — NE JAMAIS transmettre. */
  secretKeyB64: string;
}

/** Génère une paire Ed25519 neuve pour ce nœud. */
export async function generateNodeKeypair(): Promise<NodeSigningKey> {
  await ensureReady();
  const kp = sodium.crypto_sign_keypair();
  return {
    publicKeyB64: sodium.to_base64(kp.publicKey, sodium.base64_variants.ORIGINAL),
    secretKeyB64: sodium.to_base64(kp.privateKey, sodium.base64_variants.ORIGINAL),
  };
}

const SIGN_SK_KEY = 'wash_mesh_node_sign_sk';

/**
 * Clé de signature du nœud, persistée en localStorage (générée au premier
 * appel). Une valeur stockée corrompue est régénérée (nouvelle identité).
 * TOFU non implémenté côté serveur (il stocke `node_pubkey` sans alerter
 * sur changement) : la vérification de continuité de clé reste un futur.
 */
export async function getOrCreateNodeSigningKey(): Promise<NodeSigningKey> {
  await ensureReady();
  const stored = localStorage.getItem(SIGN_SK_KEY);
  if (stored) {
    try {
      const sk = sodium.from_base64(stored, sodium.base64_variants.ORIGINAL);
      const pk = sodium.crypto_sign_ed25519_sk_to_pk(sk);
      return {
        publicKeyB64: sodium.to_base64(pk, sodium.base64_variants.ORIGINAL),
        secretKeyB64: stored,
      };
    } catch {
      // Stockage corrompu → on régénère ci-dessous.
    }
  }
  const kp = await generateNodeKeypair();
  localStorage.setItem(SIGN_SK_KEY, kp.secretKeyB64);
  return kp;
}

/**
 * Signe le bundle EN PLACE : pose `node_pubkey` (dérivée du secret), calcule
 * la signature Ed25519 (base64) sur les octets canoniques, puis recalcule
 * `checksum` (qui couvre aussi la signature, comme le relai). Re-signer un
 * bundle écrase proprement la signature précédente. Retourne le bundle.
 */
export async function signBundle(bundle: MeshBundle, secretKeyB64: string): Promise<MeshBundle> {
  await ensureReady();
  const sk = sodium.from_base64(secretKeyB64, sodium.base64_variants.ORIGINAL);
  const pk = sodium.crypto_sign_ed25519_sk_to_pk(sk);
  bundle.node_pubkey = sodium.to_base64(pk, sodium.base64_variants.ORIGINAL);
  delete bundle.signature;
  const sig = sodium.crypto_sign_detached(canonicalBytes(bundle), sk);
  bundle.signature = sodium.to_base64(sig, sodium.base64_variants.ORIGINAL);
  bundle.checksum = await checksumOf(bundle);
  return bundle;
}

/**
 * Vérifie la signature Ed25519 d'un bundle. `publicKeyB64` explicite
 * prioritaire, sinon `bundle.node_pubkey`. Ne jette jamais : false =
 * absente / invalide / bundle altéré (échec fermé).
 */
export async function verifyBundle(bundle: MeshBundle, publicKeyB64?: string): Promise<boolean> {
  try {
    await ensureReady();
    const keyB64 = publicKeyB64 ?? bundle.node_pubkey;
    if (!keyB64 || !bundle.signature) return false;
    const pk = sodium.from_base64(keyB64, sodium.base64_variants.ORIGINAL);
    const sig = sodium.from_base64(bundle.signature, sodium.base64_variants.ORIGINAL);
    return sodium.crypto_sign_verify_detached(sig, canonicalBytes(bundle), pk);
  } catch {
    return false;
  }
}
