<?php

namespace Tests\Feature;

use App\Models\School;
use App\Models\User;
use App\Notifications\CriticalIncidentNotification;
use App\Services\IncidentTriageService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Notification;
use Tests\TestCase;

class CriticalIncidentNotificationTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        $this->seed(\Database\Seeders\WashRoleSeeder::class);
    }

    public function test_critical_incident_notifies_admins_and_agents(): void
    {
        Notification::fake();
        Http::fake(['*' => Http::response(null, 500)]);

        $admin = User::factory()->create();
        $admin->assignRole('wash_admin');
        $tech = User::factory()->create();
        $tech->assignRole('maintenance_agent');
        $reporter = User::factory()->create();
        $reporter->assignRole('school_reporter');

        $school = School::create([
            'name' => 'École de Bonanjo', 'code' => 'DOU-BON-001', 'district' => 'Wouri',
        ]);

        app(IncidentTriageService::class)->ingest(
            $school, 'text', 'Urgent pompe cassée, 200 élèves sans eau !', null, null
        );

        Notification::assertSentTo($admin, CriticalIncidentNotification::class);
        Notification::assertSentTo($tech, CriticalIncidentNotification::class);
        Notification::assertNotSentTo($reporter, CriticalIncidentNotification::class);
    }

    public function test_non_critical_incident_sends_nothing(): void
    {
        Notification::fake();
        Http::fake(['*' => Http::response(null, 500)]);

        $admin = User::factory()->create();
        $admin->assignRole('wash_admin');
        $school = School::create([
            'name' => 'École de Bali', 'code' => 'DOU-BAL-003', 'district' => 'Wouri',
        ]);

        app(IncidentTriageService::class)->ingest($school, 'text', 'Petite fuite au robinet du préau.', null, null);

        Notification::assertNothingSent();
    }
}
