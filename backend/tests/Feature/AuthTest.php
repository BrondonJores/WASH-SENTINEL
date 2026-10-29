<?php

namespace Tests\Feature;

use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Hash;
use Tests\TestCase;

class AuthTest extends TestCase
{
    use RefreshDatabase;

    public function test_login_returns_token_and_roles(): void
    {
        $this->seed(\Database\Seeders\WashRoleSeeder::class);
        $user = User::factory()->create(['password' => Hash::make('secret123')]);
        $user->assignRole('wash_admin');

        $response = $this->postJson('/api/v1/auth/token', [
            'email' => $user->email,
            'password' => 'secret123',
        ]);

        $response->assertOk();
        $response->assertJsonPath('user.email', $user->email);
        $response->assertJsonPath('user.roles', ['wash_admin']);
        $this->assertNotEmpty($response->json('token'));
    }

    public function test_login_rejects_bad_credentials_without_hint(): void
    {
        $user = User::factory()->create();

        $this->postJson('/api/v1/auth/token', ['email' => $user->email, 'password' => 'wrong'])
            ->assertStatus(401)
            ->assertJson(['message' => 'Identifiants invalides.']);

        $this->postJson('/api/v1/auth/token', ['email' => 'nobody@example.com', 'password' => 'wrong'])
            ->assertStatus(401)
            ->assertJson(['message' => 'Identifiants invalides.']);
    }

    public function test_logout_revokes_current_token(): void
    {
        $user = User::factory()->create();
        $token = $user->createToken('admin')->plainTextToken;

        $this->withToken($token)->deleteJson('/api/v1/auth/token')->assertOk();
        $this->assertEquals(0, $user->tokens()->count());

        $this->app['auth']->forgetGuards();
        $this->withToken($token)->getJson('/api/user')->assertUnauthorized();
    }

    public function test_admin_routes_require_authentication(): void
    {
        $this->getJson('/api/v1/admin/model-profiles')->assertUnauthorized();
    }
}
