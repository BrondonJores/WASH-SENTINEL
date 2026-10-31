<?php

namespace Tests\Feature;

use App\Models\Incident;
use App\Models\Report;
use App\Models\School;
use App\Models\User;
use Database\Seeders\WashRoleSeeder;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Notifications\DatabaseNotification;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class WashCrudFiltersTest extends TestCase
{
    use RefreshDatabase;

    private function admin(): User
    {
        $this->seed(WashRoleSeeder::class);
        $user = User::create(['name' => 'Admin', 'email' => 'admin@wash.cm', 'password' => 'secret']);
        $user->assignRole('wash_admin');
        Sanctum::actingAs($user);

        return $user;
    }

    /** @return array{Incident, Incident} */
    private function seedIncidents(): array
    {
        $schoolA = School::create(['name' => 'EP Pompeville', 'code' => 'EP-F1', 'district' => 'Mvila']);
        $schoolB = School::create(['name' => 'College Kiosque Nord', 'code' => 'EP-F2', 'district' => 'Wouri']);

        $high = Incident::create([
            'school_id' => $schoolA->id,
            'reference_code' => 'WASH-FILT-AAA',
            'title' => 'Pompe manuelle en panne',
            'category' => 'water_point',
            'status' => 'reported',
            'urgency' => 'high',
            'priority_score' => 90.0,
            'affected_students' => 500,
        ]);
        $low = Incident::create([
            'school_id' => $schoolB->id,
            'reference_code' => 'WASH-FILT-BBB',
            'title' => 'Latrines bouchees au bloc B',
            'category' => 'toilets_latrines',
            'status' => 'reported',
            'urgency' => 'low',
            'priority_score' => 10.0,
            'affected_students' => 50,
        ]);

        return [$high, $low];
    }

    /** @return array{Report, Report, Report} */
    private function seedReports(Incident $incident): array
    {
        $voice = Report::create([
            'incident_id' => $incident->id,
            'school_id' => $incident->school_id,
            'channel' => 'voice',
            'raw_content' => 'Message vocal de test',
            'is_duplicate' => false,
        ]);
        $dup = Report::create([
            'school_id' => $incident->school_id,
            'channel' => 'text',
            'raw_content' => 'Doublon de test',
            'is_duplicate' => true,
            'duplicate_of_incident_id' => $incident->id,
        ]);
        $photo = Report::create([
            'school_id' => $incident->school_id,
            'channel' => 'photo',
            'raw_content' => 'Photo de test',
            'is_duplicate' => false,
        ]);

        return [$voice, $dup, $photo];
    }

    private function seedNotification(User $user, ?string $readAt): DatabaseNotification
    {
        return DatabaseNotification::create([
            'id' => Str::uuid()->toString(),
            'type' => 'App\\Notifications\\TestNotification',
            'notifiable_type' => User::class,
            'notifiable_id' => $user->id,
            'data' => ['message' => 'test'],
            'read_at' => $readAt,
        ]);
    }

    public function test_incidents_search_matches_title(): void
    {
        [$high] = $this->seedIncidents();

        $this->getJson('/api/v1/wash/incidents?search=pompe')
            ->assertOk()
            ->assertJsonCount(1, 'data')
            ->assertJsonPath('data.0.id', $high->id);
    }

    public function test_incidents_search_matches_reference_code_case_insensitive(): void
    {
        $this->seedIncidents();

        // Référence stockée en majuscules, recherchée en minuscules.
        $this->getJson('/api/v1/wash/incidents?search=filt-bbb')
            ->assertOk()
            ->assertJsonCount(1, 'data')
            ->assertJsonPath('data.0.reference_code', 'WASH-FILT-BBB');
    }

    public function test_incidents_search_matches_school_name(): void
    {
        $this->seedIncidents();

        $this->getJson('/api/v1/wash/incidents?search=kiosque')
            ->assertOk()
            ->assertJsonCount(1, 'data')
            ->assertJsonPath('data.0.reference_code', 'WASH-FILT-BBB');
    }

    public function test_incidents_category_filter(): void
    {
        [, $low] = $this->seedIncidents();

        $this->getJson('/api/v1/wash/incidents?category=toilets_latrines')
            ->assertOk()
            ->assertJsonCount(1, 'data')
            ->assertJsonPath('data.0.id', $low->id);
    }

    public function test_incidents_sort_priority_score_desc(): void
    {
        [$high, $low] = $this->seedIncidents();

        $this->getJson('/api/v1/wash/incidents?sort=-priority_score')
            ->assertOk()
            ->assertJsonPath('data.0.id', $high->id)
            ->assertJsonPath('data.1.id', $low->id);
    }

    public function test_incidents_sort_affected_students_asc(): void
    {
        [$high, $low] = $this->seedIncidents();

        $this->getJson('/api/v1/wash/incidents?sort=affected_students')
            ->assertOk()
            ->assertJsonPath('data.0.id', $low->id)
            ->assertJsonPath('data.1.id', $high->id);
    }

    public function test_incidents_unknown_sort_falls_back_to_default(): void
    {
        [$high, $low] = $this->seedIncidents();

        // Tri actuel inchangé : priority_score desc puis latest.
        $this->getJson('/api/v1/wash/incidents?sort=nope')
            ->assertOk()
            ->assertJsonCount(2, 'data')
            ->assertJsonPath('data.0.id', $high->id)
            ->assertJsonPath('data.1.id', $low->id);
    }

    public function test_reports_channel_filter(): void
    {
        [$high] = $this->seedIncidents();
        [$voice] = $this->seedReports($high);

        $this->getJson('/api/v1/wash/reports?channel=voice')
            ->assertOk()
            ->assertJsonCount(1, 'data')
            ->assertJsonPath('data.0.id', $voice->id);
    }

    public function test_reports_is_duplicate_filter(): void
    {
        [$high] = $this->seedIncidents();
        [$voice, $dup, $photo] = $this->seedReports($high);

        $this->getJson('/api/v1/wash/reports?is_duplicate=1')
            ->assertOk()
            ->assertJsonCount(1, 'data')
            ->assertJsonPath('data.0.id', $dup->id);

        $res = $this->getJson('/api/v1/wash/reports?is_duplicate=0')->assertOk();
        $res->assertJsonCount(2, 'data');
        $ids = [$res->json('data.0.id'), $res->json('data.1.id')];
        $this->assertContains($voice->id, $ids);
        $this->assertContains($photo->id, $ids);

        // Valeur inattendue : filtre ignoré, tout est rendu.
        $this->getJson('/api/v1/wash/reports?is_duplicate=yes')
            ->assertOk()
            ->assertJsonCount(3, 'data');
    }

    public function test_notifications_unread_filter(): void
    {
        $user = $this->admin();
        $other = User::create(['name' => 'Other', 'email' => 'other@wash.cm', 'password' => 'secret']);

        $read = $this->seedNotification($user, now()->toDateTimeString());
        $unreadA = $this->seedNotification($user, null);
        $unreadB = $this->seedNotification($user, null);
        $this->seedNotification($other, null);

        $res = $this->getJson('/api/v1/notifications?unread=1')->assertOk();
        $res->assertJsonCount(2, 'data');
        $ids = [$res->json('data.0.id'), $res->json('data.1.id')];
        $this->assertContains($unreadA->id, $ids);
        $this->assertContains($unreadB->id, $ids);
        $this->assertNotContains($read->id, $ids);

        // Sans filtre : les 3 notifications de l'utilisateur, pas celle d'autrui.
        $this->getJson('/api/v1/notifications')->assertOk()->assertJsonCount(3, 'data');
    }
}
