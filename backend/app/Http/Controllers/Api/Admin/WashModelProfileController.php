<?php

namespace App\Http\Controllers\Api\Admin;

use App\Http\Controllers\Controller;
use App\Models\AiModelProfile;
use App\Contracts\AiEngineClient;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\DB;
use Illuminate\Validation\Rule;

class WashModelProfileController extends Controller
{
    public const NAME_MAX = 128;

    public const PROVIDERS = ['ollama', 'openai_compatible'];

    public const BASE_URL_MAX = 255;

    public const MODEL_MAX = 128;

    public const API_KEY_MAX = 500;

    public const TIMEOUT_MIN = 5;

    public const TIMEOUT_MAX = 600;

    public const PROVIDER_TYPES_CACHE_TTL = 3600;

    /** Repli console quand le moteur IA est injoignable (valeurs inchangées). */
    public const FALLBACK_PROVIDER_TYPES = [
        'providers' => [
            [
                'id' => 'ollama',
                'label' => 'Ollama (modèle local)',
                'description' => 'Modèles hébergés localement.',
                'api_key_required' => false,
                'fields' => [
                    ['name' => 'base_url', 'label' => 'URL Ollama', 'type' => 'url', 'default' => 'http://ollama:11434', 'required' => true],
                    ['name' => 'model', 'label' => 'Modèle texte', 'type' => 'text', 'default' => 'llama3.2:3b', 'required' => true],
                    ['name' => 'vision_model', 'label' => 'Modèle vision', 'type' => 'text', 'default' => 'llama3.2-vision:11b', 'required' => false],
                    ['name' => 'embed_model', 'label' => 'Modèle embeddings', 'type' => 'text', 'default' => 'nomic-embed-text', 'required' => false],
                ],
            ],
            [
                'id' => 'openai_compatible',
                'label' => 'API externe (format OpenAI)',
                'description' => 'OpenAI, Groq, Together, Mistral.',
                'api_key_required' => true,
                'fields' => [
                    ['name' => 'base_url', 'label' => 'URL de base (/v1)', 'type' => 'url', 'default' => 'https://api.openai.com/v1', 'required' => true],
                    ['name' => 'model', 'label' => 'Modèle texte', 'type' => 'text', 'default' => 'gpt-4o-mini', 'required' => true],
                    ['name' => 'vision_model', 'label' => 'Modèle vision', 'type' => 'text', 'default' => '', 'required' => false],
                    ['name' => 'embed_model', 'label' => 'Modèle embeddings', 'type' => 'text', 'default' => 'text-embedding-3-small', 'required' => false],
                ],
            ],
        ],
    ];

    public function index()
    {
        return response()->json(
            AiModelProfile::orderByDesc('is_active')->orderBy('name')->get()
        );
    }

    public function store(Request $request)
    {
        $validated = $request->validate([
            'name' => ['required', 'string', 'max:' . self::NAME_MAX, 'unique:ai_model_profiles,name'],
            'provider' => ['required', 'in:' . implode(',', self::PROVIDERS)],
            'base_url' => ['required', 'url', 'max:' . self::BASE_URL_MAX],
            'model' => ['required', 'string', 'max:' . self::MODEL_MAX],
            'vision_model' => ['nullable', 'string', 'max:' . self::MODEL_MAX],
            'embed_model' => ['nullable', 'string', 'max:' . self::MODEL_MAX],
            'api_key' => ['nullable', 'string', 'max:' . self::API_KEY_MAX],
            'timeout' => ['nullable', 'integer', 'min:' . self::TIMEOUT_MIN, 'max:' . self::TIMEOUT_MAX],
        ]);

        $profile = DB::transaction(function () use ($validated) {
            if (!AiModelProfile::where('is_active', true)->exists()) {
                $validated['is_active'] = true;
            }

            return AiModelProfile::create($validated);
        });
        Cache::forget(AiModelProfile::CACHE_KEY);

        return response()->json(['message' => 'Profil modèle créé.', 'profile' => $profile->fresh()], 201);
    }

    public function show(AiModelProfile $modelProfile)
    {
        return response()->json($modelProfile);
    }

    public function update(Request $request, AiModelProfile $modelProfile)
    {
        $validated = $request->validate([
            'name' => ['sometimes', 'string', 'max:' . self::NAME_MAX, Rule::unique('ai_model_profiles', 'name')->ignore($modelProfile->id)],
            'provider' => ['sometimes', 'in:' . implode(',', self::PROVIDERS)],
            'base_url' => ['sometimes', 'url', 'max:' . self::BASE_URL_MAX],
            'model' => ['sometimes', 'string', 'max:' . self::MODEL_MAX],
            'vision_model' => ['nullable', 'string', 'max:' . self::MODEL_MAX],
            'embed_model' => ['nullable', 'string', 'max:' . self::MODEL_MAX],
            'api_key' => ['nullable', 'string', 'max:' . self::API_KEY_MAX],
            'timeout' => ['sometimes', 'integer', 'min:' . self::TIMEOUT_MIN, 'max:' . self::TIMEOUT_MAX],
        ]);

        if (array_key_exists('api_key', $validated) && empty($validated['api_key'])) {
            unset($validated['api_key']);
        }

        $modelProfile->update($validated);
        Cache::forget(AiModelProfile::CACHE_KEY);

        return response()->json(['message' => 'Profil modèle mis à jour.', 'profile' => $modelProfile->fresh()]);
    }

    public function destroy(AiModelProfile $modelProfile)
    {
        if ($modelProfile->is_active) {
            return response()->json(['message' => 'Impossible de supprimer le profil actif. Activez un autre profil d\u2019abord.'], 422);
        }
        $modelProfile->delete();
        Cache::forget(AiModelProfile::CACHE_KEY);

        return response()->json(['message' => 'Profil modèle supprimé.']);
    }

    public function activate(AiModelProfile $modelProfile)
    {
        DB::transaction(function () use ($modelProfile) {
            AiModelProfile::where('is_active', true)->update(['is_active' => false]);
            $modelProfile->update(['is_active' => true]);
        });
        Cache::forget(AiModelProfile::CACHE_KEY);

        return response()->json(['message' => "Profil « {$modelProfile->name} » activé.", 'profile' => $modelProfile->fresh()]);
    }

    public function test(AiModelProfile $modelProfile, AiEngineClient $ai)
    {
        try {
            $result = $ai->testProfile($modelProfile->testPayload());
            $ok = (bool) ($result['ok'] ?? false);
        } catch (\Throwable $e) {
            $result = ['ok' => false, 'error' => $e->getMessage()];
            $ok = false;
        }

        $modelProfile->update([
            'last_tested_at' => now(),
            'last_test_status' => $ok ? 'success' : 'failed',
            'last_test_latency_ms' => $result['latency_ms'] ?? null,
        ]);

        return response()->json([...$result, 'profile' => $modelProfile->fresh()]);
    }

    public function providerTypes(AiEngineClient $ai)
    {
        try {
            $types = $ai->providerTypes();
            Cache::put('wash.provider_types', $types, self::PROVIDER_TYPES_CACHE_TTL);

            return response()->json($types);
        } catch (\Throwable) {
            return response()->json(Cache::get('wash.provider_types', self::FALLBACK_PROVIDER_TYPES));
        }
    }
}
