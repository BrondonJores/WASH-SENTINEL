<?php

namespace Tests\Feature;

use App\Models\AiAnalysis;
use App\Models\Incident;
use App\Models\School;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

class WashAgentLoopTest extends TestCase
{
    use RefreshDatabase;

    public function test_converse_sends_context_and_returns_agent_answer(): void
    {
        Http::fake([
            '*/v1/agent/chat' => Http::response([
                'answer' => 'Voici la situation.',
                'tools_executed' => ['summarize_district'],
                'cards' => [['type' => 'district_summary', 'title' => 'Synthèse', 'data' => []]],
                'model_used' => 'test-llm',
            ], 200),
        ]);

        $school = School::create([
            'name' => 'École de Bonanjo', 'code' => 'DOU-BON-001', 'district' => 'Wouri',
        ]);
        \App\Models\MaintenanceLog::create([
            'incident_id' => Incident::create([
                'school_id' => $school->id, 'title' => 'Ancienne panne',
                'category' => 'water_point', 'issue_type' => 'leak',
                'status' => 'resolved', 'urgency' => 'low',
            ])->id,
            'school_id' => $school->id,
            'cost_amount' => 50000, 'repaired_at' => now()->subMonth(),
        ]);
        Incident::create([
            'school_id' => $school->id, 'title' => 'Pompe cassée',
            'category' => 'water_point', 'issue_type' => 'total_breakdown',
            'status' => 'triaged', 'urgency' => 'critical',
            'priority_score' => 94.0, 'affected_students' => 450,
            'ai_summary' => 'Pompe cassée.',
        ]);

        $response = $this->postJson('/api/v1/wash/agent/converse', [
            'message' => 'Quelle est la situation ?',
        ]);

        $response->assertOk();
        $response->assertJsonPath('answer', 'Voici la situation.');
        $response->assertJsonPath('tools_executed', ['summarize_district']);

        Http::assertSent(fn ($request) =>
            str_ends_with($request->url(), '/v1/agent/chat')
            && count($request->data()['context']['schools'] ?? []) === 1
            && count($request->data()['context']['incidents'] ?? []) === 1
            && count($request->data()['context']['recent_incidents'] ?? []) === 2
            && count($request->data()['context']['maintenance_logs'] ?? []) === 1
        );
        $this->assertEquals(1, AiAnalysis::where('analysis_type', 'agent')->count());
    }

    public function test_converse_validates_message(): void
    {
        $this->postJson('/api/v1/wash/agent/converse', ['message' => ''])
            ->assertStatus(422);
    }
}
