<?php

namespace Tests\Feature;

use App\Services\MeshSignature;
use Tests\TestCase;

/**
 * Signatures Ed25519 des bundles mesh (V2 « signatures nœuds »).
 * Test pur du service (aucune BDD) + vecteur doré partagé avec Python
 * (test_sig_verify.py) et TS (smoke /tmp) : seed
 * sha256('wash-sentinel-mesh-sig-golden-v1'), généré par ext-sodium.
 */
class MeshSignatureTest extends TestCase
{
    private const GOLDEN_SECRET_B64 = 'geBvTaFaB8DESUEbfrm3gnvT0xTHJTs4tRkcseXtj66Gd326hcVHGLNtFcmNQzNBknRX0AH+qos2OGBzeyMwKQ==';

    private const GOLDEN_PUBLIC_B64 = 'hnd9uoXFRxizbRXJjUMzQZJ0V9AB/qqLNjhgc3sjMCk=';

    private const GOLDEN_SIG_B64 = 'f6DrYLlnkZbx4+YFRx8UKeXuql2DXjfrwkO/jPx7e8+fAUD6O3agxVljp5NTfB4ypbxSUycmh6t4V6X7sCB2BQ==';

    private const GOLDEN_CANON = '{"bundle_id":"3fa85f64-5717-4562-b3fc-2c963f66afa6","channel":"text",'
        .'"created_at":"2026-01-15T10:00:00.000Z","destination":"dtn://wash-sentinel/ingest",'
        .'"expires_at":"2026-01-22T10:00:00.000Z","lifetime_seconds":604800,"max_hops":10,'
        .'"message":"Pompe brisée, 400 élèves sans eau potable",'
        .'"node_pubkey":"hnd9uoXFRxizbRXJjUMzQZJ0V9AB/qqLNjhgc3sjMCk=",'
        .'"origin_node_id":"node-A-yokadouma","priority":"high","school_code":"CM-EST-42",'
        .'"school_id":42,"v":1}';

    /** @return array<string, mixed> */
    private function goldenBundle(): array
    {
        return [
            'v' => 1,
            'bundle_id' => '3fa85f64-5717-4562-b3fc-2c963f66afa6',
            'origin_node_id' => 'node-A-yokadouma',
            'school_id' => 42,
            'school_code' => 'CM-EST-42',
            'channel' => 'text',
            'message' => 'Pompe brisée, 400 élèves sans eau potable',
            'created_at' => '2026-01-15T10:00:00.000Z',
            'expires_at' => '2026-01-22T10:00:00.000Z',
            'max_hops' => 10,
            'hops' => ['node-A-yokadouma', 'node-B-taximoto'],
            'destination' => 'dtn://wash-sentinel/ingest',
            'lifetime_seconds' => 604800,
            'previous_node' => 'node-A-yokadouma',
            'copies_remaining' => 4,
            'priority' => 'high',
            'node_pubkey' => self::GOLDEN_PUBLIC_B64,
            'signature' => self::GOLDEN_SIG_B64,
        ];
    }

    public function test_golden_canonical_matches_spec(): void
    {
        $this->assertSame(self::GOLDEN_CANON, MeshSignature::canonicalString($this->goldenBundle()));
        $this->assertSame(self::GOLDEN_CANON, MeshSignature::canonicalBytes($this->goldenBundle()));
        // Slashs et accents bruts (ni \/ ni \uXXXX), exclusions appliquées.
        $this->assertStringContainsString('dtn://wash-sentinel/ingest', self::GOLDEN_CANON);
        $this->assertStringContainsString('brisée', self::GOLDEN_CANON);
        $this->assertStringNotContainsString('"hops":', self::GOLDEN_CANON);
        $this->assertStringNotContainsString('"signature":', self::GOLDEN_CANON);
    }

    public function test_golden_signature_layout(): void
    {
        $this->assertSame(64, strlen((string) base64_decode(self::GOLDEN_SIG_B64, true)));
        $this->assertSame(32, strlen((string) base64_decode(self::GOLDEN_PUBLIC_B64, true)));
        $this->assertSame(88, strlen(self::GOLDEN_SIG_B64));
        $this->assertSame(44, strlen(self::GOLDEN_PUBLIC_B64));
    }

    public function test_golden_signature_verifies(): void
    {
        $this->assertTrue(MeshSignature::verify($this->goldenBundle()));
        $this->assertTrue(MeshSignature::verify($this->goldenBundle(), self::GOLDEN_PUBLIC_B64));
    }

    public function test_sign_is_deterministic_and_matches_golden(): void
    {
        $bundle = $this->goldenBundle();
        unset($bundle['signature']);
        $this->assertSame(self::GOLDEN_SIG_B64, MeshSignature::sign($bundle, self::GOLDEN_SECRET_B64));
    }

    public function test_sign_verify_roundtrip(): void
    {
        $keys = MeshSignature::generateKeypair();
        $this->assertSame(44, strlen($keys['public']));
        $this->assertSame(88, strlen($keys['secret']));

        $signed = MeshSignature::signBundle([
            'v' => 1, 'bundle_id' => 'b1', 'origin_node_id' => 'node-X', 'school_id' => 7,
            'message' => 'hello', 'created_at' => '2026-01-15T10:00:00.000Z',
            'expires_at' => '2026-01-22T10:00:00.000Z', 'hops' => ['node-X'],
        ], $keys['secret']);

        $this->assertNotNull($signed);
        $this->assertSame($keys['public'], $signed['node_pubkey']);
        $this->assertTrue(MeshSignature::verify($signed));
    }

    public function test_tampered_content_fails(): void
    {
        foreach (['message' => 'Pompe réparée, tout va bien', 'school_id' => 43, 'priority' => 'normal'] as $key => $value) {
            $tampered = $this->goldenBundle();
            $tampered[$key] = $value;
            $this->assertFalse(MeshSignature::verify($tampered), "champ $key");
        }
        // Couper-coller : signature valide sous une autre clé.
        $other = MeshSignature::generateKeypair();
        $cutpaste = $this->goldenBundle();
        $cutpaste['node_pubkey'] = $other['public'];
        $this->assertFalse(MeshSignature::verify($cutpaste));
    }

    public function test_forward_mutations_preserve_signature(): void
    {
        $relayed = $this->goldenBundle();
        $relayed['hops'] = ['node-A-yokadouma', 'node-B-taximoto', 'node-C-bertoua'];
        $relayed['previous_node'] = 'node-B-taximoto';
        $relayed['copies_remaining'] = 1;
        $relayed['checksum'] = 'recalculé-par-le-relai';
        $this->assertTrue(MeshSignature::verify($relayed));
    }

    public function test_wrong_pubkey_fails(): void
    {
        $other = MeshSignature::generateKeypair();
        $this->assertFalse(MeshSignature::verify($this->goldenBundle(), $other['public']));
    }

    public function test_malformed_inputs_fail_closed(): void
    {
        $this->assertFalse(MeshSignature::verify([]));
        $noSig = $this->goldenBundle();
        unset($noSig['signature']);
        $this->assertFalse(MeshSignature::verify($noSig));
        $noKey = $this->goldenBundle();
        unset($noKey['node_pubkey']);
        $this->assertFalse(MeshSignature::verify($noKey));
        $badB64 = $this->goldenBundle();
        $badB64['signature'] = '!!!pas-du-base64!!!';
        $this->assertFalse(MeshSignature::verify($badB64));
        $badLen = $this->goldenBundle();
        $badLen['signature'] = base64_encode('court');
        $this->assertFalse(MeshSignature::verify($badLen));
        $nonString = $this->goldenBundle();
        $nonString['signature'] = 12345;
        $this->assertFalse(MeshSignature::verify($nonString));
        $this->assertNull(MeshSignature::sign($this->goldenBundle(), 'pas-une-clé'));
        $this->assertNull(MeshSignature::sign($this->goldenBundle(), base64_encode('court')));
        $this->assertNull(MeshSignature::signBundle($this->goldenBundle(), 'pas-une-clé'));
    }

    public function test_null_values_are_dropped_like_ts_undefined(): void
    {
        $a = $this->goldenBundle();
        unset($a['school_code']);
        $b = $this->goldenBundle();
        $b['school_code'] = null;
        $this->assertSame(MeshSignature::canonicalString($a), MeshSignature::canonicalString($b));
    }
}
