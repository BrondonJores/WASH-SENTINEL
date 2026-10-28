<?php

namespace App\Services;

use App\Contracts\AiEngineClient;
use App\Contracts\IncidentTriage;
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
    public function __construct(protected AiEngineClient $ai) {}

    public function ingest(School $school, string $channel, ?string $message, ?UploadedFile $audio, ?UploadedFile $photo, ?User $reporter = null): array
    {
        $audioPath = $audio ? $audio->store('reports/audio', 'public') : null;
        $photoPath = $photo ? $photo->store('reports/photos', 'public') : null;

        $started = (int) (microtime(true) * 1000);
        try {
            $triage = $this->ai->triage(
                $message,
                $audio ? storage_path('app/public/' . $audioPath) : null,
                $school->name,
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

        $visual = null;
        if ($photo) {
            try {
                $visual = $this->ai->analyzeImage(storage_path('app/public/' . $photoPath));
            } catch (\Throwable $e) {
                Log::warning('AI vision fallback: ' . $e->getMessage());
            }
        }

        $candidates = $school->openIncidents()->latest()->take(20)->get()
            ->map(fn (Incident $i) => [
                'id' => $i->id,
                'summary' => $i->ai_summary ?: $i->title,
                'category' => $i->category,
            ])->all();

        $duplicate = ['is_duplicate' => false, 'matched_incident_id' => null, 'similarity_score' => 0.0];
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
            'raw_content' => $rawText,
            'audio_path' => $audioPath,
            'photo_path' => $photoPath,
            'is_duplicate' => (bool) ($duplicate['is_duplicate'] ?? false),
            'duplicate_of_incident_id' => $duplicate['matched_incident_id'] ?? null,
            'duplicate_similarity_score' => (float) ($duplicate['similarity_score'] ?? 0.0),
            'raw_ai_extraction' => $extraction,
        ]);

        if ($report->is_duplicate && $report->duplicate_of_incident_id) {
            $incident = Incident::findOrFail($report->duplicate_of_incident_id);
            $report->update(['incident_id' => $incident->id]);
        } else {
            $incident = Incident::create([
                'school_id' => $school->id,
                'title' => Str::limit($extraction['short_summary'] ?? $rawText, 120, '…'),
                'category' => $extraction['infrastructure_type'] ?? 'other',
                'issue_type' => $extraction['issue_type'] ?? 'other',
                'status' => 'triaged',
                'urgency' => $extraction['urgency_level'] ?? 'medium',
                'health_hazard' => $this->mapHazard($extraction['health_hazard_risk'] ?? 'low'),
                'priority_score' => (float) ($extraction['recommended_priority_score'] ?? 50.0),
                'affected_students' => (int) ($extraction['estimated_affected_students'] ?? 0),
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
            'input_payload' => ['raw_text' => Str::limit($rawText, 2000), 'channel' => $channel],
            'output_payload' => ['extraction' => $extraction, 'duplicate' => $duplicate, 'visual' => $visual],
            'model_used' => $modelUsed,
            'confidence' => $confidence,
            'processing_ms' => (int) (microtime(true) * 1000) - $started,
        ]);

        return [
            'report' => $report->fresh(),
            'incident' => $incident->fresh('school'),
            'is_duplicate' => $report->is_duplicate,
            'extraction' => $extraction,
            'visual' => $visual,
        ];
    }

    protected function fallbackExtraction(string $rawText): array
    {
        $lower = mb_strtolower($rawText);
        $urgency = 'medium';
        foreach (['urgent', 'critique', 'choléra', 'sans eau', 'immédiat'] as $kw) {
            if (str_contains($lower, $kw)) {
                $urgency = 'critical';
                break;
            }
        }

        return [
            'school_detected' => null,
            'infrastructure_type' => 'other',
            'issue_type' => 'other',
            'urgency_level' => $urgency,
            'estimated_affected_students' => 0,
            'health_hazard_risk' => 'low',
            'short_summary' => Str::limit($rawText, 200, '…'),
            'recommended_priority_score' => $urgency === 'critical' ? 85.0 : 50.0,
        ];
    }

    protected function mapHazard(string $risk): string
    {
        return $risk === 'severe' ? 'severe' : $risk;
    }
}
