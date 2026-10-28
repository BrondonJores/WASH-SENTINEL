<?php

namespace App\Services;

use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\Http;

class WashAiEngineService
{
    public function __construct(
        protected string $baseUrl = '',
        protected int $timeout = 120,
    ) {
        $this->baseUrl = $baseUrl ?: (string) config('services.ai_engine.url', 'http://ai-engine:8000');
        $this->timeout = (int) config('services.ai_engine.timeout', 120);
    }

    public function health(): array
    {
        return Http::timeout(10)->get($this->baseUrl . '/health')->throw()->json();
    }

    public function triage(?string $text, ?string $audioPath, ?string $schoolName): array
    {
        $request = Http::timeout($this->timeout);
        if ($audioPath) {
            $request = $request->attach('audio', file_get_contents($audioPath), basename($audioPath));
        }

        return $request->post($this->baseUrl . '/v1/wash/triage', array_filter([
            'text' => $text,
            'school_name' => $schoolName,
        ]))->throw()->json();
    }

    public function extract(string $rawText, ?string $schoolName = null): array
    {
        return Http::timeout($this->timeout)->post($this->baseUrl . '/v1/wash/extract', [
            'raw_text' => $rawText,
            'school_name' => $schoolName,
        ])->throw()->json();
    }

    public function checkDuplicates(string $incomingSummary, array $activeIncidents, float $threshold = 0.80): array
    {
        return Http::timeout($this->timeout)->post($this->baseUrl . '/v1/wash/check-duplicates', [
            'incoming_summary' => $incomingSummary,
            'active_incidents' => $activeIncidents,
            'similarity_threshold' => $threshold,
        ])->throw()->json();
    }

    public function analyzeImage(string $photoPath): array
    {
        return Http::timeout($this->timeout)
            ->attach('photo', file_get_contents($photoPath), basename($photoPath))
            ->post($this->baseUrl . '/v1/wash/analyze-image')
            ->throw()->json();
    }

    public function repairPlan(string $summary, string $infrastructure, string $issue, string $urgency): array
    {
        return Http::timeout($this->timeout)->post($this->baseUrl . '/v1/wash/generate-repair-plan', [
            'incident_summary' => $summary,
            'infrastructure_type' => $infrastructure,
            'issue_type' => $issue,
            'urgency_level' => $urgency,
        ])->throw()->json();
    }

    public function epidemicScan(string $district, array $recentIncidents): array
    {
        return Http::timeout($this->timeout)->post($this->baseUrl . '/v1/wash/detect-epidemic-risk', [
            'district' => $district,
            'recent_incidents' => $recentIncidents,
        ])->throw()->json();
    }

    public function copilotChat(string $query, ?string $district, array $schoolsData): array
    {
        return Http::timeout($this->timeout)->post($this->baseUrl . '/v1/wash/copilot/chat', [
            'user_query' => $query,
            'district' => $district,
            'schools_data' => $schoolsData,
        ])->throw()->json();
    }

    public function replaceVsRepair(array $schoolHistory): array
    {
        return Http::timeout($this->timeout)->post($this->baseUrl . '/v1/wash/copilot/replace-vs-repair', $schoolHistory)->throw()->json();
    }

    public function dispatchPlan(string $district, array $schools): array
    {
        return Http::timeout($this->timeout)->post($this->baseUrl . '/v1/wash/equity/dispatch-plan', [
            'district' => $district,
            'schools' => $schools,
        ])->throw()->json();
    }

    public function synthesize(string $text, string $voice = 'fr_FR-upmc-medium'): array
    {
        return Http::timeout($this->timeout)->post($this->baseUrl . '/v1/voice/synthesize', [
            'text' => $text,
            'voice' => $voice,
        ])->throw()->json();
    }
}
