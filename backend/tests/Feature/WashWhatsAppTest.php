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

class WashWhatsAppTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        FakeWhatsAppService::reset();
        $this->app->bind(WhatsAppClient::class, FakeWhatsAppService::class);
        config(['services.whatsapp.simulator' => true]);
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
        config(['services.whatsapp.verify_token' => 'secret-token']);

        $this->get('/api/v1/whatsapp/webhook?hub_mode=subscribe&hub_verify_token=secret-token&hub_challenge=CHALLENGE123')
            ->assertOk()
            ->assertSee('CHALLENGE123', false);
    }

    public function test_verify_rejects_bad_token(): void
    {
        config(['services.whatsapp.verify_token' => 'secret-token']);

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
        config(['services.whatsapp.simulator' => false]);
        config(['services.whatsapp.app_secret' => 'test-secret']);

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
}
