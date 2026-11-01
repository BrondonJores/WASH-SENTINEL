<?php

namespace Tests\Feature;

use App\Contracts\WhatsAppClient;
use App\Models\Incident;
use App\Models\Report;
use App\Models\School;
use App\Models\SchoolContact;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Notification;
use Tests\Support\FakeWhatsAppService;
use Tests\TestCase;

class WashWhatsAppSuiviTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        FakeWhatsAppService::reset();
        $this->app->bind(WhatsAppClient::class, FakeWhatsAppService::class);
        config(['whatsapp.simulator' => true]);
        Notification::fake();
    }

    protected function fixture(string $name): array
    {
        return json_decode(file_get_contents(base_path("tests/Fixtures/whatsapp/{$name}.json")), true);
    }

    protected function textPayload(string $body, string $from = '237600112233', string $id = 'wamid.SUIVI001'): array
    {
        $payload = $this->fixture('text');
        $payload['entry'][0]['changes'][0]['value']['messages'][0] = [
            'from' => $from,
            'id' => $id,
            'timestamp' => '1760000000',
            'type' => 'text',
            'text' => ['body' => $body],
        ];

        return $payload;
    }

    protected function audioPayload(string $id, string $from = '237600112233'): array
    {
        $payload = $this->fixture('audio');
        $payload['entry'][0]['changes'][0]['value']['messages'][0]['id'] = $id;
        $payload['entry'][0]['changes'][0]['value']['messages'][0]['from'] = $from;

        return $payload;
    }

    protected function seedContact(): School
    {
        $school = School::create([
            'name' => 'École de Bonanjo', 'code' => 'DOU-BON-001', 'district' => 'Wouri',
        ]);
        SchoolContact::create([
            'school_id' => $school->id, 'phone' => '237600112233',
            'name' => 'Clarisse Eko', 'role' => 'directrice', 'is_verified' => true,
        ]);

        return $school;
    }

    protected function seedIncident(School $school, array $overrides = []): Incident
    {
        return Incident::create(array_merge([
            'school_id' => $school->id,
            'reference_code' => 'WASH-2026-TEST01',
            'title' => 'Fuite robinet bloc A',
            'ai_summary' => 'Fuite robinet bloc A',
            'status' => 'in_progress',
            'urgency' => 'medium',
        ], $overrides));
    }

    protected function sentTexts(): array
    {
        return array_values(array_filter(
            FakeWhatsAppService::$sent,
            fn ($m) => ($m['type'] ?? '') === 'text'
        ));
    }

    public function test_suivi_by_reference_text(): void
    {
        $school = $this->seedContact();
        $incident = $this->seedIncident($school);

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->textPayload(
            'Bonjour, suivi WASH-2026-TEST01 svp ?',
            '237600112233',
            'wamid.SUIVI_REF_001'
        ));

        $this->assertEquals('suivi', $results[0]['status'] ?? null);
        $this->assertEquals($incident->id, $results[0]['incident_id'] ?? null);

        // Zéro création : ni incident ni Report.
        $this->assertEquals(1, Incident::count());
        $this->assertEquals(0, Report::count());

        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $reply = $texts[0]['message'];
        $this->assertStringContainsString('WASH-2026-TEST01', $reply);
        $this->assertStringContainsString('Fuite robinet bloc A', $reply);
        $this->assertStringContainsString('équipe en intervention', $reply);
        $this->assertStringContainsString('Prochaine étape', $reply);
        $this->assertLessThanOrEqual(397, mb_strlen($reply));
    }

    public function test_suivi_without_reference_returns_latest_incident(): void
    {
        $school = $this->seedContact();
        $this->seedIncident($school, [
            'reference_code' => 'WASH-2026-OLD001', 'status' => 'resolved',
            'title' => 'Pompe HS', 'ai_summary' => 'Pompe HS cour',
        ]);
        $latest = $this->seedIncident($school, [
            'reference_code' => 'WASH-2026-NEW002', 'status' => 'assigned',
            'title' => 'Toilettes bouchées bloc B', 'ai_summary' => 'Toilettes bouchées bloc B',
        ]);

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->textPayload(
            'Bonjour, où en est mon dossier ?',
            '237600112233',
            'wamid.SUIVI_LAST_001'
        ));

        $this->assertEquals('suivi', $results[0]['status'] ?? null);
        $this->assertEquals($latest->id, $results[0]['incident_id'] ?? null);

        $this->assertEquals(2, Incident::count());
        $this->assertEquals(0, Report::count());

        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $reply = $texts[0]['message'];
        $this->assertStringContainsString('WASH-2026-NEW002', $reply);
        $this->assertStringContainsString('technicien assigné', $reply);
        $this->assertLessThanOrEqual(397, mb_strlen($reply));
    }

    public function test_suivi_voice_transcript(): void
    {
        $school = $this->seedContact();
        $incident = $this->seedIncident($school, ['status' => 'triaged']);
        Http::fake([
            '*/v1/voice/transcribe' => Http::response(['transcript' => 'Bonjour, où en est mon signalement ?'], 200),
        ]);

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->audioPayload('wamid.SUIVI_VOC_001'));

        $this->assertEquals('suivi', $results[0]['status'] ?? null);
        $this->assertEquals($incident->id, $results[0]['incident_id'] ?? null);

        $this->assertEquals(1, Incident::count());
        $this->assertEquals(0, Report::count());

        // Fiche texte uniquement : ni boutons Oui/Non, ni note vocale.
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $reply = $texts[0]['message'];
        $this->assertStringContainsString($incident->reference_code, $reply);
        $this->assertStringContainsString('pris en compte par notre équipe', $reply);
        $this->assertLessThanOrEqual(397, mb_strlen($reply));
    }

    public function test_suivi_school_without_incident_gets_guided_reply(): void
    {
        $this->seedContact();

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->textPayload(
            'Je veux suivre mon signalement svp.',
            '237600112233',
            'wamid.SUIVI_EMPTY_001'
        ));

        $this->assertEquals('suivi', $results[0]['status'] ?? null);
        $this->assertArrayNotHasKey('incident_id', $results[0]);

        $this->assertEquals(0, Incident::count());
        $this->assertEquals(0, Report::count());

        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $reply = $texts[0]['message'];
        $this->assertStringContainsString("Aucun signalement pour l'instant", $reply);
        $this->assertStringContainsString('décrivez votre panne', $reply);
    }

    public function test_suivi_english(): void
    {
        $school = $this->seedContact();
        $incident = $this->seedIncident($school, [
            'status' => 'assigned', 'title' => 'Leaking tap block A', 'ai_summary' => 'Leaking tap block A',
        ]);

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->textPayload(
            'Hello, what is the status of my report?',
            '237600112233',
            'wamid.SUIVI_EN_001'
        ));

        $this->assertEquals('suivi', $results[0]['status'] ?? null);
        $this->assertEquals($incident->id, $results[0]['incident_id'] ?? null);

        $this->assertEquals(1, Incident::count());
        $this->assertEquals(0, Report::count());

        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $reply = $texts[0]['message'];
        $this->assertStringContainsString($incident->reference_code, $reply);
        $this->assertStringContainsString('Status:', $reply);
        $this->assertStringContainsString('technician assigned', $reply);
        $this->assertStringContainsString('Next step:', $reply);
        $this->assertLessThanOrEqual(397, mb_strlen($reply));
    }

    public function test_suivi_unknown_reference_gets_guided_reply(): void
    {
        $school = $this->seedContact();
        $this->seedIncident($school);

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->textPayload(
            'Suivi WASH-2026-ZZZZ99 ?',
            '237600112233',
            'wamid.SUIVI_UNK_001'
        ));

        $this->assertEquals('suivi', $results[0]['status'] ?? null);
        $this->assertEquals(1, Incident::count());
        $this->assertEquals(0, Report::count());

        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $this->assertStringContainsString('WASH-2026-ZZZZ99', $texts[0]['message']);
    }

    public function test_pending_clarification_keeps_priority_over_suivi(): void
    {
        config(['filesystems.disks.public.root' => sys_get_temp_dir() . '/wash-test-public']);
        $school = $this->seedContact();
        $incident = $this->seedIncident($school, ['status' => 'reported']);
        Http::fake([
            '*/v1/wash/triage' => Http::response([
                'raw_text' => 'Robinet qui fuit.',
                'extraction' => [
                    'data' => [
                        'school_detected' => null,
                        'infrastructure_type' => 'water_point',
                        'issue_type' => 'leak',
                        'urgency_level' => 'medium',
                        'estimated_affected_students' => 0,
                        'health_hazard_risk' => 'low',
                        'short_summary' => 'Fuite sur un robinet.',
                    ],
                    'model_used' => 'test-llm',
                    'confidence_score' => 0.9,
                ],
            ], 200),
            '*/v1/voice/transcribe' => Http::response(['transcript' => 'Le robinet du bloc A fuit beaucoup.'], 200),
            '*/v1/voice/synthesize' => Http::response(['audio_base64' => base64_encode('fake-tts')], 200),
        ]);

        // Vocal initial puis clic Non → clarification en attente.
        $this->postJson('/api/v1/whatsapp/webhook', $this->audioPayload('wamid.SUIVI_CLAR_A'))->assertOk();
        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('interactive_no'))->assertOk();
        FakeWhatsAppService::$sent = [];
        $this->assertEquals(2, Incident::count());

        // Un message de suivi pendant la clarification reste une correction.
        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->textPayload(
            'Où en est mon dossier, le bloc B aussi fuit ?',
            '237600112233',
            'wamid.SUIVI_CLAR_TXT'
        ));

        $this->assertEquals('clarification_applied', $results[0]['status'] ?? null);
        $this->assertEquals(2, Incident::count());

        // … puis le suivi passe au tour suivant (clé consommée par Oui).
        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('interactive_yes'))->assertOk();
        FakeWhatsAppService::$sent = [];

        $results = $service->handlePayload($this->textPayload(
            'Où en est mon dossier ?',
            '237600112233',
            'wamid.SUIVI_CLAR_TXT2'
        ));
        $this->assertEquals('suivi', $results[0]['status'] ?? null);
        $this->assertNotEmpty($results[0]['incident_id'] ?? null);
    }
}
