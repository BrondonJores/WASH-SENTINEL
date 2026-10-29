<?php

namespace Tests\Feature;

use App\Models\School;
use App\Services\IncidentTriageService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

class WashTriageLanguageTest extends TestCase
{
    use RefreshDatabase;

    public function test_triage_sends_school_language_to_ai_engine(): void
    {
        Http::fake([
            '*/v1/wash/triage' => Http::response([
                'raw_text' => 'Fuite robinet préau.',
                'extraction' => [
                    'data' => [
                        'school_detected' => 'École de Nkol',
                        'infrastructure_type' => 'water_point',
                        'issue_type' => 'leak',
                        'urgency_level' => 'medium',
                        'estimated_affected_students' => 0,
                        'health_hazard_risk' => 'low',
                        'short_summary' => 'Fuite sur le robinet du préau.',
                    ],
                    'model_used' => 'test-llm',
                    'confidence_score' => 0.9,
                ],
            ], 200),
        ]);

        $school = School::create([
            'name' => 'École de Nkol', 'code' => 'RUR-NKOL-005',
            'district' => 'Mvila', 'default_language' => 'dua_Latn',
        ]);

        $result = app(IncidentTriageService::class)->ingest($school, 'text', 'Fuite robinet préau.', null, null);

        Http::assertSent(fn ($request) =>
            str_ends_with($request->url(), '/v1/wash/triage')
            && ($request->header('X-STT-Language')[0] ?? null) === 'dua_Latn'
        );
        $this->assertEquals('water_point', $result['incident']->category);
        $this->assertEquals('leak', $result['incident']->issue_type);
    }
}
