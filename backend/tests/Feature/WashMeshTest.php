<?php

namespace Tests\Feature;

use App\Models\MeshBundle;
use App\Models\Report;
use App\Models\School;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Str;
use Tests\TestCase;

class WashMeshTest extends TestCase
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
            'received_via_node_id' => 'node-C-bertoua',
        ], $over);
    }

    public function test_mesh_batch_creates_incident_via_triage(): void
    {
        $school = School::create(['name' => 'EP Yokadouma', 'code' => 'CM-EST-42', 'district' => 'Boumba-et-Ngoko']);

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->bundlePayload($school)]])
            ->assertCreated()
            ->assertJsonPath('summary.accepted', 1)
            ->assertJsonPath('incidents.0.hop_count', 2);

        $this->assertDatabaseHas('mesh_bundles', ['status' => 'delivered', 'hop_count' => 2]);
        $this->assertDatabaseHas('reports', ['source' => 'mesh', 'school_id' => $school->id]);
        $this->assertEquals(1, Report::where('source', 'mesh')->count());
    }

    public function test_duplicate_bundle_id_is_ignored(): void
    {
        $school = School::create(['name' => 'EP Yokadouma', 'code' => 'CM-EST-42', 'district' => 'Boumba-et-Ngoko']);
        $payload = $this->bundlePayload($school);

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$payload]])->assertCreated();
        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$payload]])
            ->assertCreated()
            ->assertJsonPath('summary.duplicates', 1);

        $this->assertEquals(1, MeshBundle::count());
        $this->assertEquals(1, Report::where('source', 'mesh')->count());
    }

    public function test_expired_bundle_is_not_triaged(): void
    {
        $school = School::create(['name' => 'EP Yokadouma', 'code' => 'CM-EST-42', 'district' => 'Boumba-et-Ngoko']);

        $this->postJson('/api/v1/mesh/bundles', [
            'bundles' => [$this->bundlePayload($school, ['expires_at' => now()->subDay()->toIso8601String()])],
        ])->assertCreated()->assertJsonPath('summary.expired', 1);

        $this->assertDatabaseHas('mesh_bundles', ['status' => 'expired']);
        $this->assertEquals(0, Report::where('source', 'mesh')->count());
    }

    public function test_max_hops_exceeded_is_rejected(): void
    {
        $school = School::create(['name' => 'EP Yokadouma', 'code' => 'CM-EST-42', 'district' => 'Boumba-et-Ngoko']);
        $hops = array_map(fn ($i) => "node-{$i}", range(0, 11));

        $this->postJson('/api/v1/mesh/bundles', [
            'bundles' => [$this->bundlePayload($school, ['hops' => $hops, 'max_hops' => 10])],
        ])->assertCreated()->assertJsonPath('summary.rejected', 1);

        $this->assertEquals(0, MeshBundle::count());
    }

    public function test_stats_endpoint(): void
    {
        $school = School::create(['name' => 'EP Yokadouma', 'code' => 'CM-EST-42', 'district' => 'Boumba-et-Ngoko']);
        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->bundlePayload($school)]])->assertCreated();

        $this->getJson('/api/v1/mesh/stats')
            ->assertOk()
            ->assertJsonPath('total', 1)
            ->assertJsonPath('avg_hops', 2)
            ->assertJsonPath('origins', 1);
    }

    public function test_v11_fields_are_stored_with_defaults(): void
    {
        $school = School::create(['name' => 'EP Yokadouma', 'code' => 'CM-EST-42', 'district' => 'Boumba-et-Ngoko']);

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->bundlePayload($school, [
            'lifetime_seconds' => 3600,
            'copies_remaining' => 4,
            'priority' => 'high',
            'custody_requested' => true,
            'signature' => str_repeat('a', 128),
        ])]])->assertCreated();

        $bundle = MeshBundle::first();
        $this->assertEquals('dtn://wash-sentinel/ingest', $bundle->destination_eid);
        $this->assertEquals(3600, $bundle->lifetime_seconds);
        $this->assertEquals(4, $bundle->copies_remaining);
        $this->assertEquals('high', $bundle->priority);
        $this->assertTrue($bundle->custody_requested);
        $this->assertEquals('node-B-taximoto', $bundle->previous_node_id);
        // lifetime dérivé côté serveur : ~1 h, pas l'expires_at du client.
        $this->assertTrue($bundle->expires_at->diffInMinutes(now()->addHour()) < 2);
    }

    public function test_ingest_key_is_enforced_when_configured(): void
    {
        config(['services.mesh.ingest_key' => 'relay-secret']);
        $school = School::create(['name' => 'EP Yokadouma', 'code' => 'CM-EST-42', 'district' => 'Boumba-et-Ngoko']);

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->bundlePayload($school)]])
            ->assertUnauthorized();

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->bundlePayload($school)]],
            ['X-Mesh-Key' => 'relay-secret'])
            ->assertCreated()->assertJsonPath('summary.accepted', 1);
    }

    public function test_daily_cap_per_origin_is_enforced(): void
    {
        config(['services.mesh.daily_cap_per_origin' => 1]);
        $school = School::create(['name' => 'EP Yokadouma', 'code' => 'CM-EST-42', 'district' => 'Boumba-et-Ngoko']);

        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->bundlePayload($school)]])->assertCreated();
        $this->postJson('/api/v1/mesh/bundles', ['bundles' => [$this->bundlePayload($school)]])
            ->assertCreated()->assertJsonPath('summary.quota_exceeded', 1);

        $this->assertEquals(1, MeshBundle::count());
    }
}
