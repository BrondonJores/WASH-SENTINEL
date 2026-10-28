<?php

namespace App\Contracts;

use App\Models\AiModelProfile;

interface AiEngineClient
{
    public function activeProfile(): ?AiModelProfile;

    public function profileHeaders(): array;

    public function health(): array;

    public function providerTypes(): array;

    public function testProfile(array $profile): array;

    public function triage(?string $text, ?string $audioPath, ?string $schoolName): array;

    public function extract(string $rawText, ?string $schoolName = null): array;

    public function checkDuplicates(string $incomingSummary, array $activeIncidents, float $threshold = 0.80): array;

    public function analyzeImage(string $photoPath): array;

    public function repairPlan(string $summary, string $infrastructure, string $issue, string $urgency): array;

    public function epidemicScan(string $district, array $recentIncidents): array;

    public function copilotChat(string $query, ?string $district, array $schoolsData): array;

    public function replaceVsRepair(array $schoolHistory): array;

    public function dispatchPlan(string $district, array $schools): array;

    public function synthesize(string $text, string $voice = 'fr_FR-upmc-medium'): array;
}
