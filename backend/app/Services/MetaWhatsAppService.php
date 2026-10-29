<?php

namespace App\Services;

use App\Contracts\WhatsAppClient;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;

class MetaWhatsAppService implements WhatsAppClient
{
    protected function baseUrl(): string
    {
        return rtrim((string) config('services.whatsapp.base_url', 'https://graph.facebook.com/v21.0'), '/');
    }

    protected function token(): string
    {
        return (string) config('services.whatsapp.access_token', '');
    }

    protected function phoneNumberId(): string
    {
        return (string) config('services.whatsapp.phone_number_id', '');
    }

    public function isSimulator(): bool
    {
        return (bool) config('services.whatsapp.simulator', false);
    }

    public function verifySignature(string $rawBody, ?string $signature): bool
    {
        $secret = (string) config('services.whatsapp.app_secret', '');
        if ($secret === '') {
            return true;
        }

        return hash_equals('sha256=' . hash_hmac('sha256', $rawBody, $secret), (string) $signature);
    }

    public function parseWebhook(array $payload): array
    {
        $messages = [];
        foreach ($payload['entry'] ?? [] as $entry) {
            foreach ($entry['changes'] ?? [] as $change) {
                $value = $change['value'] ?? [];
                foreach ($value['messages'] ?? [] as $message) {
                    $type = $message['type'] ?? '';
                    $normalized = [
                        'from' => $message['from'] ?? '',
                        'message_id' => $message['id'] ?? '',
                        'type' => $type,
                        'text' => null,
                        'media_id' => null,
                    ];
                    if ($type === 'text') {
                        $normalized['text'] = $message['text']['body'] ?? null;
                    } elseif ($type === 'audio' && isset($message['audio']['id'])) {
                        $normalized['media_id'] = $message['audio']['id'];
                    } elseif ($type === 'image' && isset($message['image']['id'])) {
                        $normalized['media_id'] = $message['image']['id'];
                        $normalized['text'] = $message['image']['caption'] ?? null;
                    } else {
                        continue;
                    }
                    $messages[] = $normalized;
                }
            }
        }

        return $messages;
    }

    public function downloadMedia(string $mediaId): array
    {
        if ($this->isSimulator()) {
            Log::info('WhatsApp simulator: media download skipped.', ['media_id' => $mediaId]);

            return ['bytes' => '', 'mime' => 'application/octet-stream', 'filename' => "sim-{$mediaId}.bin"];
        }

        $meta = Http::withToken($this->token())
            ->timeout(30)
            ->get("{$this->baseUrl()}/{$mediaId}")
            ->throw()
            ->json();

        $response = Http::withToken($this->token())
            ->timeout(60)
            ->get($meta['url'] ?? '');
        $response->throw();

        $mime = $meta['mime_type'] ?? 'application/octet-stream';

        return ['bytes' => $response->body(), 'mime' => $mime, 'filename' => "whatsapp-{$mediaId}"];
    }

    public function sendText(string $to, string $message): array
    {
        if ($this->isSimulator()) {
            Log::info('WhatsApp simulator: message not sent.', ['to' => $to, 'message' => $message]);

            return ['messages' => [['id' => 'sim-' . uniqid()]]];
        }

        return Http::withToken($this->token())
            ->timeout(30)
            ->post("{$this->baseUrl()}/{$this->phoneNumberId()}/messages", [
                'messaging_product' => 'whatsapp',
                'to' => $to,
                'type' => 'text',
                'text' => ['body' => $message],
            ])
            ->throw()
            ->json();
    }
}
