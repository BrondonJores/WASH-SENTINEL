<?php

namespace App\Services;

use App\Contracts\AiEngineClient;
use App\Contracts\IncidentTriage;
use App\Notifications\CriticalIncidentNotification;
use App\Models\AiAnalysis;
use App\Models\Incident;
use App\Models\Report;
use App\Models\School;
use App\Models\User;
use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Str;

class IncidentTriageService implements IncidentTriage
{
    /**
     * LOT 6 — formule de priorité, MIROIR de backend/ai-engine/app/extractor.py
     * (WashExtractor::calculate_priority_score + PRIORITY_WEIGHT_*,
     * URGENCY_SCORES, HAZARD_SCORES, MAX_AFFECTED_STUDENTS,
     * DEFAULT_URGENCY_SCORE, DEFAULT_HAZARD_SCORE).
     * Formule partagée : round(u*0.35 + h*0.35 + s*0.30, 1),
     * s = min(élèves, 1000)/1000*100. Parité ancrée par
     * tests/Feature/WashLot6ParityTest.php. Divergence historique documentée :
     * à 0 élève, extractor.py substitue DEFAULT_AFFECTED_STUDENTS=50 (sortie
     * LLM) tandis que le PHP score le 0 explicite (saisie humaine) — conservée
     * (extraction pure). Arrondi : PHP (half away) vs Python (banker's)
     * divergent sur les demis exacts (ex. 49.25) — vecteurs de parité choisis
     * hors de ce cas.
     */
    public const PRIORITY_WEIGHT_URGENCY = 0.35;

    public const PRIORITY_WEIGHT_HAZARD = 0.35;

    public const PRIORITY_WEIGHT_STUDENTS = 0.30;

    public const PRIORITY_URGENCY_SCORES = ['low' => 10.0, 'medium' => 45.0, 'high' => 75.0, 'critical' => 100.0];

    public const PRIORITY_HAZARD_SCORES = ['low' => 10.0, 'medium' => 40.0, 'high' => 75.0, 'severe' => 100.0];

    public const PRIORITY_MAX_STUDENTS = 1000;

    public const PRIORITY_DEFAULT_URGENCY_SCORE = 45.0;

    public const PRIORITY_DEFAULT_HAZARD_SCORE = 40.0;

    public function __construct(protected AiEngineClient $ai) {}

    public function ingest(School $school, string $channel, ?string $message, ?UploadedFile $audio, ?UploadedFile $photo, ?User $reporter = null, string $source = 'web', ?array $overrides = null): array
    {
        $audioPath = $audio ? $audio->store('reports/audio', 'public') : null;
        $photoPath = $photo ? $photo->store('reports/photos', 'public') : null;

        $started = (int) (microtime(true) * 1000);
        try {
            $triage = $this->ai->triage(
                $message,
                $audio ? storage_path('app/public/' . $audioPath) : null,
                $school->name,
                $school->default_language,
            );
            $rawText = (string) ($triage['raw_text'] ?? $message ?? '');
            $extraction = $triage['extraction']['data'] ?? $triage['extraction'] ?? [];
            $modelUsed = (string) ($triage['extraction']['model_used'] ?? 'llama3.2:3b');
            $confidence = (float) ($triage['extraction']['confidence_score'] ?? 0.9);
        } catch (\Throwable $e) {
            Log::warning('AI triage fallback: ' . $e->getMessage());
            $rawText = (string) ($message ?? '[message vocal]');
            $extraction = $this->fallbackExtraction($rawText);
            $modelUsed = 'fallback-rules';
            $confidence = 0.4;
        }

        if ($overrides) {
            $extraction = $this->applyOverrides($extraction, $overrides);
        }

        $visual = null;
        if ($photo) {
            try {
                $visual = $this->ai->analyzeImage(storage_path('app/public/' . $photoPath));
            } catch (\Throwable $e) {
                Log::warning('AI vision fallback: ' . $e->getMessage());
            }
        }

        $candidates = $school->openIncidents()->latest()->take(config('wash.triage.duplicate_candidate_limit'))->get()
            ->map(fn (Incident $i) => [
                'id' => $i->id,
                'summary' => $i->ai_summary ?: $i->title,
                'category' => $i->category,
            ])->all();

        $simDefault = (float) config('wash.triage.duplicate_similarity_default');
        $duplicate = ['is_duplicate' => false, 'matched_incident_id' => null, 'similarity_score' => $simDefault];
        if (count($candidates) > 0) {
            try {
                $duplicate = $this->ai->checkDuplicates($rawText, $candidates);
            } catch (\Throwable $e) {
                Log::warning('AI duplicate fallback: ' . $e->getMessage());
            }
        }

        $report = Report::create([
            'school_id' => $school->id,
            'reporter_id' => $reporter?->id,
            'channel' => $channel,
            'source' => $source,
            'raw_content' => $rawText,
            'audio_path' => $audioPath,
            'photo_path' => $photoPath,
            'is_duplicate' => (bool) ($duplicate['is_duplicate'] ?? false),
            'duplicate_of_incident_id' => $duplicate['matched_incident_id'] ?? null,
            'duplicate_similarity_score' => (float) ($duplicate['similarity_score'] ?? $simDefault),
            'raw_ai_extraction' => $extraction,
        ]);

        if ($report->is_duplicate && $report->duplicate_of_incident_id) {
            $incident = Incident::findOrFail($report->duplicate_of_incident_id);
            $report->update(['incident_id' => $incident->id]);
        } else {
            $incident = Incident::create([
                'school_id' => $school->id,
                'title' => Str::limit($extraction['short_summary'] ?? $rawText, config('wash.triage.title_max_chars'), '…'),
                'category' => $extraction['infrastructure_type'] ?? config('wash.triage.default_category'),
                'issue_type' => $extraction['issue_type'] ?? config('wash.triage.default_issue_type'),
                'status' => config('wash.triage.default_status'),
                'urgency' => $extraction['urgency_level'] ?? config('wash.triage.default_urgency'),
                'health_hazard' => $this->mapHazard($extraction['health_hazard_risk'] ?? config('wash.triage.default_hazard')),
                'priority_score' => (float) ($extraction['recommended_priority_score'] ?? config('wash.triage.default_priority_score')),
                'affected_students' => (int) ($extraction['estimated_affected_students'] ?? config('wash.triage.default_affected_students')),
                'ai_summary' => $extraction['short_summary'] ?? $rawText,
                'ai_tags' => array_values(array_filter([
                    $extraction['infrastructure_type'] ?? null,
                    $extraction['issue_type'] ?? null,
                    $extraction['urgency_level'] ?? null,
                ])),
            ]);
            $report->update(['incident_id' => $incident->id]);
        }

        AiAnalysis::create([
            'incident_id' => $incident->id,
            'report_id' => $report->id,
            'analysis_type' => 'triage',
            'input_payload' => ['raw_text' => Str::limit($rawText, config('wash.triage.ai_input_max_chars')), 'channel' => $channel],
            'output_payload' => ['extraction' => $extraction, 'duplicate' => $duplicate, 'visual' => $visual],
            'model_used' => $modelUsed,
            'confidence' => $confidence,
            'processing_ms' => (int) (microtime(true) * 1000) - $started,
        ]);

        if (!$report->is_duplicate && $incident->urgency === 'critical') {
            $this->notifyCritical($incident);
        }

        return [
            'report' => $report->fresh(),
            'incident' => $incident->fresh('school'),
            'is_duplicate' => $report->is_duplicate,
            'extraction' => $extraction,
            'visual' => $visual,
        ];
    }

    protected function notifyCritical(Incident $incident): void
    {
        try {
            User::role(['wash_admin', 'maintenance_agent'])->each(
                fn (User $user) => $user->notify(new CriticalIncidentNotification($incident))
            );
        } catch (\Throwable $e) {
            Log::warning('Critical notification failed: ' . $e->getMessage());
        }
    }

    protected function fallbackExtraction(string $rawText): array
    {
        $lower = mb_strtolower($rawText);
        $urgency = config('wash.triage.default_urgency');
        foreach (config('wash.triage.fallback_critical_keywords') as $kw) {
            if (str_contains($lower, $kw)) {
                $urgency = 'critical';
                break;
            }
        }

        return [
            'school_detected' => null,
            'infrastructure_type' => config('wash.triage.default_category'),
            'issue_type' => config('wash.triage.default_issue_type'),
            'urgency_level' => $urgency,
            'estimated_affected_students' => config('wash.triage.default_affected_students'),
            'health_hazard_risk' => config('wash.triage.default_hazard'),
            'short_summary' => Str::limit($rawText, config('wash.triage.fallback_summary_max_chars'), '…'),
            'recommended_priority_score' => $urgency === 'critical'
                ? config('wash.triage.fallback_critical_priority_score')
                : config('wash.triage.fallback_priority_score'),
        ];
    }

    protected function mapHazard(string $risk): string
    {
        return $risk === 'severe' ? 'severe' : $risk;
    }

    public function createManualIncident(School $school, array $data, User $author): Incident
    {
        return Incident::create([
            'school_id' => $school->id,
            'title' => $data['title'],
            'category' => $data['category'],
            'issue_type' => config('wash.triage.manual_issue_type'), // déclaré humainement, diagnostic à qualifier
            'status' => config('wash.triage.default_status'),
            'urgency' => $data['urgency'],
            'health_hazard' => config('wash.triage.manual_hazard'),
            'priority_score' => $this->priorityScore($data['urgency'], config('wash.triage.manual_hazard'), (int) $data['affected_students']),
            'affected_students' => (int) $data['affected_students'],
            'ai_summary' => "Déclaré par {$author->name} via Sentinel : {$data['title']}",
            'ai_tags' => [$data['category'], $data['urgency'], config('wash.triage.manual_tag')],
        ])->fresh('school');
    }

    protected function applyOverrides(array $extraction, array $overrides): array
    {
        if (isset($overrides['category']) && in_array($overrides['category'], config('wash.categories'), true)) {
            $extraction['infrastructure_type'] = $overrides['category'];
        }
        if (isset($overrides['urgency']) && in_array($overrides['urgency'], config('wash.urgencies'), true)) {
            $extraction['urgency_level'] = $overrides['urgency'];
        }
        if (isset($overrides['affected_students']) && is_numeric($overrides['affected_students'])) {
            $extraction['estimated_affected_students'] = max(0, (int) $overrides['affected_students']);
        }
        $extraction['recommended_priority_score'] = $this->priorityScore(
            $extraction['urgency_level'] ?? config('wash.triage.default_urgency'),
            $extraction['health_hazard_risk'] ?? config('wash.triage.default_hazard'),
            (int) ($extraction['estimated_affected_students'] ?? config('wash.triage.default_affected_students'))
        );
        $extraction['human_overrides'] = $overrides;

        return $extraction;
    }

    protected function priorityScore(string $urgency, string $hazard, int $students): float
    {
        $u = self::PRIORITY_URGENCY_SCORES[$urgency] ?? self::PRIORITY_DEFAULT_URGENCY_SCORE;
        $h = self::PRIORITY_HAZARD_SCORES[$hazard] ?? self::PRIORITY_DEFAULT_HAZARD_SCORE;
        $s = (min($students, self::PRIORITY_MAX_STUDENTS) / (float) self::PRIORITY_MAX_STUDENTS) * 100.0;

        return round($u * self::PRIORITY_WEIGHT_URGENCY + $h * self::PRIORITY_WEIGHT_HAZARD + $s * self::PRIORITY_WEIGHT_STUDENTS, 1);
    }
}
