<?php

namespace Tests\Feature;

use App\Models\AiAnalysis;
use App\Models\Incident;
use App\Models\School;
use App\Models\User;
use Database\Seeders\WashRoleSeeder;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class WashCrudTest extends TestCase
{
    use RefreshDatabase;

    private function admin(): User
    {
        $this->seed(WashRoleSeeder::class);
        $user = User::create(['name' => 'Admin', 'email' => 'admin@wash.cm', 'password' => 'secret']);
        $user->assignRole('wash_admin');
        Sanctum::actingAs($user);

        return $user;
    }

    private function seedIncident(): Incident
    {
        $school = School::create(['name' => 'EP Test', 'code' => 'EP-T1', 'district' => 'Mvila']);

        return Incident::create([
            'school_id' => $school->id,
            'title' => 'Pompe en panne',
            'category' => 'water_point',
            'status' => 'reported',
            'urgency' => 'high',
        ]);
    }

    public function test_guest_cannot_access_admin_ai_analyses(): void
    {
        $this->getJson('/api/v1/admin/ai-analyses')->assertUnauthorized();
    }

    public function test_admin_can_list_ai_analyses(): void
    {
        $this->admin();
        $incident = $this->seedIncident();
        AiAnalysis::create([
            'incident_id' => $incident->id,
            'analysis_type' => 'triage',
            'output_payload' => ['priority' => 88],
            'model_used' => 'test-model',
            'confidence' => 0.9,
        ]);

        $this->getJson('/api/v1/admin/ai-analyses')
            ->assertOk()
            ->assertJsonPath('data.0.analysis_type', 'triage')
            ->assertJsonPath('data.0.incident.reference_code', $incident->reference_code);
    }

    public function test_update_status_accepts_all_lifecycle_values(): void
    {
        $this->admin();
        $incident = $this->seedIncident();

        foreach (['triaged', 'assigned', 'in_progress', 'resolved'] as $status) {
            $this->patchJson("/api/v1/wash/incidents/{$incident->id}/status", ['status' => $status])
                ->assertOk()
                ->assertJsonPath('incident.status', $status);
        }

        $this->patchJson("/api/v1/wash/incidents/{$incident->id}/status", ['status' => 'nope'])
            ->assertUnprocessable();
    }

    public function test_assignable_users_requires_permission(): void
    {
        $user = User::create(['name' => 'B', 'email' => 'b@wash.cm', 'password' => 'secret']);
        Sanctum::actingAs($user);
        $this->getJson('/api/v1/wash/assignable-users')->assertForbidden();

        $this->admin();
        $this->getJson('/api/v1/wash/assignable-users')->assertOk();
    }
}
