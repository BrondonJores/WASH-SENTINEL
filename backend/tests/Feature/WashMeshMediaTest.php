<?php

namespace Tests\Feature;

use App\Models\MeshBundle;
use App\Models\Report;
use App\Models\School;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Storage;
use Illuminate\Support\Str;
use Tests\TestCase;

class WashMeshMediaTest extends TestCase
{
    use RefreshDatabase;

    private function manifestPayload(School $school, string $manifestId, string $b64, array $over = []): array
    {
        return array_merge([
            'bundle_id' => $manifestId,
            'origin_node_id' => 'node-A',
            'school_id' => $school->id,
            'channel' => 'photo',
            'message' => 'Tuyau percé, photo à suivre.',
            'hops' => ['node-A'],
            'expires_at' => now()->addDays(7)->toIso8601String(),
            'fragment_total' => 2,
            'media_mime' => 'image/jpeg',
            'media_size' => strlen(base64_decode($b64)),
            'media_sha256' => hash('sha256', $b64),
        ], $over);
    }

    private function fragmentPayload(School $school, string $manifestId, int $offset, string $chunk): array
    {
        return [
            'bundle_id' => (string) Str::uuid(),
            'bundle_group' => $manifestId,
            'origin_node_id' => 'node-A',
            'school_id' => $school->id,
            'channel' => 'photo',
            'hops' => ['node-A'],
            'expires_at' => now()->addDays(7)->toIso8601String(),
            'fragment_offset' => $offset,
            'fragment_total' => 2,
            'chunk' => $chunk,
        ];
    }

    public function test_manifest_creates_incident_then_fragments_attach_photo(): void
    {
        Storage::fake('public');
        $school = School::create(['name' => 'EP Yokadouma', 'code' => 'CE042', 'district' => 'Est']);
        $b64 = base64_encode(random_bytes(1000));
        $manifestId = (string) Str::uuid();
        $half = intdiv(strlen($b64), 2);

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->manifestPayload($school, $manifestId, $b64)]])
            ->assertCreated()->assertJsonPath('summary.accepted', 1);

        $report = Report::where('source', 'mesh')->first();
        $this->assertNotNull($report);
        $this->assertNull($report->photo_path); // texte live, média différé

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [
            $this->fragmentPayload($school, $manifestId, 1, substr($b64, $half)),
            $this->fragmentPayload($school, $manifestId, 0, substr($b64, 0, $half)),
        ]])->assertCreated()->assertJsonPath('summary.fragments', 2);

        $report->refresh();
        $this->assertNotNull($report->photo_path);
        Storage::disk('public')->assertExists($report->photo_path);
        $this->assertEquals(2, MeshBundle::where('bundle_group', $manifestId)->where('status', 'delivered')->count());
    }

    public function test_fragments_before_manifest_still_assemble(): void
    {
        Storage::fake('public');
        $school = School::create(['name' => 'EP Test', 'code' => 'CE1', 'district' => 'Est']);
        $b64 = base64_encode(random_bytes(500));
        $manifestId = (string) Str::uuid();
        $half = intdiv(strlen($b64), 2);

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [
            $this->fragmentPayload($school, $manifestId, 0, substr($b64, 0, $half)),
            $this->fragmentPayload($school, $manifestId, 1, substr($b64, $half)),
        ]])->assertCreated();

        $this->assertNull(Report::where('source', 'mesh')->first());

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->manifestPayload($school, $manifestId, $b64)]])
            ->assertCreated();

        $this->assertNotNull(Report::where('source', 'mesh')->first()->photo_path);
    }

    public function test_incomplete_group_does_not_attach(): void
    {
        Storage::fake('public');
        $school = School::create(['name' => 'EP Test', 'code' => 'CE1', 'district' => 'Est']);
        $b64 = base64_encode(random_bytes(500));
        $manifestId = (string) Str::uuid();

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->manifestPayload($school, $manifestId, $b64)]])
            ->assertCreated();
        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [
            $this->fragmentPayload($school, $manifestId, 0, substr($b64, 0, 100)),
        ]])->assertCreated();

        $this->assertNull(Report::where('source', 'mesh')->first()->photo_path);
        $this->assertEquals(1, MeshBundle::where('bundle_group', $manifestId)->where('status', 'pending')->count());
    }

    public function test_sealed_media_is_decrypted_before_attach(): void
    {
        Storage::fake('public');
        $school = School::create(['name' => 'EP Test', 'code' => 'CE1', 'district' => 'Est']);
        $keypair = sodium_crypto_box_keypair();
        config(['services.mesh.seal_secret' => base64_encode(sodium_crypto_box_secretkey($keypair))]);
        $plainB64 = base64_encode(random_bytes(500));
        $sealedB64 = base64_encode(sodium_crypto_box_seal($plainB64, sodium_crypto_box_publickey($keypair)));
        $manifestId = (string) Str::uuid();
        $half = intdiv(strlen($sealedB64), 2);

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->manifestPayload($school, $manifestId, $sealedB64, [
            'media_sealed_alg' => 'nacl-sealed-box',
            'media_sha256' => hash('sha256', $plainB64),
        ])]])->assertCreated();

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [
            $this->fragmentPayload($school, $manifestId, 0, substr($sealedB64, 0, $half)),
            $this->fragmentPayload($school, $manifestId, 1, substr($sealedB64, $half)),
        ]])->assertCreated();

        $report = Report::where('source', 'mesh')->first();
        $this->assertNotNull($report->photo_path);
        $this->assertEquals(base64_decode($plainB64), Storage::disk('public')->get($report->photo_path));
    }

    public function test_hash_mismatch_blocks_attach(): void
    {
        Storage::fake('public');
        $school = School::create(['name' => 'EP Test', 'code' => 'CE1', 'district' => 'Est']);
        $b64 = base64_encode(random_bytes(500));
        $manifestId = (string) Str::uuid();
        $half = intdiv(strlen($b64), 2);

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->manifestPayload($school, $manifestId, $b64, [
            'media_sha256' => hash('sha256', 'autre-chose'),
        ])]])->assertCreated();
        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [
            $this->fragmentPayload($school, $manifestId, 0, substr($b64, 0, $half)),
            $this->fragmentPayload($school, $manifestId, 1, substr($b64, $half)),
        ]])->assertCreated();

        $this->assertNull(Report::where('source', 'mesh')->first()->photo_path);
    }

    public function test_manifest_without_message_is_rejected(): void
    {
        $school = School::create(['name' => 'EP Test', 'code' => 'CE1', 'district' => 'Est']);

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->manifestPayload($school, (string) Str::uuid(), base64_encode('x'), [
            'message' => null,
        ])]])
            ->assertCreated()
            ->assertJsonPath('summary.rejected', 1);
    }
}
