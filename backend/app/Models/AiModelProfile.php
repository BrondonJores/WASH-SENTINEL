<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Casts\Attribute;
use Illuminate\Database\Eloquent\Model;

class AiModelProfile extends Model
{
    public const CACHE_KEY = 'wash.active_ai_profile';

    protected $fillable = [
        'name', 'provider', 'base_url', 'model',
        'vision_model', 'embed_model', 'api_key', 'timeout',
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

    public function llmHeaders(): array
    {
        return array_filter([
            'X-LLM-Provider' => $this->provider,
            'X-LLM-Base-URL' => $this->base_url,
            'X-LLM-Model' => $this->model,
            'X-LLM-Vision-Model' => $this->vision_model,
            'X-LLM-Embed-Model' => $this->embed_model,
            'X-LLM-Api-Key' => $this->plainApiKey(),
            'X-LLM-Timeout' => (string) $this->timeout,
        ]);
    }

    public function testPayload(): array
    {
        return [
            'provider' => $this->provider,
            'base_url' => $this->base_url,
            'model' => $this->model,
            'vision_model' => $this->vision_model,
            'embed_model' => $this->embed_model,
            'api_key' => $this->plainApiKey(),
            'timeout' => 30,
        ];
    }

    public static function active(): ?self
    {
        return self::where('is_active', true)->first()
            ?? self::where('is_default', true)->first();
    }
}
