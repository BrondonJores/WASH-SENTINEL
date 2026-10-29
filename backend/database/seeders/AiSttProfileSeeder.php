<?php

namespace Database\Seeders;

use App\Models\AiSttProfile;
use Illuminate\Database\Seeder;

class AiSttProfileSeeder extends Seeder
{
    public function run(): void
    {
        AiSttProfile::updateOrCreate(
            ['name' => 'Whisper local (français)'],
            [
                'driver' => 'whisper_cpp',
                'base_url' => null,
                'model' => env('VOICE_STT_MODEL', '/models/whisper/ggml-base.bin'),
                'tokens_path' => null,
                'api_key' => null,
                'default_language' => 'fr',
                'threads' => 2,
                'timeout' => 120,
                'is_active' => true,
                'is_default' => true,
            ]
        );

        AiSttProfile::updateOrCreate(
            ['name' => 'Omnilingual local (langues locales)'],
            [
                'driver' => 'omnilingual_onnx',
                'base_url' => null,
                'model' => env('OMNI_STT_MODEL', '/models/omnilingual/model.int8.onnx'),
                'tokens_path' => env('OMNI_STT_TOKENS', '/models/omnilingual/tokens.txt'),
                'api_key' => null,
                'default_language' => 'dua_Latn',
                'threads' => 2,
                'timeout' => 180,
                'is_active' => false,
                'is_default' => false,
            ]
        );

        AiSttProfile::updateOrCreate(
            ['name' => 'Cloud Whisper API'],
            [
                'driver' => 'cloud_whisper',
                'base_url' => 'https://api.openai.com/v1',
                'model' => 'whisper-1',
                'tokens_path' => null,
                'api_key' => null,
                'default_language' => 'fr',
                'threads' => 2,
                'timeout' => 120,
                'is_active' => false,
                'is_default' => false,
            ]
        );
    }
}
