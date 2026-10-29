<?php

namespace Database\Seeders;

use App\Models\AiModelProfile;
use Illuminate\Database\Seeder;

class AiModelProfileSeeder extends Seeder
{
    public function run(): void
    {
        AiModelProfile::updateOrCreate(
            ['name' => 'Llama 3.2 Local (Ollama)'],
            [
                'provider' => 'ollama',
                'base_url' => env('OLLAMA_URL', 'http://ollama:11434'),
                'model' => env('OLLAMA_MODEL', 'llama3.2:3b'),
                'vision_model' => env('OLLAMA_VISION_MODEL', 'llama3.2-vision:11b'),
                'embed_model' => env('OLLAMA_EMBED_MODEL', 'nomic-embed-text'),
                'api_key' => null,
                'timeout' => 120,
                'is_active' => true,
                'is_default' => true,
            ]
        );

        AiModelProfile::updateOrCreate(
            ['name' => 'API externe (template)'],
            [
                'provider' => 'openai_compatible',
                'base_url' => 'https://api.openai.com/v1',
                'model' => 'gpt-4o-mini',
                'vision_model' => null,
                'embed_model' => 'text-embedding-3-small',
                'api_key' => null,
                'timeout' => 120,
                'is_active' => false,
                'is_default' => false,
            ]
        );

        // Modeles deja telecharges (ollama-local : gemma3:1b comme think-tank, gemma2:2b).
        // Importer les blobs une fois (voir README), puis Tester + Activer depuis Reglages IA.
        AiModelProfile::updateOrCreate(
            ['name' => 'Gemma 3 1B — tests (Ollama)'],
            [
                'provider' => 'ollama',
                'base_url' => env('OLLAMA_URL', 'http://ollama:11434'),
                'model' => 'gemma3:1b',
                'vision_model' => null,
                'embed_model' => null,
                'api_key' => null,
                'timeout' => 120,
                'is_active' => false,
                'is_default' => false,
            ]
        );

        AiModelProfile::updateOrCreate(
            ['name' => 'Gemma 2 2B — tests (Ollama)'],
            [
                'provider' => 'ollama',
                'base_url' => env('OLLAMA_URL', 'http://ollama:11434'),
                'model' => 'gemma2:2b',
                'vision_model' => null,
                'embed_model' => null,
                'api_key' => null,
                'timeout' => 120,
                'is_active' => false,
                'is_default' => false,
            ]
        );
    }
}
