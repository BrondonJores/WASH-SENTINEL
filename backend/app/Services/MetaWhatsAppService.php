<?php

namespace App\Services;

use App\Contracts\WhatsAppClient;
use Illuminate\Http\Client\ConnectionException;
use Illuminate\Http\Client\RequestException;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;

class MetaWhatsAppService implements WhatsAppClient
{
    /**
     * Repli ultime si AUCUNE config ne fournit base_url (ni whatsapp.base_url
     * ni legacy services.whatsapp) : n'arrive qu'en test pur sans config.
     * Source unique en exploitation : config/whatsapp.php 'base_url'.
     */
    protected const FALLBACK_BASE_URL = 'https://graph.facebook.com/v21.0';

    /** Retries HTTP Graph API : 5 tentatives, 1 s d'intervalle (inchangés). */
    protected const RETRY_TIMES = 5;

    protected const RETRY_SLEEP_MS = 1000;

    /** Timeouts HTTP (secondes) : 30 s par défaut, 60 s pour les médias. */
    protected const TIMEOUT_DEFAULT = 30;

    protected const TIMEOUT_MEDIA = 60;

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
        return rtrim((string) $this->cfg('base_url', self::FALLBACK_BASE_URL), '/');
    }

    protected function token(): string
    {
        return (string) $this->cfg('token', '');
    }

    protected function phoneNumberId(): string
    {
        return (string) $this->cfg('phone_number_id', '');
    }

    /**
     * Client HTTP vers Graph API avec retries honnêtes (le DNS Docker flanche
     * par intermittence : cURL error 6, parfois plusieurs secondes).
     * 5 tentatives, 1 s d'intervalle. Rejoués : erreurs de connexion + 429
     * (rate limit Meta) + 5xx. Jamais rejoués : 401/403 (token expiré ou
     * invalide), 400, 404 — les rejouer n'y changerait rien.
     */
    protected function http(): \Illuminate\Http\Client\PendingRequest
    {
        return Http::withToken($this->token())->retry(
            self::RETRY_TIMES,
            self::RETRY_SLEEP_MS,
            function (\Throwable $e): bool {
                if ($e instanceof ConnectionException) {
                    return true;
                }
                if ($e instanceof RequestException && $e->response) {
                    $status = $e->response->status();

                    return $status === 429 || ($status >= 500 && $status < 600);
                }

                return false;
            }
        );
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

    /**
     * Normalise un payload webhook en liste de messages exploitables.
     * Blindage cas extrêmes : niveaux malformés (non-tableaux, champs
     * absents) ignorés sans lever ; types non supportés (sticker, réaction,
     * localisation, contact, vidéo, document, sondage, ordre...) normalisés
     * en 'unsupported' + 'unsupported_type' (jamais muets : le service répond
     * un guidage). Les accusés de lecture/livraison (statuses, sans messages)
     * restent ignorés : pas de message usager, pas de réponse.
     */
    public function parseWebhook(array $payload): array
    {
        $messages = [];
        $entries = $payload['entry'] ?? [];
        if (!is_array($entries)) {
            return [];
        }
        foreach ($entries as $entry) {
            if (!is_array($entry)) {
                continue;
            }
            $changes = $entry['changes'] ?? [];
            if (!is_array($changes)) {
                continue;
            }
            foreach ($changes as $change) {
                if (!is_array($change)) {
                    continue;
                }
                $value = $change['value'] ?? [];
                if (!is_array($value)) {
                    continue;
                }
                $rawMessages = $value['messages'] ?? [];
                if (!is_array($rawMessages)) {
                    continue;
                }
                foreach ($rawMessages as $message) {
                    if (is_array($message)) {
                        $messages[] = $this->normalizeMessage($message);
                    }
                }
            }
        }

        return $messages;
    }

    /** Normalise UN message brut Meta (champs contraints, type guidé). */
    protected function normalizeMessage(array $message): array
    {
        $type = $message['type'] ?? '';
        $normalized = [
            'from' => $this->stringField($message, 'from'),
            'message_id' => $this->stringField($message, 'id'),
            // Id Meta (wamid) : clé d'idempotence des relivraisons.
            'wamid' => $this->stringField($message, 'id'),
            'type' => is_string($type) ? $type : '',
            'text' => null,
            'media_id' => null,
            'button_id' => null,
            'unsupported_type' => null,
        ];
        $type = $normalized['type'];
        if ($type === 'text') {
            $body = $message['text']['body'] ?? null;
            $normalized['text'] = is_string($body) ? $body : null;
        } elseif ($type === 'audio' && isset($message['audio']['id'])) {
            $normalized['media_id'] = $this->stringField($message['audio'], 'id') ?: null;
        } elseif ($type === 'image' && isset($message['image']['id'])) {
            $normalized['media_id'] = $this->stringField($message['image'], 'id') ?: null;
            $caption = $message['image']['caption'] ?? null;
            $normalized['text'] = is_string($caption) ? $caption : null;
        } elseif ($type === 'interactive') {
            $this->normalizeInteractive($message, $normalized);
        } else {
            // Sticker, réaction, localisation, contact, vidéo, document,
            // sondage, ordre, futurs types... : guidage, jamais muet.
            $normalized['type'] = 'unsupported';
            $normalized['unsupported_type'] = $type !== '' ? $type : 'unknown';
        }

        return $normalized;
    }

    /**
     * Clic bouton : format Cloud API actuel (button_reply), listes
     * (list_reply, même contrat id), ancien format (button payload).
     * Réponse interactive inconnue : 'unsupported' (guidage, jamais muet).
     */
    protected function normalizeInteractive(array $message, array &$normalized): void
    {
        $interactive = $message['interactive'] ?? null;
        $reply = is_array($interactive) ? ($interactive['button_reply'] ?? $interactive['list_reply'] ?? null) : null;
        if (is_array($reply) && isset($reply['id'])) {
            $normalized['type'] = 'interactive';
            $normalized['button_id'] = $this->stringField($reply, 'id');
            $normalized['text'] = $this->stringField($reply, 'title') ?: null;
        } elseif (isset($message['interactive']['button']['payload'])) {
            $normalized['type'] = 'interactive';
            $normalized['button_id'] = $this->stringField($message['interactive']['button'], 'payload');
            $normalized['text'] = $this->stringField($message['interactive']['button'], 'text') ?: null;
        } else {
            $normalized['type'] = 'unsupported';
            $normalized['unsupported_type'] = 'interactive';
        }
    }

    /** Champ texte contraint (payload malformé : '' au lieu de lever). */
    protected function stringField(mixed $holder, string $key): string
    {
        if (!is_array($holder)) {
            return '';
        }
        $value = $holder[$key] ?? '';

        return is_string($value) || is_int($value) ? (string) $value : '';
    }

    public function downloadMedia(string $mediaId): array
    {
        if ($this->isSimulator()) {
            Log::info('WhatsApp simulator: media download skipped.', ['media_id' => $mediaId]);

            return ['bytes' => '', 'mime' => 'application/octet-stream', 'filename' => "sim-{$mediaId}.bin"];
        }

        $meta = $this->http()
            ->timeout(self::TIMEOUT_DEFAULT)
            ->get("{$this->baseUrl()}/{$mediaId}")
            ->throw()
            ->json();

        $response = $this->http()
            ->timeout(self::TIMEOUT_MEDIA)
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

        return $this->http()
            ->timeout(self::TIMEOUT_DEFAULT)
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

        return $this->http()
            ->timeout(self::TIMEOUT_DEFAULT)
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

        $response = $this->http()
            ->timeout(self::TIMEOUT_MEDIA)
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

        return $this->http()
            ->timeout(self::TIMEOUT_DEFAULT)
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

        return $this->http()
            ->timeout(self::TIMEOUT_DEFAULT)
            ->post("{$this->baseUrl()}/{$this->phoneNumberId()}/messages", $payload)
            ->throw()
            ->json();
    }
}
