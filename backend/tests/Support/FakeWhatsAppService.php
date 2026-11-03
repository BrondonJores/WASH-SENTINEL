<?php

namespace Tests\Support;

use App\Services\MetaWhatsAppService;

class FakeWhatsAppService extends MetaWhatsAppService
{
    public static array $sent = [];

    public static array $media = [];

    public static array $uploads = [];

    /** Panne injectée : levée par downloadMedia (ex. 404, timeout DNS). */
    public static ?\Throwable $downloadError = null;

    /** Panne injectée : sendText lève (Graph API down), rien n'est envoyé. */
    public static bool $failSend = false;

    /** Panne injectée : sendText lève cette erreur précise (ex. 131047). */
    public static ?\Throwable $sendError = null;

    public function downloadMedia(string $mediaId): array
    {
        if (self::$downloadError) {
            throw self::$downloadError;
        }

        return self::$media[$mediaId] ?? [
            'bytes' => 'fake-voice-note-bytes',
            'mime' => 'audio/ogg',
            'filename' => "wa-{$mediaId}.ogg",
        ];
    }

    public function sendText(string $to, string $message): array
    {
        if (self::$sendError) {
            throw self::$sendError;
        }
        if (self::$failSend) {
            throw new \RuntimeException('Graph API down (panne injectée).');
        }
        self::$sent[] = ['type' => 'text', 'to' => $to, 'message' => $message];

        return ['messages' => [['id' => 'fake-' . count(self::$sent)]]];
    }

    public function sendInteractiveButtons(string $to, string $body, array $buttons): array
    {
        self::$sent[] = ['type' => 'interactive', 'to' => $to, 'message' => $body, 'buttons' => $buttons];

        return ['messages' => [['id' => 'fake-' . count(self::$sent)]]];
    }

    public function uploadMedia(string $bytes, string $mime, ?string $filename = null): string
    {
        self::$uploads[] = ['bytes' => $bytes, 'mime' => $mime, 'filename' => $filename];

        return 'fake-media-' . count(self::$uploads);
    }

    public function sendAudio(string $to, string $mediaId): array
    {
        self::$sent[] = ['type' => 'audio', 'to' => $to, 'message' => '', 'media_id' => $mediaId];

        return ['messages' => [['id' => 'fake-' . count(self::$sent)]]];
    }

    public function sendTemplate(string $to, string $template, string $language, array $bodyParams = []): array
    {
        self::$sent[] = [
            'type' => 'template', 'to' => $to, 'message' => '',
            'template' => $template, 'language' => $language, 'params' => $bodyParams,
        ];

        return ['messages' => [['id' => 'fake-' . count(self::$sent)]]];
    }

    public static function reset(): void
    {
        self::$sent = [];
        self::$media = [];
        self::$uploads = [];
        self::$downloadError = null;
        self::$failSend = false;
        self::$sendError = null;
    }
}
