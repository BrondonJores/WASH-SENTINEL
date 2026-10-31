<?php

namespace Tests\Feature;

use App\Models\MeshBundle;
use App\Models\Report;
use App\Models\School;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class WashSmsTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        config(['services.mesh.sms_secret' => 'test-secret']);
    }

    private function school(): School
    {
        return School::create(['name' => 'EP Yokadouma', 'code' => 'CE042', 'district' => 'Est']);
    }

    public function test_sms_creates_incident_with_ticket_and_reply(): void
    {
        $this->school();

        $this->postJson('/api/v1/mesh/sms', [
            'secret' => 'test-secret',
            'from' => '+237600000001',
            'message' => 'WASH CE042 P pompe cassee ce matin',
        ])
            ->assertCreated()
            ->assertJsonPath('ticket', fn ($t) => $t !== null)
            ->assertJsonPath('reply', fn ($r) => str_contains($r, 'WASH OK'));

        $this->assertDatabaseHas('mesh_bundles', ['origin_node_id' => 'sms:+237600000001', 'status' => 'delivered']);
        $this->assertDatabaseHas('reports', ['source' => 'sms']);
    }

    public function test_bad_secret_is_rejected(): void
    {
        $this->postJson('/api/v1/mesh/sms', [
            'secret' => 'wrong', 'from' => '+2371', 'message' => 'WASH CE042 P',
        ])->assertForbidden();

        $this->assertEquals(0, MeshBundle::count());
    }

    public function test_invalid_format_returns_help_reply(): void
    {
        $this->school();

        $this->postJson('/api/v1/mesh/sms', [
            'secret' => 'test-secret', 'from' => '+2371', 'message' => 'BONJOUR',
        ])
            ->assertUnprocessable()
            ->assertJsonPath('reply', fn ($r) => str_contains($r, 'WASH CODE'));

        $this->assertEquals(0, Report::where('source', 'sms')->count());
    }

    public function test_duplicate_sms_within_24h_is_ignored(): void
    {
        $this->school();
        $payload = ['secret' => 'test-secret', 'from' => '+2371', 'message' => 'WASH CE042 L'];

        $this->postJson('/api/v1/mesh/sms', $payload)->assertCreated();
        $this->postJson('/api/v1/mesh/sms', $payload)->assertOk()->assertJsonPath('duplicate', true);

        $this->assertEquals(1, Report::where('source', 'sms')->count());
    }

    public function test_sender_quota_is_enforced(): void
    {
        config(['services.mesh.sms_quota_per_sender' => 1]);
        $this->school();

        $this->postJson('/api/v1/mesh/sms', [
            'secret' => 'test-secret', 'from' => '+2371', 'message' => 'WASH CE042 P',
        ])->assertCreated();

        $this->postJson('/api/v1/mesh/sms', [
            'secret' => 'test-secret', 'from' => '+2371', 'message' => 'WASH CE042 L',
        ])->assertStatus(429);
    }
}
