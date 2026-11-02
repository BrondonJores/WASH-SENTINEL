<?php

namespace Tests\Feature;

use App\Contracts\WhatsAppClient;
use App\Models\Incident;
use App\Models\School;
use App\Models\SchoolContact;
use App\Services\WashWhatsAppService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Facades\Notification;
use Tests\Support\FakeWhatsAppService;
use Tests\TestCase;

/**
 * Câblage détection de langue : choix FR/EN demandé une seule fois quand le
 * texte est incertain SANS langue mémorisée (rejeu du texte, anti-boucle),
 * et langue acoustique DÉTECTÉE mémorisée pour les vocaux (jamais
 * language_effective). Le détecté non fr/en ne bascule rien (phrasebook).
 */
class WashWhatsAppLangChoiceTest extends TestCase
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

    protected function textPayload(string $body, string $from = '237600112233', string $id = 'wamid.LANGC01'): array
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
        return Http::response(['audio_base64' => base64_encode('fake-audio')], 200);
    }

    protected function sentTexts(): array
    {
        return array_values(array_filter(
            FakeWhatsAppService::$sent,
            fn ($m) => ($m['type'] ?? '') === 'text'
        ));
    }

    protected function rememberedLang(string $from = '237600112233'): ?string
    {
        $reflection = new \ReflectionMethod(WashWhatsAppService::class, 'rememberedLang');
        $reflection->setAccessible(true);

        return $reflection->invokeArgs(app(WashWhatsAppService::class), [$from]);
    }

    /** « Citerne vide » : indice WASH, aucun marqueur FR/EN → incertain. */
    public function test_uncertain_text_without_memory_asks_once(): void
    {
        $this->seedContact();
        Http::fake(['*/v1/wash/triage' => $this->triageResponse()]);

        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload('Citerne vide'))->assertOk();

        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $this->assertStringContainsString('En quelle langue préférez-vous continuer', $texts[0]['message']);
        $this->assertSame(0, Incident::count());
        $this->assertNull($this->rememberedLang());
    }

    public function test_lang_choice_replays_pending_text(): void
    {
        $this->seedContact();
        Http::fake(['*/v1/wash/triage' => $this->triageResponse()]);

        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload('Citerne vide', '237600112233', 'wamid.LANGC10'))->assertOk();
        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload('EN', '237600112233', 'wamid.LANGC11'))->assertOk();

        // Choix persisté + texte rejoué : incident créé, réponse EN.
        $this->assertSame(1, Incident::count());
        $this->assertSame('en', $this->rememberedLang());
        $texts = $this->sentTexts();
        $last = end($texts);
        $this->assertStringContainsString('Thanks! Case', $last['message']);
    }

    public function test_lang_choice_fr_flows_french(): void
    {
        $this->seedContact();
        Http::fake(['*/v1/wash/triage' => $this->triageResponse()]);

        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload('Citerne vide', '237600112233', 'wamid.LANGC20'))->assertOk();
        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload('fr', '237600112233', 'wamid.LANGC21'))->assertOk();

        $this->assertSame(1, Incident::count());
        $this->assertSame('fr', $this->rememberedLang());
    }

    public function test_new_content_instead_of_choice_moves_on_without_reask(): void
    {
        $this->seedContact();
        Http::fake(['*/v1/wash/triage' => $this->triageResponse()]);

        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload('Citerne vide', '237600112233', 'wamid.LANGC30'))->assertOk();
        // Nouveau contenu (pas FR/EN) : trié aussitôt, question jamais reposée.
        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload('Citerne vide toujours', '237600112233', 'wamid.LANGC31'))->assertOk();

        $this->assertSame(1, Incident::count());
        $asks = array_filter(
            $this->sentTexts(),
            fn ($m) => str_contains($m['message'], 'En quelle langue préférez-vous continuer')
        );
        $this->assertCount(1, $asks);
    }

    public function test_suivi_state_not_hijacked_by_lang_ask(): void
    {
        $school = $this->seedContact();
        Incident::create([
            'school_id' => $school->id,
            'reference_code' => 'WASH-2026-TEST01',
            'title' => 'Fuite robinet bloc A',
            'ai_summary' => 'Fuite robinet bloc A',
            'status' => 'in_progress',
            'urgency' => 'medium',
        ]);
        Http::fake(['*/v1/wash/triage' => $this->triageResponse()]);

        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload('suivre mon dossier', '237600112233', 'wamid.LANGC40'))->assertOk();
        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload('NON', '237600112233', 'wamid.LANGC41'))->assertOk();
        // Slot école sans marqueur ni mémoire : le suivi continue, pas de question langue.
        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload('Bonanjo', '237600112233', 'wamid.LANGC42'))->assertOk();

        $texts = $this->sentTexts();
        $last = end($texts);
        $this->assertStringContainsString('Quel jour', $last['message']);
        foreach ($texts as $sent) {
            $this->assertStringNotContainsString('En quelle langue préférez-vous continuer', $sent['message']);
        }
    }

    public function test_voice_detected_english_replies_english(): void
    {
        config(['filesystems.disks.public.root' => sys_get_temp_dir() . '/wash-test-public']);
        $this->seedContact();
        Http::fake([
            '*/v1/wash/triage' => $this->triageResponse(),
            '*/v1/voice/transcribe' => Http::response([
                'transcript' => 'hm hm',
                'language_detected' => 'en',
            ], 200),
            '*/v1/voice/synthesize' => $this->synthesizeResponse(),
        ]);

        $this->postJson('/api/v1/whatsapp/webhook', $this->audioPayload('wamid.LANGC50'))->assertOk();

        $this->assertSame('en', $this->rememberedLang());
        $texts = $this->sentTexts();
        $this->assertStringContainsString('Thanks! Case', $texts[0]['message']);
    }

    public function test_voice_transcription_logs_stt_driver(): void
    {
        Log::spy();
        config(['filesystems.disks.public.root' => sys_get_temp_dir().'/wash-test-public']);
        $this->seedContact();
        Http::fake([
            '*/v1/wash/triage' => $this->triageResponse(),
            '*/v1/voice/transcribe' => Http::response([
                'transcript' => 'fuite robinet',
                'language_detected' => 'fr',
                'driver' => 'meta_transcribe',
                'detection' => ['mode' => 'direct'],
            ], 200),
            '*/v1/voice/synthesize' => $this->synthesizeResponse(),
        ]);

        $this->postJson('/api/v1/whatsapp/webhook', $this->audioPayload('wamid.LANGC70'))->assertOk();

        Log::shouldHaveReceived('info')->with('WhatsApp STT transcribed', \Mockery::on(
            fn ($ctx) => ($ctx['driver'] ?? null) === 'meta_transcribe'
        ))->once();
    }

    public function test_voice_detected_bbj_keeps_default_flow(): void
    {
        config(['filesystems.disks.public.root' => sys_get_temp_dir() . '/wash-test-public']);
        $this->seedContact();
        Http::fake([
            '*/v1/wash/triage' => $this->triageResponse(),
            '*/v1/voice/transcribe' => Http::response([
                'transcript' => 'pou tshi lepom',
                'language_detected' => 'bbj_Latn',
            ], 200),
            '*/v1/voice/synthesize' => $this->synthesizeResponse(),
        ]);

        $this->postJson('/api/v1/whatsapp/webhook', $this->audioPayload('wamid.LANGC60'))->assertOk();

        // Pas de bascule mémoire sur langue non fr/en, flux FR par défaut, sans crash.
        $this->assertNull($this->rememberedLang());
        $this->assertSame(1, Incident::count());
    }
}
