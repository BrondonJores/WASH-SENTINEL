<?php

namespace Tests\Feature;

use App\Services\DossierPosterService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Storage;
use Illuminate\Validation\ValidationException;
use Tests\TestCase;

class WashDossierDeliveryTest extends TestCase
{
    use RefreshDatabase;

    /** PNG 1px réel (pas de GD en CI). */
    private const TINY_PNG_BASE64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';

    private function service(): DossierPosterService
    {
        return app(DossierPosterService::class);
    }

    private function agentOk(array $cards): void
    {
        Http::fake([
            '*/v1/agent/chat' => Http::response([
                'answer' => 'Voici votre dossier.',
                'tools_executed' => ['build_dossier'],
                'cards' => $cards,
                'model_used' => 'test-llm',
            ], 200),
        ]);
    }

    public function test_persist_poster_stores_base64_and_returns_absolute_url(): void
    {
        Storage::fake('public');

        $url = $this->service()->persistPoster(self::TINY_PNG_BASE64, null, 'Dossier Mvila');

        $this->assertStringStartsWith('http', $url);
        $this->assertStringContainsString('/storage/reports/posters/', $url);
        $this->assertStringContainsString('dossier-mvila-', $url);
        $this->assertCount(1, Storage::disk('public')->files(DossierPosterService::DIRECTORY));
    }

    public function test_persist_poster_is_deterministic_without_duplicates(): void
    {
        Storage::fake('public');

        $first = $this->service()->persistPoster(self::TINY_PNG_BASE64, null, 'Dossier Mvila');
        $second = $this->service()->persistPoster(self::TINY_PNG_BASE64, null, 'Dossier Mvila');

        $this->assertSame($first, $second);
        $this->assertCount(1, Storage::disk('public')->files(DossierPosterService::DIRECTORY));
    }

    public function test_persist_poster_over_5mo_is_guided_422(): void
    {
        Storage::fake('public');
        $this->assertSame(5242880, DossierPosterService::MAX_BYTES);

        $bytes = (string) base64_decode(self::TINY_PNG_BASE64);
        $bytes .= str_repeat('0', DossierPosterService::MAX_BYTES - strlen($bytes) + 1);

        try {
            $this->service()->persistPoster(base64_encode($bytes), null, 'lourde');
            $this->fail('Une affiche > 5 Mo doit être refusée avec un guidage.');
        } catch (ValidationException $e) {
            $this->assertSame(422, $e->status);
            $this->assertStringContainsString('5 Mo', (string) collect($e->errors())->flatten()->first());
        }
        $this->assertCount(0, Storage::disk('public')->allFiles());
    }

    public function test_persist_poster_invalid_mime_is_guided(): void
    {
        Storage::fake('public');

        try {
            $this->service()->persistPoster(base64_encode('ceci-n-est-pas-une-image'), null, 'affiche');
            $this->fail('Un mime invalide doit être refusé avec un guidage.');
        } catch (ValidationException $e) {
            $this->assertStringContainsString(
                'JPEG, PNG ou WebP',
                (string) collect($e->errors())->flatten()->first()
            );
        }
    }

    public function test_persist_poster_downloads_mocked_remote_url(): void
    {
        Storage::fake('public');
        Http::fake([
            'affiches.test/*' => Http::response((string) base64_decode(self::TINY_PNG_BASE64), 200, [
                'Content-Type' => 'image/png',
            ]),
        ]);

        $url = $this->service()->persistPoster(null, 'https://affiches.test/dossier.png', 'distante');

        $this->assertStringStartsWith('http', $url);
        $this->assertStringContainsString('/storage/reports/posters/', $url);
        $this->assertCount(1, Storage::disk('public')->files(DossierPosterService::DIRECTORY));
    }

    public function test_persist_poster_remote_failure_is_guided_never_500(): void
    {
        Storage::fake('public');
        Http::fake([
            'affiches.test/*' => Http::response('oups', 500),
        ]);

        try {
            $this->service()->persistPoster(null, 'https://affiches.test/absente.png', 'distante');
            $this->fail('Un téléchargement en échec doit être guidé, jamais 500.');
        } catch (ValidationException $e) {
            $this->assertStringContainsString(
                'récupérée',
                (string) collect($e->errors())->flatten()->first()
            );
        }
    }

    public function test_converse_rewrites_poster_base64_to_persisted_url(): void
    {
        Storage::fake('public');
        $this->agentOk([[
            'type' => 'poster',
            'title' => 'Affiche du dossier',
            'data' => [
                'image_base64' => self::TINY_PNG_BASE64,
                'prompt' => 'Forage au lever du soleil',
                'caption' => 'Eau pour Mvila',
            ],
        ]]);

        $response = $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Prépare le dossier Mvila']);

        $response->assertOk();
        $card = $response->json('cards.0');
        $this->assertSame('poster', $card['type']);
        $this->assertArrayNotHasKey('image_base64', $card['data']);
        $this->assertStringStartsWith('http', $card['data']['image_url']);
        $this->assertStringContainsString('/storage/reports/posters/', $card['data']['image_url']);
        $this->assertSame('Eau pour Mvila', $card['data']['caption']);
    }

    public function test_converse_leaves_dossier_report_untouched(): void
    {
        Storage::fake('public');
        $report = [
            'type' => 'dossier_report',
            'title' => 'Dossier Mvila',
            'data' => [
                'subject' => 'Mvila',
                'period' => 'janvier à mars',
                'sections' => [
                    ['heading' => 'État des lieux', 'body_md' => 'Forage **en panne**.', 'figures' => []],
                    ['heading' => 'Budget', 'body_md' => '- Pompe : 120 000 XAF', 'figures' => []],
                ],
            ],
        ];
        $this->agentOk([$report]);

        $response = $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Prépare le dossier Mvila']);

        $response->assertOk();
        $this->assertSame($report, $response->json('cards.0'));
    }

    public function test_converse_corrupted_poster_returns_guided_note_never_500(): void
    {
        Storage::fake('public');
        $this->agentOk([[
            'type' => 'poster',
            'title' => 'Affiche du dossier',
            'data' => ['image_base64' => '!!!pas-du-base64!!!', 'caption' => 'Mvila'],
        ]]);

        $response = $this->postJson('/api/v1/wash/agent/converse', ['message' => 'Prépare le dossier Mvila']);

        $response->assertOk();
        $card = $response->json('cards.0');
        $this->assertArrayNotHasKey('image_base64', $card['data']);
        $this->assertArrayNotHasKey('image_url', $card['data']);
        $this->assertNotEmpty($card['data']['note']);
    }
}
