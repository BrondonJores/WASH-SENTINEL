<?php

namespace Database\Seeders;

use App\Models\AiSttProfile;
use Illuminate\Database\Seeder;

class AiSttProfileSeeder extends Seeder
{
    public function run(): void
    {
        $this->seedProfile('Whisper local (français)', [
            'driver' => 'whisper_cpp',
            'base_url' => null,
            'model' => env('VOICE_STT_MODEL', '/models/whisper/ggml-base.bin'),
            'tokens_path' => null,
            'api_key' => null,
            'default_language' => 'fr',
            'threads' => 2,
            'timeout' => 120,
        ], true, true);

        $this->seedProfile('Omnilingual local (langues locales)', [
            'driver' => 'omnilingual_onnx',
            'base_url' => null,
            'model' => env('OMNI_STT_MODEL', '/models/omnilingual/model.int8.onnx'),
            'tokens_path' => env('OMNI_STT_TOKENS', '/models/omnilingual/tokens.txt'),
            'api_key' => null,
            'default_language' => 'dua_Latn',
            'threads' => 2,
            'timeout' => 180,
        ], false, false);

        $this->seedProfile('Cloud Whisper API', [
            'driver' => 'cloud_whisper',
            'base_url' => 'https://api.openai.com/v1',
            'model' => 'whisper-1',
            'tokens_path' => null,
            'api_key' => null,
            'default_language' => 'fr',
            'threads' => 2,
            'timeout' => 120,
        ], false, false);

        // Meta Muse Transcribe : inactif par défaut, clé à coller dans
        // Réglages (jamais écrasée au re-seed, cf. seedProfile).
        $this->seedProfile('Meta Muse Transcribe (cloud)', [
            'driver' => 'meta_transcribe',
            'base_url' => 'https://api.meta.ai/v1',
            'model' => 'muse-voice-transcribe-1.0',
            'tokens_path' => null,
            'api_key' => null,
            'default_language' => 'fr',
            'threads' => 2,
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
        $profile = AiSttProfile::firstOrCreate(
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
