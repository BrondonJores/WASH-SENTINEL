<?php

namespace Tests\Feature;

use App\Contracts\WhatsAppClient;
use App\Models\Incident;
use App\Models\Report;
use App\Models\School;
use App\Models\SchoolContact;
use App\Services\MetaWhatsAppService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Notification;
use Tests\Support\FakeWhatsAppService;
use Tests\TestCase;

class WashWhatsAppTest extends TestCase
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

    protected function fakeTriage(): void
    {
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

    public function test_verify_returns_challenge_with_valid_token(): void
    {
        config(['whatsapp.verify_token' => 'secret-token']);

        $this->get('/api/v1/whatsapp/webhook?hub_mode=subscribe&hub_verify_token=secret-token&hub_challenge=CHALLENGE123')
            ->assertOk()
            ->assertSee('CHALLENGE123', false);
    }

    public function test_verify_rejects_bad_token(): void
    {
        config(['whatsapp.verify_token' => 'secret-token']);

        $this->get('/api/v1/whatsapp/webhook?hub_mode=subscribe&hub_verify_token=wrong&hub_challenge=CHALLENGE123')
            ->assertForbidden();
    }

    public function test_text_message_creates_whatsapp_report(): void
    {
        $this->seedContact();
        $this->fakeTriage();

        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('text'))
            ->assertOk()
            ->assertJson(['received' => true]);

        $report = Report::first();
        $this->assertNotNull($report);
        $this->assertEquals('whatsapp', $report->source);
        $this->assertEquals('text', $report->channel);
        $this->assertStringContainsStringIgnoringCase('robinet', $report->raw_content);

        $this->assertCount(1, FakeWhatsAppService::$sent);
        $this->assertEquals('237600112233', FakeWhatsAppService::$sent[0]['to']);
        $this->assertStringContainsString('enregistré', FakeWhatsAppService::$sent[0]['message']);
    }

    public function test_audio_message_uses_voice_channel(): void
    {
        config(['filesystems.disks.public.root' => sys_get_temp_dir() . '/wash-test-public']);
        $this->seedContact();
        $this->fakeTriage();

        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('audio'))
            ->assertOk();

        $report = Report::first();
        $this->assertNotNull($report);
        $this->assertEquals('whatsapp', $report->source);
        $this->assertEquals('voice', $report->channel);
        $this->assertNotNull($report->audio_path);
    }

    public function test_audio_message_sends_confirmation_buttons(): void
    {
        config(['filesystems.disks.public.root' => sys_get_temp_dir() . '/wash-test-public']);
        $this->seedContact();
        $this->fakeTriage();

        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('audio'))
            ->assertOk();

        $interactive = array_values(array_filter(
            FakeWhatsAppService::$sent,
            fn ($m) => ($m['type'] ?? '') === 'interactive'
        ));
        $this->assertCount(1, $interactive);
        $ids = array_column($interactive[0]['buttons'] ?? [], 'id');
        $this->assertContains('wash_oui', $ids);
        $this->assertContains('wash_non', $ids);
    }

    public function test_yes_button_confirms_pending_incident(): void
    {
        config(['filesystems.disks.public.root' => sys_get_temp_dir() . '/wash-test-public']);
        $this->seedContact();
        $this->fakeTriage();

        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('audio'))->assertOk();
        $incident = Incident::first();
        $this->assertNotNull($incident);
        $this->assertNotContains('confirme-usager', $incident->ai_tags ?? []);

        FakeWhatsAppService::$sent = [];
        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('interactive_yes'))
            ->assertOk();

        $this->assertContains('confirme-usager', $incident->fresh()->ai_tags ?? []);
        $last = end(FakeWhatsAppService::$sent);
        $this->assertStringContainsString('confirmé', $last['message']);
    }

    public function test_no_button_asks_one_short_question(): void
    {
        config(['filesystems.disks.public.root' => sys_get_temp_dir() . '/wash-test-public']);
        $this->seedContact();
        $this->fakeTriage();

        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('audio'))->assertOk();

        FakeWhatsAppService::$sent = [];
        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('interactive_no'))
            ->assertOk();

        $this->assertCount(1, FakeWhatsAppService::$sent);
        $question = FakeWhatsAppService::$sent[0]['message'];
        $this->assertStringContainsString('Que dois-je corriger', $question);
        $this->assertLessThan(120, mb_strlen($question));
    }

    public function test_legacy_services_keys_still_honored_when_canonical_absent(): void
    {
        config([
            'whatsapp.simulator' => null,
            'whatsapp.verify_token' => null,
            'whatsapp.app_secret' => null,
            'services.whatsapp.simulator' => true,
            'services.whatsapp.verify_token' => 'legacy-token',
            'services.whatsapp.app_secret' => '',
        ]);

        $service = app(\App\Services\MetaWhatsAppService::class);
        $this->assertTrue($service->isSimulator());
        $this->assertTrue($service->verifySignature('body', null));

        $this->getJson('/api/v1/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=legacy-token&hub.challenge=abc')
            ->assertOk()
            ->assertSee('abc', false);
    }

    public function test_unknown_number_gets_registration_reply(): void
    {
        $this->fakeTriage();

        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('unknown'))
            ->assertOk();

        $this->assertEquals(0, Incident::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $this->assertStringContainsString('aucune école', FakeWhatsAppService::$sent[0]['message']);
    }

    public function test_bad_signature_is_rejected_when_not_simulator(): void
    {
        config(['whatsapp.simulator' => false]);
        config(['whatsapp.app_secret' => 'test-secret']);

        $raw = json_encode($this->fixture('text'));
        $this->call('POST', '/api/v1/whatsapp/webhook', [], [], [], [
            'CONTENT_TYPE' => 'application/json',
            'HTTP_X-Hub-Signature-256' => 'sha256=invalid',
        ], $raw)->assertForbidden();

        $valid = 'sha256=' . hash_hmac('sha256', $raw, 'test-secret');
        $this->seedContact();
        $this->fakeTriage();
        $this->call('POST', '/api/v1/whatsapp/webhook', [], [], [], [
            'CONTENT_TYPE' => 'application/json',
            'HTTP_X-Hub-Signature-256' => $valid,
        ], $raw)->assertOk();
        $this->assertEquals(1, Incident::count());
    }

    public function test_empty_secret_is_closed_in_live_mode(): void
    {
        config(['whatsapp.simulator' => false]);
        config(['whatsapp.app_secret' => '', 'services.whatsapp.app_secret' => '']);
        $this->assertFalse((new MetaWhatsAppService())->verifySignature('{}', null));

        config(['whatsapp.simulator' => true]);
        $this->assertTrue((new MetaWhatsAppService())->verifySignature('{}', null));
    }

    public function test_download_media_survives_dns_blips(): void
    {
        config([
            'whatsapp.simulator' => false,
            'whatsapp.token' => 'test-token',
            'whatsapp.base_url' => 'https://graph.facebook.com/v21.0',
        ]);
        $attempts = 0;
        Http::fake(function ($request) use (&$attempts) {
            if (str_contains($request->url(), 'graph.facebook.com/v21.0/MEDIA123')) {
                $attempts++;
                if ($attempts < 3) {
                    throw new \Illuminate\Http\Client\ConnectionException('Could not resolve host');
                }

                return Http::response(['url' => 'https://cdn.test/MEDIA123', 'mime_type' => 'audio/ogg'], 200);
            }

            return Http::response('OGG-BYTES', 200);
        });

        $media = (new MetaWhatsAppService())->downloadMedia('MEDIA123');

        $this->assertEquals(3, $attempts);
        $this->assertEquals('OGG-BYTES', $media['bytes']);
        $this->assertEquals('audio/ogg', $media['mime']);
    }

    public function test_receive_records_last_webhook_at(): void
    {
        $this->seedContact();
        $this->fakeTriage();
        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('text'))->assertOk();

        $at = Cache::get('wash.whatsapp.last_webhook_at');
        $this->assertNotNull($at);
        $this->getJson('/api/v1/whatsapp/diagnostics')->assertJsonPath('last_webhook_at', $at);
    }

    public function test_redelivery_same_wamid_creates_single_incident(): void
    {
        $this->seedContact();
        $this->fakeTriage();

        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('text'))
            ->assertOk()
            ->assertJson(['received' => true]);
        $this->assertEquals(1, Incident::count());

        // Relivraison Meta (retry, même wamid) : accusé, sans doublon ni 2e envoi.
        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('text'))
            ->assertOk()
            ->assertJson(['received' => true, 'status' => 'duplicate_delivery']);

        $this->assertEquals(1, Incident::count());
        $this->assertEquals(1, Report::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
        // Diagnostics non cassés : horodaté même sur relivraison.
        $this->assertNotNull(Cache::get('wash.whatsapp.last_webhook_at'));
        $this->assertTrue(Cache::has('wash.whatsapp.seen.wamid.TEXT001'));
    }

    public function test_different_wamids_create_two_incidents(): void
    {
        $this->seedContact();
        $this->fakeTriage();

        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('text'))->assertOk();

        $second = $this->fixture('text');
        $second['entry'][0]['changes'][0]['value']['messages'][0]['id'] = 'wamid.TEXT002';
        $second['entry'][0]['changes'][0]['value']['messages'][0]['text']['body'] = 'Les toilettes du bloc B sont bouchées, ça déborde.';
        $this->postJson('/api/v1/whatsapp/webhook', $second)->assertOk();

        $this->assertEquals(2, Incident::count());
        $this->assertEquals(2, Report::count());
        $this->assertCount(2, FakeWhatsAppService::$sent);
    }

    public function test_service_dedupes_job_retry_without_resend(): void
    {
        $this->seedContact();
        $this->fakeTriage();

        $service = app(\App\Services\WashWhatsAppService::class);

        $first = $service->handlePayload($this->fixture('text'));
        $this->assertEquals('triaged', $first[0]['status'] ?? null);
        $this->assertEquals(1, Incident::count());

        // Rejeu du même payload (retry job) : ni triage ni envoi.
        $second = $service->handlePayload($this->fixture('text'));
        $this->assertEquals('duplicate_delivery', $second[0]['status'] ?? null);
        $this->assertEquals(1, Incident::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
    }

    // --------------------------------------------------------------
    // Blindage cas extrêmes : retries Graph API honnêtes, list_reply,
    // idempotence intra-payload.
    // --------------------------------------------------------------

    protected function liveGraphConfig(): void
    {
        config([
            'whatsapp.simulator' => false,
            'whatsapp.token' => 'test-token',
            'whatsapp.phone_number_id' => '999',
            'whatsapp.base_url' => 'https://graph.facebook.com/v21.0',
        ]);
    }

    public function test_rate_limit_429_is_retried_then_succeeds(): void
    {
        $this->liveGraphConfig();
        $attempts = 0;
        Http::fake(function () use (&$attempts) {
            $attempts++;

            return $attempts < 3
                ? Http::response(['error' => 'rate limited'], 429)
                : Http::response(['messages' => [['id' => 'wamid.LIVE429']]], 200);
        });

        $response = (new MetaWhatsAppService())->sendText('237600112233', 'Merci !');

        $this->assertEquals('wamid.LIVE429', $response['messages'][0]['id']);
        $this->assertEquals(3, $attempts);
    }

    public function test_server_500_is_retried_then_succeeds(): void
    {
        $this->liveGraphConfig();
        $attempts = 0;
        Http::fake(function () use (&$attempts) {
            $attempts++;

            return $attempts < 2
                ? Http::response('Meta incident', 500)
                : Http::response(['messages' => [['id' => 'wamid.LIVE500']]], 200);
        });

        $response = (new MetaWhatsAppService())->sendText('237600112233', 'Merci !');

        $this->assertEquals('wamid.LIVE500', $response['messages'][0]['id']);
        $this->assertEquals(2, $attempts);
    }

    public function test_token_expiry_401_is_not_retried(): void
    {
        $this->liveGraphConfig();
        $attempts = 0;
        Http::fake(function () use (&$attempts) {
            $attempts++;

            return Http::response(['error' => ['message' => 'expired token', 'code' => 190]], 401);
        });

        try {
            (new MetaWhatsAppService())->sendText('237600112233', 'Merci !');
            $this->fail('401 attendu.');
        } catch (\Illuminate\Http\Client\RequestException $e) {
            $this->assertEquals(401, $e->response->status());
        }
        $this->assertEquals(1, $attempts);
    }

    public function test_media_404_is_not_retried(): void
    {
        $this->liveGraphConfig();
        $attempts = 0;
        Http::fake(function () use (&$attempts) {
            $attempts++;

            return Http::response(['error' => 'not found'], 404);
        });

        try {
            (new MetaWhatsAppService())->downloadMedia('MEDIA_DEAD');
            $this->fail('404 attendu.');
        } catch (\Illuminate\Http\Client\RequestException $e) {
            $this->assertEquals(404, $e->response->status());
        }
        $this->assertEquals(1, $attempts);
    }

    public function test_list_reply_yes_confirms_pending_incident(): void
    {
        config(['filesystems.disks.public.root' => sys_get_temp_dir() . '/wash-test-public']);
        $this->seedContact();
        $this->fakeTriage();

        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('audio'))->assertOk();
        $incident = Incident::first();
        $this->assertNotNull($incident);

        // Même contrat id via list_reply (listes Meta) que button_reply.
        $list = $this->fixture('interactive_yes');
        $list['entry'][0]['changes'][0]['value']['messages'][0]['id'] = 'wamid.LIST_YES_001';
        $list['entry'][0]['changes'][0]['value']['messages'][0]['interactive'] = [
            'type' => 'list_reply',
            'list_reply' => ['id' => 'wash_oui', 'title' => 'Oui'],
        ];
        FakeWhatsAppService::$sent = [];
        $this->postJson('/api/v1/whatsapp/webhook', $list)->assertOk();

        $this->assertContains('confirme-usager', $incident->fresh()->ai_tags ?? []);
        $last = end(FakeWhatsAppService::$sent);
        $this->assertStringContainsString('confirmé', $last['message']);
    }

    public function test_same_wamid_twice_in_one_payload_is_processed_once(): void
    {
        $this->seedContact();
        $this->fakeTriage();

        $payload = $this->fixture('text');
        $message = $payload['entry'][0]['changes'][0]['value']['messages'][0];
        $payload['entry'][0]['changes'][0]['value']['messages'] = [$message, $message];

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($payload);

        $this->assertCount(2, $results);
        $this->assertEquals('triaged', $results[0]['status'] ?? null);
        $this->assertEquals('duplicate_delivery', $results[1]['status'] ?? null);
        $this->assertEquals(1, Incident::count());
        $this->assertEquals(1, Report::count());
        $this->assertCount(1, FakeWhatsAppService::$sent);
    }
}
