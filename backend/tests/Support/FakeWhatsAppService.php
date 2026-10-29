<?php

namespace Tests\Support;

use App\Services\MetaWhatsAppService;

class FakeWhatsAppService extends MetaWhatsAppService
{
    public static array $sent = [];

    public static array $media = [];

    public function downloadMedia(string $mediaId): array
    {
        return self::$media[$mediaId] ?? [
            'bytes' => 'fake-voice-note-bytes',
            'mime' => 'audio/ogg',
            'filename' => "wa-{$mediaId}.ogg",
        ];
    }

    public function sendText(string $to, string $message): array
    {
        self::$sent[] = ['to' => $to, 'message' => $message];

        return ['messages' => [['id' => 'fake-' . count(self::$sent)]]];
    }

    public static function reset(): void
    {
        self::$sent = [];
        self::$media = [];
    }
}
