<?php

namespace Tests\Feature;

use App\Models\MeshNodeKey;
use App\Models\School;
use App\Services\MeshSignature;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Str;
use Tests\TestCase;

class MeshNodeKeyTest extends TestCase
{
    use RefreshDatabase;

    private function bundlePayload(School $school, array $over = []): array
    {
        return array_merge([
            'bundle_id' => (string) Str::uuid(),
            'origin_node_id' => 'node-A-yokadouma',
            'school_id' => $school->id,
            'message' => 'Pompe brisée depuis ce matin, 400 élèves sans eau.',
            'hops' => ['node-A-yokadouma', 'node-B-taximoto', 'node-C-bertoua'],
            'max_hops' => 10,
            'expires_at' => now()->addDays(7)->toIso8601String(),
        ], $over);
    }

    private function signedPayload(School $school, string $secret, array $over = []): array
    {
        $signed = MeshSignature::signBundle($this->bundlePayload($school, $over), $secret);
        $this->assertNotNull($signed);
        $signed['received_via_node_id'] = 'node-C-bertoua';

        return $signed;
    }

    public function test_first_deposit_memorizes_key(): void
    {
        $school = School::create(['name' => 'EP Yokadouma', 'code' => 'CM-EST-42', 'district' => 'Boumba-et-Ngoko']);
        $pair = MeshSignature::generateKeypair();

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->signedPayload($school, $pair['secret'])]])
            ->assertCreated()
            ->assertJsonPath('summary.accepted', 1)
            ->assertJsonPath('summary.key_changed', 0);

        $this->assertDatabaseHas('mesh_node_keys', [
            'origin_node_id' => 'node-A-yokadouma',
            'node_pubkey' => $pair['public'],
        ]);
        $this->assertNotNull(MeshNodeKey::firstWhere('origin_node_id', 'node-A-yokadouma')->first_seen_at);
        $this->assertNull(MeshNodeKey::firstWhere('origin_node_id', 'node-A-yokadouma')->last_changed_at);
    }

    public function test_same_key_accepted_without_alert_counter(): void
    {
        $school = School::create(['name' => 'EP Yokadouma', 'code' => 'CM-EST-42', 'district' => 'Boumba-et-Ngoko']);
        $pair = MeshSignature::generateKeypair();

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->signedPayload($school, $pair['secret'])]])
            ->assertCreated();
        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->signedPayload($school, $pair['secret'])]])
            ->assertCreated()
            ->assertJsonPath('summary.accepted', 1)
            ->assertJsonPath('summary.key_changed', 0);

        $this->assertEquals(1, MeshNodeKey::where('origin_node_id', 'node-A-yokadouma')->count());
        $this->assertNull(MeshNodeKey::firstWhere('origin_node_id', 'node-A-yokadouma')->last_changed_at);
    }

    public function test_changed_key_accepted_with_alert_and_db_updated(): void
    {
        $school = School::create(['name' => 'EP Yokadouma', 'code' => 'CM-EST-42', 'district' => 'Boumba-et-Ngoko']);
        $pairA = MeshSignature::generateKeypair();
        $pairB = MeshSignature::generateKeypair();

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->signedPayload($school, $pairA['secret'])]])
            ->assertCreated();

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->signedPayload($school, $pairB['secret'])]])
            ->assertCreated()
            ->assertJsonPath('summary.accepted', 1)
            ->assertJsonPath('summary.key_changed', 1);

        $row = MeshNodeKey::firstWhere('origin_node_id', 'node-A-yokadouma');
        $this->assertEquals($pairB['public'], $row->node_pubkey);
        $this->assertNotNull($row->last_changed_at);
    }

    public function test_unsigned_bundle_creates_no_row(): void
    {
        $school = School::create(['name' => 'EP Yokadouma', 'code' => 'CM-EST-42', 'district' => 'Boumba-et-Ngoko']);

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->bundlePayload($school)]])
            ->assertCreated()
            ->assertJsonPath('summary.accepted', 1);

        $this->assertEquals(0, MeshNodeKey::count());
    }
}
