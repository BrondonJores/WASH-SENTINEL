<?php

namespace App\Services;

use App\Contracts\WhatsAppClient;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;

class MetaWhatsAppService implements WhatsAppClient
{
    /**
     * Lit config/whatsapp.php en priorité, avec repli sur l'ancien
     * config/services.php ['whatsapp'] (compat ascendante).
     */
    protected function cfg(string $key, mixed $default = ''): mixed
    {
        $legacyMap = [
            'base_url' => 'base_url',
            'phone_number_id' => 'phone_number_id',
            'token' => 'access_token',
            'verify_token' => 'verify_token',
            'app_secret' => 'app_secret',
            'simulator' => 'simulator',
        ];

        $value = config("whatsapp.{$key}");
        if ($value !== null && $value !== '') {
            return $value;
        }
        if (isset($legacyMap[$key])) {
            $legacy = config("services.whatsapp.{$legacyMap[$key]}");
            if ($legacy !== null && $legacy !== '') {
                return $legacy;
            }
        }

        return $default;
    }

    protected function baseUrl(): string
    {
        return rtrim((string) $this->cfg('base_url', 'https://graph.facebook.com/v21.0'), '/');
    }

    protected function token(): string
    {
        return (string) $this->cfg('token', '');
    }

    protected function phoneNumberId(): string
    {
        return (string) $this->cfg('phone_number_id', '');
    }

    public function isSimulator(): bool
    {
        return (bool) $this->cfg('simulator', false);
    }

    public function verifySignature(string $rawBody, ?string $signature): bool
    {
        $secret = (string) $this->cfg('app_secret', '');
        if ($secret === '') {
            // Sans secret : ouvert en simulateur (dev), fermé en live.
            return $this->isSimulator();
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
                        'button_id' => null,
                    ];
                    if ($type === 'text') {
                        $normalized['text'] = $message['text']['body'] ?? null;
                    } elseif ($type === 'audio' && isset($message['audio']['id'])) {
                        $normalized['media_id'] = $message['audio']['id'];
                    } elseif ($type === 'image' && isset($message['image']['id'])) {
                        $normalized['media_id'] = $message['image']['id'];
                        $normalized['text'] = $message['image']['caption'] ?? null;
                    } elseif ($type === 'interactive') {
                        // Format Cloud API actuel : button_reply ; ancien : button payload.
                        $reply = $message['interactive']['button_reply'] ?? null;
                        if (is_array($reply) && isset($reply['id'])) {
                            $normalized['type'] = 'interactive';
                            $normalized['button_id'] = $reply['id'];
                            $normalized['text'] = $reply['title'] ?? null;
                        } elseif (isset($message['interactive']['button']['payload'])) {
                            $normalized['type'] = 'interactive';
                            $normalized['button_id'] = $message['interactive']['button']['payload'];
                            $normalized['text'] = $message['interactive']['button']['text'] ?? null;
                        } else {
                            continue;
                        }
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

    public function sendInteractiveButtons(string $to, string $body, array $buttons): array
    {
        if ($this->isSimulator()) {
            Log::info('WhatsApp simulator: interactive buttons not sent.', ['to' => $to, 'body' => $body, 'buttons' => $buttons]);

            return ['messages' => [['id' => 'sim-' . uniqid()]]];
        }

        $action = ['buttons' => []];
        foreach (array_slice($buttons, 0, 3) as $button) {
            $action['buttons'][] = [
                'type' => 'reply',
                'reply' => [
                    'id' => mb_substr((string) ($button['id'] ?? ''), 0, 256),
                    'title' => mb_substr((string) ($button['title'] ?? ''), 0, 20),
                ],
            ];
        }

        return Http::withToken($this->token())
            ->timeout(30)
            ->post("{$this->baseUrl()}/{$this->phoneNumberId()}/messages", [
                'messaging_product' => 'whatsapp',
                'to' => $to,
                'type' => 'interactive',
                'interactive' => [
                    'type' => 'button',
                    'body' => ['text' => $body],
                    'action' => $action,
                ],
            ])
            ->throw()
            ->json();
    }

    public function uploadMedia(string $bytes, string $mime, ?string $filename = null): string
    {
        if ($this->isSimulator()) {
            return 'sim-media-' . uniqid();
        }

        $response = Http::withToken($this->token())
            ->timeout(60)
            ->attach('file', $bytes, $filename ?? 'whatsapp-media', ['ContentType' => $mime])
            ->post("{$this->baseUrl()}/{$this->phoneNumberId()}/media", [
                'messaging_product' => 'whatsapp',
            ])
            ->throw()
            ->json();

        return (string) ($response['id'] ?? '');
    }

    public function sendAudio(string $to, string $mediaId): array
    {
        if ($this->isSimulator()) {
            Log::info('WhatsApp simulator: audio not sent.', ['to' => $to, 'media_id' => $mediaId]);

            return ['messages' => [['id' => 'sim-' . uniqid()]]];
        }

        return Http::withToken($this->token())
            ->timeout(30)
            ->post("{$this->baseUrl()}/{$this->phoneNumberId()}/messages", [
                'messaging_product' => 'whatsapp',
                'to' => $to,
                'type' => 'audio',
                'audio' => ['id' => $mediaId],
            ])
            ->throw()
            ->json();
    }

    public function sendTemplate(string $to, string $template, string $language, array $bodyParams = []): array
    {
        if ($this->isSimulator()) {
            Log::info('WhatsApp simulator: template not sent.', ['to' => $to, 'template' => $template]);

            return ['messages' => [['id' => 'sim-' . uniqid()]]];
        }

        $payload = [
            'messaging_product' => 'whatsapp',
            'to' => $to,
            'type' => 'template',
            'template' => [
                'name' => $template,
                'language' => ['code' => $language],
            ],
        ];
        if ($bodyParams !== []) {
            $payload['template']['components'] = [[
                'type' => 'body',
                'parameters' => array_map(
                    fn ($p) => ['type' => 'text', 'text' => (string) $p],
                    array_values($bodyParams)
                ),
            ]];
        }

        return Http::withToken($this->token())
            ->timeout(30)
            ->post("{$this->baseUrl()}/{$this->phoneNumberId()}/messages", $payload)
            ->throw()
            ->json();
    }
}
