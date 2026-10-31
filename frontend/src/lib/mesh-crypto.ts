// V2 E2E : chiffrement scellé vers la clé publique du serveur (libsodium,
// même primitive que PHP ext-sodium — zéro crypto maison).
// Le contenu chiffré ne quitte le téléphone qu'illisible pour les relais ;
import sodium from 'libsodium-wrappers';

export const SEAL_ALG = 'nacl-sealed-box' as const;

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
    const res = await fetch(`${apiUrl}/v1/mesh/key`);
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
