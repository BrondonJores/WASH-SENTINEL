<?php

namespace Tests\Feature;

use App\Http\Controllers\Api\WashReportController;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

class WashAgentPhotoTest extends TestCase
{
    use RefreshDatabase;

    /** PNG 1px réel (pas de GD en CI : UploadedFile::fake()->image() indisponible). */
    private const TINY_PNG_BASE64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';

    private function photoFile(string $name = 'forage.png', int $padBytes = 0): UploadedFile
    {
        $bytes = (string) base64_decode(self::TINY_PNG_BASE64);
        if ($padBytes > 0) {
            // Bourrage final : getimagesize/finfo restent valides, seul le poids change.
            $bytes .= str_repeat('0', $padBytes);
        }
        $path = (string) tempnam(sys_get_temp_dir(), 'wash-photo-');
        file_put_contents($path, $bytes);

        return new UploadedFile($path, $name, 'image/png', null, true);
    }

    public function test_converse_relays_valid_image_as_base64(): void
    {
        Http::fake([
            '*/v1/agent/chat' => Http::response([
                'answer' => 'Photo bien reçue.',
                'tools_executed' => [],
                'cards' => [],
                'model_used' => 'test-llm',
            ], 200),
        ]);

        $file = $this->photoFile();
        $expectedBase64 = base64_encode((string) file_get_contents($file->getPathname()));

        $response = $this->post('/api/v1/wash/agent/converse', [
            'message' => 'Regarde cette photo du forage.',
            'image' => $file,
        ]);

        $response->assertOk();
        $response->assertJsonPath('answer', 'Photo bien reçue.');

        Http::assertSent(fn ($request) =>
            str_ends_with($request->url(), '/v1/agent/chat')
            && ($request->data()['image_base64'] ?? null) === $expectedBase64
            && ($request->data()['image_mime'] ?? null) === 'image/png'
            && ($request->data()['message'] ?? null) === 'Regarde cette photo du forage.'
        );
    }

    public function test_converse_accepts_photo_without_text(): void
    {
        Http::fake([
            '*/v1/agent/chat' => Http::response([
                'answer' => 'Je vois une fuite.',
                'tools_executed' => [],
                'cards' => [],
                'model_used' => 'test-llm',
            ], 200),
        ]);

        $response = $this->post('/api/v1/wash/agent/converse', [
            'image' => $this->photoFile('fuite.png'),
        ]);

        $response->assertOk();
        Http::assertSent(fn ($request) =>
            str_ends_with($request->url(), '/v1/agent/chat')
            && isset($request->data()['image_base64'])
            && ($request->data()['image_mime'] ?? null) === 'image/png'
        );
    }

    public function test_converse_rejects_oversized_image_with_guidance(): void
    {
        Http::fake();

        // Dépasse 10 Mo tout en restant une image lisible (bourrage final).
        $file = $this->photoFile('lourde.png', 11 * 1024 * 1024);

        $response = $this->post('/api/v1/wash/agent/converse', [
            'message' => 'Photo lourde.',
            'image' => $file,
        ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors(['image']);
        $this->assertStringContainsString(
            'trop lourde',
            (string) json_encode($response->json('errors.image'))
        );
        Http::assertNothingSent();
    }

    public function test_converse_rejects_invalid_image_with_guidance(): void
    {
        Http::fake();

        $response = $this->post('/api/v1/wash/agent/converse', [
            'message' => 'Pas une photo.',
            'image' => UploadedFile::fake()->create('notes.txt', 10, 'text/plain'),
        ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors(['image']);
        Http::assertNothingSent();
    }

    public function test_converse_json_without_image_payload_unchanged(): void
    {
        Http::fake([
            '*/v1/agent/chat' => Http::response([
                'answer' => 'Réponse normale.',
                'tools_executed' => [],
                'cards' => [],
                'model_used' => 'test-llm',
            ], 200),
        ]);

        $response = $this->postJson('/api/v1/wash/agent/converse', [
            'message' => 'Quelle est la situation ?',
        ]);

        $response->assertOk();

        Http::assertSent(fn ($request) =>
            str_ends_with($request->url(), '/v1/agent/chat')
            && !array_key_exists('image_base64', $request->data())
            && !array_key_exists('image_mime', $request->data())
        );
    }

    public function test_converse_still_requires_message_without_image(): void
    {
        $this->postJson('/api/v1/wash/agent/converse', ['message' => ''])
            ->assertStatus(422)
            ->assertJsonValidationErrors(['message']);
    }

    public function test_converse_multipart_forwards_history_and_guided(): void
    {
        Http::fake([
            '*/v1/agent/chat' => Http::response([
                'answer' => 'Avec contexte.',
                'tools_executed' => [],
                'cards' => [],
                'model_used' => 'test-llm',
            ], 200),
        ]);

        // Contrat front (api.ts converse multipart) : history[i][role|content], guided '1'.
        $response = $this->post('/api/v1/wash/agent/converse', [
            'message' => 'Et ici ?',
            'history' => [['role' => 'user', 'content' => 'Première question']],
            'guided' => '1',
            'image' => $this->photoFile(),
        ]);

        $response->assertOk();
        Http::assertSent(fn ($request) =>
            str_ends_with($request->url(), '/v1/agent/chat')
            && ($request->data()['history'] ?? null) === [['role' => 'user', 'content' => 'Première question']]
            && ($request->data()['guided'] ?? null) === true
            && isset($request->data()['image_base64'])
        );
    }

    public function test_photo_limit_matches_report_controller(): void
    {
        $this->assertSame(WashReportController::PHOTO_MAX_KB, config('wash.photo.max_kb'));
        $this->assertSame(10240, config('wash.photo.max_kb'));
    }
}
