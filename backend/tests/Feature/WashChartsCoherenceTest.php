<?php

namespace Tests\Feature;

use App\Models\Incident;
use App\Models\MaintenanceLog;
use App\Models\School;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

class WashChartsCoherenceTest extends TestCase
{
    use RefreshDatabase;

    public function test_converse_context_carries_resolved_incident_categories(): void
    {
        Http::fake([
            '*/v1/agent/chat' => Http::response([
                'answer' => 'Voici les chiffres.',
                'tools_executed' => [],
                'cards' => [],
                'model_used' => 'test-llm',
            ], 200),
        ]);

        $school = School::create([
            'name' => 'École de Nyo', 'code' => 'SAN-NYO-008', 'district' => 'Sanaga-Maritime',
        ]);
        // Incident résolu lié à un journal : la catégorie doit survivre
        // dans le contexte (budget_compare ne doit pas le mettre en unknown).
        $resolved = Incident::create([
            'school_id' => $school->id, 'title' => 'Pompe remise en service',
            'category' => 'water_point', 'issue_type' => 'total_breakdown',
            'status' => 'resolved', 'urgency' => 'medium',
        ]);
        MaintenanceLog::create([
            'incident_id' => $resolved->id, 'school_id' => $school->id,
            'cost_amount' => 505000, 'repaired_at' => now()->subDays(9),
        ]);
        Incident::create([
            'school_id' => $school->id, 'title' => 'Caniveau bouché',
            'category' => 'sewage_drainage', 'issue_type' => 'blockage',
            'status' => 'reported', 'urgency' => 'high',
        ]);

        $this->postJson('/api/v1/wash/agent/converse', [
            'message' => 'Compare les budgets',
        ])->assertOk();

        Http::assertSent(function ($request) use ($resolved) {
            if (! str_ends_with($request->url(), '/v1/agent/chat')) {
                return false;
            }
            $context = $request->data()['context'] ?? [];

            // 1. recent_incidents porte la catégorie (même résolus).
            $recent = collect($context['recent_incidents'] ?? []);
            if ($recent->isEmpty() || $recent->contains(fn ($r) => empty($r['category']))) {
                return false;
            }
            if (! $recent->contains(fn ($r) => ($r['id'] ?? null) === $resolved->id
                && ($r['category'] ?? null) === 'water_point')) {
                return false;
            }

            // 2. maintenance_logs porte la catégorie de l'incident lié.
            $logs = collect($context['maintenance_logs'] ?? []);
            if (! $logs->contains(fn ($l) => ($l['incident_id'] ?? null) === $resolved->id
                && ($l['category'] ?? null) === 'water_point')) {
                return false;
            }

            // 3. map incident_id -> categorie dédiée (clés int ou string).
            $map = $context['incident_categories'] ?? null;
            if (! is_array($map)) {
                return false;
            }
            $hit = ($map[$resolved->id] ?? null) === 'water_point'
                || ($map[(string) $resolved->id] ?? null) === 'water_point';

            return $hit;
        });
    }
}
