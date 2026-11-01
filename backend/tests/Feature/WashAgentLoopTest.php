<?php

namespace Tests\Feature;

use App\Models\AiAnalysis;
use App\Models\Incident;
use App\Models\School;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\UploadedFile;
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
            'latitude' => 4.0252, 'longitude' => 9.6845,
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
            && ($request->data()['context']['schools'][0]['latitude'] ?? null) === 4.0252
            && ($request->data()['context']['schools'][0]['longitude'] ?? null) === 9.6845
        );
        $this->assertEquals(1, AiAnalysis::where('analysis_type', 'agent')->count());
    }

    public function test_converse_validates_message(): void
    {
        $this->postJson('/api/v1/wash/agent/converse', ['message' => ''])
            ->assertStatus(422);
    }

    public function test_converse_forwards_guided_true_to_engine(): void
    {
        Http::fake([
            '*/v1/agent/chat' => Http::response([
                'answer' => 'Guidé activé.',
                'tools_executed' => [],
                'cards' => [],
                'model_used' => 'test-llm',
            ], 200),
        ]);

        $response = $this->postJson('/api/v1/wash/agent/converse', [
            'message' => 'Signale une fuite',
            'guided' => true,
        ]);

        $response->assertOk();

        Http::assertSent(fn ($request) =>
            str_ends_with($request->url(), '/v1/agent/chat')
            && ($request->data()['guided'] ?? null) === true
        );
    }

    public function test_transcribe_accepts_english_language(): void
    {
        Http::fake([
            '*/v1/voice/transcribe' => Http::response([
                'transcript' => 'There is a leak at the borehole.',
                'language' => 'en',
                'language_effective' => 'en',
            ], 200),
        ]);

        $response = $this->post('/api/v1/wash/agent/transcribe', [
            'audio' => UploadedFile::fake()->create('note.wav', 10, 'audio/wav'),
            'language' => 'en',
        ]);

        $response->assertOk();
        $response->assertJsonPath('language', 'en');
        Http::assertSent(fn ($request) =>
            str_ends_with($request->url(), '/v1/voice/transcribe')
        );
    }

    public function test_synthesize_accepts_english_language(): void
    {
        Http::fake([
            '*/v1/voice/synthesize' => Http::response([
                'audio_base64' => base64_encode('RIFFfake'),
                'mime_type' => 'audio/wav',
                'language_effective' => 'en',
            ], 200),
        ]);

        $response = $this->postJson('/api/v1/wash/agent/synthesize', [
            'text' => 'There is a leak at the borehole.',
            'language' => 'en',
        ]);

        $response->assertOk();
        Http::assertSent(fn ($request) =>
            str_ends_with($request->url(), '/v1/voice/synthesize')
            && ($request->data()['language'] ?? null) === 'en'
        );
    }

    public function test_voice_endpoints_reject_unknown_language(): void
    {
        $this->post('/api/v1/wash/agent/transcribe', [
            'audio' => UploadedFile::fake()->create('note.wav', 10, 'audio/wav'),
            'language' => 'klingon',
        ])->assertStatus(422);

        $this->postJson('/api/v1/wash/agent/synthesize', [
            'text' => 'bonjour',
            'language' => 'klingon',
        ])->assertStatus(422);
    }

    public function test_converse_guided_absent_payload_unchanged(): void
    {
        Http::fake([
            '*/v1/agent/chat' => Http::response([
                'answer' => 'Réponse normale.',
                'tools_executed' => [],
                'cards' => [],
                'model_used' => 'test-llm',
            ], 200),
        ]);

        $response = $this->postJson('/api/v1/wash/agent/converse', [
            'message' => 'Quelle est la situation ?',
        ]);

        $response->assertOk();

        Http::assertSent(fn ($request) =>
            str_ends_with($request->url(), '/v1/agent/chat')
            && !array_key_exists('guided', $request->data())
        );
    }
}
