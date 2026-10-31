<?php

namespace Tests\Feature;

use App\Models\Incident;
use App\Models\School;
use App\Models\User;
use App\Notifications\WashRelanceNotification;
use App\Services\WashRelanceService;
use Database\Seeders\WashRoleSeeder;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Notification;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class WashRelancesTest extends TestCase
{
    use RefreshDatabase;

    private const ENDPOINT = '/api/v1/wash/relances/dormants';

    private function makeUser(string $role, string $email): User
    {
        $user = User::factory()->create(['email' => $email]);
        $user->assignRole($role);

        return $user;
    }

    private function actingAsRole(string $role, string $email): User
    {
        $user = $this->makeUser($role, $email);
        Sanctum::actingAs($user);

        return $user;
    }

    private function makeSchool(): School
    {
        return School::create(['name' => 'EP Relance', 'code' => 'EP-REL-1', 'district' => 'Mvila']);
    }

    private function makeIncident(School $school, array $attrs = [], ?int $updatedDaysAgo = null): Incident
    {
        $incident = Incident::create([
            'school_id' => $school->id,
            'title' => 'Pompe en panne',
            'category' => 'water_point',
            'status' => 'triaged',
            'urgency' => 'high',
            'priority_score' => 50.0,
            ...$attrs,
        ]);

        if ($updatedDaysAgo !== null) {
            Incident::whereKey($incident->id)->update(['updated_at' => now()->subDays($updatedDaysAgo)]);
            $incident->refresh();
        }

        return $incident;
    }

    public function test_dormants_returns_only_dormant_open_incident(): void
    {
        $this->seed(WashRoleSeeder::class);
        $school = $this->makeSchool();

        $this->makeIncident($school, ['status' => 'triaged', 'priority_score' => 99.0]);
        $dormant = $this->makeIncident($school, ['status' => 'assigned', 'priority_score' => 60.0], 10);
        $this->makeIncident($school, ['status' => 'resolved', 'priority_score' => 90.0], 20);

        $ids = app(WashRelanceService::class)->dormants(7)->pluck('id')->all();

        $this->assertEquals([$dormant->id], $ids);
    }

    public function test_dormants_respects_days_threshold(): void
    {
        $this->seed(WashRoleSeeder::class);
        $school = $this->makeSchool();

        $fresh = $this->makeIncident($school, ['status' => 'triaged'], 6);
        $old = $this->makeIncident($school, ['status' => 'in_progress'], 8);

        $ids = app(WashRelanceService::class)->dormants(7)->pluck('id')->all();

        $this->assertContains($old->id, $ids);
        $this->assertNotContains($fresh->id, $ids);
    }

    public function test_dormants_orders_by_priority_desc(): void
    {
        $this->seed(WashRoleSeeder::class);
        $school = $this->makeSchool();

        $low = $this->makeIncident($school, ['status' => 'reported', 'priority_score' => 10.0], 10);
        $high = $this->makeIncident($school, ['status' => 'triaged', 'priority_score' => 80.0], 10);

        $ids = app(WashRelanceService::class)->dormants(7)->pluck('id')->all();

        $this->assertEquals([$high->id, $low->id], $ids);
    }

    public function test_dry_run_lists_without_sending(): void
    {
        $this->seed(WashRoleSeeder::class);
        Notification::fake();
        $this->actingAsRole('wash_admin', 'admin@wash.cm');

        $school = $this->makeSchool();
        $dormant = $this->makeIncident($school, ['status' => 'triaged'], 10);
        $this->makeIncident($school, ['status' => 'triaged']);

        $this->getJson(self::ENDPOINT.'?days=7')
            ->assertOk()
            ->assertJsonPath('dry_run', true)
            ->assertJsonPath('count', 1)
            ->assertJsonPath('incidents.0.id', $dormant->id);

        $this->postJson(self::ENDPOINT, ['days' => 7])
            ->assertOk()
            ->assertJsonPath('dry_run', true)
            ->assertJsonPath('count', 1);

        Notification::assertNothingSent();
    }

    public function test_send_notifies_assignee_and_staff(): void
    {
        $this->seed(WashRoleSeeder::class);
        Notification::fake();

        $admin = $this->makeUser('wash_admin', 'admin@wash.cm');
        $tech = $this->makeUser('maintenance_agent', 'tech@wash.cm');
        Sanctum::actingAs($admin);

        $school = $this->makeSchool();
        $assigned = $this->makeIncident($school, [
            'status' => 'assigned',
            'assigned_to_user_id' => $tech->id,
        ], 10);
        $orphan = $this->makeIncident($school, ['status' => 'triaged'], 12);
        $this->makeIncident($school, ['status' => 'triaged']);

        $this->postJson(self::ENDPOINT, ['days' => 7, 'dry_run' => false])
            ->assertOk()
            ->assertJsonPath('dry_run', false)
            ->assertJsonPath('count', 2)
            ->assertJsonPath('sent', 3);

        Notification::assertSentTo($tech, WashRelanceNotification::class);
        Notification::assertSentTo($admin, WashRelanceNotification::class);

        // Assigné : 2 notifs (son incident + l'orphelin diffusé au staff).
        // Admin : 1 notif (l'orphelin uniquement).
        $this->assertCount(2, Notification::sent($tech, WashRelanceNotification::class));
        $this->assertCount(1, Notification::sent($admin, WashRelanceNotification::class));

        $this->assertTrue(
            Notification::sent($tech, WashRelanceNotification::class)
                ->contains(fn ($n) => $n->incident->id === $assigned->id)
        );
        $this->assertTrue(
            Notification::sent($admin, WashRelanceNotification::class)
                ->contains(fn ($n) => $n->incident->id === $orphan->id)
        );
    }

    public function test_validation_rejects_invalid_days(): void
    {
        $this->seed(WashRoleSeeder::class);
        $this->actingAsRole('wash_admin', 'admin@wash.cm');

        $this->getJson(self::ENDPOINT.'?days=0')->assertUnprocessable();
        $this->getJson(self::ENDPOINT.'?days=999')->assertUnprocessable();
        $this->postJson(self::ENDPOINT, ['days' => 0])->assertUnprocessable();
        $this->postJson(self::ENDPOINT, ['days' => 999, 'dry_run' => false])->assertUnprocessable();
    }

    public function test_relance_requires_staff_permission(): void
    {
        $this->seed(WashRoleSeeder::class);
        $this->actingAsRole('school_reporter', 'reporter@wash.cm');

        $this->getJson(self::ENDPOINT)->assertForbidden();
        $this->postJson(self::ENDPOINT, ['days' => 7, 'dry_run' => false])->assertForbidden();

        $this->actingAsRole('maintenance_agent', 'tech@wash.cm');

        $this->getJson(self::ENDPOINT)->assertOk();
        $this->postJson(self::ENDPOINT, ['days' => 7, 'dry_run' => true])->assertOk();
    }
}
