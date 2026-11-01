<?php

namespace App\Services;

/**
 * Signatures Ed25519 des bundles mesh (V2 « signatures nœuds »).
 *
 * Le checksum SHA-256 détecte la corruption, pas la malice : n'importe quel
 * relai peut réécrire un bundle et recalculer son checksum. La signature
 * Ed25519 prouve que le bundle vient du détenteur de la clé du nœud origine
 * et que son contenu immuable n'a pas été altéré en route.
 *
 * ————————————————————————————————————————————————————————————————
 * FORMAT (référence pour le portage Kotlin — à suivre à l'octet près)
 * ————————————————————————————————————————————————————————————————
 * 1. Champs transportés (tous optionnels, additifs) :
 *    - `signature`   : signature Ed25519, base64 STANDARD avec padding
 *                      (RFC 4648 §4, alphabet +/ et = final) → 88 caractères.
 *    - `node_pubkey` : clé publique Ed25519 du nœud origine, base64
 *                      standard → 44 caractères. Auto-annoncée, SANS
 *                      mémorisation à ce jour : aucune table TOFU, aucune
 *                      alerte en cas de changement de clé (chantier futur).
 *                      Vérification cryptographique seule, audit only.
 * 2. Octets signés = forme canonique du bundle :
 *    - objet JSON avec EXACTEMENT les clés du bundle reçu, SAUF les 5
 *      champs exclus : checksum, hops, previous_node, copies_remaining,
 *      signature. `node_pubkey` est INCLUSE (la signature lie le contenu
 *      à la clé annoncée ; hops/copies/previous_node restent mutables
 *      pour que les relais puissent router sans invalider la signature).
 *    - clés avec valeur nulle (null) ou absentes : OMUSES (le SDK TS
 *      n'émet jamais null, seulement des clés absentes).
 *    - clés triées par ordre lexicographique d'octets (toutes les clés
 *      sont ASCII, donc identique en UTF-8 / UTF-16 / code points).
 *    - sérialisation COMPACTE : séparateurs `,` et `:` sans aucune espace,
 *      EXACTEMENT comme `JSON.stringify(o, clesTriees)` de JavaScript.
 *    - texte brut UTF-8 : les accents NE SONT PAS échappés (pas de \u00e9),
 *      les slashs NE SONT PAS échappés (pas de `\/` — `dtn://…` reste tel
 *      quel), les fins de ligne U+2028/U+2029 ne sont pas échappées.
 *      Seuls `"`, `\` et les contrôles C0 sont échappés (forme courte
 *      \n \t etc. comme org.json / kotlinx.serialization par défaut).
 *    - encodage final : UTF-8 (chaîne → bytes sans BOM).
 * 3. Algorithme : Ed25519 pur (RFC 8032), variante libsodium
 *    `crypto_sign_detached` : signature détachée de 64 octets sur les
 *    octets canoniques, PAS de pré-hachage. Clé secrète 64 octets au
 *    format libsodium (seed 32 o. || pubkey 32 o.).
 * 4. Ordre des opérations côté émetteur : poser `node_pubkey`, effacer
 *    toute `signature` précédente, signer, poser `signature`, PUIS
 *    (re)calculer `checksum` — le checksum couvre aussi la signature
 *    (même ensemble de champs que le relai), il est donc calculé après.
 * 5. Côté vérifieur : reconstruire la forme canonique depuis le JSON
 *    REÇU (chaînes d'origine intactes, en particulier les dates ISO —
 *    ne JAMAIS re-sérialiser un objet date parsé, `…Z` ≠ `…+00:00`).
 *    Retourner faux (jamais d'exception) sur tout bundle malformé.
 *
 * Exemple canonique (avec node_pubkey 44 car. fictive AAA…) :
 * {"bundle_id":"…","channel":"text","created_at":"2026-01-15T10:00:00.000Z",
 * "destination":"dtn://wash-sentinel/ingest","expires_at":"…",
 * "max_hops":10,"media_sha256":null…} — NON : les nulls sont omis, les
 * dates gardent leur forme d'origine, une seule ligne, pas d'espaces.
 *
 * Implémentations sœurs (même vecteur de test doré partagé) :
 * TS `mesh/sdk/mesh-sdk.ts#canonicalBytes` + `frontend/src/lib/mesh-crypto.ts`,
 * Python `mesh/server/mesh_verify.py`.
 */
class MeshSignature
{
    public const ALG = 'ed25519';

    /**
     * LOT 7 — noms des champs signature (CONTRAT avec les implémentations
     * sœurs TS/Python + portage Kotlin : ne jamais renommer, voir l'en-tête).
     */
    public const FIELD_SIGNATURE = 'signature';

    public const FIELD_NODE_PUBKEY = 'node_pubkey';

    /** Champs exclus des octets signés (mutables de routage + témoins). */
    public const SIGN_EXCLUDED = ['checksum', 'hops', 'previous_node', 'copies_remaining', self::FIELD_SIGNATURE];

    /**
     * Forme canonique signée. null si le bundle n'est pas sérialisable
     * (UTF-8 invalide). Voir l'en-tête de classe pour la spécification.
     */
    public static function canonicalString(array $bundle): ?string
    {
        $payload = [];
        foreach ($bundle as $key => $value) {
            if (in_array($key, self::SIGN_EXCLUDED, true) || $value === null) {
                continue;
            }
            $payload[$key] = $value;
        }
        ksort($payload, SORT_STRING);
        // UNESCAPED_SLASHES + UNESCAPED_UNICODE + UNESCAPED_LINE_TERMINATORS :
        // sans eux, PHP produirait `\/`, \u00e9, \u2028 et la signature
        // calculée en TS/Python ne vérifierait pas. Séparateurs compacts
        // par défaut (comme JSON.stringify).
        $raw = json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_LINE_TERMINATORS);

        return $raw === false ? null : $raw;
    }

    /** Octets UTF-8 de la forme canonique — l'entrée exacte d'Ed25519. */
    public static function canonicalBytes(array $bundle): ?string
    {
        return self::canonicalString($bundle);
    }

    /** Génère une paire Ed25519 neuve. Clés en base64 standard. */
    public static function generateKeypair(): array
    {
        $keypair = sodium_crypto_sign_keypair();

        return [
            'public' => base64_encode(sodium_crypto_sign_publickey($keypair)),
            'secret' => base64_encode(sodium_crypto_sign_secretkey($keypair)),
        ];
    }

    /**
     * Signe les octets canoniques du bundle. Retourne la signature base64,
     * ou null si la clé est invalide / le bundle non sérialisable.
     * Ne modifie pas le bundle (voir signBundle pour la variante complète).
     */
    public static function sign(array $bundle, string $secretKeyB64): ?string
    {
        $secret = base64_decode($secretKeyB64, true);
        if ($secret === false || strlen($secret) !== SODIUM_CRYPTO_SIGN_SECRETKEYBYTES) {
            return null;
        }
        $message = self::canonicalBytes($bundle);
        if ($message === null) {
            return null;
        }
        try {
            return base64_encode(sodium_crypto_sign_detached($message, $secret));
        } catch (\Throwable) {
            return null;
        }
    }

    /**
     * Variante complète : pose `node_pubkey` (dérivée du secret), signe et
     * pose `signature`. Retourne le nouveau bundle, ou null si impossible.
     * Le `checksum` n'est PAS recalculé ici (le serveur ne le vérifie pas ;
     * côté TS, signBundle le recalcule pour le relai).
     */
    public static function signBundle(array $bundle, string $secretKeyB64): ?array
    {
        $secret = base64_decode($secretKeyB64, true);
        if ($secret === false || strlen($secret) !== SODIUM_CRYPTO_SIGN_SECRETKEYBYTES) {
            return null;
        }
        $bundle[self::FIELD_NODE_PUBKEY] = base64_encode(sodium_crypto_sign_publickey_from_secretkey($secret));
        unset($bundle[self::FIELD_SIGNATURE]);
        $signature = self::sign($bundle, $secretKeyB64);
        if ($signature === null) {
            return null;
        }
        $bundle[self::FIELD_SIGNATURE] = $signature;

        return $bundle;
    }

    /**
     * Vérifie la signature Ed25519 d'un bundle. Clé explicite prioritaire,
     * sinon `node_pubkey` du bundle. Ne jette jamais : false = absente,
     * invalide, malformée ou bundle altéré (échec fermé).
     */
    public static function verify(array $bundle, ?string $publicKeyB64 = null): bool
    {
        try {
            $keyB64 = $publicKeyB64 ?? ($bundle[self::FIELD_NODE_PUBKEY] ?? null);
            $sigB64 = $bundle[self::FIELD_SIGNATURE] ?? null;
            if (! is_string($keyB64) || $keyB64 === '' || ! is_string($sigB64) || $sigB64 === '') {
                return false;
            }
            $public = base64_decode($keyB64, true);
            $signature = base64_decode($sigB64, true);
            if ($public === false || strlen($public) !== SODIUM_CRYPTO_SIGN_PUBLICKEYBYTES
                || $signature === false || strlen($signature) !== SODIUM_CRYPTO_SIGN_BYTES) {
                return false;
            }
            $message = self::canonicalBytes($bundle);
            if ($message === null) {
                return false;
            }

            return sodium_crypto_sign_verify_detached($signature, $message, $public);
        } catch (\Throwable) {
            return false;
        }
    }
}
