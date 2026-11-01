<?php

namespace Tests\Feature;

use App\Contracts\WhatsAppClient;
use App\Models\Incident;
use App\Models\Report;
use App\Models\School;
use App\Models\SchoolContact;
use App\Services\MetaWhatsAppService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Notification;
use Tests\Support\FakeWhatsAppService;
use Tests\TestCase;

class WashWhatsAppGuidanceTest extends TestCase
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

    protected function textPayload(string $body, string $from = '237600112233', string $id = 'wamid.GUIDE001'): array
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

    protected function triageResponse()
    {
        return Http::response([
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
        ], 200);
    }

    protected function fakeTriage(): void
    {
        Http::fake(['*/v1/wash/triage' => $this->triageResponse()]);
    }

    protected function fakeDuplicate(int $incidentId): void
    {
        Http::fake([
            '*/v1/wash/triage' => $this->triageResponse(),
            '*/v1/wash/check-duplicates' => Http::response([
                'is_duplicate' => true,
                'matched_incident_id' => $incidentId,
                'similarity_score' => 0.95,
            ], 200),
        ]);
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

    public function test_unknown_school_gets_guided_ecole_reply(): void
    {
        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('unknown'))->assertOk();

        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('aucune école', $reply);
        $this->assertStringContainsString('ECOLE', $reply);
        $this->assertStringContainsString('De quelle école parlez-vous', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_unknown_school_with_ecole_format_is_acknowledged(): void
    {
        $this->postJson(
            '/api/v1/whatsapp/webhook',
            $this->textPayload('ECOLE Collège Saint-Michel', '237699999999', 'wamid.GUIDE002')
        )->assertOk();

        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('Collège Saint-Michel', $reply);
        $this->assertStringContainsString('aucune école', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_unreadable_audio_gets_guided_reply(): void
    {
        $this->seedContact();
        FakeWhatsAppService::$media['MEDIA_AUDIO_1'] = [
            'bytes' => '', 'mime' => 'audio/ogg', 'filename' => 'wa-empty.ogg',
        ];

        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('audio'))->assertOk();

        $this->assertEquals(0, Incident::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString("pas compris", $reply);
        $this->assertStringContainsString('Réenregistrez', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_duplicate_gets_guided_reply(): void
    {
        $this->seedContact();
        $this->fakeTriage();
        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('text'))->assertOk();
        $this->assertEquals(1, Incident::count());
        $reference = Incident::first()->reference_code;

        $this->fakeDuplicate(Incident::first()->id);
        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload(
            'Le robinet du bloc A fuit toujours autant.',
            '237600112233',
            'wamid.GUIDE003'
        ))->assertOk();

        $this->assertEquals(1, Incident::count());
        $this->assertCount(2, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[1]['message'];
        $this->assertStringContainsString('Déjà reçu', $reply);
        $this->assertStringContainsString($reference, $reply);
        $this->assertStringContainsString('suivi', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_off_topic_gets_guided_reply_with_examples(): void
    {
        $this->seedContact();

        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload(
            'Quel est le menu de la cantine demain ?',
            '237600112233',
            'wamid.GUIDE004'
        ))->assertOk();

        $this->assertEquals(0, Incident::count());
        $this->assertEquals(0, Report::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('robinet', $reply);
        $this->assertStringContainsString('toilettes', $reply);
        $this->assertStringContainsString('savon', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_creation_ok_gets_recap_reference_and_next_steps(): void
    {
        $this->seedContact();
        $this->fakeTriage();

        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('text'))->assertOk();

        $incident = Incident::first();
        $this->assertNotNull($incident);
        $this->assertStringStartsWith('WASH-', $incident->reference_code);

        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('enregistré', $reply);
        $this->assertStringContainsString($incident->reference_code, $reply);
        $this->assertStringContainsString('Fuite sur un robinet', $reply);
        $this->assertStringContainsString('La suite', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_simulator_path_sends_without_http_call(): void
    {
        config(['whatsapp.simulator' => true]);
        Http::fake();

        $response = (new MetaWhatsAppService())->sendText(
            '237600112233', 'Déjà reçu ! Incident WASH-2026-ABCDEF suivi par nos équipes.'
        );

        $this->assertStringStartsWith('sim-', $response['messages'][0]['id']);
        Http::assertNothingSent();
    }

    public function test_live_path_posts_guided_text_to_graph_api(): void
    {
        config([
            'whatsapp.simulator' => false,
            'whatsapp.token' => 'test-token',
            'whatsapp.phone_number_id' => '999',
        ]);
        Http::fake([
            '*' => Http::response(['messages' => [['id' => 'wamid.LIVE001']]], 200),
        ]);

        (new MetaWhatsAppService())->sendText(
            '237600112233', 'Merci ! Incident WASH-2026-ABCDEF enregistré : fuite.'
        );

        Http::assertSent(fn ($request) => str_contains($request->url(), '999/messages')
            && ($request['text']['body'] ?? '') === 'Merci ! Incident WASH-2026-ABCDEF enregistré : fuite.');
    }

    public function test_oversized_audio_gets_guided_reply_without_incident(): void
    {
        // Le faux média fait 22 o ('fake-voice-note-bytes') : plafond à 10 o.
        config(['whatsapp.max_media_bytes' => 10]);
        $this->seedContact();

        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('audio'))->assertOk();

        $this->assertEquals(0, Incident::count());
        $this->assertEquals(0, Report::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('trop lourde', $reply);
        $this->assertStringContainsString('renvoie plus court', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_oversized_photo_gets_guided_reply_without_incident(): void
    {
        config(['whatsapp.max_media_bytes' => 10]);
        $this->seedContact();
        FakeWhatsAppService::$media['MEDIA_PHOTO_BIG'] = [
            'bytes' => str_repeat('x', 64), 'mime' => 'image/jpeg', 'filename' => 'wa-big.jpg',
        ];

        $payload = $this->fixture('audio');
        $payload['entry'][0]['changes'][0]['value']['messages'][0] = [
            'from' => '237600112233',
            'id' => 'wamid.PHOTO_BIG_001',
            'timestamp' => '1760000000',
            'type' => 'image',
            'image' => ['id' => 'MEDIA_PHOTO_BIG', 'mime_type' => 'image/jpeg', 'caption' => 'fuite au bloc A'],
        ];

        $this->postJson('/api/v1/whatsapp/webhook', $payload)->assertOk();

        $this->assertEquals(0, Incident::count());
        $this->assertEquals(0, Report::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $reply = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('trop lourde', $reply);
        $this->assertStringContainsString('plus légère', $reply);
        $this->assertLessThan(400, mb_strlen($reply));
    }

    public function test_oversized_declared_size_rejected_before_body(): void
    {
        $this->seedContact();
        // Taille déclarée (métadonnées) > plafond par défaut (10 Mo),
        // même avec un petit corps : rejeté sans incident.
        FakeWhatsAppService::$media['MEDIA_AUDIO_BIG'] = [
            'bytes' => 'tiny', 'mime' => 'audio/ogg', 'filename' => 'wa-big.ogg',
            'file_size' => 20 * 1024 * 1024,
        ];

        $payload = $this->fixture('audio');
        $payload['entry'][0]['changes'][0]['value']['messages'][0]['id'] = 'wamid.AUDIO_BIG_001';
        $payload['entry'][0]['changes'][0]['value']['messages'][0]['audio']['id'] = 'MEDIA_AUDIO_BIG';

        $this->postJson('/api/v1/whatsapp/webhook', $payload)->assertOk();

        $this->assertEquals(0, Incident::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $this->assertStringContainsString('trop lourde', FakeWhatsAppService::$sent[0]['message']);
    }
}
