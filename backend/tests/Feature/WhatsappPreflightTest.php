<?php

namespace Tests\Feature;

use Illuminate\Support\Facades\Http;
use Tests\TestCase;

class WhatsappPreflightTest extends TestCase
{
    private function liveConfig(array $overrides = []): void
    {
        config(array_merge([
            'whatsapp.enabled' => true,
            'whatsapp.base_url' => 'https://graph.facebook.com/v21.0',
            'whatsapp.phone_number_id' => '1234567890',
            'whatsapp.waba_id' => 'waba-001',
            'whatsapp.token' => 'live-TOKEN-should-never-leak-001',
            'whatsapp.verify_token' => 'verify-TOKEN-should-never-leak-002',
            'whatsapp.app_secret' => 'app-secret-value',
            'whatsapp.simulator' => false,
            'services.whatsapp.simulator' => false,
            'services.whatsapp.verify_token' => '',
            'services.whatsapp.access_token' => '',
            'services.whatsapp.phone_number_id' => '',
            'services.whatsapp.app_secret' => '',
        ], $overrides));
    }

    public function test_preflight_tout_vert_en_live(): void
    {
        $this->liveConfig();
        Http::fake([
            '*' => Http::response(['display_phone_number' => '+221 77 000 00 00'], 200),
        ]);

        $this->artisan('wash:whatsapp:preflight')
            ->assertExitCode(0)
            ->expectsOutputToContain('Preflight RÉUSSI');

        Http::assertSent(function ($request) {
            return str_contains((string) $request->url(), '/1234567890')
                && ($request->data()['fields'] ?? null) === 'display_phone_number'
                && $request->hasHeader('Authorization');
        });
    }

    public function test_preflight_n_expose_aucun_secret(): void
    {
        $this->liveConfig();
        Http::fake(['*' => Http::response(['display_phone_number' => '+221 77 000 00 00'], 200)]);

        $exitCode = \Illuminate\Support\Facades\Artisan::call('wash:whatsapp:preflight');
        $output = \Illuminate\Support\Facades\Artisan::output();

        $this->assertSame(0, $exitCode);
        $this->assertStringNotContainsString('live-TOKEN-should-never-leak-001', $output);
        $this->assertStringNotContainsString('verify-TOKEN-should-never-leak-002', $output);
        $this->assertStringNotContainsString('app-secret-value', $output);
    }

    public function test_preflight_token_invalide_401(): void
    {
        $this->liveConfig();
        Http::fake(['*' => Http::response(['error' => ['message' => 'Invalid OAuth access token.']], 401)]);

        $this->artisan('wash:whatsapp:preflight')
            ->assertExitCode(1)
            ->expectsOutputToContain('401');
    }

    public function test_preflight_secret_manquant_en_live(): void
    {
        $this->liveConfig(['whatsapp.app_secret' => '', 'whatsapp.app_secret' => '']);
        Http::fake(['*' => Http::response(['display_phone_number' => '+221 77 000 00 00'], 200)]);

        $this->artisan('wash:whatsapp:preflight')
            ->assertExitCode(1)
            ->expectsOutputToContain('WHATSAPP_APP_SECRET');
    }

    public function test_preflight_simulateur_ne_fait_aucun_appel_meta(): void
    {
        $this->liveConfig([
            'whatsapp.app_secret' => '',
            'whatsapp.app_secret' => '',
            'whatsapp.simulator' => true,
            'whatsapp.simulator' => true,
        ]);
        Http::fake(['*' => Http::response(['display_phone_number' => '+221 77 000 00 00'], 200)]);

        // Hors production : le simulateur n'est qu'un avertissement.
        $this->assertNotEquals('production', app()->environment());
        $this->artisan('wash:whatsapp:preflight')->assertExitCode(0);

        Http::assertNothingSent();
    }
}
