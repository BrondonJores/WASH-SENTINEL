<?php

namespace Tests\Feature;

use App\Models\Team;
use App\Models\User;
use Database\Seeders\WashRoleSeeder;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class WashTeamTest extends TestCase
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

    private function payload(array $over = []): array
    {
        return array_merge([
            'name' => 'Équipe Wouri Nord',
            'district' => 'Wouri',
            'phone' => '+237 6 90 11 22',
            'specialties' => ['forage', 'pompes manuelles'],
            'is_active' => true,
        ], $over);
    }

    public function test_guest_cannot_manage_teams(): void
    {
        $this->getJson('/api/v1/wash/teams')->assertUnauthorized();
        $this->postJson('/api/v1/wash/teams', $this->payload())->assertUnauthorized();
    }

    public function test_admin_can_crud_teams(): void
    {
        $this->admin();

        // Création.
        $created = $this->postJson('/api/v1/wash/teams', $this->payload())
            ->assertCreated()
            ->assertJsonPath('team.name', 'Équipe Wouri Nord')
            ->assertJsonPath('team.specialties', ['forage', 'pompes manuelles'])
            ->json('team');

        // Liste + filtres.
        Team::create($this->payload(['name' => 'Équipe Mvila Rurale', 'district' => 'Mvila']));
        $this->getJson('/api/v1/wash/teams')
            ->assertOk()
            ->assertJsonPath('total', 2);
        $this->getJson('/api/v1/wash/teams?district=Mvila')
            ->assertOk()
            ->assertJsonPath('total', 1)
            ->assertJsonPath('data.0.name', 'Équipe Mvila Rurale');

        // Détail.
        $this->getJson("/api/v1/wash/teams/{$created['id']}")
            ->assertOk()
            ->assertJsonPath('district', 'Wouri');

        // Mise à jour.
        $this->patchJson("/api/v1/wash/teams/{$created['id']}", [
            'phone' => '+237 6 00 00 00',
            'is_active' => false,
        ])
            ->assertOk()
            ->assertJsonPath('team.phone', '+237 6 00 00 00')
            ->assertJsonPath('team.is_active', false);

        // Suppression.
        $this->deleteJson("/api/v1/wash/teams/{$created['id']}")->assertOk();
        $this->getJson("/api/v1/wash/teams/{$created['id']}")->assertNotFound();
    }

    public function test_store_validates_strictly(): void
    {
        $this->admin();

        // Nom et district requis.
        $this->postJson('/api/v1/wash/teams', [])->assertUnprocessable()
            ->assertJsonValidationErrors(['name', 'district']);

        // Nom unique.
        Team::create($this->payload());
        $this->postJson('/api/v1/wash/teams', $this->payload())->assertUnprocessable()
            ->assertJsonValidationErrors(['name']);

        // Spécialités : tableau de chaînes courtes.
        $this->postJson('/api/v1/wash/teams', $this->payload([
            'name' => 'Autre équipe',
            'specialties' => 'forage',
        ]))->assertUnprocessable()->assertJsonValidationErrors(['specialties']);

        $this->postJson('/api/v1/wash/teams', $this->payload([
            'name' => 'Autre équipe',
            'specialties' => [str_repeat('x', 65)],
        ]))->assertUnprocessable()->assertJsonValidationErrors(['specialties.0']);
    }

    public function test_update_validates_uniqueness(): void
    {
        $this->admin();

        $a = Team::create($this->payload(['name' => 'Équipe A']));
        $b = Team::create($this->payload(['name' => 'Équipe B']));

        // Conflit avec une autre équipe.
        $this->patchJson("/api/v1/wash/teams/{$b->id}", ['name' => 'Équipe A'])
            ->assertUnprocessable()->assertJsonValidationErrors(['name']);

        // Garder son propre nom : OK.
        $this->patchJson("/api/v1/wash/teams/{$a->id}", ['name' => 'Équipe A'])
            ->assertOk();
    }
}
