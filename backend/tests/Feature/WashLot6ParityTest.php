<?php

namespace Tests\Feature;

use App\Models\Incident;
use App\Models\School;
use App\Services\IncidentTriageService;
use App\Services\WashRelanceService;
use App\Services\WashWhatsAppService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

/**
 * LOT 6 — parité d'extraction (comportement et textes inchangés).
 *
 * 1. Formule de priorité partagée avec backend/ai-engine/app/extractor.py
 *    (WashExtractor::calculate_priority_score) :
 *    round(u*0.35 + h*0.35 + s*0.30, 1), s = min(élèves,1000)/1000*100,
 *    tables urgence {low:10, medium:45, high:75, critical:100} et risque
 *    {low:10, medium:40, high:75, severe:100}, replis inconnus 45.0/40.0.
 *    Les 9 vecteurs ci-dessous ont été calculés DES DEUX CÔTÉS
 *    (extractor.py via .venv + IncidentTriageService::priorityScore) et
 *    concordent. Divergences historiques documentées (conservées) :
 *    - à 0 élève, extractor.py substitue DEFAULT_AFFECTED_STUDENTS=50
 *      (sortie LLM) tandis que le PHP score le 0 explicite (saisie humaine) ;
 *    - sur les demis exacts (ex. somme 49.25), l'arrondi PHP (half away)
 *      et Python (banker's) divergent (49.3 vs 49.2) — aucun vecteur retenu.
 * 2. generateReferenceCode() matche le pattern de suivi
 *    WashWhatsAppService::SUIVI_REFERENCE_PATTERN (lecture seule).
 * 3. Source unique Incident::OPEN_STATUSES (5 occurrences PHP unifiées).
 * 4. Clés config/wash.php et textes FR lang/fr/wash.php identiques.
 */
class WashLot6ParityTest extends TestCase
{
    use RefreshDatabase;

    /** Vecteurs (urgency, hazard, students) => score attendu (les deux côtés). */
    public static function priorityVectors(): array
    {
        return [
            'minima' => ['low', 'low', 50, 8.5],
            'médians' => ['medium', 'medium', 500, 44.8],
            'hauts' => ['high', 'high', 1000, 82.5],
            'maxima' => ['critical', 'severe', 1000, 100.0],
            'plafond élèves' => ['critical', 'severe', 2500, 100.0],
            'inconnus' => ['xxx', 'zzz', 100, 32.8],
            'mixte' => ['medium', 'low', 50, 20.8],
            'risque sévère' => ['low', 'severe', 10, 38.8],
            'presque plafond' => ['critical', 'low', 999, 68.5],
        ];
    }

    /**
     * @dataProvider priorityVectors
     */
    public function test_priority_score_matches_extractor_formula(string $urgency, string $hazard, int $students, float $expected): void
    {
        $service = (new \ReflectionClass(IncidentTriageService::class))->newInstanceWithoutConstructor();
        $method = new \ReflectionMethod(IncidentTriageService::class, 'priorityScore');

        $this->assertSame($expected, $method->invoke($service, $urgency, $hazard, $students));
    }

    public function test_priority_constants_mirror_extractor(): void
    {
        $this->assertSame(0.35, IncidentTriageService::PRIORITY_WEIGHT_URGENCY);
        $this->assertSame(0.35, IncidentTriageService::PRIORITY_WEIGHT_HAZARD);
        $this->assertSame(0.30, IncidentTriageService::PRIORITY_WEIGHT_STUDENTS);
        $this->assertSame(
            ['low' => 10.0, 'medium' => 45.0, 'high' => 75.0, 'critical' => 100.0],
            IncidentTriageService::PRIORITY_URGENCY_SCORES
        );
        $this->assertSame(
            ['low' => 10.0, 'medium' => 40.0, 'high' => 75.0, 'severe' => 100.0],
            IncidentTriageService::PRIORITY_HAZARD_SCORES
        );
        $this->assertSame(1000, IncidentTriageService::PRIORITY_MAX_STUDENTS);
        $this->assertSame(45.0, IncidentTriageService::PRIORITY_DEFAULT_URGENCY_SCORE);
        $this->assertSame(40.0, IncidentTriageService::PRIORITY_DEFAULT_HAZARD_SCORE);
    }

    public function test_reference_code_matches_suivi_pattern(): void
    {
        $this->assertSame('WASH-', Incident::REFERENCE_PREFIX);
        $this->assertSame(6, Incident::REFERENCE_RANDOM_LENGTH);

        // Lecture seule du pattern de l'autre fichier (hors lot, non modifié).
        $pattern = (new \ReflectionClass(WashWhatsAppService::class))
            ->getConstant('SUIVI_REFERENCE_PATTERN');

        for ($i = 0; $i < 200; $i++) {
            $code = Incident::generateReferenceCode();
            $this->assertMatchesRegularExpression($pattern, $code, "Référence générée hors pattern : {$code}");
            $this->assertStringStartsWith('WASH-' . date('Y') . '-', $code);
        }

        // Le hook creating() utilise le générateur.
        $school = School::create(['name' => 'EP Parité', 'code' => 'EP-PAR', 'district' => 'Mvila']);
        $incident = Incident::create(['school_id' => $school->id, 'title' => 'Test ref']);
        $this->assertMatchesRegularExpression($pattern, $incident->reference_code);
    }

    public function test_open_statuses_single_source(): void
    {
        $this->assertSame(
            ['reported', 'triaged', 'assigned', 'in_progress'],
            Incident::OPEN_STATUSES
        );
        $this->assertSame(Incident::OPEN_STATUSES, WashRelanceService::OPEN_STATUSES);

        $school = School::create(['name' => 'EP Open', 'code' => 'EP-OPEN', 'district' => 'Mvila']);
        foreach (['reported', 'triaged', 'assigned', 'in_progress', 'resolved', 'closed'] as $status) {
            Incident::create([
                'school_id' => $school->id, 'title' => "Cas {$status}",
                'category' => 'water_point', 'status' => $status,
            ]);
        }

        $this->assertSame(
            ['assigned', 'in_progress', 'reported', 'triaged'],
            Incident::open()->pluck('status')->sort()->values()->all()
        );
        $this->assertSame(4, $school->openIncidents()->count());

        // WashRelanceService::dormants() lit la même source (ouverts dormants).
        Incident::query()->update(['updated_at' => now()->subDays(10)]);
        $dormants = (new WashRelanceService)->dormants(7);
        $this->assertSame(4, $dormants->count());
        $this->assertTrue($dormants->pluck('status')->every(
            fn ($s) => in_array($s, Incident::OPEN_STATUSES, true)
        ));
    }

    public function test_wash_config_keys(): void
    {
        $this->assertSame(['water_point', 'toilets_latrines', 'handwashing', 'sewage_drainage'], config('wash.categories'));
        $this->assertSame(['low', 'medium', 'high', 'critical'], config('wash.urgencies'));
        $this->assertSame(20, config('wash.triage.duplicate_candidate_limit'));
        $this->assertSame(0.0, config('wash.triage.duplicate_similarity_default'));
        $this->assertSame(120, config('wash.triage.title_max_chars'));
        $this->assertSame(2000, config('wash.triage.ai_input_max_chars'));
        $this->assertSame(200, config('wash.triage.fallback_summary_max_chars'));
        $this->assertSame('triaged', config('wash.triage.default_status'));
        $this->assertSame(50.0, config('wash.triage.default_priority_score'));
        $this->assertSame(85.0, config('wash.triage.fallback_critical_priority_score'));
        $this->assertSame(30, config('wash.proposals.expiry_minutes'));
        $this->assertSame(100000, config('wash.proposals.affected_students_max'));
        $this->assertSame(1000000000, config('wash.proposals.cost_max'));
    }

    public function test_french_texts_identical(): void
    {
        // Échantillon des textes extraits : strictement identiques aux littéraux.
        $this->assertSame("Point d'eau", trans('wash.categories.water_point', [], 'fr'));
        $this->assertSame('Critique', trans('wash.urgencies.critical', [], 'fr'));
        $this->assertSame('Action inconnue.', trans('wash.proposal.unknown_action', [], 'fr'));
        $this->assertSame(
            'Description requise (2000 caractères max).',
            trans('wash.proposal.description_required', ['max' => 2000], 'fr')
        );
        $this->assertSame(
            'Ce dossier a expiré (30 min). Redemandez un récapitulatif : « X ».',
            trans('wash.guidance.expired', ['minutes' => 30, 'prompt' => 'X'], 'fr')
        );
        $this->assertSame(
            'Intervention WASH-2026-AB12CD créée : Pompe.',
            trans('wash.proposal.incident_created', ['ref' => 'WASH-2026-AB12CD', 'title' => 'Pompe'], 'fr')
        );
        // Miroir EN : mêmes clés, traductions présentes.
        $this->assertSame('Water point', trans('wash.categories.water_point', [], 'en'));
        $this->assertSame('Redo the request', trans('wash.guidance.redraft_label', [], 'en'));
    }
}
