<?php

namespace Tests\Feature;

use App\Contracts\WhatsAppClient;
use App\Models\Incident;
use App\Models\IncidentSubscription;
use App\Models\MaintenanceLog;
use App\Models\School;
use App\Models\SchoolContact;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Laravel\Sanctum\Sanctum;
use Spatie\Permission\Models\Permission;
use Tests\Support\FakeWhatsAppService;
use Tests\TestCase;

class WashIncidentProgressTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        FakeWhatsAppService::reset();
        $this->app->bind(WhatsAppClient::class, FakeWhatsAppService::class);
        config(['whatsapp.simulator' => true]);
    }

    protected function seedContact(string $phone = '237600112233'): School
    {
        $school = School::create([
            'name' => 'École de Bonanjo', 'code' => 'DOU-BON-001', 'district' => 'Wouri',
        ]);
        SchoolContact::create([
            'school_id' => $school->id, 'phone' => $phone,
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
            'status' => 'triaged',
            'urgency' => 'medium',
        ], $overrides));
    }

    protected function subscribe(Incident $incident, string $phone = '237600112233'): IncidentSubscription
    {
        return IncidentSubscription::create([
            'incident_id' => $incident->id,
            'channel' => 'whatsapp',
            'recipient' => $phone,
            'locale' => 'fr',
            'is_active' => true,
        ]);
    }

    protected function actingMaintainer(): void
    {
        Permission::findOrCreate('update incident status', 'web');
        $user = \App\Models\User::factory()->create();
        $user->givePermissionTo('update incident status');
        Sanctum::actingAs($user);
    }

    protected function lastTextTo(string $phone): ?string
    {
        $texts = array_values(array_filter(
            FakeWhatsAppService::$sent,
            fn ($m) => ($m['type'] ?? '') === 'text' && ($m['to'] ?? '') === $phone
        ));

        return $texts === [] ? null : $texts[count($texts) - 1]['message'];
    }

    public function test_status_change_notifies_subscriber(): void
    {
        $school = $this->seedContact();
        $incident = $this->seedIncident($school);
        $this->subscribe($incident);
        $this->actingMaintainer();

        $this->patchJson("/api/v1/wash/incidents/{$incident->id}/status", ['status' => 'resolved'])
            ->assertOk();

        $message = $this->lastTextTo('237600112233');
        $this->assertNotNull($message, 'Aucun WhatsApp envoyé au directeur abonné.');
        $this->assertStringContainsString('WASH-2026-TEST01', $message);
        $this->assertStringContainsString('résolu', mb_strtolower($message));
    }

    public function test_maintenance_log_notifies_subscriber(): void
    {
        $school = $this->seedContact();
        $incident = $this->seedIncident($school);
        $this->subscribe($incident);

        MaintenanceLog::create([
            'incident_id' => $incident->id,
            'school_id' => $school->id,
            'cost_amount' => 50000,
            'currency' => 'XAF',
            'notes' => 'Joint de pompe remplacé',
        ]);

        $message = $this->lastTextTo('237600112233');
        $this->assertNotNull($message, 'Aucun WhatsApp envoyé à la journalisation.');
        $this->assertStringContainsString('WASH-2026-TEST01', $message);
        $this->assertStringContainsString('50 000', $message);
    }

    public function test_no_subscription_no_notification(): void
    {
        $school = $this->seedContact();
        $incident = $this->seedIncident($school);

        $incident->update(['status' => 'resolved']);

        $this->assertSame([], FakeWhatsAppService::$sent);
    }

    public function test_failed_send_never_breaks_request(): void
    {
        $school = $this->seedContact();
        $incident = $this->seedIncident($school);
        $sub = $this->subscribe($incident);
        FakeWhatsAppService::$failSend = true;
        $this->actingMaintainer();

        $this->patchJson("/api/v1/wash/incidents/{$incident->id}/status", ['status' => 'resolved'])
            ->assertOk();

        $this->assertSame('resolved', $incident->fresh()->status);
        $this->assertNotNull($sub->fresh()->last_error);
    }

    public function test_stop_unsubscribes_phone(): void
    {
        $school = $this->seedContact();
        $incident = $this->seedIncident($school);
        $sub = $this->subscribe($incident);

        $payload = json_decode(file_get_contents(base_path('tests/Fixtures/whatsapp/text.json')), true);
        $payload['entry'][0]['changes'][0]['value']['messages'][0] = [
            'from' => '237600112233',
            'id' => 'wamid.STOP001',
            'timestamp' => '1760000000',
            'type' => 'text',
            'text' => ['body' => 'STOP'],
        ];
        $this->postJson('/api/v1/whatsapp/webhook', $payload)->assertOk();

        $this->assertFalse($sub->fresh()->is_active);
        $message = $this->lastTextTo('237600112233');
        $this->assertNotNull($message);
        $this->assertStringContainsString('plus de messages', mb_strtolower($message));
    }

    public function test_template_fallback_on_131047_window_error(): void
    {
        $school = $this->seedContact();
        $incident = $this->seedIncident($school);
        $this->subscribe($incident);
        config(['whatsapp.progress_template' => 'wash_progress_fr']);
        FakeWhatsAppService::$sendError = new \RuntimeException('(#131047) Re-engagement message');

        $incident->update(['status' => 'in_progress']);

        $templates = array_values(array_filter(
            FakeWhatsAppService::$sent,
            fn ($m) => ($m['type'] ?? '') === 'template'
        ));
        $this->assertNotEmpty($templates, 'Aucun template envoyé après erreur 131047.');
        $this->assertSame('wash_progress_fr', $templates[0]['template']);
        $this->assertContains('WASH-2026-TEST01', $templates[0]['params']);
    }
}
