<?php

namespace Tests\Feature;

use App\Models\AiSttProfile;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Cache;
use Tests\TestCase;

class AiSttProfileTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        Cache::forget(AiSttProfile::CACHE_KEY);
    }

    public function test_active_profile_falls_back_to_default(): void
    {
        $default = AiSttProfile::create([
            'name' => 'Whisper', 'driver' => 'whisper_cpp',
            'model' => '/models/whisper/ggml-base.bin',
            'is_default' => true,
        ]);

        $this->assertEquals($default->id, AiSttProfile::active()->id);

        $omni = AiSttProfile::create([
            'name' => 'Omnilingual', 'driver' => 'omnilingual_onnx',
            'model' => '/models/omnilingual/model.int8.onnx',
            'tokens_path' => '/models/omnilingual/tokens.txt',
            'default_language' => 'dua_Latn',
            'is_active' => true,
        ]);

        $this->assertEquals($omni->id, AiSttProfile::active()->id);
    }

    public function test_api_key_is_encrypted_and_masked(): void
    {
        $profile = AiSttProfile::create([
            'name' => 'Cloud', 'driver' => 'cloud_whisper',
            'base_url' => 'https://api.example.com/v1', 'model' => 'whisper-1',
            'api_key' => 'sk-cloud-key-5678',
        ]);

        $this->assertNotEquals('sk-cloud-key-5678', $profile->getRawOriginal('api_key'));
        $this->assertEquals('sk-cloud-key-5678', $profile->plainApiKey());
        $this->assertEquals('***5678', $profile->api_key_masked);
        $this->assertArrayNotHasKey('api_key', $profile->toArray());
    }

    public function test_stt_headers_carry_active_profile(): void
    {
        AiSttProfile::create([
            'name' => 'Omnilingual', 'driver' => 'omnilingual_onnx',
            'model' => '/models/omnilingual/model.int8.onnx',
            'tokens_path' => '/models/omnilingual/tokens.txt',
            'default_language' => 'dua_Latn',
            'is_active' => true,
        ]);

        $headers = app(\App\Services\WashAiEngineService::class)->sttHeaders();

        $this->assertEquals('omnilingual_onnx', $headers['X-STT-Driver']);
        $this->assertEquals('dua_Latn', $headers['X-STT-Language']);
    }

    public function test_admin_can_activate_a_profile(): void
    {
        $user = User::factory()->create();
        $whisper = AiSttProfile::create([
            'name' => 'Whisper', 'driver' => 'whisper_cpp', 'is_active' => true,
        ]);
        $omni = AiSttProfile::create([
            'name' => 'Omnilingual', 'driver' => 'omnilingual_onnx',
        ]);

        $response = $this->actingAs($user)->postJson("/api/v1/admin/stt-profiles/{$omni->id}/activate");

        $response->assertOk();
        $this->assertTrue($omni->fresh()->is_active);
        $this->assertFalse($whisper->fresh()->is_active);
    }

    public function test_admin_cannot_delete_the_active_profile(): void
    {
        $user = User::factory()->create();
        $profile = AiSttProfile::create([
            'name' => 'Whisper', 'driver' => 'whisper_cpp', 'is_active' => true,
        ]);

        $this->actingAs($user)
            ->deleteJson("/api/v1/admin/stt-profiles/{$profile->id}")
            ->assertStatus(422);
    }
}
