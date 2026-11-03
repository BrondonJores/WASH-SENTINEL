<?php

namespace Tests\Feature;

use App\Models\AiModelProfile;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Cache;
use Tests\TestCase;

class AiModelProfileTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        $this->seed(\Database\Seeders\WashRoleSeeder::class);
        Cache::forget(AiModelProfile::CACHE_KEY);
    }

    public function test_active_profile_falls_back_to_default(): void
    {
        $default = AiModelProfile::create([
            'name' => 'Local', 'provider' => 'ollama',
            'base_url' => 'http://ollama:11434', 'model' => 'llama3.2:3b',
            'is_default' => true,
        ]);

        $this->assertEquals($default->id, AiModelProfile::active()->id);

        $external = AiModelProfile::create([
            'name' => 'Cloud', 'provider' => 'openai_compatible',
            'base_url' => 'https://api.example.com/v1', 'model' => 'x',
            'is_active' => true,
        ]);

        $this->assertEquals($external->id, AiModelProfile::active()->id);
    }

    public function test_api_key_is_encrypted_and_masked(): void
    {
        $profile = AiModelProfile::create([
            'name' => 'Cloud', 'provider' => 'openai_compatible',
            'base_url' => 'https://api.example.com/v1', 'model' => 'x',
            'api_key' => 'sk-secret-key-1234',
        ]);

        $this->assertNotEquals('sk-secret-key-1234', $profile->getRawOriginal('api_key'));
        $this->assertEquals('sk-secret-key-1234', $profile->plainApiKey());
        $this->assertEquals('***1234', $profile->api_key_masked);
        $this->assertArrayNotHasKey('api_key', $profile->toArray());
    }

    public function test_llm_headers_carry_active_profile(): void
    {
        AiModelProfile::create([
            'name' => 'Local', 'provider' => 'ollama',
            'base_url' => 'http://ollama:11434', 'model' => 'llama3.2:3b',
            'is_active' => true,
        ]);

        $headers = app(\App\Services\WashAiEngineService::class)->profileHeaders();

        $this->assertEquals('ollama', $headers['X-LLM-Provider']);
        $this->assertEquals('llama3.2:3b', $headers['X-LLM-Model']);
    }

    public function test_admin_can_activate_a_profile(): void
    {
        $user = User::factory()->create();
        $user->givePermissionTo('manage ai settings');
        $local = AiModelProfile::create([
            'name' => 'Local', 'provider' => 'ollama',
            'base_url' => 'http://ollama:11434', 'model' => 'a', 'is_active' => true,
        ]);
        $cloud = AiModelProfile::create([
            'name' => 'Cloud', 'provider' => 'openai_compatible',
            'base_url' => 'https://api.example.com/v1', 'model' => 'b',
        ]);

        $response = $this->actingAs($user)->postJson("/api/v1/admin/model-profiles/{$cloud->id}/activate");

        $response->assertOk();
        $this->assertTrue($cloud->fresh()->is_active);
        $this->assertFalse($local->fresh()->is_active);
        $this->assertEquals($cloud->id, AiModelProfile::active()->id);
    }

    public function test_admin_cannot_delete_the_active_profile(): void
    {
        $user = User::factory()->create();
        $user->givePermissionTo('manage ai settings');
        $profile = AiModelProfile::create([
            'name' => 'Local', 'provider' => 'ollama',
            'base_url' => 'http://ollama:11434', 'model' => 'a', 'is_active' => true,
        ]);

        $this->actingAs($user)
            ->deleteJson("/api/v1/admin/model-profiles/{$profile->id}")
            ->assertStatus(422);
    }

    public function test_meta_spark_profile_seeded_inactive_without_key(): void
    {
        $this->seed(\Database\Seeders\AiModelProfileSeeder::class);

        $profile = AiModelProfile::where('name', 'Meta Muse Spark (cloud)')->firstOrFail();
        $this->assertEquals('openai_compatible', $profile->provider);
        $this->assertEquals('https://api.meta.ai/v1', $profile->base_url);
        $this->assertEquals('muse-spark-1.3-contributor', $profile->model);
        $this->assertFalse($profile->is_active);
        $this->assertNull($profile->plainApiKey());
        // Le local reste le défaut primaire.
        $this->assertTrue(AiModelProfile::where('name', 'Llama 3.2 Local (Ollama)')->firstOrFail()->is_default);
    }

    public function test_reseed_never_overwrites_admin_config(): void
    {
        // Régression réelle : le re-seed de start.sh réécrivait la config
        // (URL/modèle) d'un profil Meta configuré dans Réglages.
        $this->seed(\Database\Seeders\AiModelProfileSeeder::class);
        $meta = AiModelProfile::where('name', 'Meta Muse Spark (cloud)')->firstOrFail();
        AiModelProfile::query()->update(['is_active' => false]);
        $meta->update([
            'model' => 'muse-spark-1.3-custom',
            'timeout' => 45,
            'api_key' => 'SEKRET',
            'is_active' => true,
        ]);

        $this->seed(\Database\Seeders\AiModelProfileSeeder::class);

        $fresh = $meta->fresh();
        $this->assertEquals('muse-spark-1.3-custom', $fresh->model);
        $this->assertEquals(45, $fresh->timeout);
        $this->assertEquals('SEKRET', $fresh->plainApiKey());
        $this->assertTrue($fresh->is_active);
        $this->assertEquals($meta->id, AiModelProfile::active()->id);
    }
}
