<?php

namespace App\Contracts;

use App\Models\AiModelProfile;
use App\Models\AiSttProfile;

interface AiEngineClient
{
    public function activeProfile(): ?AiModelProfile;

    public function profileHeaders(): array;

    public function activeSttProfile(): ?AiSttProfile;

    public function sttHeaders(): array;

    public function health(): array;

    public function providerTypes(): array;

    public function testProfile(array $profile): array;

    public function sttTypes(): array;

    public function testSttProfile(array $payload): array;

    public function triage(?string $text, ?string $audioPath, ?string $schoolName, ?string $language = null): array;

    public function extract(string $rawText, ?string $schoolName = null): array;

    public function checkDuplicates(string $incomingSummary, array $activeIncidents, float $threshold = 0.80): array;

    public function analyzeImage(string $photoPath): array;

    public function repairPlan(string $summary, string $infrastructure, string $issue, string $urgency): array;

    public function epidemicScan(string $district, array $recentIncidents): array;

    public function copilotChat(string $query, ?string $district, array $schoolsData): array;

    public function replaceVsRepair(array $schoolHistory): array;

    public function agentChat(string $message, array $history, array $context): array;

    public function dispatchPlan(string $district, array $schools): array;

    public function synthesize(string $text, string $voice = 'fr_FR-upmc-medium'): array;
}
