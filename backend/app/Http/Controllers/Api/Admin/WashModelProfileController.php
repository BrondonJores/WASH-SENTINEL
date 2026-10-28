<?php

namespace App\Http\Controllers\Api\Admin;

use App\Http\Controllers\Controller;
use App\Models\AiModelProfile;
use App\Services\WashAiEngineService;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\DB;
use Illuminate\Validation\Rule;

class WashModelProfileController extends Controller
{
    public function index()
    {
        return response()->json(
            AiModelProfile::orderByDesc('is_active')->orderBy('name')->get()
        );
    }

    public function store(Request $request)
    {
        $validated = $request->validate([
            'name' => ['required', 'string', 'max:128', 'unique:ai_model_profiles,name'],
            'provider' => ['required', 'in:ollama,openai_compatible'],
            'base_url' => ['required', 'url', 'max:255'],
            'model' => ['required', 'string', 'max:128'],
            'vision_model' => ['nullable', 'string', 'max:128'],
            'embed_model' => ['nullable', 'string', 'max:128'],
            'api_key' => ['nullable', 'string', 'max:500'],
            'timeout' => ['nullable', 'integer', 'min:5', 'max:600'],
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
            'name' => ['sometimes', 'string', 'max:128', Rule::unique('ai_model_profiles', 'name')->ignore($modelProfile->id)],
            'provider' => ['sometimes', 'in:ollama,openai_compatible'],
            'base_url' => ['sometimes', 'url', 'max:255'],
            'model' => ['sometimes', 'string', 'max:128'],
            'vision_model' => ['nullable', 'string', 'max:128'],
            'embed_model' => ['nullable', 'string', 'max:128'],
            'api_key' => ['nullable', 'string', 'max:500'],
            'timeout' => ['sometimes', 'integer', 'min:5', 'max:600'],
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

    public function test(AiModelProfile $modelProfile, WashAiEngineService $ai)
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

    public function providerTypes(WashAiEngineService $ai)
    {
        try {
            $types = $ai->providerTypes();
            Cache::put('wash.provider_types', $types, 3600);

            return response()->json($types);
        } catch (\Throwable) {
            return response()->json(Cache::get('wash.provider_types', [
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
            ]));
        }
    }
}
