<?php

namespace Tests\Feature;

use App\Contracts\WhatsAppClient;
use App\Models\Incident;
use App\Models\Report;
use App\Models\School;
use App\Models\SchoolContact;
use Carbon\Carbon;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Notification;
use Tests\Support\FakeWhatsAppService;
use Tests\TestCase;

class WashWhatsAppSuiviTest extends TestCase
{
    use RefreshDatabase;

    protected int $wamidSeq = 0;

    protected function setUp(): void
    {
        parent::setUp();
        FakeWhatsAppService::reset();
        $this->app->bind(WhatsAppClient::class, FakeWhatsAppService::class);
        config(['whatsapp.simulator' => true]);
        Notification::fake();
    }

    protected function tearDown(): void
    {
        Carbon::setTestNow();
        parent::tearDown();
    }

    protected function fixture(string $name): array
    {
        return json_decode(file_get_contents(base_path("tests/Fixtures/whatsapp/{$name}.json")), true);
    }

    protected function textPayload(string $body, string $from = '237600112233', string $id = 'wamid.SUIVI001'): array
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

    protected function audioPayload(string $id, string $from = '237600112233'): array
    {
        $payload = $this->fixture('audio');
        $payload['entry'][0]['changes'][0]['value']['messages'][0]['id'] = $id;
        $payload['entry'][0]['changes'][0]['value']['messages'][0]['from'] = $from;

        return $payload;
    }

    protected function seedContact(string $phone = '237600112233', string $schoolName = 'École de Bonanjo', string $code = 'DOU-BON-001'): School
    {
        $school = School::create([
            'name' => $schoolName, 'code' => $code, 'district' => 'Wouri',
        ]);
        SchoolContact::create([
            'school_id' => $school->id, 'phone' => $phone,
            'name' => 'Clarisse Eko', 'role' => 'directrice', 'is_verified' => true,
        ]);

        return $school;
    }

    protected function seedIncident(School $school, array $overrides = []): Incident
    {
        return Incident::create(array_merge([
            'school_id' => $school->id,
            'reference_code' => 'WASH-2026-TEST01',
            'title' => 'Fuite robinet bloc A',
            'ai_summary' => 'Fuite robinet bloc A',
            'status' => 'in_progress',
            'urgency' => 'medium',
        ], $overrides));
    }

    protected function setCreatedDay(Incident $incident, string $datetime): Incident
    {
        $incident->forceFill(['created_at' => Carbon::parse($datetime)])->save();

        return $incident->fresh();
    }

    protected function freezeToday(string $datetime = '2026-11-02 10:00:00'): void
    {
        Carbon::setTestNow(Carbon::parse($datetime));
    }

    protected function fakeTriageNotDuplicate(): void
    {
        Http::fake([
            '*/v1/wash/triage' => Http::response([
                'raw_text' => 'Robinet qui fuit.',
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
            '*/v1/wash/check-duplicates' => Http::response([
                'is_duplicate' => false,
                'matched_incident_id' => null,
                'similarity_score' => 0.1,
            ], 200),
        ]);
    }

    /** Envoie un message texte suivi et retourne le résultat (état cache persisté). */
    protected function send(string $body, string $from = '237600112233'): array
    {
        $this->wamidSeq++;
        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->textPayload(
            $body, $from, sprintf('wamid.SUIVI.%d', $this->wamidSeq)
        ));

        return $results[0] ?? [];
    }

    protected function sentTexts(): array
    {
        return array_values(array_filter(
            FakeWhatsAppService::$sent,
            fn ($m) => ($m['type'] ?? '') === 'text'
        ));
    }

    protected function lastText(): string
    {
        $texts = $this->sentTexts();
        $this->assertNotEmpty($texts);

        return end($texts)['message'];
    }

    public function test_suivi_by_reference_text(): void
    {
        $school = $this->seedContact();
        $incident = $this->seedIncident($school);

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->textPayload(
            'Bonjour, suivi WASH-2026-TEST01 svp ?',
            '237600112233',
            'wamid.SUIVI_REF_001'
        ));

        $this->assertEquals('suivi', $results[0]['status'] ?? null);
        $this->assertEquals($incident->id, $results[0]['incident_id'] ?? null);

        // Zéro création : ni incident ni Report.
        $this->assertEquals(1, Incident::count());
        $this->assertEquals(0, Report::count());

        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $reply = $texts[0]['message'];
        $this->assertStringContainsString('WASH-2026-TEST01', $reply);
        $this->assertStringContainsString('Fuite robinet bloc A', $reply);
        $this->assertStringContainsString('équipe en intervention', $reply);
        $this->assertStringContainsString('Prochaine étape', $reply);
        $this->assertStringContainsString('*École :* École de Bonanjo', $reply);
        $this->assertStringContainsString('*Urgence :* moyenne', $reply);
        $this->assertStringContainsString('Signalé le', $reply);
        $this->assertLessThanOrEqual(397, mb_strlen($reply));
    }

    public function test_suivi_sans_reference_demande_id_au_lieu_du_dernier(): void
    {
        $school = $this->seedContact();
        $this->seedIncident($school, [
            'reference_code' => 'WASH-2026-OLD001', 'status' => 'resolved',
            'title' => 'Pompe HS', 'ai_summary' => 'Pompe HS cour',
        ]);
        $this->seedIncident($school, [
            'reference_code' => 'WASH-2026-NEW002', 'status' => 'assigned',
            'title' => 'Toilettes bouchées bloc B', 'ai_summary' => 'Toilettes bouchées bloc B',
        ]);

        $result = $this->send('je voudrais suivre mon dossier');

        $this->assertEquals('suivi', $result['status'] ?? null);
        $this->assertEquals('awaiting_id', $result['step'] ?? null);
        $this->assertArrayNotHasKey('incident_id', $result);

        $this->assertEquals(2, Incident::count());
        $this->assertEquals(0, Report::count());

        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $reply = $texts[0]['message'];
        // On guide (demande d'ID), on ne renvoie pas le dernier dossier.
        $this->assertStringContainsString('numéro WASH', $reply);
        $this->assertStringContainsString('NON', $reply);
        $this->assertStringNotContainsString('WASH-2026-NEW002', $reply);
        $this->assertStringNotContainsString('WASH-2026-OLD001', $reply);
        $this->assertLessThanOrEqual(397, mb_strlen($reply));
    }

    public function test_flux_id_direct_renvoie_fiche_complete(): void
    {
        $school = $this->seedContact();
        $incident = $this->seedIncident($school, ['status' => 'assigned', 'urgency' => 'high']);

        $result = $this->send('je voudrais suivre mon dossier');
        $this->assertEquals('awaiting_id', $result['step'] ?? null);
        $this->assertStringContainsString('numéro WASH', $this->lastText());

        $result = $this->send('WASH-2026-TEST01');
        $this->assertEquals('suivi', $result['status'] ?? null);
        $this->assertEquals($incident->id, $result['incident_id'] ?? null);

        $reply = $this->lastText();
        $this->assertStringContainsString('WASH-2026-TEST01', $reply);
        $this->assertStringContainsString('technicien assigné', $reply);
        $this->assertStringContainsString('*Urgence :* haute', $reply);
        $this->assertStringContainsString('*École :* École de Bonanjo', $reply);
        $this->assertStringContainsString('Signalé le', $reply);
        $this->assertStringContainsString('Fuite robinet bloc A', $reply);
        $this->assertLessThanOrEqual(397, mb_strlen($reply));

        $this->assertEquals(1, Incident::count());
        $this->assertEquals(0, Report::count());
    }

    public function test_flux_complet_ecole_date_choix(): void
    {
        $this->freezeToday();
        $school = $this->seedContact();
        $older = $this->setCreatedDay($this->seedIncident($school, [
            'reference_code' => 'WASH-2026-HIER01', 'status' => 'in_progress',
            'title' => 'Fuite robinet bloc A', 'ai_summary' => 'Fuite robinet bloc A',
        ]), '2026-11-01 08:00:00');
        $newer = $this->setCreatedDay($this->seedIncident($school, [
            'reference_code' => 'WASH-2026-HIER02', 'status' => 'assigned',
            'title' => 'Toilettes bouchées bloc B', 'ai_summary' => 'Toilettes bouchées bloc B',
        ]), '2026-11-01 15:00:00');

        $result = $this->send('je voudrais suivre mon dossier');
        $this->assertEquals('awaiting_id', $result['step'] ?? null);
        $this->assertStringContainsString('numéro WASH', $this->lastText());

        $result = $this->send('je ne connais pas le numéro');
        $this->assertEquals('awaiting_school', $result['step'] ?? null);
        $this->assertStringContainsString('De quelle *école*', $this->lastText());

        $result = $this->send("c'est l'école de Bonanjo");
        $this->assertEquals('awaiting_date', $result['step'] ?? null);
        $this->assertStringContainsString('Quel jour', $this->lastText());

        $result = $this->send('hier');
        $this->assertEquals('awaiting_choice', $result['step'] ?? null);
        $proposal = $this->lastText();
        $this->assertStringContainsString('*1) WASH-2026-HIER02', $proposal);
        $this->assertStringContainsString('*2) WASH-2026-HIER01', $proposal);
        $this->assertStringContainsString('NUMÉRO', $proposal);
        $this->assertLessThanOrEqual(397, mb_strlen($proposal));

        $result = $this->send('2');
        $this->assertEquals('suivi', $result['status'] ?? null);
        $this->assertEquals($older->id, $result['incident_id'] ?? null);
        $reply = $this->lastText();
        $this->assertStringContainsString('WASH-2026-HIER01', $reply);
        $this->assertStringContainsString('équipe en intervention', $reply);
        $this->assertStringContainsString('*École :* École de Bonanjo', $reply);
        $this->assertLessThanOrEqual(397, mb_strlen($reply));

        $this->assertNotEquals($newer->id, $result['incident_id'] ?? null);
        $this->assertEquals(2, Incident::count());
        $this->assertEquals(0, Report::count());
    }

    public function test_id_partiel_unique_resout_directement(): void
    {
        $school = $this->seedContact();
        $incident = $this->seedIncident($school);
        $this->seedIncident($school, [
            'reference_code' => 'WASH-2026-TEST02', 'title' => 'Pompe HS',
            'ai_summary' => 'Pompe HS cour',
        ]);

        $this->send('suivre mon dossier');
        $result = $this->send('TEST01');

        $this->assertEquals('suivi', $result['status'] ?? null);
        $this->assertEquals($incident->id, $result['incident_id'] ?? null);
        $this->assertStringContainsString('WASH-2026-TEST01', $this->lastText());
        $this->assertEquals(2, Incident::count());
        $this->assertEquals(0, Report::count());
    }

    public function test_id_partiel_ambigu_propose_liste(): void
    {
        $school = $this->seedContact();
        $this->seedIncident($school);
        $latest = $this->seedIncident($school, [
            'reference_code' => 'WASH-2026-TEST02', 'title' => 'Pompe HS',
            'ai_summary' => 'Pompe HS cour',
        ]);

        $this->send('suivre mon dossier');
        $result = $this->send('TEST0');

        $this->assertEquals('awaiting_choice', $result['step'] ?? null);
        $proposal = $this->lastText();
        $this->assertStringContainsString('Plusieurs dossiers correspondent', $proposal);
        $this->assertStringContainsString('*1) WASH-2026-TEST02', $proposal);
        $this->assertStringContainsString('*2) WASH-2026-TEST01', $proposal);

        $result = $this->send('1');
        $this->assertEquals($latest->id, $result['incident_id'] ?? null);
        $this->assertEquals(2, Incident::count());
        $this->assertEquals(0, Report::count());
    }

    public function test_ecole_donnee_directement_a_etape_id(): void
    {
        $school = $this->seedContact();
        $this->seedIncident($school);

        $this->send('suivre mon dossier');
        $result = $this->send("c'est l'école de Bonanjo");

        $this->assertEquals('awaiting_date', $result['step'] ?? null);
        $this->assertStringContainsString('Quel jour', $this->lastText());
    }

    public function test_date_donnee_directement_a_etape_id(): void
    {
        $this->freezeToday();
        $school = $this->seedContact();
        $this->setCreatedDay($this->seedIncident($school), '2026-11-01 09:00:00');

        $this->send('suivre mon dossier');
        $result = $this->send('hier');

        $this->assertEquals('awaiting_choice', $result['step'] ?? null);
        $proposal = $this->lastText();
        $this->assertStringContainsString('*1) WASH-2026-TEST01', $proposal);
        $this->assertStringContainsString('NUMÉRO', $proposal);
    }

    public function test_ecole_inconnue_puis_mon_ecole(): void
    {
        $school = $this->seedContact();
        $this->seedIncident($school);

        $this->send('suivre mon dossier');
        $result = $this->send('non');
        $this->assertEquals('awaiting_school', $result['step'] ?? null);
        $this->assertStringContainsString('De quelle *école*', $this->lastText());

        $result = $this->send('École de Nullepart XYZ');
        $this->assertEquals('awaiting_school', $result['step'] ?? null);
        $this->assertStringContainsString('ne trouve pas cette école', $this->lastText());

        $result = $this->send('mon école');
        $this->assertEquals('awaiting_date', $result['step'] ?? null);
        $this->assertStringContainsString('Quel jour', $this->lastText());
    }

    public function test_ecoles_homonymes_demandent_precision(): void
    {
        $school = $this->seedContact();
        $this->seedIncident($school);
        School::create(['name' => 'École de Bonanjo Village', 'code' => 'DOU-BON-002', 'district' => 'Wouri']);

        $this->send('suivre mon dossier');
        $this->send('non');
        $result = $this->send('Bonanjo');

        $this->assertEquals('awaiting_school', $result['step'] ?? null);
        $reply = $this->lastText();
        $this->assertStringContainsString('Plusieurs écoles', $reply);
        $this->assertStringContainsString('École de Bonanjo', $reply);
        $this->assertStringContainsString('École de Bonanjo Village', $reply);

        $result = $this->send('École de Bonanjo Village');
        $this->assertEquals('awaiting_date', $result['step'] ?? null);
        $this->assertStringContainsString('Quel jour', $this->lastText());
    }

    public function test_date_le_2_et_jour_seul(): void
    {
        $this->freezeToday();
        $school = $this->seedContact();
        $this->setCreatedDay($this->seedIncident($school), '2026-11-02 08:00:00');

        $this->send('suivre mon dossier');
        $this->send('non');
        $this->send('Bonanjo');
        $result = $this->send('le 2');

        $this->assertEquals('awaiting_choice', $result['step'] ?? null);
        $this->assertStringContainsString('*1) WASH-2026-TEST01', $this->lastText());

        // Même attente avec le jour seul (« 2 »).
        Cache::forget('wash.whatsapp.suivi.237600112233');
        $this->send('suivre mon dossier');
        $this->send('non');
        $this->send('Bonanjo');
        $result = $this->send('2');

        $this->assertEquals('awaiting_choice', $result['step'] ?? null);
        $this->assertStringContainsString('*1) WASH-2026-TEST01', $this->lastText());
    }

    public function test_date_format_numerique(): void
    {
        $this->freezeToday();
        $school = $this->seedContact();
        $this->setCreatedDay($this->seedIncident($school), '2026-11-02 08:00:00');

        $this->send('suivre mon dossier');
        $this->send('non');
        $this->send('Bonanjo');
        $result = $this->send('02/11');

        $this->assertEquals('awaiting_choice', $result['step'] ?? null);
        $this->assertStringContainsString('*1) WASH-2026-TEST01', $this->lastText());
    }

    public function test_date_mois_en_lettres(): void
    {
        $this->freezeToday();
        $school = $this->seedContact();
        $this->setCreatedDay($this->seedIncident($school), '2026-11-02 08:00:00');

        $this->send('suivre mon dossier');
        $this->send('non');
        $this->send('Bonanjo');
        $result = $this->send('2 novembre');

        $this->assertEquals('awaiting_choice', $result['step'] ?? null);
        $this->assertStringContainsString('*1) WASH-2026-TEST01', $this->lastText());
    }

    public function test_aucun_dossier_ce_jour_la_puis_autre_date(): void
    {
        $this->freezeToday();
        $school = $this->seedContact();
        $this->setCreatedDay($this->seedIncident($school), '2026-11-02 08:00:00');

        $this->send('suivre mon dossier');
        $this->send('non');
        $this->send('Bonanjo');
        $result = $this->send('hier');

        $this->assertEquals('awaiting_date', $result['step'] ?? null);
        $this->assertArrayNotHasKey('incident_id', $result);
        $reply = $this->lastText();
        $this->assertStringContainsString('Aucun dossier', $reply);
        $this->assertStringContainsString('École de Bonanjo', $reply);

        $result = $this->send("aujourd'hui");
        $this->assertEquals('awaiting_choice', $result['step'] ?? null);
        $this->assertStringContainsString('*1) WASH-2026-TEST01', $this->lastText());
    }

    public function test_choix_invalide_repropose_liste(): void
    {
        $this->freezeToday();
        $school = $this->seedContact();
        $this->setCreatedDay($this->seedIncident($school, [
            'reference_code' => 'WASH-2026-CHX01', 'title' => 'Fuite robinet',
            'ai_summary' => 'Fuite robinet bloc A',
        ]), '2026-11-01 08:00:00');
        $latest = $this->setCreatedDay($this->seedIncident($school, [
            'reference_code' => 'WASH-2026-CHX02', 'title' => 'Pompe HS',
            'ai_summary' => 'Pompe HS cour',
        ]), '2026-11-01 15:00:00');

        $this->send('suivre mon dossier');
        $this->send('non');
        $this->send('Bonanjo');
        $this->send('hier');

        $result = $this->send('poulet');
        $this->assertEquals('awaiting_choice', $result['step'] ?? null);
        $reply = $this->lastText();
        $this->assertStringContainsString("Je n'ai pas compris", $reply);
        $this->assertStringContainsString('*1) WASH-2026-CHX02', $reply);
        $this->assertStringContainsString('*2) WASH-2026-CHX01', $reply);

        $result = $this->send('9');
        $this->assertEquals('awaiting_choice', $result['step'] ?? null);
        $this->assertStringContainsString("Je n'ai pas compris", $this->lastText());

        $result = $this->send('1');
        $this->assertEquals($latest->id, $result['incident_id'] ?? null);
        $this->assertEquals(2, Incident::count());
        $this->assertEquals(0, Report::count());
    }

    public function test_choix_par_id_affiche(): void
    {
        $this->freezeToday();
        $school = $this->seedContact();
        $target = $this->setCreatedDay($this->seedIncident($school, [
            'reference_code' => 'WASH-2026-CHX01',
        ]), '2026-11-01 08:00:00');
        $this->setCreatedDay($this->seedIncident($school, [
            'reference_code' => 'WASH-2026-CHX02', 'title' => 'Pompe HS',
            'ai_summary' => 'Pompe HS cour',
        ]), '2026-11-01 15:00:00');

        $this->send('suivre mon dossier');
        $this->send('non');
        $this->send('Bonanjo');
        $this->send('hier');

        $result = $this->send('WASH-2026-CHX01');

        $this->assertEquals('suivi', $result['status'] ?? null);
        $this->assertEquals($target->id, $result['incident_id'] ?? null);
        $this->assertStringContainsString('WASH-2026-CHX01', $this->lastText());
    }

    public function test_aucun_choix_revient_a_la_date(): void
    {
        $this->freezeToday();
        $school = $this->seedContact();
        $this->setCreatedDay($this->seedIncident($school), '2026-11-02 08:00:00');

        $this->send('suivre mon dossier');
        // Réponse inclassable à l'étape ID : on redemande, sans casser le flux.
        $junk = $this->send('TEST0nope');
        $this->assertEquals('awaiting_id', $junk['step'] ?? null);
        $this->send('non');
        $this->send('Bonanjo');
        $this->send('hier');
        // « hier » n'a rien donné : on prend une date avec un dossier...
        $this->send("aujourd'hui");

        $result = $this->send('aucun');
        $this->assertEquals('awaiting_date', $result['step'] ?? null);
        $this->assertStringContainsString('Quel jour', $this->lastText());

        $result = $this->send("aujourd'hui");
        $this->assertEquals('awaiting_choice', $result['step'] ?? null);
        $this->assertStringContainsString('*1) WASH-2026-TEST01', $this->lastText());
    }

    public function test_annuler_arrete_le_suivi(): void
    {
        $school = $this->seedContact();
        $this->seedIncident($school);

        $this->send('suivre mon dossier');
        $result = $this->send('annuler');

        $this->assertEquals('suivi', $result['status'] ?? null);
        $this->assertEquals('cancelled', $result['step'] ?? null);
        $this->assertStringContainsString('on arrête le suivi', $this->lastText());

        // Reprise : un nouveau « suivi » repart de zéro.
        $result = $this->send('suivre mon dossier');
        $this->assertEquals('awaiting_id', $result['step'] ?? null);
        $this->assertArrayNotHasKey('incident_id', $result);
        $this->assertStringContainsString('numéro WASH', $this->lastText());
    }

    public function test_recommencer_repart_de_id(): void
    {
        $school = $this->seedContact();
        $this->seedIncident($school);
        $this->seedIncident($school, [
            'reference_code' => 'WASH-2026-CHX02', 'title' => 'Pompe HS',
            'ai_summary' => 'Pompe HS cour',
        ]);

        $this->send('suivre mon dossier');
        $this->send('WASH-2026');
        $result = $this->send('recommencer');

        $this->assertEquals('awaiting_id', $result['step'] ?? null);
        $this->assertStringContainsString('numéro WASH', $this->lastText());

        $result = $this->send('WASH-2026-TEST01');
        $this->assertEquals('WASH-2026-TEST01', Incident::find($result['incident_id'] ?? null)->reference_code ?? null);
    }

    public function test_nouvelle_panne_interrompt_le_suivi(): void
    {
        $school = $this->seedContact();
        $this->seedIncident($school);
        $this->fakeTriageNotDuplicate();

        $this->send('suivre mon dossier');

        // Nouvelle panne en plein suivi : triage normal, état oublié.
        $result = $this->send('Le robinet du bloc A fuit beaucoup.');
        $this->assertEquals('triaged', $result['status'] ?? null);
        $this->assertEquals(2, Incident::count());

        // Reprise après interruption : le suivi repart de la demande d'ID.
        $result = $this->send('où en est mon dossier ?');
        $this->assertEquals('suivi', $result['status'] ?? null);
        $this->assertEquals('awaiting_id', $result['step'] ?? null);
        $this->assertArrayNotHasKey('incident_id', $result);
        $this->assertStringContainsString('numéro WASH', $this->lastText());
    }

    public function test_etat_suivi_isole_par_numero(): void
    {
        $school = $this->seedContact();
        $incident = $this->seedIncident($school);
        $this->seedContact('237600445566', 'École de Bali', 'DOU-BAL-001');

        $this->send('suivre mon dossier', '237600112233');

        // Un autre numéro discute librement : pas d'état suivi pour lui.
        $this->send('Bonjour', '237600445566');
        $otherReply = $this->lastText();
        $this->assertStringContainsString('Je suis *Sentinel*', $otherReply);
        $this->assertStringNotContainsString('NUMÉRO', $otherReply);

        // Le premier numéro reprend son suivi où il l'avait laissé.
        $result = $this->send('WASH-2026-TEST01', '237600112233');
        $this->assertEquals($incident->id, $result['incident_id'] ?? null);
        $this->assertStringContainsString('WASH-2026-TEST01', $this->lastText());
    }

    public function test_suivi_voice_transcript(): void
    {
        $school = $this->seedContact();
        $incident = $this->seedIncident($school, ['status' => 'triaged']);
        Http::fake([
            '*/v1/voice/transcribe' => Http::response(['transcript' => 'Bonjour, où en est mon signalement ?'], 200),
        ]);

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->audioPayload('wamid.SUIVI_VOC_001'));

        $this->assertEquals('suivi', $results[0]['status'] ?? null);
        $this->assertEquals('awaiting_id', $results[0]['step'] ?? null);

        $this->assertEquals(1, Incident::count());
        $this->assertEquals(0, Report::count());

        // Demande d'ID texte uniquement : ni boutons Oui/Non, ni note vocale.
        $this->assertCount(1, FakeWhatsAppService::$sent);
        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $this->assertStringContainsString('numéro WASH', $texts[0]['message']);
        $this->assertLessThanOrEqual(397, mb_strlen($texts[0]['message']));

        // Suite au message suivant : le bon code résout.
        $result = $this->send('WASH-2026-TEST01');
        $this->assertEquals($incident->id, $result['incident_id'] ?? null);
        $this->assertStringContainsString('pris en compte par notre équipe', $this->lastText());
    }

    public function test_suivi_school_without_incident_gets_guided_reply(): void
    {
        $this->seedContact();

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->textPayload(
            'Je veux suivre mon signalement svp.',
            '237600112233',
            'wamid.SUIVI_EMPTY_001'
        ));

        $this->assertEquals('suivi', $results[0]['status'] ?? null);
        $this->assertArrayNotHasKey('incident_id', $results[0]);

        $this->assertEquals(0, Incident::count());
        $this->assertEquals(0, Report::count());

        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $reply = $texts[0]['message'];
        $this->assertStringContainsString("Aucun signalement pour l'instant", $reply);
        $this->assertStringContainsString('Décrivez votre panne', $reply);
    }

    public function test_suivi_english(): void
    {
        $this->freezeToday();
        $school = $this->seedContact();
        $incident = $this->setCreatedDay($this->seedIncident($school, [
            'status' => 'assigned', 'title' => 'Leaking tap block A', 'ai_summary' => 'Leaking tap block A',
        ]), '2026-11-01 09:00:00');

        $result = $this->send('Hello, what is the status of my report?');
        $this->assertEquals('awaiting_id', $result['step'] ?? null);
        $reply = $this->lastText();
        $this->assertStringContainsString('WASH number', $reply);
        $this->assertStringContainsString('reply *NO*', $reply);
        $this->assertStringNotContainsString($incident->reference_code, $reply);

        $result = $this->send('NO');
        $this->assertEquals('awaiting_school', $result['step'] ?? null);
        $this->assertStringContainsString('Which school', $this->lastText());

        $result = $this->send('Bonanjo');
        $this->assertEquals('awaiting_date', $result['step'] ?? null);
        $this->assertStringContainsString('which day', $this->lastText());

        $result = $this->send('yesterday');
        $this->assertEquals('awaiting_choice', $result['step'] ?? null);
        $proposal = $this->lastText();
        $this->assertStringContainsString('I found *1* case(s)', $proposal);
        $this->assertStringContainsString('*1) WASH-2026-TEST01', $proposal);
        $this->assertStringContainsString('NUMBER', $proposal);

        $result = $this->send('1');
        $this->assertEquals($incident->id, $result['incident_id'] ?? null);
        $reply = $this->lastText();
        $this->assertStringContainsString($incident->reference_code, $reply);
        $this->assertStringContainsString('Status:', $reply);
        $this->assertStringContainsString('technician assigned', $reply);
        $this->assertStringContainsString('School:* École de Bonanjo', $reply);
        $this->assertStringContainsString('Priority:* medium', $reply);
        $this->assertStringContainsString('Next step:', $reply);
        $this->assertLessThanOrEqual(397, mb_strlen($reply));

        $this->assertEquals(1, Incident::count());
        $this->assertEquals(0, Report::count());
    }

    public function test_suivi_unknown_reference_gets_guided_reply(): void
    {
        $school = $this->seedContact();
        $incident = $this->seedIncident($school);

        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->textPayload(
            'Suivi WASH-2026-ZZZZ99 ?',
            '237600112233',
            'wamid.SUIVI_UNK_001'
        ));

        $this->assertEquals('suivi', $results[0]['status'] ?? null);
        $this->assertEquals(1, Incident::count());
        $this->assertEquals(0, Report::count());

        $texts = $this->sentTexts();
        $this->assertCount(1, $texts);
        $this->assertStringContainsString('WASH-2026-ZZZZ99', $texts[0]['message']);

        // Le bon code au message suivant résout (état conservé).
        $result = $this->send('WASH-2026-TEST01');
        $this->assertEquals($incident->id, $result['incident_id'] ?? null);
    }

    public function test_pending_clarification_keeps_priority_over_suivi(): void
    {
        config(['filesystems.disks.public.root' => sys_get_temp_dir() . '/wash-test-public']);
        $school = $this->seedContact();
        $incident = $this->seedIncident($school, ['status' => 'reported']);
        Http::fake([
            '*/v1/wash/triage' => Http::response([
                'raw_text' => 'Robinet qui fuit.',
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
            // Anti-régression hermétique : sans ce stub, la détection de doublons
            // part en vrai HTTP vers l'ai-engine quand il est allumé.
            '*/v1/wash/check-duplicates' => Http::response([
                'is_duplicate' => false,
                'matched_incident_id' => null,
                'similarity_score' => 0.1,
            ], 200),
            '*/v1/voice/transcribe' => Http::response(['transcript' => 'Le robinet du bloc A fuit beaucoup.'], 200),
            '*/v1/voice/synthesize' => Http::response(['audio_base64' => base64_encode('fake-tts')], 200),
        ]);

        // Vocal initial puis clic Non → clarification en attente.
        $this->postJson('/api/v1/whatsapp/webhook', $this->audioPayload('wamid.SUIVI_CLAR_A'))->assertOk();
        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('interactive_no'))->assertOk();
        FakeWhatsAppService::$sent = [];
        $this->assertEquals(2, Incident::count());

        // Un message de suivi pendant la clarification reste une correction.
        $service = app(\App\Services\WashWhatsAppService::class);
        $results = $service->handlePayload($this->textPayload(
            'Où en est mon dossier, le bloc B aussi fuit ?',
            '237600112233',
            'wamid.SUIVI_CLAR_TXT'
        ));

        $this->assertEquals('clarification_applied', $results[0]['status'] ?? null);
        $this->assertEquals(2, Incident::count());

        // … puis le suivi guidé démarre au tour suivant (clé consommée par Oui).
        $this->postJson('/api/v1/whatsapp/webhook', $this->fixture('interactive_yes'))->assertOk();
        FakeWhatsAppService::$sent = [];

        $results = $service->handlePayload($this->textPayload(
            'Où en est mon dossier ?',
            '237600112233',
            'wamid.SUIVI_CLAR_TXT2'
        ));
        $this->assertEquals('suivi', $results[0]['status'] ?? null);
        $this->assertEquals('awaiting_id', $results[0]['step'] ?? null);
        $this->assertArrayNotHasKey('incident_id', $results[0]);
        $this->assertStringContainsString('numéro WASH', $this->lastText());
    }

    /** « update about my incident » : intention suivie + réponse EN. */
    public function test_suivi_update_about_my_incident_replies_english(): void
    {
        $school = $this->seedContact();
        $this->seedIncident($school);

        $result = $this->send('hello i want to have update about my incident');

        $this->assertEquals('suivi', $result['status'] ?? null);
        $this->assertEquals('awaiting_id', $result['step'] ?? null);
        $this->assertStringContainsString('WASH number', $this->lastText());
    }

    /** Slot EN en cours de suivi FR : le message courant gagne, état rafraîchi. */
    public function test_suivi_step_english_message_wins_over_french_state(): void
    {
        $school = $this->seedContact();
        $this->seedIncident($school);

        $this->send('je voudrais suivre mon dossier');
        $this->assertStringContainsString('numéro WASH', $this->lastText());

        FakeWhatsAppService::$sent = [];
        $this->send('NO, I do not have it, my incident update please');

        $this->assertStringContainsString('Which school is it', $this->lastText());
    }

    /** Garde FR : « le status de mon dossier » reste en français (veto). */
    public function test_suivi_french_status_stays_french(): void
    {
        $school = $this->seedContact();
        $this->seedIncident($school);

        $result = $this->send('le status de mon dossier ?');

        $this->assertEquals('suivi', $result['status'] ?? null);
        $this->assertStringContainsString('numéro WASH', $this->lastText());
    }
}
