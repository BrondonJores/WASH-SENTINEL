<?php

namespace Tests\Feature;

use App\Models\Incident;
use App\Models\School;
use App\Models\User;
use App\Notifications\CriticalIncidentNotification;
use App\Notifications\WashRelanceNotification;
use App\Services\MeshMediaAssembler;
use App\Services\MeshSeal;
use App\Services\MeshSignature;
use App\Services\MeshSmsParser;
use App\Services\MetaWhatsAppService;
use App\Services\WashAiEngineService;
use App\Services\WashWhatsAppPersonality;
use App\Services\WashWhatsAppService;
use Carbon\Carbon;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

/**
 * LOT 7 anti-valeurs-en-dur (canaux WhatsApp/mesh/notifications) :
 * extraction pure — textes octet-identiques, constantes à valeurs
 * inchangées. Ce test épingle les valeurs contrat ; les tests Feature
 * existants (non modifiés) couvrent les comportements de bout en bout.
 */
class WashLot7CanauxTest extends TestCase
{
    use RefreshDatabase;

    /** Toutes les clés LOT 7 résolvent (jamais de clé brute). */
    public function test_lang_keys_resolve(): void
    {
        $frKeys = [
            'wash.whatsapp.error_technical', 'wash.whatsapp.unreadable_audio',
            'wash.whatsapp.unreadable_photo', 'wash.whatsapp.confirmed_stale',
            'wash.whatsapp.confirmed', 'wash.whatsapp.clarify_ask',
            'wash.whatsapp.clarify_applied', 'wash.whatsapp.stale_note',
            'wash.whatsapp.buttons_body', 'wash.whatsapp.button_yes',
            'wash.whatsapp.button_no', 'wash.whatsapp.tts_confirm',
            'wash.whatsapp.unknown_school_ecole', 'wash.whatsapp.unknown_school',
            'wash.whatsapp.off_topic', 'wash.whatsapp.created',
            'wash.whatsapp.duplicate', 'wash.whatsapp.oversized_audio',
            'wash.whatsapp.oversized_photo', 'wash.whatsapp.voice_placeholder',
            'wash.whatsapp.urgency.low', 'wash.whatsapp.urgency.medium',
            'wash.whatsapp.urgency.high', 'wash.whatsapp.urgency.critical',
            'wash.whatsapp.suivi.card', 'wash.whatsapp.suivi.since',
            'wash.whatsapp.suivi.next_fallback', 'wash.whatsapp.suivi.empty',
            'wash.whatsapp.suivi.unknown_reference',
            'wash.personality.greeting', 'wash.personality.identity',
            'wash.personality.capabilities', 'wash.personality.thanks',
            'wash.notifications.critical.subject', 'wash.notifications.critical.intro',
            'wash.notifications.critical.school', 'wash.notifications.critical.summary',
            'wash.notifications.critical.priority', 'wash.notifications.critical.action',
            'wash.notifications.relance.subject', 'wash.notifications.relance.stale',
            'wash.notifications.relance.school', 'wash.notifications.relance.title',
            'wash.notifications.relance.status', 'wash.notifications.relance.action',
        ];
        foreach ($frKeys as $key) {
            $this->assertNotEquals($key, trans($key, [], 'fr'), "missing FR key {$key}");
        }
        foreach (['reported', 'triaged', 'assigned', 'in_progress', 'resolved', 'closed'] as $status) {
            $this->assertNotEquals("wash.whatsapp.suivi.status.{$status}", trans("wash.whatsapp.suivi.status.{$status}", [], 'fr'));
            $this->assertNotEquals("wash.whatsapp.suivi.next.{$status}", trans("wash.whatsapp.suivi.next.{$status}", [], 'fr'));
            $this->assertNotEquals("wash.whatsapp.suivi.status.{$status}", trans("wash.whatsapp.suivi.status.{$status}", [], 'en'));
            $this->assertNotEquals("wash.whatsapp.suivi.next.{$status}", trans("wash.whatsapp.suivi.next.{$status}", [], 'en'));
        }

        $enKeys = [
            'wash.whatsapp.confirmed_stale', 'wash.whatsapp.confirmed',
            'wash.whatsapp.clarify_ask', 'wash.whatsapp.clarify_applied',
            'wash.whatsapp.stale_note', 'wash.whatsapp.buttons_body',
            'wash.whatsapp.button_yes', 'wash.whatsapp.button_no',
            'wash.whatsapp.tts_confirm', 'wash.whatsapp.created',
            'wash.whatsapp.duplicate', 'wash.whatsapp.suivi.card',
            'wash.whatsapp.suivi.since', 'wash.whatsapp.suivi.next_fallback',
            'wash.whatsapp.suivi.empty', 'wash.whatsapp.suivi.unknown_reference',
            'wash.personality.greeting', 'wash.personality.identity',
            'wash.personality.capabilities', 'wash.personality.thanks',
        ];
        foreach ($enKeys as $key) {
            $this->assertNotEquals($key, trans($key, [], 'en'), "missing EN key {$key}");
        }
    }

    /** isoFormat localisé == rendus d'origine (mois FR manuels, 'M j'), 12 mois. */
    public function test_short_day_matches_legacy_rendering_all_months(): void
    {
        $expectedFr = [
            1 => '2 janv.', 2 => '2 févr.', 3 => '2 mars', 4 => '2 avr.',
            5 => '2 mai', 6 => '2 juin', 7 => '2 juil.', 8 => '2 août',
            9 => '2 sept.', 10 => '2 oct.', 11 => '2 nov.', 12 => '2 déc.',
        ];
        $service = (new \ReflectionClass(WashWhatsAppService::class))->newInstanceWithoutConstructor();
        $frenchDay = new \ReflectionMethod(WashWhatsAppService::class, 'frenchDay');
        $englishDay = new \ReflectionMethod(WashWhatsAppService::class, 'englishDay');

        foreach ($expectedFr as $month => $expected) {
            $date = Carbon::create(2026, $month, 2, 12, 0, 0);
            $this->assertSame($expected, $frenchDay->invoke($service, $date), "FR month {$month}");
            $this->assertSame($date->format('M j'), $englishDay->invoke($service, $date), "EN month {$month}");
        }
    }

    /** Constantes Meta : valeurs inchangées (retry 5×1000, timeouts 30/60). */
    public function test_meta_consts_keep_values(): void
    {
        $ref = new \ReflectionClass(MetaWhatsAppService::class);
        $this->assertSame(5, $ref->getConstant('RETRY_TIMES'));
        $this->assertSame(1000, $ref->getConstant('RETRY_SLEEP_MS'));
        $this->assertSame(30, $ref->getConstant('TIMEOUT_DEFAULT'));
        $this->assertSame(60, $ref->getConstant('TIMEOUT_MEDIA'));
        $this->assertSame('https://graph.facebook.com/v21.0', $ref->getConstant('FALLBACK_BASE_URL'));
        $this->assertSame('https://graph.facebook.com/v21.0', config('whatsapp.base_url'));
    }

    /** Constantes + config ai-engine : valeurs inchangées, config effective. */
    public function test_ai_engine_consts_and_config_keep_values(): void
    {
        $this->assertSame(120, WashAiEngineService::DEFAULT_TIMEOUT);
        $this->assertSame(10, WashAiEngineService::TIMEOUT_HEALTH);
        $this->assertSame(15, WashAiEngineService::TIMEOUT_PROVIDER_TYPES);
        $this->assertSame(45, WashAiEngineService::TIMEOUT_TEST_PROFILE);
        $this->assertSame(120, WashAiEngineService::TIMEOUT_TEST_STT);
        $this->assertSame(60, WashAiEngineService::PROFILE_CACHE_TTL);
        $this->assertSame(0.80, WashAiEngineService::DEFAULT_DUPLICATE_THRESHOLD);

        $this->assertSame(10, config('services.ai_engine.timeout_health'));
        $this->assertSame(15, config('services.ai_engine.timeout_provider_types'));
        $this->assertSame(45, config('services.ai_engine.timeout_test_profile'));
        $this->assertSame(120, config('services.ai_engine.timeout_test_stt'));
        $this->assertSame(60, config('services.ai_engine.profile_cache_ttl'));
        $this->assertSame(0.80, (float) config('services.ai_engine.duplicate_threshold'));
    }

    /** Seuil doublons : défaut 0.80, config sinon, explicite prioritaire. */
    public function test_check_duplicates_threshold_resolution(): void
    {
        Http::fake(['*' => Http::response(['is_duplicate' => false], 200)]);
        $client = new WashAiEngineService('http://ai-engine:8000');

        $client->checkDuplicates('pompe cassee', []);
        $this->assertSame(0.80, (float) Http::recorded()[0][0]->data()['similarity_threshold']);

        config(['services.ai_engine.duplicate_threshold' => 0.9]);
        $client->checkDuplicates('pompe cassee', []);
        $this->assertSame(0.9, (float) Http::recorded()[1][0]->data()['similarity_threshold']);

        $client->checkDuplicates('pompe cassee', [], 0.7);
        $this->assertSame(0.7, (float) Http::recorded()[2][0]->data()['similarity_threshold']);
    }

    /** Personnalité : textes lang identiques, non-conversationnel → null. */
    public function test_personality_texts_identical(): void
    {
        $personality = new WashWhatsAppPersonality();

        $this->assertSame(trans('wash.personality.greeting', [], 'fr'), $personality->replyFor('Bonjour'));
        $this->assertSame(trans('wash.personality.greeting', [], 'en'), $personality->replyFor('Hello'));
        $this->assertStringStartsWith('Bonjour ! Je suis Sentinel', $personality->replyFor('Salut'));
        $this->assertStringStartsWith('Hello! I am Sentinel', $personality->replyFor('Hi!'));
        $this->assertNull($personality->replyFor('Le robinet du bloc A fuit depuis hier'));
        $this->assertNull($personality->replyFor(null));
    }

    /** Mesh SMS : contrat 160/HELP intact, gabarits identiques. */
    public function test_mesh_sms_contract_values(): void
    {
        $this->assertSame(160, MeshSmsParser::ACK_MAX_LENGTH);
        $this->assertSame(100, MeshSmsParser::DETAIL_MAX_LENGTH);
        $this->assertSame(3, MeshSmsParser::MIN_TOKENS);
        $this->assertSame('[SMS]', MeshSmsParser::PREFIX_SMS);
        $this->assertSame('[USSD]', MeshSmsParser::PREFIX_USSD);
        $this->assertSame(
            'Envoyez: WASH CODE TYPE. Ex: WASH DOU-BON-001 P (P=panne, L=latrine, E=eau, H=hygiene).',
            MeshSmsParser::HELP
        );

        $school = School::create(['name' => 'EP Test', 'code' => 'CE042', 'district' => 'Est']);
        $parser = new MeshSmsParser();

        $this->assertSame('WASH OK CE042 P WASH-2026-0042 Merci!', $parser->acknowledge($school, 'P', 'WASH-2026-0042'));

        $parsed = $parser->parse('WASH CE042 P pompe cassee');
        $this->assertTrue($parsed['ok']);
        $this->assertStringStartsWith('[SMS] EP Test : panne pompe/forage — ', $parsed['normalized']);

        $unknown = $parser->parse('WASH XXX P');
        $this->assertFalse($unknown['ok']);
        $this->assertSame("Code ecole 'XXX' inconnu. ".MeshSmsParser::HELP, $unknown['error']);

        $this->assertSame(
            '[USSD] EP Test : panne pompe/forage (URGENT) — POMPE HS',
            $parser->buildUssdMessage($school, 'P', 'urgente', 'POMPE HS')
        );
    }

    /** Mesh assembleur/sceau/signature : consts à valeurs inchangées. */
    public function test_mesh_consts_keep_values(): void
    {
        $this->assertSame(200, MeshMediaAssembler::MAX_FRAGMENTS);
        $this->assertSame('application/octet-stream', MeshMediaAssembler::DEFAULT_MIME);
        $this->assertSame('bin', MeshMediaAssembler::DEFAULT_EXT);
        $this->assertSame('reports/photos/', MeshMediaAssembler::PHOTO_DIR);
        $this->assertSame('reports/audio/', MeshMediaAssembler::AUDIO_DIR);
        $this->assertSame('mesh-', MeshMediaAssembler::FILE_PREFIX);
        $this->assertSame('delivered', MeshMediaAssembler::STATUS_DELIVERED);
        $this->assertSame('fragment_total', MeshMediaAssembler::FIELD_FRAGMENT_TOTAL);

        $this->assertSame('services.mesh.seal_secret', MeshSeal::CONFIG_KEY);
        $this->assertSame('nacl-sealed-box', MeshSeal::ALG);

        $this->assertSame('signature', MeshSignature::FIELD_SIGNATURE);
        $this->assertSame('node_pubkey', MeshSignature::FIELD_NODE_PUBKEY);
        $this->assertContains('signature', MeshSignature::SIGN_EXCLUDED);
    }

    /** Notifications : mail FR identique, URL legacy inchangée (route absente). */
    public function test_notifications_identical_mail_and_url(): void
    {
        $school = School::create(['name' => 'École de Bonanjo', 'code' => 'DOU-BON-001', 'district' => 'Wouri']);
        $incident = Incident::create([
            'school_id' => $school->id,
            'reference_code' => 'WASH-2026-RCLD5U',
            'title' => 'Pompe cassée',
            'ai_summary' => 'Pompe cassée, 200 élèves sans eau',
            'status' => 'reported',
            'urgency' => 'critical',
            'priority_score' => 95.5,
            'affected_students' => 200,
        ]);
        $notifiable = User::factory()->make();

        $critical = (new CriticalIncidentNotification($incident))->toMail($notifiable);
        $this->assertSame('Incident CRITIQUE : École de Bonanjo (WASH-2026-RCLD5U)', $critical->subject);
        $this->assertSame([
            "Un incident critique vient d'être signalé et trié par l'IA.",
            'École : École de Bonanjo (Wouri)',
            'Résumé : Pompe cassée, 200 élèves sans eau',
            'Élèves affectés : 200 — Priorité IA : 95.5/100',
        ], $critical->introLines);
        $this->assertSame("Voir l'incident", $critical->actionText);
        $this->assertSame(url("/api/v1/wash/incidents/{$incident->id}"), $critical->actionUrl);

        $relance = (new WashRelanceNotification($incident, 12))->toMail($notifiable);
        $this->assertSame('Relance incident dormant : WASH-2026-RCLD5U (École de Bonanjo)', $relance->subject);
        $this->assertSame([
            "L'incident WASH-2026-RCLD5U est sans activité depuis 12 jour(s).",
            'École : École de Bonanjo (Wouri)',
            'Titre : Pompe cassée',
            'Statut : reported — Priorité IA : 95.5/100',
        ], $relance->introLines);
        $this->assertSame(url("/api/v1/wash/incidents/{$incident->id}"), $relance->actionUrl);
    }
}
