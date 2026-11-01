<?php

namespace Tests\Feature;

use App\Http\Controllers\Api\WashIncidentController;
use App\Models\Incident;
use App\Models\MeshBundle;
use App\Models\School;
use App\Models\User;
use Database\Seeders\WashRoleSeeder;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Storage;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

/**
 * LOT 8 — contrôleurs API : anti-valeurs-en-dur.
 *
 * 1. Régression statuts : 'assigned' et 'in_progress' acceptés par
 *    updateStatus ; l'ancien token concaténé 'assigned.in_progress' rejeté.
 * 2. Parité langues voix : wash.voice.languages == SUPPORTED_VOICE_LANGUAGES
 *    (ai-engine/app/stt_providers.py, lu depuis le fichier Python).
 * 3. Parité voix TTS : wash.voice.default_tts_voice == DEFAULT_TTS_VOICE
 *    (ai-engine/app/schemas.py).
 * 4. Plafonds audio unifiés à 12 Mo (12288 Ko) : agent (montée 10240 ->)
 *    et report (baisse 20480 ->) ; photo 10 Mo inchangée.
 * 5. Contrat mesh : TTL 7 j + max_hops 10 par défaut (config + comportement).
 */
class WashLot8ControllersTest extends TestCase
{
    use RefreshDatabase;

    private function admin(): User
    {
        $this->seed(WashRoleSeeder::class);
        $user = User::create(['name' => 'Admin', 'email' => 'admin@wash.cm', 'password' => 'secret']);
        $user->assignRole('wash_admin');
        Sanctum::actingAs($user);

        return $user;
    }

    private function seedIncident(): Incident
    {
        $school = School::create(['name' => 'EP Test', 'code' => 'EP-T1', 'district' => 'Mvila']);

        return Incident::create([
            'school_id' => $school->id,
            'title' => 'Pompe en panne',
            'category' => 'water_point',
            'status' => 'reported',
            'urgency' => 'high',
        ]);
    }

    public function test_status_const_has_no_concatenated_token(): void
    {
        $this->assertContains('assigned', WashIncidentController::STATUSES);
        $this->assertContains('in_progress', WashIncidentController::STATUSES);
        $this->assertNotContains('assigned.in_progress', WashIncidentController::STATUSES);
        $this->assertSame(
            ['reported', 'triaged', 'assigned', 'in_progress', 'resolved', 'closed'],
            WashIncidentController::STATUSES
        );
    }

    public function test_update_status_regression_assigned_and_in_progress(): void
    {
        $this->admin();
        $incident = $this->seedIncident();

        foreach (['assigned', 'in_progress'] as $status) {
            $this->patchJson("/api/v1/wash/incidents/{$incident->id}/status", ['status' => $status])
                ->assertOk()
                ->assertJsonPath('incident.status', $status);
        }

        // L'ancien token concaténé (bug du point) doit être rejeté.
        $this->patchJson("/api/v1/wash/incidents/{$incident->id}/status", ['status' => 'assigned.in_progress'])
            ->assertUnprocessable();

        $this->patchJson("/api/v1/wash/incidents/{$incident->id}/status", ['status' => 'nope'])
            ->assertUnprocessable();
    }

    public function test_voice_languages_parity_with_engine(): void
    {
        $src = file_get_contents(base_path('ai-engine/app/stt_providers.py'));
        $this->assertNotFalse($src);

        preg_match('/SUPPORTED_VOICE_LANGUAGES[^=]*=\s*\{([^}]*)\}/', $src, $m);
        $this->assertNotEmpty($m, 'Set SUPPORTED_VOICE_LANGUAGES introuvable dans stt_providers.py');

        preg_match_all('/"([^"]+)"/', $m[1], $langs);
        $engine = $langs[1];
        $this->assertNotEmpty($engine);

        $this->assertEqualsCanonicalizing($engine, config('wash.voice.languages'));
        $this->assertContains('bbj_Latn', config('wash.voice.languages'));
    }

    public function test_tts_voice_parity_with_engine(): void
    {
        $src = file_get_contents(base_path('ai-engine/app/schemas.py'));
        $this->assertNotFalse($src);

        preg_match('/DEFAULT_TTS_VOICE\s*=\s*"([^"]+)"/', $src, $m);
        $this->assertNotEmpty($m, 'DEFAULT_TTS_VOICE introuvable dans schemas.py');

        $this->assertSame($m[1], config('wash.voice.default_tts_voice'));
    }

    public function test_transcribe_accepts_bbj_latn(): void
    {
        Http::fake([
            '*/v1/voice/transcribe' => Http::response([
                'transcript' => 'Test ghomala.',
                'language' => 'bbj_Latn',
                'language_effective' => 'bbj_Latn',
            ], 200),
        ]);

        $this->post('/api/v1/wash/agent/transcribe', [
            'audio' => UploadedFile::fake()->create('note.wav', 10, 'audio/wav'),
            'language' => 'bbj_Latn',
        ])->assertOk()->assertJsonPath('language', 'bbj_Latn');
    }

    public function test_synthesize_accepts_bbj_latn(): void
    {
        Http::fake([
            '*/v1/voice/synthesize' => Http::response([
                'audio_base64' => base64_encode('RIFFfake'),
                'mime_type' => 'audio/wav',
                'language_effective' => 'bbj_Latn',
            ], 200),
        ]);

        $this->postJson('/api/v1/wash/agent/synthesize', [
            'text' => 'Bonjour',
            'language' => 'bbj_Latn',
        ])->assertOk();
    }

    public function test_agent_audio_ceiling_is_12mo(): void
    {
        $this->assertSame(12288, config('wash.voice.audio_max_kb'));

        Http::fake([
            '*/v1/voice/transcribe' => Http::response([
                'transcript' => 'ok',
                'language' => 'fr',
                'language_effective' => 'fr',
            ], 200),
        ]);

        // 11 Mo : accepté (l'ancien plafond 10 Mo l'aurait rejeté).
        $this->post('/api/v1/wash/agent/transcribe', [
            'audio' => UploadedFile::fake()->create('note.wav', 11264, 'audio/wav'),
        ])->assertOk();

        // 13 Mo : rejeté (plafond 12 Mo).
        $this->post('/api/v1/wash/agent/transcribe', [
            'audio' => UploadedFile::fake()->create('note.wav', 13312, 'audio/wav'),
        ])->assertUnprocessable()->assertJsonValidationErrors('audio');
    }

    public function test_report_audio_ceiling_is_12mo_and_photo_still_10mo(): void
    {
        Storage::fake('public');
        Http::fake([
            '*/v1/wash/triage' => Http::response([
                'raw_text' => 'Fuite robinet.',
                'extraction' => [
                    'data' => [
                        'school_detected' => 'EP Test',
                        'infrastructure_type' => 'water_point',
                        'issue_type' => 'leak',
                        'urgency_level' => 'medium',
                        'estimated_affected_students' => 0,
                        'health_hazard_risk' => 'low',
                        'short_summary' => 'Fuite sur le robinet.',
                    ],
                    'model_used' => 'test-llm',
                    'confidence_score' => 0.9,
                ],
            ], 200),
        ]);

        $school = School::create(['name' => 'EP Test', 'code' => 'EP-T1', 'district' => 'Mvila']);

        // 13 Mo : rejeté (l'ancien plafond 20 Mo l'aurait accepté).
        $this->post('/api/v1/wash/reports', [
            'school_id' => $school->id,
            'audio' => UploadedFile::fake()->create('note.wav', 13312, 'audio/wav'),
        ])->assertUnprocessable()->assertJsonValidationErrors('audio');

        // 11 Mo : accepté.
        $this->post('/api/v1/wash/reports', [
            'school_id' => $school->id,
            'audio' => UploadedFile::fake()->create('note.wav', 11264, 'audio/wav'),
        ])->assertCreated();

        // Photo 11 Mo : rejetée (plafond photo 10 Mo inchangé).
        // Pas de fake()->image() : l'extension GD est absente ; le mime
        // déclaré suffit (la règle image se base sur le mime rapporté).
        $this->post('/api/v1/wash/reports', [
            'school_id' => $school->id,
            'photo' => UploadedFile::fake()->create('photo.jpg', 11264, 'image/jpeg'),
        ])->assertUnprocessable()->assertJsonValidationErrors('photo');
    }

    public function test_mesh_contract_defaults(): void
    {
        $this->assertSame(7, config('wash.mesh.default_ttl_days'));
        $this->assertSame(10, config('wash.mesh.default_max_hops'));

        $school = School::create(['name' => 'EP Mesh', 'code' => 'EP-MESH', 'district' => 'Mvila']);
        $bundleId = (string) Str::uuid();

        $this->postJson('/api/v1/mesh/bundles', [
            'bundle_id' => $bundleId,
            'origin_node_id' => 'node-lot8',
            'school_id' => $school->id,
            'message' => 'Pompe brisée, 200 élèves sans eau.',
        ])->assertCreated()->assertJsonPath('summary.accepted', 1);

        $bundle = MeshBundle::where('bundle_id', $bundleId)->firstOrFail();
        $this->assertSame(10, $bundle->max_hops);
        $this->assertEqualsWithDelta(now()->addDays(7)->timestamp, $bundle->expires_at->timestamp, 180);
    }

    public function test_lot8_config_keys(): void
    {
        $this->assertSame(20, config('wash.pagination.default'));
        $this->assertSame(5, config('wash.pagination.min'));
        $this->assertSame(100, config('wash.pagination.max'));
        $this->assertSame('fr', config('wash.voice.default_language'));
        $this->assertSame(1000, config('wash.voice.text_max_chars'));
        $this->assertSame(64, config('wash.voice.voice_max_chars'));
        $this->assertSame(16, config('wash.voice.language_max_chars'));
        $this->assertSame('dtn://wash-sentinel/ingest', config('wash.mesh.default_destination_eid'));
    }
}
