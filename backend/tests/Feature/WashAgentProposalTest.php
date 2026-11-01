<?php

namespace Tests\Feature;

use App\Contracts\AiEngineClient;
use App\Models\AgentProposal;
use App\Models\Incident;
use App\Models\MaintenanceLog;
use App\Models\School;
use App\Models\User;
use App\Services\AgentProposalService;
use Database\Seeders\WashRoleSeeder;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Validation\ValidationException;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class WashAgentProposalTest extends TestCase
{
    use RefreshDatabase;

    private function userWithRole(string $role, string $email): User
    {
        $this->seed(WashRoleSeeder::class);
        $user = User::create(['name' => $role, 'email' => $email, 'password' => 'secret']);
        $user->assignRole($role);
        Sanctum::actingAs($user);

        return $user;
    }

    private function school(): School
    {
        return School::create(['name' => 'EP Test', 'code' => 'EP-T9', 'district' => 'Mvila']);
    }

    private function agentResponse(array $cardData): array
    {
        return [
            'answer' => 'Voici le récapitulatif.',
            'tools_executed' => ['prepare_report'],
            'cards' => [[
                'type' => 'action_confirmation',
                'title' => 'Confirmer',
                'data' => $cardData,
            ]],
            'model_used' => 'stub',
        ];
    }

    private function mockAgent(array $response, ?array $triage = null): void
    {
        $this->mock(AiEngineClient::class, function ($mock) use ($response, $triage) {
            $mock->shouldReceive('agentChat')->andReturn($response);
            if ($triage) {
                $mock->shouldReceive('triage')->andReturn($triage);
            }
        });
    }

    private function triagePayload(): array
    {
        return [
            'raw_text' => 'Fuite au robinet du préau',
            'extraction' => [
                'data' => [
                    'short_summary' => 'Fuite au robinet',
                    'infrastructure_type' => 'water_point',
                    'issue_type' => 'leak',
                    'urgency_level' => 'low',
                    'health_hazard_risk' => 'low',
                    'recommended_priority_score' => 12.0,
                    'estimated_affected_students' => 0,
                ],
                'model_used' => 'stub',
                'confidence_score' => 0.9,
            ],
        ];
    }

    public function test_reporter_drafts_and_confirms_report_with_overrides(): void
    {
        $user = $this->userWithRole('school_reporter', 'rep@wash.cm');
        $school = $this->school();
        $this->mockAgent($this->agentResponse([
            'action' => 'create_report',
            'complete' => true,
            'slots' => [
                'school_id' => $school->id,
                'description' => 'Latrines bouchées qui débordent',
                'category' => 'toilets_latrines',
                'urgency' => 'critical',
                'affected_students' => 300,
            ],
        ]), $this->triagePayload());

        $res = $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Signale des latrines bouchées']);
        $res->assertOk();
        $proposalId = $res->json('cards.0.data.proposal_id');
        $this->assertNotNull($proposalId);
        $this->assertDatabaseHas('agent_proposals', ['id' => $proposalId, 'status' => 'pending', 'user_id' => $user->id]);

        $confirm = $this->postJson("/api/v1/wash/agent/proposals/{$proposalId}/confirm");
        $confirm->assertOk();
        $this->assertTrue($confirm->json('result.is_duplicate') === false);
        $incident = Incident::findOrFail($confirm->json('result.incident_id'));
        $this->assertSame('critical', $incident->urgency);
        $this->assertSame('toilets_latrines', $incident->category);
        $this->assertSame(300, $incident->affected_students);
        $this->assertSame('confirmed', AgentProposal::find($proposalId)->status);

        $this->postJson("/api/v1/wash/agent/proposals/{$proposalId}/confirm")->assertStatus(409);
    }

    public function test_reporter_cannot_draft_incident(): void
    {
        $this->userWithRole('school_reporter', 'rep@wash.cm');
        $school = $this->school();
        $this->mockAgent($this->agentResponse([
            'action' => 'create_incident',
            'complete' => true,
            'slots' => [
                'school_id' => $school->id, 'title' => 'Forage HS',
                'category' => 'water_point', 'urgency' => 'high', 'affected_students' => 100,
            ],
        ]));

        $res = $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Crée une intervention']);
        $res->assertOk()->assertJsonPath('cards.0.data.not_permitted', true);
        $this->assertDatabaseCount('agent_proposals', 0);
    }

    public function test_maintenance_agent_creates_incident_directly(): void
    {
        $this->userWithRole('maintenance_agent', 'agent@wash.cm');
        $school = $this->school();
        $this->mockAgent($this->agentResponse([
            'action' => 'create_incident',
            'complete' => true,
            'slots' => [
                'school_id' => $school->id, 'title' => 'Forage à réhabiliter',
                'category' => 'water_point', 'urgency' => 'high', 'affected_students' => 195,
            ],
        ]));

        $proposalId = $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Crée une intervention'])
            ->assertOk()->json('cards.0.data.proposal_id');
        $confirm = $this->postJson("/api/v1/wash/agent/proposals/{$proposalId}/confirm");
        $confirm->assertOk();
        $incident = Incident::findOrFail($confirm->json('result.incident_id'));
        $this->assertSame('triaged', $incident->status);
        $this->assertSame('Forage à réhabiliter', $incident->title);
    }

    public function test_maintenance_agent_confirms_maintenance_log(): void
    {
        $user = $this->userWithRole('maintenance_agent', 'agent@wash.cm');
        $school = $this->school();
        $incident = Incident::create([
            'school_id' => $school->id, 'title' => 'Pompe HS', 'category' => 'water_point',
            'status' => 'reported', 'urgency' => 'high',
        ]);
        $this->mockAgent($this->agentResponse([
            'action' => 'create_maintenance_log',
            'complete' => true,
            'slots' => ['incident_id' => $incident->id, 'cost_amount' => 150000, 'notes' => 'Débouchage'],
        ]));

        $proposalId = $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Journalise 150000'])
            ->assertOk()->json('cards.0.data.proposal_id');
        $this->postJson("/api/v1/wash/agent/proposals/{$proposalId}/confirm")->assertOk();
        $this->assertDatabaseHas('maintenance_logs', [
            'incident_id' => $incident->id, 'cost_amount' => 150000,
            'performed_by' => $user->id, 'school_id' => $school->id,
        ]);
    }

    public function test_confirm_requires_owner(): void
    {
        $this->userWithRole('school_reporter', 'a@wash.cm');
        $school = $this->school();
        $proposal = AgentProposal::create([
            'user_id' => User::where('email', 'a@wash.cm')->first()->id,
            'action' => 'create_report',
            'payload' => ['school_id' => $school->id],
            'status' => 'pending',
            'expires_at' => now()->addMinutes(30),
        ]);
        $this->userWithRole('wash_admin', 'b@wash.cm');

        $this->postJson("/api/v1/wash/agent/proposals/{$proposal->id}/confirm")->assertForbidden();
    }

    public function test_expired_proposal_returns_gone(): void
    {
        $user = $this->userWithRole('school_reporter', 'rep@wash.cm');
        $proposal = AgentProposal::create([
            'user_id' => $user->id, 'action' => 'create_report', 'payload' => [],
            'status' => 'pending', 'expires_at' => now()->subMinute(),
        ]);

        $this->postJson("/api/v1/wash/agent/proposals/{$proposal->id}/confirm")->assertStatus(410);
        $this->assertSame('expired', $proposal->fresh()->status);
    }

    public function test_cancel_then_confirm_conflicts(): void
    {
        $this->userWithRole('school_reporter', 'rep@wash.cm');
        $school = $this->school();
        $this->mockAgent($this->agentResponse([
            'action' => 'create_report',
            'complete' => true,
            'slots' => [
                'school_id' => $school->id, 'description' => 'Fuite au robinet',
                'category' => 'water_point', 'urgency' => 'low', 'affected_students' => 10,
            ],
        ]));

        $proposalId = $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Signale une fuite'])
            ->assertOk()->json('cards.0.data.proposal_id');
        $this->postJson("/api/v1/wash/agent/proposals/{$proposalId}/cancel")->assertOk();
        $this->postJson("/api/v1/wash/agent/proposals/{$proposalId}/confirm")->assertStatus(409);
    }

    public function test_bare_oui_confirms_pending_without_ai(): void
    {
        $user = $this->userWithRole('school_reporter', 'rep@wash.cm');
        $school = $this->school();
        $this->mock(AiEngineClient::class, function ($mock) {
            $mock->shouldReceive('agentChat')->never();
            $mock->shouldReceive('triage')->andReturn($this->triagePayload());
        });
        AgentProposal::create([
            'user_id' => $user->id,
            'action' => 'create_report',
            'payload' => [
                'school_id' => $school->id, 'school_name' => $school->name,
                'description' => 'Fuite au robinet', 'category' => 'water_point',
                'urgency' => 'low', 'affected_students' => 10,
            ],
            'status' => 'pending',
            'expires_at' => now()->addMinutes(30),
        ]);

        $res = $this->postJson('/api/v1/wash/agent/converse', ['message' => 'oui']);
        $res->assertOk()->assertJsonPath('tools_executed.0', 'confirm_proposal');
        $this->assertStringContainsString('validé', $res->json('answer'));
        $this->assertSame('confirmed', AgentProposal::first()->status);
    }

    public function test_bare_oui_ambiguous_falls_through_to_ai(): void
    {
        $user = $this->userWithRole('school_reporter', 'rep@wash.cm');
        $this->mockAgent(['answer' => 'Laquelle ?', 'tools_executed' => [], 'cards' => [], 'model_used' => 'stub']);
        AgentProposal::insert([
            ['user_id' => $user->id, 'action' => 'create_report', 'payload' => '{}', 'status' => 'pending', 'expires_at' => now()->addMinutes(30), 'created_at' => now(), 'updated_at' => now()],
            ['user_id' => $user->id, 'action' => 'create_report', 'payload' => '{}', 'status' => 'pending', 'expires_at' => now()->addMinutes(30), 'created_at' => now(), 'updated_at' => now()],
        ]);

        $res = $this->postJson('/api/v1/wash/agent/converse', ['message' => 'oui']);
        $res->assertOk()->assertJsonPath('answer', 'Laquelle ?');
        $this->assertSame(2, AgentProposal::where('status', 'pending')->count());
    }

    public function test_guest_gets_login_required_card(): void
    {
        $this->mockAgent($this->agentResponse([
            'action' => 'create_report',
            'complete' => true,
            'slots' => ['school_id' => 1, 'description' => 'x', 'category' => 'water_point', 'urgency' => 'low', 'affected_students' => 1],
        ]));

        $res = $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Signale une fuite']);
        $res->assertOk()->assertJsonPath('cards.0.data.login_required', true);
        $this->assertDatabaseCount('agent_proposals', 0);
    }

    public function test_invalid_slots_rejected(): void
    {
        $user = $this->userWithRole('school_reporter', 'rep@wash.cm');
        $service = app(AgentProposalService::class);

        try {
            $service->draft($user, 'create_report', ['school_id' => 9999]);
            $this->fail('Validation attendue.');
        } catch (ValidationException $e) {
            $this->assertArrayHasKey('school_id', $e->errors());
        }
        try {
            $service->draft($user, 'hack_the_planet', []);
            $this->fail('Validation attendue.');
        } catch (ValidationException $e) {
            $this->assertArrayHasKey('action', $e->errors());
        }
        $this->assertDatabaseCount('agent_proposals', 0);
    }

    public function test_expired_confirm_returns_guided_redraft_payload(): void
    {
        $user = $this->userWithRole('school_reporter', 'rep@wash.cm');
        $school = $this->school();
        $proposal = AgentProposal::create([
            'user_id' => $user->id, 'action' => 'create_report',
            'payload' => [
                'school_id' => $school->id, 'school_name' => $school->name,
                'description' => 'Fuite au robinet', 'category' => 'water_point',
                'urgency' => 'low', 'affected_students' => 10,
            ],
            'status' => 'pending', 'expires_at' => now()->subMinute(),
        ]);

        $res = $this->postJson("/api/v1/wash/agent/proposals/{$proposal->id}/confirm");
        $res->assertStatus(410)
            ->assertJsonPath('status', 'expired')
            ->assertJsonPath('next_action.label', 'Refaire la demande');
        $this->assertStringContainsString('expiré', mb_strtolower((string) $res->json('message')));
        $this->assertStringContainsString('Redemandez', (string) $res->json('message'));
        $this->assertNotEmpty($res->json('next_action.prompt'));
        $this->assertSame('expired', $proposal->fresh()->status);
    }

    public function test_double_confirm_returns_already_recorded_guidance(): void
    {
        $user = $this->userWithRole('maintenance_agent', 'agent@wash.cm');
        $school = $this->school();
        $proposal = AgentProposal::create([
            'user_id' => $user->id, 'action' => 'create_incident',
            'payload' => [
                'school_id' => $school->id, 'school_name' => $school->name,
                'title' => 'Forage à réhabiliter', 'category' => 'water_point',
                'urgency' => 'high', 'affected_students' => 195,
            ],
            'status' => 'pending', 'expires_at' => now()->addMinutes(30),
        ]);

        $ref = $this->postJson("/api/v1/wash/agent/proposals/{$proposal->id}/confirm")
            ->assertOk()->json('result.reference_code');

        $res = $this->postJson("/api/v1/wash/agent/proposals/{$proposal->id}/confirm");
        $res->assertStatus(409)
            ->assertJsonPath('status', 'already_confirmed')
            ->assertJsonPath('reference_code', $ref);
        $this->assertStringContainsString('Déjà enregistré', (string) $res->json('message'));
        $this->assertStringContainsString((string) $ref, (string) $res->json('message'));
        $this->assertStringContainsString((string) $ref, (string) $res->json('next_action.prompt'));
    }

    public function test_confirm_cancelled_returns_conflict_guidance(): void
    {
        $user = $this->userWithRole('school_reporter', 'rep@wash.cm');
        $school = $this->school();
        $proposal = AgentProposal::create([
            'user_id' => $user->id, 'action' => 'create_report',
            'payload' => [
                'school_id' => $school->id, 'school_name' => $school->name,
                'description' => 'Fuite au robinet', 'category' => 'water_point',
                'urgency' => 'low', 'affected_students' => 10,
            ],
            'status' => 'pending', 'expires_at' => now()->addMinutes(30),
        ]);
        $this->postJson("/api/v1/wash/agent/proposals/{$proposal->id}/cancel")->assertOk();

        $res = $this->postJson("/api/v1/wash/agent/proposals/{$proposal->id}/confirm");
        $res->assertStatus(409)
            ->assertJsonPath('status', 'conflict')
            ->assertJsonPath('next_action.label', 'Refaire la demande');
        $this->assertStringContainsString('déjà traité', mb_strtolower((string) $res->json('message')));
        $this->assertNotEmpty($res->json('next_action.prompt'));
    }

    public function test_confirm_without_permission_returns_refused_guidance(): void
    {
        $user = $this->userWithRole('school_reporter', 'rep@wash.cm');
        $school = $this->school();
        $proposal = AgentProposal::create([
            'user_id' => $user->id, 'action' => 'create_incident',
            'payload' => [
                'school_id' => $school->id, 'school_name' => $school->name,
                'title' => 'Forage HS', 'category' => 'water_point',
                'urgency' => 'high', 'affected_students' => 100,
            ],
            'status' => 'pending', 'expires_at' => now()->addMinutes(30),
        ]);

        $res = $this->postJson("/api/v1/wash/agent/proposals/{$proposal->id}/confirm");
        $res->assertStatus(403)->assertJsonPath('status', 'forbidden');
        $this->assertStringContainsString('refusée', mb_strtolower((string) $res->json('message')));
        $this->assertStringContainsString("Rien n'a été créé", (string) $res->json('message'));
        $this->assertSame('pending', $proposal->fresh()->status);
    }
}
