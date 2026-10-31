<?php

namespace Database\Seeders;

use App\Models\AiModelProfile;
use Illuminate\Database\Seeder;

class AiModelProfileSeeder extends Seeder
{
    public function run(): void
    {
        $this->seedProfile('Llama 3.2 Local (Ollama)', [
            'provider' => 'ollama',
            'base_url' => env('OLLAMA_URL', 'http://ollama:11434'),
            'model' => env('OLLAMA_MODEL', 'llama3.2:3b'),
            'vision_model' => env('OLLAMA_VISION_MODEL', 'llama3.2-vision:11b'),
            'embed_model' => env('OLLAMA_EMBED_MODEL', 'nomic-embed-text'),
            'api_key' => null,
            'timeout' => 120,
        ], true, true);

        $this->seedProfile('API externe (template)', [
            'provider' => 'openai_compatible',
            'base_url' => 'https://api.openai.com/v1',
            'model' => 'gpt-4o-mini',
            'vision_model' => null,
            'embed_model' => 'text-embedding-3-small',
            'api_key' => null,
            'timeout' => 120,
        ], false, false);

        // Modeles deja telecharges (ollama-local : gemma3:1b comme think-tank, gemma2:2b).
        // Importer les blobs une fois (voir README), puis Tester + Activer depuis Reglages IA.
        $this->seedProfile('Gemma 3 1B — tests (Ollama)', [
            'provider' => 'ollama',
            'base_url' => env('OLLAMA_URL', 'http://ollama:11434'),
            'model' => 'gemma3:1b',
            'vision_model' => null,
            'embed_model' => null,
            'api_key' => null,
            'timeout' => 120,
        ], false, false);

        $this->seedProfile('Gemma 2 2B — tests (Ollama)', [
            'provider' => 'ollama',
            'base_url' => env('OLLAMA_URL', 'http://ollama:11434'),
            'model' => 'gemma2:2b',
            'vision_model' => null,
            'embed_model' => null,
            'api_key' => null,
            'timeout' => 120,
        ], false, false);
    }

    /**
     * Crée le profil avec les flags initiaux, puis rafraîchit la config seule.
     * start.sh re-seed à chaque boot : les flags is_active/is_default choisis
     * par l'admin dans Réglages ne sont JAMAIS réécrits ici.
     */
    private function seedProfile(string $name, array $config, bool $active, bool $default): void
    {
        $profile = AiModelProfile::firstOrCreate(
            ['name' => $name],
            $config + ['is_active' => $active, 'is_default' => $default]
        );
        // Ne jamais écraser une clé API posée via Réglages (le seeder n'en fournit aucune).
        $update = $config;
        if (($update['api_key'] ?? null) === null && $profile->getRawOriginal('api_key')) {
            unset($update['api_key']);
        }
        $profile->update($update);
    }
}
