<?php

namespace Tests\Feature;

use App\Contracts\WhatsAppClient;
use App\Models\Incident;
use App\Models\School;
use App\Models\SchoolContact;
use App\Services\WashPhrasebook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Notification;
use Tests\Support\FakeWhatsAppService;
use Tests\TestCase;

/**
 * Phrasebook natif : réponses validées par des locuteurs humains (bbj, dua),
 * JAMAIS générées par le LLM. L'usager vocal reçoit sa langue + le FR.
 *
 * Chaînes « zz_ » = fixtures SYNTHÉTIQUES de test (pas du ghomala'/douala).
 * Le vrai contenu natif vit dans config/wash_phrasebook.php, rempli
 * uniquement par un locuteur (voir docs/PHRASEBOOK_NATIF.md).
 */
class WashPhrasebookTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        FakeWhatsAppService::reset();
        $this->app->bind(WhatsAppClient::class, FakeWhatsAppService::class);
        config(['whatsapp.simulator' => true]);
        Notification::fake();
    }

    protected function seedPhrasebook(bool $validated = true): void
    {
        config(['wash_phrasebook.entries.bbj_Latn.thanks_case' => [
            'fr' => 'Merci ! Dossier :ref enregistré.',
            'native' => 'zz_merci dossier :ref',
            'source' => $validated ? 'fixture-test (zz_ synthétique)' : null,
            'validator' => $validated ? 'test-fixture' : null,
            'validated_at' => $validated ? '2026-11-02' : null,
        ]]);
    }

    public function test_render_only_validated_entries(): void
    {
        $this->seedPhrasebook(true);
        $book = app(WashPhrasebook::class);

        $this->assertTrue($book->has('bbj_Latn', 'thanks_case'));
        $this->assertSame(
            'zz_merci dossier WASH-1',
            $book->render('bbj_Latn', 'thanks_case', ['ref' => 'WASH-1'])
        );
    }

    public function test_no_validator_means_no_render(): void
    {
        $this->seedPhrasebook(false);
        $book = app(WashPhrasebook::class);

        $this->assertFalse($book->has('bbj_Latn', 'thanks_case'));
        $this->assertNull($book->render('bbj_Latn', 'thanks_case', ['ref' => 'WASH-1']));
    }

    public function test_missing_lists_intents_awaiting_speaker(): void
    {
        $this->assertContains('thanks_case', app(WashPhrasebook::class)->missing('bbj_Latn'));
        $this->seedPhrasebook(true);
        $this->assertNotContains('thanks_case', app(WashPhrasebook::class)->missing('bbj_Latn'));
    }

    public function test_voice_bbj_gets_native_prefix_plus_french(): void
    {
        config(['filesystems.disks.public.root' => sys_get_temp_dir().'/wash-test-public']);
        $this->seedPhrasebook(true);
        $school = School::create([
            'name' => 'École de Bonanjo', 'code' => 'DOU-BON-001', 'district' => 'Wouri',
        ]);
        SchoolContact::create([
            'school_id' => $school->id, 'phone' => '237600112233',
            'name' => 'Clarisse Eko', 'role' => 'directrice', 'is_verified' => true,
        ]);
        Http::fake([
            '*/v1/wash/triage' => Http::response([
                'raw_text' => 'pou tshi lepom',
                'extraction' => [
                    'data' => [
                        'school_detected' => null,
                        'infrastructure_type' => 'water_point',
                        'issue_type' => 'leak',
                        'urgency_level' => 'medium',
                        'estimated_affected_students' => 0,
                        'health_hazard_risk' => 'low',
                        'short_summary' => 'Fuite sur un robinet.',
                    ],
                    'model_used' => 'test-llm',
                    'confidence_score' => 0.9,
                ],
            ], 200),
            '*/v1/voice/transcribe' => Http::response([
                'transcript' => 'pou tshi lepom',
                'language_detected' => 'bbj_Latn',
            ], 200),
            '*/v1/voice/synthesize' => Http::response(['audio_base64' => base64_encode('fake-audio')], 200),
        ]);

        $payload = json_decode(file_get_contents(base_path('tests/Fixtures/whatsapp/audio.json')), true);
        $payload['entry'][0]['changes'][0]['value']['messages'][0]['id'] = 'wamid.PHRASE01';
        $payload['entry'][0]['changes'][0]['value']['messages'][0]['from'] = '237600112233';
        $this->postJson('/api/v1/whatsapp/webhook', $payload)->assertOk();

        $this->assertSame(1, Incident::count());
        $texts = array_values(array_filter(
            FakeWhatsAppService::$sent,
            fn ($m) => ($m['type'] ?? '') === 'text'
        ));
        $ref = Incident::first()->reference_code;
        $this->assertStringContainsString('zz_merci dossier '.$ref, $texts[0]['message']);
        $this->assertStringContainsString('Merci ! Incident', $texts[0]['message']);
    }
}
