<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Casts\Attribute;
use Illuminate\Database\Eloquent\Model;

class AiSttProfile extends Model
{
    public const CACHE_KEY = 'wash.active_stt_profile';

    protected $fillable = [
        'name', 'driver', 'base_url', 'model', 'tokens_path',
        'api_key', 'default_language', 'threads', 'timeout',
        'is_active', 'is_default',
    ];

    protected $hidden = ['api_key'];

    protected $appends = ['api_key_masked'];

    protected $casts = [
        'is_active' => 'boolean',
        'is_default' => 'boolean',
    ];

    protected function apiKey(): Attribute
    {
        return Attribute::make(
            set: fn ($value) => $value ? encrypt($value) : null,
        );
    }

    protected function apiKeyMasked(): Attribute
    {
        return Attribute::make(
            get: function () {
                $raw = $this->getRawOriginal('api_key');
                if (!$raw) {
                    return null;
                }
                try {
                    $plain = decrypt($raw);
                } catch (\Throwable) {
                    return '***';
                }

                return strlen($plain) <= 4 ? '***' : '***' . substr($plain, -4);
            },
        );
    }

    public function plainApiKey(): ?string
    {
        $raw = $this->getRawOriginal('api_key');
        if (!$raw) {
            return null;
        }
        try {
            return decrypt($raw);
        } catch (\Throwable) {
            return null;
        }
    }

    public function sttHeaders(): array
    {
        return array_filter([
            'X-STT-Driver' => $this->driver,
            'X-STT-Model' => $this->model,
            'X-STT-Tokens' => $this->tokens_path,
            'X-STT-Base-URL' => $this->base_url,
            'X-STT-Api-Key' => $this->plainApiKey(),
            'X-STT-Language' => $this->default_language,
            'X-STT-Threads' => (string) $this->threads,
            'X-STT-Timeout' => (string) $this->timeout,
        ]);
    }

    public function testPayload(): array
    {
        return [
            'driver' => $this->driver,
            'base_url' => $this->base_url,
            'model' => $this->model,
            'tokens' => $this->tokens_path,
            'api_key' => $this->plainApiKey(),
            'language' => $this->default_language,
            'timeout' => 60,
        ];
    }

    public static function active(): ?self
    {
        return self::where('is_active', true)->first()
            ?? self::where('is_default', true)->first();
    }
}
