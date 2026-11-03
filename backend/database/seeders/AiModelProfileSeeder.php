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

        // Meta Muse Spark : inactif par défaut (le local reste le défaut),
        // clé à coller dans Réglages (jamais fournie ni écrasée ici).
        $this->seedProfile('Meta Muse Spark (cloud)', [
            'provider' => 'openai_compatible',
            'base_url' => 'https://api.meta.ai/v1',
            'model' => 'muse-spark-1.3-contributor',
            'vision_model' => null,
            'embed_model' => 'text-embedding-3-small',
            'api_key' => null,
            'timeout' => 120,
        ], false, false);
    }

    /**
     * Crée le profil s'il manque, ne touche JAMAIS à l'existant.
     * start.sh re-seed à chaque boot : la config posée par l'admin dans
     * Réglages (URL, modèle, clé, flags actif/défaut) survit au re-seed.
     * (Un refresh systématique a déjà détruit un profil Meta configuré.)
     */
    private function seedProfile(string $name, array $config, bool $active, bool $default): void
    {
        AiModelProfile::firstOrCreate(
            ['name' => $name],
            $config + ['is_active' => $active, 'is_default' => $default]
        );
    }
}
