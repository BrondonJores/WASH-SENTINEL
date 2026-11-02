<?php

namespace Tests\Feature;

use App\Contracts\WhatsAppClient;
use App\Models\Incident;
use App\Models\School;
use App\Models\SchoolContact;
use App\Services\WashWhatsAppService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Notification;
use Tests\Support\FakeWhatsAppService;
use Tests\TestCase;

/**
 * Détection de langue des TEXTES WhatsApp : pilotée par données
 * (config/wash_languages.php) + issue INCERTAIN guidée.
 *
 * Les méthodes langue sont protected : on les appelle par réflexion
 * (comportement réel, sans exposer de nouvelle API publique).
 */
class WashWhatsAppLanguageTest extends TestCase
{
    use RefreshDatabase;

    /** Phrase exacte du guidage incertain (FR simple + EN en config). */
    protected const ASK_FR = 'En quelle langue préférez-vous continuer ? Répondez FR ou EN';

    protected function setUp(): void
    {
        parent::setUp();
        FakeWhatsAppService::reset();
        $this->app->bind(WhatsAppClient::class, FakeWhatsAppService::class);
        config(['whatsapp.simulator' => true]);
        Notification::fake();
    }

    /** Appel d'une méthode langue protected (réflexion). */
    protected function lang(string $method, array $args = [])
    {
        $reflection = new \ReflectionMethod(WashWhatsAppService::class, $method);
        $reflection->setAccessible(true);

        return $reflection->invokeArgs(app(WashWhatsAppService::class), $args);
    }

    protected function fixture(string $name): array
    {
        return json_decode(file_get_contents(base_path("tests/Fixtures/whatsapp/{$name}.json")), true);
    }

    protected function textPayload(string $body, string $from = '237600112233', string $id = 'wamid.LANG001'): array
    {
        $payload = $this->fixture('text');
        $payload['entry'][0]['changes'][0]['value']['messages'][0] = [
            'from' => $from,
            'id' => $id,
            'timestamp' => '1760000000',
            'type' => 'text',
            'text' => ['body' => $body],
        ];

        return $payload;
    }

    protected function seedContact(): School
    {
        $school = School::create([
            'name' => 'École de Bonanjo', 'code' => 'DOU-BON-001', 'district' => 'Wouri',
        ]);
        SchoolContact::create([
            'school_id' => $school->id, 'phone' => '237600112233',
            'name' => 'Clarisse Eko', 'role' => 'directrice', 'is_verified' => true,
        ]);

        return $school;
    }

    protected function triageResponse()
    {
        return Http::response([
            'raw_text' => 'Tap leaking.',
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
        ], 200);
    }

    // --------------------------------------------------------------
    // Config chargée : marqueurs, veto, seuils, demande.
    // --------------------------------------------------------------

    public function test_config_langue_chargee_avec_marqueurs_veto_et_seuils(): void
    {
        $this->assertSame('fr', config('wash_languages.default'));
        $this->assertSame(['fr', 'en'], config('wash_languages.codes'));
        $this->assertSame('fr', config('wash_languages.veto'));
        $this->assertSame(1, config('wash_languages.min_markers'));

        // Marqueurs FR/EN des deux flux, modes d'appariement historiques.
        $this->assertSame('word', config('wash_languages.reply.match'));
        $this->assertSame('contains', config('wash_languages.suivi.match'));
        foreach (['reply.french_markers', 'reply.english_markers', 'suivi.french_markers', 'suivi.english_markers'] as $key) {
            $this->assertNotEmpty(config("wash_languages.{$key}"), "config wash_languages.{$key} vide");
        }
        $this->assertContains('bonjour', config('wash_languages.reply.french_markers'));
        $this->assertContains('please', config('wash_languages.reply.english_markers'));
        $this->assertContains('suivi', config('wash_languages.suivi.french_markers'));
        $this->assertContains('my report', config('wash_languages.suivi.english_markers'));

        // Demande polie bilingue, phrase FR exacte.
        $this->assertStringContainsString(self::ASK_FR, config('wash_languages.ask'));
    }

    // --------------------------------------------------------------
    // Pas de mots en dur dans le service (source + comportement).
    // --------------------------------------------------------------

    public function test_service_sans_listes_de_mots_en_dur(): void
    {
        $source = file_get_contents(app_path('Services/WashWhatsAppService.php'));

        // Les 4 anciennes constantes de marqueurs ont disparu.
        foreach (['REPLY_FRENCH_MARKERS', 'REPLY_ENGLISH_MARKERS', 'SUIVI_FRENCH_MARKERS', 'SUIVI_ENGLISH_MARKERS'] as $const) {
            $this->assertStringNotContainsString($const, $source, "constante {$const} encore en dur");
        }

        // Marqueurs distinctifs (absents des listes hors-scope : intention
        // suivi, filtre eau/hygiène, stop-mots) : plus aucune occurrence.
        foreach (["'good morning'", "'pupil'", "'goutte'", "'this is'"] as $marker) {
            $this->assertStringNotContainsString($marker, $source, "marqueur {$marker} encore en dur");
        }
    }

    public function test_marqueur_personnalise_en_config_bascule_en_anglais(): void
    {
        // Preuve comportementale du pilotage par données : un marqueur
        // inconnu du code, ajouté en config, tranche à lui seul.
        config(['wash_languages.reply.english_markers' => ['zebravoice']]);

        $this->assertSame('en', $this->lang('detectTextLang', ['Zebravoice au rapport.']));
        $this->assertTrue($this->lang('isEnglishReply', ['Zebravoice au rapport.']));
    }

    public function test_veto_et_seuil_config_tranchent_le_melange(): void
    {
        $mixte = 'Hello, le robinet du bloc A fuit beaucoup, please help !';

        // Veto FR historique : le mélange reste en français.
        $this->assertSame('fr', $this->lang('detectTextLang', [$mixte]));

        // Veto inversé en config : le même mélange bascule en anglais.
        config(['wash_languages.veto' => 'en']);
        $this->assertSame('en', $this->lang('detectTextLang', [$mixte]));
    }

    public function test_seuil_min_markers_rend_incertain_sous_le_seuil(): void
    {
        // Un seul marqueur EN ne suffit plus avec un seuil à 99.
        config(['wash_languages.min_markers' => 99]);

        $this->assertSame('uncertain', $this->lang('detectTextLang', ['Hello, water tap leak.']));
        $this->assertFalse($this->lang('isEnglishReply', ['Hello, water tap leak.']));
    }

    public function test_signalement_avec_marqueur_config_repond_en_anglais_bout_en_bout(): void
    {
        $this->seedContact();
        Http::fake(['*/v1/wash/triage' => $this->triageResponse()]);
        config(['wash_languages.reply.english_markers' => ['zebravoice']]);

        // « water tap leak » passe le filtre eau/hygiène ; seul « zebravoice »
        // (config seule) tranche la langue vers l'anglais.
        $this->postJson('/api/v1/whatsapp/webhook', $this->textPayload(
            'Zebravoice: water tap leak block A.',
            '237600112233',
            'wamid.LANG_CONF_001'
        ))->assertOk();

        $incident = Incident::first();
        $this->assertNotNull($incident);
        $texts = array_values(array_filter(
            FakeWhatsAppService::$sent,
            fn ($m) => ($m['type'] ?? '') === 'text'
        ));
        $this->assertCount(1, $texts);
        $this->assertStringContainsString('Thanks! Case *' . $incident->reference_code . '* recorded', $texts[0]['message']);
    }

    // --------------------------------------------------------------
    // Incertain : garde la langue mémorisée, jamais de bascule au hasard.
    // --------------------------------------------------------------

    public function test_incertain_garde_conversation_anglaise(): void
    {
        $from = '237600112233';

        // Conversation mémorisée EN, puis slots neutres (choix, NON, référence).
        $this->lang('rememberLangFromText', [$from, 'Hello, the tap in block A is leaking, please send help.']);
        $this->assertTrue($this->lang('conversationEnglish', [$from]));

        foreach (['2', 'NON', 'WASH-2026-TEST01', 'Bonanjo'] as $neutre) {
            $this->assertSame('uncertain', $this->lang('detectTextLang', [$neutre]), "« {$neutre} » devrait être incertain");
            $this->lang('rememberLangFromText', [$from, $neutre]);
            $this->assertTrue($this->lang('conversationEnglish', [$from]), "« {$neutre} » a écrasé la mémoire EN");
        }
    }

    public function test_incertain_garde_conversation_francaise(): void
    {
        $from = '237600112233';

        $this->lang('rememberLangFromText', [$from, 'Bonjour, le robinet du bloc A fuit beaucoup.']);
        $this->assertFalse($this->lang('conversationEnglish', [$from]));

        $this->lang('rememberLangFromText', [$from, 'WASH-2026-TEST01']);
        $this->assertSame('fr', $this->lang('rememberedLang', [$from]));
        $this->assertFalse($this->lang('conversationEnglish', [$from]));
    }

    // --------------------------------------------------------------
    // Incertain sans mémoire : on demande poliment, puis on persiste.
    // --------------------------------------------------------------

    public function test_incertain_sans_memoire_demande_la_langue(): void
    {
        $from = '237699988877'; // Numéro frais : aucune langue mémorisée.

        $this->assertNull($this->lang('rememberedLang', [$from]));
        $this->assertTrue($this->lang('needsLangChoice', [$from, 'WASH-2026-TEST01']));
        $this->assertTrue($this->lang('needsLangChoice', [$from, '2']));

        // Texte tranché : pas de demande même sans mémoire.
        $this->assertFalse($this->lang('needsLangChoice', [$from, 'Hello, the tap is leaking please.']));
        $this->assertFalse($this->lang('needsLangChoice', [$from, 'Bonjour, le robinet fuit.']));

        // Demande polie : phrase FR exacte + version EN.
        $ask = $this->lang('langChoiceReply', []);
        $this->assertStringContainsString(self::ASK_FR, $ask);
        $this->assertStringContainsString('Which language', $ask);
    }

    public function test_incertain_avec_memoire_ne_demande_pas(): void
    {
        $from = '237600112233';

        $this->lang('rememberLangFromText', [$from, 'Hello, the tap is leaking please.']);
        $this->assertFalse($this->lang('needsLangChoice', [$from, 'WASH-2026-TEST01']));
    }

    public function test_choix_fr_en_persiste_et_texte_libre_ignore(): void
    {
        $from = '237699988877';

        // Codes stables, insensibles à la casse et aux espaces.
        $this->assertTrue($this->lang('rememberLangChoice', [$from, 'FR']));
        $this->assertSame('fr', $this->lang('rememberedLang', [$from]));
        $this->assertTrue($this->lang('rememberLangChoice', [$from, ' en ']));
        $this->assertSame('en', $this->lang('rememberedLang', [$from]));

        // Texte libre : refusé, mémoire inchangée (reste EN).
        $this->assertFalse($this->lang('rememberLangChoice', [$from, 'peut-être']));
        $this->assertSame('en', $this->lang('rememberedLang', [$from]));

        // Sur un numéro frais, le texte libre ne crée aucune mémoire.
        $this->assertFalse($this->lang('rememberLangChoice', ['237600445566', 'bonjour !']));
        $this->assertNull($this->lang('rememberedLang', ['237600445566']));
    }

    // --------------------------------------------------------------
    // FR/EN existants inchangés (corpus des suites WhatsApp).
    // --------------------------------------------------------------

    public function test_corpus_fr_en_existant_inchange(): void
    {
        $cases = [
            // [texte, issue attendue] — issus des tests WhatsApp verts.
            ['Bonjour, le robinet du bloc A fuit beaucoup depuis hier.', 'fr'],
            ['Le robinet du bloc A fuit beaucoup.', 'fr'],
            ['Les toilettes du bloc B sont bouchées, ça déborde.', 'fr'],
            ['Hello, this is Bonanjo school, the tap in block A is leaking, please help.', 'en'],
            ['Hello, the tap in block A is leaking, please send help.', 'en'],
            ['Please, the tap in block A is leaking badly, thank you.', 'en'],
            ['Sorry, it is the toilet in block B, not block A.', 'en'],
            // Veto FR : mélange FR/EN → français.
            ['Hello, sorry : le robinet du bloc A fuit beaucoup, please help !', 'fr'],
            ['Hello, où en est mon dossier ?', 'fr'],
            // Suivi EN (marqueurs suivi, sans marqueur FR).
            ['Hello, what is the status of my report?', 'en'],
            ['Where is my report?', 'en'],
            // Suivi FR.
            ['Je veux suivre mon signalement svp.', 'fr'],
            ['Suivi WASH-2026-ZZZZ99 ?', 'fr'],
            // Frontières de mot : 'block' (EN) ≠ 'bloc' (FR).
            ['The tap in block A is leaking.', 'en'],
            ['Le robinet du bloc A fuit.', 'fr'],
            // Neutres : slots, références, noms — incertain, pas FR.
            ['2', 'uncertain'],
            ['NON', 'uncertain'],
            ['WASH-2026-TEST01', 'uncertain'],
            ['Bonanjo', 'uncertain'],
        ];

        foreach ($cases as [$text, $expected]) {
            $this->assertSame($expected, $this->lang('detectTextLang', [$text]), "« {$text} »");
        }
    }

    public function test_message_brut_prioritaire_sur_memoire(): void
    {
        $from = '237600112233';

        // Mémoire EN, mais message courant FR explicite → FR.
        $this->lang('rememberLangFromText', [$from, 'Hello, the tap is leaking please.']);
        $this->assertFalse($this->lang('messageEnglish', [['text' => 'Bonjour, le robinet fuit.', 'from' => $from]]));

        // Message courant neutre → mémoire (EN).
        $this->assertTrue($this->lang('messageEnglish', [['text' => 'WASH-2026-TEST01', 'from' => $from]]));

        // Sans texte ni mémoire → défaut FR.
        $this->assertFalse($this->lang('messageEnglish', [['from' => '237699988877']]));
    }
}
