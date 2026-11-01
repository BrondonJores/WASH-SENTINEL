<?php

namespace Tests\Feature;

use Illuminate\Support\Facades\Cache;
use Tests\TestCase;

class WashWhatsAppDiagnosticsTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        Cache::forget('wash.whatsapp.last_webhook_at');
    }

    public function test_diagnostics_reports_configured_tokens_and_hint(): void
    {
        config([
            'whatsapp.verify_token' => 'diag-verify-token',
            'whatsapp.token' => 'diag-access-token',
            'queue.default' => 'database',
            'app.url' => 'http://demo.test',
        ]);

        $this->getJson('/api/v1/whatsapp/diagnostics')
            ->assertOk()
            ->assertJson([
                'verify_token_configured' => true,
                'app_token_configured' => true,
                'webhook_url_hint' => 'http://demo.test/api/v1/whatsapp/webhook',
                'queue_connection' => 'database',
                'last_webhook_at' => null,
            ]);
    }

    public function test_diagnostics_reports_missing_tokens_without_server_error(): void
    {
        config([
            'whatsapp.verify_token' => '',
            'whatsapp.token' => '',
            'services.whatsapp.verify_token' => '',
            'services.whatsapp.access_token' => '',
        ]);

        $this->getJson('/api/v1/whatsapp/diagnostics')
            ->assertOk()
            ->assertJson([
                'verify_token_configured' => false,
                'app_token_configured' => false,
            ]);
    }

    public function test_diagnostics_exposes_no_secrets(): void
    {
        $verifyToken = 'verify-SECRET-should-never-leak-001';
        $accessToken = 'access-SECRET-should-never-leak-002';
        config([
            'whatsapp.verify_token' => $verifyToken,
            'whatsapp.token' => $accessToken,
        ]);

        $response = $this->getJson('/api/v1/whatsapp/diagnostics');
        $response->assertOk();

        $body = $response->getContent();
        $this->assertIsString($body);
        $this->assertStringNotContainsString($verifyToken, $body);
        $this->assertStringNotContainsString($accessToken, $body);
    }

    public function test_diagnostics_returns_last_webhook_at_when_cached(): void
    {
        Cache::put('wash.whatsapp.last_webhook_at', '2026-10-31T12:00:00+00:00');

        $this->getJson('/api/v1/whatsapp/diagnostics')
            ->assertOk()
            ->assertJson(['last_webhook_at' => '2026-10-31T12:00:00+00:00']);
    }
}
