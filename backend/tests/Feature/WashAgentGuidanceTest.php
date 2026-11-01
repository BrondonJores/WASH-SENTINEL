<?php

namespace Tests\Feature;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Client\ConnectionException;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

class WashAgentGuidanceTest extends TestCase
{
    use RefreshDatabase;

    public function test_ai_down_returns_guided_degraded_200(): void
    {
        Http::fake([
            '*/v1/agent/chat' => fn () => throw new ConnectionException('Could not resolve host'),
        ]);

        $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Bonjour'])
            ->assertOk()
            ->assertJsonPath('degraded', true)
            ->assertJsonPath('tools_executed', [])
            ->assertJsonFragment(['follow_ups' => ['Réessayer ?', 'Voir les incidents ouverts ?']]);
    }

    public function test_ai_timeout_returns_guided_degraded_200(): void
    {
        Http::fake([
            '*/v1/agent/chat' => fn () => throw new ConnectionException('cURL error 28: Operation timed out'),
        ]);

        $response = $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Bonjour']);
        $response->assertOk()->assertJsonPath('degraded', true);
        $this->assertStringContainsString('Réessayez', $response->json('answer'));
    }

    public function test_validation_errors_speak_french(): void
    {
        $this->postJson('/api/v1/wash/agent/converse', [])
            ->assertStatus(422)
            ->assertJsonFragment(['message' => 'Dites-moi en quelques mots ce dont vous avez besoin, par exemple « Signale une fuite au forage ».']);
    }

    public function test_soft_throttle_guides_before_hard_429(): void
    {
        Http::fake([
            '*/v1/agent/chat' => Http::response([
                'answer' => 'ok', 'tools_executed' => [], 'cards' => [], 'model_used' => 't',
            ], 200),
        ]);

        for ($i = 0; $i < 20; $i++) {
            $this->postJson('/api/v1/wash/agent/converse', ['message' => "Question {$i}"])
                ->assertOk()->assertJsonMissing(['degraded']);
        }
        $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Une de trop'])
            ->assertOk()
            ->assertJsonPath('degraded', true)
            ->assertJsonFragment(['follow_ups' => ['Voir les incidents ouverts ?']]);
    }
}
