<?php

namespace App\Http\Controllers\Api\Admin;

use App\Contracts\AiEngineClient;
use App\Http\Controllers\Controller;
use App\Models\AiSttProfile;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\DB;
use Illuminate\Validation\Rule;

class WashSttProfileController extends Controller
{
    public function index()
    {
        return response()->json(
            AiSttProfile::orderByDesc('is_active')->orderBy('name')->get()
        );
    }

    public function store(Request $request)
    {
        $validated = $request->validate([
            'name' => ['required', 'string', 'max:128', 'unique:ai_stt_profiles,name'],
            'driver' => ['required', 'in:whisper_cpp,omnilingual_onnx,cloud_whisper'],
            'base_url' => ['nullable', 'url', 'max:255'],
            'model' => ['nullable', 'string', 'max:255'],
            'tokens_path' => ['nullable', 'string', 'max:255'],
            'api_key' => ['nullable', 'string', 'max:500'],
            'default_language' => ['nullable', 'string', 'max:16'],
            'threads' => ['nullable', 'integer', 'min:1', 'max:16'],
            'timeout' => ['nullable', 'integer', 'min:5', 'max:600'],
        ]);

        $profile = DB::transaction(function () use ($validated) {
            if (!AiSttProfile::where('is_active', true)->exists()) {
                $validated['is_active'] = true;
            }

            return AiSttProfile::create($validated);
        });
        Cache::forget(AiSttProfile::CACHE_KEY);

        return response()->json(['message' => 'Profil STT créé.', 'profile' => $profile->fresh()], 201);
    }

    public function show(AiSttProfile $sttProfile)
    {
        return response()->json($sttProfile);
    }

    public function update(Request $request, AiSttProfile $sttProfile)
    {
        $validated = $request->validate([
            'name' => ['sometimes', 'string', 'max:128', Rule::unique('ai_stt_profiles', 'name')->ignore($sttProfile->id)],
            'driver' => ['sometimes', 'in:whisper_cpp,omnilingual_onnx,cloud_whisper'],
            'base_url' => ['nullable', 'url', 'max:255'],
            'model' => ['nullable', 'string', 'max:255'],
            'tokens_path' => ['nullable', 'string', 'max:255'],
            'api_key' => ['nullable', 'string', 'max:500'],
            'default_language' => ['nullable', 'string', 'max:16'],
            'threads' => ['sometimes', 'integer', 'min:1', 'max:16'],
            'timeout' => ['sometimes', 'integer', 'min:5', 'max:600'],
        ]);

        if (array_key_exists('api_key', $validated) && empty($validated['api_key'])) {
            unset($validated['api_key']);
        }

        $sttProfile->update($validated);
        Cache::forget(AiSttProfile::CACHE_KEY);

        return response()->json(['message' => 'Profil STT mis à jour.', 'profile' => $sttProfile->fresh()]);
    }

    public function destroy(AiSttProfile $sttProfile)
    {
        if ($sttProfile->is_active) {
            return response()->json(['message' => 'Impossible de supprimer le profil actif. Activez un autre profil d\u2019abord.'], 422);
        }
        $sttProfile->delete();
        Cache::forget(AiSttProfile::CACHE_KEY);

        return response()->json(['message' => 'Profil STT supprimé.']);
    }

    public function activate(AiSttProfile $sttProfile)
    {
        DB::transaction(function () use ($sttProfile) {
            AiSttProfile::where('is_active', true)->update(['is_active' => false]);
            $sttProfile->update(['is_active' => true]);
        });
        Cache::forget(AiSttProfile::CACHE_KEY);

        return response()->json(['message' => "Profil « {$sttProfile->name} » activé.", 'profile' => $sttProfile->fresh()]);
    }

    public function test(Request $request, AiSttProfile $sttProfile, AiEngineClient $ai)
    {
        $validated = $request->validate([
            'audio' => ['required', 'file', 'mimes:wav,mp3,ogg,webm,m4a,mpga', 'max:5120'],
            'language' => ['nullable', 'string', 'max:16'],
        ]);

        $payload = [
            ...$sttProfile->testPayload(),
            'audio_base64' => base64_encode(file_get_contents($validated['audio']->path())),
            'filename' => $validated['audio']->getClientOriginalName(),
            'language' => $validated['language'] ?? $sttProfile->default_language,
        ];

        try {
            $result = $ai->testSttProfile($payload);
            $ok = (bool) ($result['ok'] ?? false);
        } catch (\Throwable $e) {
            $result = ['ok' => false, 'error' => $e->getMessage()];
            $ok = false;
        }

        $sttProfile->update([
            'last_tested_at' => now(),
            'last_test_status' => $ok ? 'success' : 'failed',
            'last_test_latency_ms' => $result['latency_ms'] ?? null,
        ]);

        return response()->json([...$result, 'profile' => $sttProfile->fresh()]);
    }

    public function sttTypes(AiEngineClient $ai)
    {
        try {
            $types = $ai->sttTypes();
            Cache::put('wash.stt_types', $types, 3600);

            return response()->json($types);
        } catch (\Throwable) {
            return response()->json(Cache::get('wash.stt_types', ['drivers' => []]));
        }
    }
}
