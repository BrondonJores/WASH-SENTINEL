<?php

namespace Tests\Feature;

use App\Contracts\WhatsAppClient;
use App\Models\Incident;
use App\Models\School;
use App\Models\SchoolContact;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Notification;
use Tests\Support\FakeWhatsAppService;
use Tests\TestCase;

class WashWhatsAppEnglishTest extends TestCase
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

    protected function textPayload(string $body, string $from = '237600112233', string $id = 'wamid.EN001'): array
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

    protected function triageResponse()
    {
        return Http::response([
            'raw_text' => 'Tap leaking.',
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
        ], 200);
    }

    protected function synthesizeResponse()
    {
        return Http::response([
            'audio_base64' => base64_encode('fake-wav-bytes'),
            'mime_type' => 'audio/wav',
        ], 200);
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

    protected function sentTexts(): array
    {
        return array_values(array_filter(
            FakeWhatsAppService::$sent,
            fn ($m) => ($m['type'] ?? '') === 'text'
        ));
    }

    protected function sentInteractive(): array
    {
        return array_values(array_filter(
            FakeWhatsAppService::$sent,
            fn ($m) => ($m['type'] ?? '') === 'interactive'
        ));
    }

    protected function synthesizeRequests(): array
    {
        return Http::recorded(fn ($request) => str_contains($request->url(), '/v1/voice/synthesize'))->values()->all();
    }

    public function test_english_voice_report_gets_full_english_flow(): void
    {
        config(['filesystems.disks.public.root' => sys_get_temp_dir() . '/wash-test-public']);
        $this->seedContact();
        Http::fake([
            '*/v1/wash/triage' => $this->triageResponse(),
            '*/v1/voice/transcribe' => Http::response([
                'transcript' => 'Hello, this is Bonanjo school, the tap in block A is leaking, please help.',
                'language_effective' => 'fr',
            ], 200),
            '*/v1/voice/synthesize' => $this->synthesizeResponse(),
        ]);

        $this->postJson('/api/v1/whatsapp/webhook', $this->audioPayload('wamid.EN_VOC_001'))->assertOk();

        $incident = Incident::first();
        $this->assertNotNull($incident);

        // Récap EN (squelette EN ; vocal : résumé = transcript, non traduit).
        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $this->assertStringContainsString('Thanks! Case *' . $incident->reference_code . '* recorded', $texts[0]['message']);
        $this->assertStringContainsString('*Priority:* medium', $texts[0]['message']);
        $this->assertStringContainsString('our team is notified', $texts[0]['message']);
        $this->assertStringContainsString('the tap in block A is leaking', $texts[0]['message']);

        // Boutons Yes/No, ids inchangés.
        $interactive = $this->sentInteractive();
        $this->assertCount(1, $interactive);
        $this->assertStringContainsString('Is this correct?', $interactive[0]['message']);
        $titles = array_column($interactive[0]['buttons'] ?? [], 'title');
        $ids = array_column($interactive[0]['buttons'] ?? [], 'id');
        $this->assertContains('Yes', $titles);
        $this->assertContains('No', $titles);
        $this->assertContains('wash_oui', $ids);
        $this->assertContains('wash_non', $ids);

        // TTS demandé en anglais (jamais language_effective STT).
        $tts = $this->synthesizeRequests();
        $this->assertNotEmpty($tts);
        $this->assertSame('en', $tts[0][0]->data()['language']);
        $this->assertSame('en-medium', $tts[0][0]->data()['voice']);
        $this->assertStringContainsString('Thanks! Case', $tts[0][0]->data()['text']);

        // Note vocale envoyée.
        $audio = array_values(array_filter(
            FakeWhatsAppService::$sent,
            fn ($m) => ($m['type'] ?? '') === 'audio'
        ));
        $this->assertCount(1, $audio);
    }

    public function test_english_text_report_gets_english_reply(): void
    {
        $this->seedContact();
        Http::fake(['*/v1/wash/triage' => $this->triageResponse()]);

        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload(
            'Hello, the tap in block A is leaking, please send help.',
            '237600112233',
            'wamid.EN_TXT_001'
        ))->assertOk();

        $incident = Incident::first();
        $this->assertNotNull($incident);

        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $this->assertStringContainsString('Thanks! Case *' . $incident->reference_code . '* recorded', $texts[0]['message']);
        $this->assertStringContainsString('*Priority:* medium', $texts[0]['message']);
        // Squelette EN, résumé extracteur FR conservé (non traduit).
        $this->assertStringContainsString('Fuite sur un robinet.', $texts[0]['message']);
    }

    public function test_english_duplicate_gets_english_reply(): void
    {
        $this->seedContact();
        Http::fake(['*/v1/wash/triage' => $this->triageResponse()]);
        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload(
            'Hello, the tap in block A is leaking, please send help.',
            '237600112233',
            'wamid.EN_DUP_001'
        ))->assertOk();
        $reference = Incident::first()->reference_code;
        $this->assertEquals(1, Incident::count());

        Http::fake([
            '*/v1/wash/triage' => $this->triageResponse(),
            '*/v1/wash/check-duplicates' => Http::response([
                'is_duplicate' => true,
                'matched_incident_id' => Incident::first()->id,
                'similarity_score' => 0.95,
            ], 200),
        ]);
        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload(
            'Hello, the tap in block A is still leaking badly, thank you.',
            '237600112233',
            'wamid.EN_DUP_002'
        ))->assertOk();

        $this->assertEquals(1, Incident::count());
        $texts = $this->sentTexts();
        $this->assertCount(2, $texts);
        $this->assertStringContainsString('Already received!', $texts[1]['message']);
        $this->assertStringContainsString($reference, $texts[1]['message']);
    }

    public function test_yes_after_english_voice_confirms_in_english(): void
    {
        config(['filesystems.disks.public.root' => sys_get_temp_dir() . '/wash-test-public']);
        $this->seedContact();
        Http::fake([
            '*/v1/wash/triage' => $this->triageResponse(),
            '*/v1/voice/transcribe' => Http::response([
                'transcript' => 'Hello, this is Bonanjo school, the tap in block A is leaking.',
            ], 200),
        ]);

        $this->postJson('/api/v1/whatsapp/webhook', $this->audioPayload('wamid.EN_YES_001'))->assertOk();
        $incident = Incident::first();
        $this->assertNotNull($incident);

        FakeWhatsAppService::$sent = [];
        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('interactive_yes'))->assertOk();

        $this->assertContains('confirme-usager', $incident->fresh()->ai_tags ?? []);
        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $this->assertStringContainsString('Perfect, confirmed!', $texts[0]['message']);
        $this->assertStringContainsString($incident->reference_code, $texts[0]['message']);
    }

    public function test_no_then_english_correction_stays_english(): void
    {
        config(['filesystems.disks.public.root' => sys_get_temp_dir() . '/wash-test-public']);
        $this->seedContact();
        Http::fake([
            '*/v1/wash/triage' => $this->triageResponse(),
            '*/v1/voice/transcribe' => Http::response([
                'transcript' => 'Hello, this is Bonanjo school, the tap in block A is leaking.',
            ], 200),
        ]);

        $this->postJson('/api/v1/whatsapp/webhook', $this->audioPayload('wamid.EN_NO_001'))->assertOk();

        FakeWhatsAppService::$sent = [];
        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('interactive_no'))->assertOk();
        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $this->assertStringContainsString('What should I fix?', $texts[0]['message']);

        FakeWhatsAppService::$sent = [];
        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload(
            'Sorry, it is the toilet in block B, not block A.',
            '237600112233',
            'wamid.EN_CORR_001'
        ))->assertOk();

        $this->assertEquals(1, Incident::count());
        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $this->assertStringContainsString('Thanks! I fixed it', $texts[0]['message']);
        $this->assertStringContainsString('Is this correct?', $texts[0]['message']);

        $interactive = $this->sentInteractive();
        $this->assertCount(1, $interactive);
        $titles = array_column($interactive[0]['buttons'] ?? [], 'title');
        $this->assertContains('Yes', $titles);
        $this->assertContains('No', $titles);
    }

    public function test_french_voice_flow_unchanged(): void
    {
        config(['filesystems.disks.public.root' => sys_get_temp_dir() . '/wash-test-public']);
        $this->seedContact();
        Http::fake([
            '*/v1/wash/triage' => $this->triageResponse(),
            '*/v1/voice/transcribe' => Http::response([
                'transcript' => 'Bonjour, le robinet du bloc A fuit beaucoup depuis hier.',
            ], 200),
            '*/v1/voice/synthesize' => $this->synthesizeResponse(),
        ]);

        $this->postJson('/api/v1/whatsapp/webhook', $this->audioPayload('wamid.EN_FR_001'))->assertOk();

        $incident = Incident::first();
        $this->assertNotNull($incident);

        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $this->assertStringContainsString('enregistré', $texts[0]['message']);
        $this->assertStringContainsString('*Priorité :* moyenne', $texts[0]['message']);

        $interactive = $this->sentInteractive();
        $this->assertCount(1, $interactive);
        $titles = array_column($interactive[0]['buttons'] ?? [], 'title');
        $this->assertContains('Oui', $titles);
        $this->assertContains('Non', $titles);

        $tts = $this->synthesizeRequests();
        $this->assertNotEmpty($tts);
        $this->assertSame('fr', $tts[0][0]->data()['language']);
        $this->assertSame('fr_FR-upmc-medium', $tts[0][0]->data()['voice']);
    }

    // --------------------------------------------------------------
    // Blindage cas extrêmes : mélange FR/EN, guidage conservé.
    // --------------------------------------------------------------

    public function test_mixed_suivi_with_french_markers_stays_french(): void
    {
        $this->seedContact();
        Http::fake(['*/v1/wash/triage' => $this->triageResponse()]);

        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload(
            'Le robinet du bloc A fuit beaucoup.',
            '237600112233',
            'wamid.EN_MIXSUIVI_0'
        ))->assertOk();
        $this->assertEquals(1, Incident::count());

        // Mélange EN + marqueurs FR : le veto FR gagne, suivi en français.
        FakeWhatsAppService::$sent = [];
        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload(
            'Hello, où en est mon dossier ?',
            '237600112233',
            'wamid.EN_MIXSUIVI_1'
        ))->assertOk();

        $this->assertEquals(1, Incident::count());
        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $this->assertStringContainsString('Pour suivre votre dossier', $texts[0]['message']);
        $this->assertLessThan(400, mb_strlen($texts[0]['message']));
    }

    public function test_mixed_report_without_french_markers_gets_guided_reply(): void
    {
        $this->seedContact();
        Http::fake(['*/v1/wash/triage' => $this->triageResponse()]);

        // Marqueurs EN seuls (« tap », « please ») : réponse EN guidée,
        // jamais d'erreur générique ni de silence.
        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload(
            'Please, the tap in block A is leaking badly, thank you.',
            '237600112233',
            'wamid.EN_MIXGUIDE_1'
        ))->assertOk();

        $incident = Incident::first();
        $this->assertNotNull($incident);
        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $this->assertStringContainsString($incident->reference_code, $texts[0]['message']);
        $this->assertStringContainsString('Next:', $texts[0]['message']);
        $this->assertLessThan(400, mb_strlen($texts[0]['message']));
    }
}
