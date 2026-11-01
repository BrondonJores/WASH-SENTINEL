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
    public const NAME_MAX = 128;

    public const DRIVERS = ['whisper_cpp', 'omnilingual_onnx', 'cloud_whisper'];

    public const URL_MAX = 255;

    public const PATH_MAX = 255;

    public const API_KEY_MAX = 500;

    public const LANGUAGE_MAX = 16;

    public const THREADS_MIN = 1;

    public const THREADS_MAX = 16;

    public const TIMEOUT_MIN = 5;

    public const TIMEOUT_MAX = 600;

    /** Plafond du fichier de test console — inchangé (hors unification 12 Mo). */
    public const TEST_AUDIO_MAX_KB = 5120;

    public const TEST_AUDIO_MIMES = ['wav', 'mp3', 'ogg', 'webm', 'm4a', 'mpga'];

    public const STT_TYPES_CACHE_TTL = 3600;

    public function index()
    {
        return response()->json(
            AiSttProfile::orderByDesc('is_active')->orderBy('name')->get()
        );
    }

    public function store(Request $request)
    {
        $validated = $request->validate([
            'name' => ['required', 'string', 'max:' . self::NAME_MAX, 'unique:ai_stt_profiles,name'],
            'driver' => ['required', 'in:' . implode(',', self::DRIVERS)],
            'base_url' => ['nullable', 'url', 'max:' . self::URL_MAX],
            'model' => ['nullable', 'string', 'max:' . self::PATH_MAX],
            'tokens_path' => ['nullable', 'string', 'max:' . self::PATH_MAX],
            'api_key' => ['nullable', 'string', 'max:' . self::API_KEY_MAX],
            'default_language' => ['nullable', 'string', 'max:' . self::LANGUAGE_MAX],
            'threads' => ['nullable', 'integer', 'min:' . self::THREADS_MIN, 'max:' . self::THREADS_MAX],
            'timeout' => ['nullable', 'integer', 'min:' . self::TIMEOUT_MIN, 'max:' . self::TIMEOUT_MAX],
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
            'name' => ['sometimes', 'string', 'max:' . self::NAME_MAX, Rule::unique('ai_stt_profiles', 'name')->ignore($sttProfile->id)],
            'driver' => ['sometimes', 'in:' . implode(',', self::DRIVERS)],
            'base_url' => ['nullable', 'url', 'max:' . self::URL_MAX],
            'model' => ['nullable', 'string', 'max:' . self::PATH_MAX],
            'tokens_path' => ['nullable', 'string', 'max:' . self::PATH_MAX],
            'api_key' => ['nullable', 'string', 'max:' . self::API_KEY_MAX],
            'default_language' => ['nullable', 'string', 'max:' . self::LANGUAGE_MAX],
            'threads' => ['sometimes', 'integer', 'min:' . self::THREADS_MIN, 'max:' . self::THREADS_MAX],
            'timeout' => ['sometimes', 'integer', 'min:' . self::TIMEOUT_MIN, 'max:' . self::TIMEOUT_MAX],
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
            'audio' => ['required', 'file', 'mimes:' . implode(',', self::TEST_AUDIO_MIMES), 'max:' . self::TEST_AUDIO_MAX_KB],
            'language' => ['nullable', 'string', 'max:' . self::LANGUAGE_MAX],
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
            Cache::put('wash.stt_types', $types, self::STT_TYPES_CACHE_TTL);

            return response()->json($types);
        } catch (\Throwable) {
            return response()->json(Cache::get('wash.stt_types', ['drivers' => []]));
        }
    }
}
