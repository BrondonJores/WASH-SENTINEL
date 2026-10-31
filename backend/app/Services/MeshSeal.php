<?php

namespace App\Services;

/**
 * E2E mesh (libsodium sealed boxes, anonymes — pas de PKI nœuds).
 * Utilisé par l'ingestion (messages) et l'assembleur médias (fragments).
 */
class MeshSeal
{
    public const ALG = 'nacl-sealed-box';

    public static function publicKeyB64(): ?string
    {
        $secret = self::secretKey();
        if ($secret === null) {
            return null;
        }

        return base64_encode(sodium_crypto_box_publickey_from_secretkey($secret));
    }

    /** Ouvre une enveloppe base64. null = algo/secret/box invalide. */
    public static function open(string $sealedB64, ?string $alg): ?string
    {
        if ($alg !== self::ALG) {
            return null;
        }
        $secret = self::secretKey();
        if ($secret === null) {
            return null;
        }
        $box = base64_decode($sealedB64, true);
        if ($box === false) {
            return null;
        }
        try {
            $keypair = $secret.sodium_crypto_box_publickey_from_secretkey($secret);
            $open = sodium_crypto_box_seal_open($box, $keypair);

            return $open === false ? null : $open;
        } catch (\Throwable) {
            return null;
        }
    }

    private static function secretKey(): ?string
    {
        $secret = base64_decode((string) config('services.mesh.seal_secret'), true);

        return $secret !== false && strlen($secret) === SODIUM_CRYPTO_BOX_SECRETKEYBYTES ? $secret : null;
    }
}
