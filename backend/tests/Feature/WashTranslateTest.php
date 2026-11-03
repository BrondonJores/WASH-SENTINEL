<?php

namespace Tests\Feature;

use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

class WashTranslateTest extends TestCase
{
    /** Lot traduit via le moteur, réponse alignée sur l'ordre reçu. */
    public function test_translates_batch_through_engine(): void
    {
        Http::fake(['*' => Http::response(['translations' => ['Broken pump', 'Flooded yard']], 200)]);

        $response = $this->postJson('/api/v1/wash/agent/translate', [
            'texts' => ['Pompe cassée', 'Cour inondée'],
            'target' => 'en',
        ])->assertOk();

        $response->assertJson(['translations' => ['Broken pump', 'Flooded yard']]);
        Http::assertSent(fn ($request) => str_ends_with($request->url(), '/v1/wash/translate')
            && $request['texts'] === ['Pompe cassée', 'Cour inondée']
            && $request['target'] === 'en');
    }

    /** Second appel identique : servi par le cache, zéro HTTP. */
    public function test_second_identical_call_hits_cache(): void
    {
        Cache::flush();
        Http::fake(['*' => Http::response(['translations' => ['Broken pump']], 200)]);
        $payload = ['texts' => ['Pompe cassée'], 'target' => 'en'];

        $this->postJson('/api/v1/wash/agent/translate', $payload)->assertOk();
        $this->postJson('/api/v1/wash/agent/translate', $payload)->assertOk()
            ->assertJson(['translations' => ['Broken pump']]);

        Http::assertSentCount(1);
    }

    /** Réponse moteur incomplète : repli sur l'original, jamais de vide. */
    public function test_incomplete_engine_response_falls_back(): void
    {
        Cache::flush();
        Http::fake(['*' => Http::response(['translations' => ['Broken pump']], 200)]);

        $this->postJson('/api/v1/wash/agent/translate', [
            'texts' => ['Pompe cassée', 'Cour inondée'],
            'target' => 'en',
        ])->assertOk()->assertJson(['translations' => ['Broken pump', 'Cour inondée']]);
    }

    /** Validation : lot requis borné, cible en/fr. */
    public function test_validates_payload(): void
    {
        $this->postJson('/api/v1/wash/agent/translate', ['texts' => [], 'target' => 'en'])
            ->assertStatus(422);
        $this->postJson('/api/v1/wash/agent/translate', ['texts' => ['x'], 'target' => 'xx'])
            ->assertStatus(422);
    }
}
