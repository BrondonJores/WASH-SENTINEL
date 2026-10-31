<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\AiAnalysis;
use App\Models\Incident;
use App\Models\MaintenanceLog;
use App\Models\School;
use App\Contracts\AiEngineClient;
use App\Models\AgentProposal;
use App\Models\User;
use App\Services\AgentProposalService;
use Illuminate\Validation\ValidationException;
use Symfony\Component\HttpKernel\Exception\AccessDeniedHttpException;
use Illuminate\Http\Request;

class WashAgentController extends Controller
{
    public function copilotChat(Request $request, AiEngineClient $ai)
    {
        $validated = $request->validate([
            'user_query' => ['required', 'string', 'max:2000'],
            'district' => ['nullable', 'string', 'max:128'],
        ]);

        $schoolsData = $this->maintenanceProfiles($validated['district'] ?? null);

        $response = $ai->copilotChat($validated['user_query'], $validated['district'] ?? null, $schoolsData);

        AiAnalysis::create([
            'analysis_type' => 'copilot',
            'input_payload' => ['query' => $validated['user_query'], 'district' => $validated['district'] ?? null],
            'output_payload' => $response,
        ]);

        return response()->json($response);
    }

    public function replaceVsRepair(School $school, AiEngineClient $ai)
    {
        $history = [
            'school_id' => $school->id,
            'school_name' => $school->name,
            'district' => $school->district,
            'equipment_type' => $school->equipment_type,
            'installation_year' => $school->installation_year,
            'estimated_replacement_cost' => (float) $school->estimated_replacement_cost,
            'incident_count' => $school->incidents()->count(),
            'total_repair_cost' => (float) $school->maintenanceLogs()->sum('cost_amount'),
            'total_days_without_service' => (int) $school->maintenanceLogs()->sum('days_without_service'),
        ];

        return response()->json($ai->replaceVsRepair($history));
    }

    public function dispatchPlan(Request $request, AiEngineClient $ai)
    {
        $validated = $request->validate(['district' => ['required', 'string', 'max:128']]);

        $schools = School::where('district', $validated['district'])->with(['openIncidents', 'maintenanceLogs'])->take(30)->get();

        $profiles = $schools->map(function (School $s) {
            $open = $s->openIncidents;
            $oldest = $open->sortBy('created_at')->first();
            $latest = $open->sortByDesc('created_at')->first();
            $lastFix = $s->maintenanceLogs->sortByDesc('repaired_at')->first();
            $urgencies = ['low' => 0, 'medium' => 1, 'high' => 2, 'critical' => 3];
            $maxUrgency = $open->sortByDesc(fn ($i) => $urgencies[$i->urgency] ?? 0)->first()?->urgency ?? 'low';

            return [
                'school_id' => $s->id,
                'school_name' => $s->name,
                'district' => $s->district,
                'distance_from_center_km' => (float) $s->distance_from_center_km,
                'days_without_water' => $oldest ? (int) $oldest->created_at->diffInDays(now()) : 0,
                'total_students' => (int) $s->student_count,
                'female_students' => (int) $s->female_students,
                'broken_toilets' => (int) $s->broken_toilets,
                'months_since_last_intervention' => $lastFix?->repaired_at
                    ? (int) $lastFix->repaired_at->diffInMonths(now())
                    : 12,
                'urgency_level' => $maxUrgency,
                'issue_summary' => (string) ($latest?->ai_summary ?? $latest?->title ?? ''),
                'lat' => $s->latitude ? (float) $s->latitude : null,
                'lng' => $s->longitude ? (float) $s->longitude : null,
            ];
        })->all();

        $response = $ai->dispatchPlan($validated['district'], $profiles);

        AiAnalysis::create([
            'analysis_type' => 'equity',
            'input_payload' => ['district' => $validated['district'], 'schools' => count($profiles)],
            'output_payload' => $response,
        ]);

        return response()->json($response);
    }

    public function epidemicScan(Request $request, AiEngineClient $ai)
    {
        $validated = $request->validate(['district' => ['required', 'string', 'max:128']]);

        $recent = Incident::with('school:id,name,district')
            ->whereHas('school', fn ($q) => $q->where('district', $validated['district']))
            ->where('created_at', '>=', now()->subDays(7))
            ->latest()->take(50)->get()
            ->map(fn (Incident $i) => [
                'id' => $i->id,
                'school_name' => $i->school->name,
                'district' => $i->school->district,
                'category' => $i->category,
                'summary' => $i->ai_summary ?: $i->title,
                'reported_at' => $i->created_at->toIso8601String(),
            ])->all();

        $response = $ai->epidemicScan($validated['district'], $recent);

        AiAnalysis::create([
            'analysis_type' => 'epidemic',
            'input_payload' => ['district' => $validated['district'], 'incidents' => count($recent)],
            'output_payload' => $response,
        ]);

        return response()->json($response);
    }

    public function synthesize(Request $request, AiEngineClient $ai)
    {
        $validated = $request->validate(['text' => ['required', 'string', 'max:1000']]);

        return response()->json($ai->synthesize($validated['text']));
    }

    public function transcribe(Request $request, AiEngineClient $ai)
    {
        $validated = $request->validate([
            'audio' => 'required|file|max:10240',
            'language' => 'nullable|string|max:16',
        ]);

        return response()->json($ai->transcribe(
            $validated['audio']->getRealPath(),
            $validated['language'] ?? 'fr',
        ));
    }
    public function converse(Request $request, AiEngineClient $ai, AgentProposalService $proposals)
    {
        $validated = $request->validate([
            'message' => ['required', 'string', 'max:2000'],
            'history' => ['nullable', 'array', 'max:20'],
            'history.*.role' => ['required_with:history', 'in:user,assistant,tool'],
            'history.*.content' => ['required_with:history', 'string', 'max:2000'],
            'district' => ['nullable', 'string', 'max:128'],
        ]);

        $user = $this->optionalUser($request);
        if ($user && ($vote = $this->interceptVote($user, $validated['message'], $proposals)) !== null) {
            return response()->json($vote);
        }

        $response = $ai->agentChat(
            $validated['message'],
            $validated['history'] ?? [],
            [
                'schools' => $this->maintenanceProfiles($validated['district'] ?? null),
                'incidents' => $this->openIncidentSnapshots($validated['district'] ?? null),
                'recent_incidents' => $this->recentIncidentSnapshots($validated['district'] ?? null),
                'maintenance_logs' => $this->maintenanceLogSnapshots($validated['district'] ?? null),
            ],
        );

        $response = $this->persistProposals($user, $response, $proposals);

        AiAnalysis::create([
            'analysis_type' => 'agent',
            'input_payload' => ['message' => $validated['message']],
            'output_payload' => $response,
        ]);

        return response()->json($response);
    }

    public function converseStream(Request $request, AiEngineClient $ai, AgentProposalService $proposals)
    {
        $validated = $request->validate([
            'message' => ['required', 'string', 'max:2000'],
            'history' => ['nullable', 'array', 'max:20'],
            'history.*.role' => ['required_with:history', 'in:user,assistant,tool'],
            'history.*.content' => ['required_with:history', 'string', 'max:2000'],
            'district' => ['nullable', 'string', 'max:128'],
        ]);

        $user = $this->optionalUser($request);
        $vote = $user ? $this->interceptVote($user, $validated['message'], $proposals) : null;
        $context = [
            'schools' => $this->maintenanceProfiles($validated['district'] ?? null),
            'incidents' => $this->openIncidentSnapshots($validated['district'] ?? null),
            'recent_incidents' => $this->recentIncidentSnapshots($validated['district'] ?? null),
            'maintenance_logs' => $this->maintenanceLogSnapshots($validated['district'] ?? null),
        ];

        return response()->stream(function () use ($validated, $context, $user, $vote, $ai, $proposals) {
            $emit = function (string $event, array $data): void {
                echo "event: {$event}\ndata: " . json_encode($data, JSON_UNESCAPED_UNICODE) . "\n\n";
                flush();
            };
            // Repli honnête : une réponse complète réémise en events SSE.
            $emitFull = function (array $full) use ($emit): void {
                $emit('tools', ['event' => 'tools', 'tools' => $full['tools_executed'] ?? []]);
                $emit('cards', ['event' => 'cards', 'cards' => $full['cards'] ?? []]);
                foreach (mb_str_split((string) ($full['answer'] ?? ''), 40) as $chunk) {
                    $emit('delta', ['event' => 'delta', 'text' => $chunk]);
                }
                $emit('done', ['event' => 'done', 'model' => $full['model_used'] ?? '', 'follow_ups' => $full['follow_ups'] ?? []]);
            };

            if ($vote !== null) {
                $emitFull($vote);

                return;
            }

            try {
                $client = new \GuzzleHttp\Client([
                    'base_uri' => (string) config('services.ai_engine.url', 'http://ai-engine:8000'),
                    'timeout' => (int) config('services.ai_engine.timeout', 120),
                ]);
                $upstream = $client->post('/v1/agent/chat/stream', [
                    'stream' => true,
                    'headers' => ['Accept' => 'text/event-stream'] + $ai->profileHeaders() + $ai->sttHeaders(),
                    'json' => [
                        'message' => $validated['message'],
                        'history' => $validated['history'] ?? [],
                        'context' => $context,
                    ],
                ]);
                $body = $upstream->getBody();
                while (! $body->eof()) {
                    echo $body->read(1024);
                    flush();
                }
            } catch (\Throwable) {
                $full = $this->persistProposals($user, $ai->agentChat(
                    $validated['message'],
                    $validated['history'] ?? [],
                    $context,
                ), $proposals);
                $emitFull($full);
            }
        }, 200, [
            'Content-Type' => 'text/event-stream',
            'Cache-Control' => 'no-cache',
            'X-Accel-Buffering' => 'no',
        ]);
    }

    protected function optionalUser(Request $request): ?User
    {
        try {
            return auth('sanctum')->user();
        } catch (\Throwable) {
            return null;
        }
    }

    protected function interceptVote(User $user, string $message, AgentProposalService $service): ?array
    {
        $text = mb_strtolower(trim($message));
        if (mb_strlen($text) > 40) {
            return null;
        }
        $confirm = (bool) preg_match("/^(oui|ouais|ok|okay|confirmer?|je confirme|vas-?y|allons-?y|valider?|je valide|d'accord|d’accord)[.! ]*$/u", $text);
        $cancel = !$confirm && (bool) preg_match("/^(non|annuler?|annule|stop|laisse tomber|oublie)[.! ]*$/u", $text);
        if (!$confirm && !$cancel) {
            return null;
        }
        $pending = AgentProposal::where('user_id', $user->id)
            ->where('status', AgentProposal::STATUS_PENDING)
            ->where('expires_at', '>', now())
            ->latest()->get();
        if ($pending->count() !== 1) {
            return null;
        }
        try {
            if ($confirm) {
                $result = $service->confirm($user, $pending->first());
                return $this->voteResponse(true, null, $result);
            }
            $result = $service->cancel($user, $pending->first());
            return $this->voteResponse(false, null, $result);
        } catch (\Throwable $e) {
            return $this->voteResponse($confirm, $e->getMessage(), []);
        }
    }

    protected function voteResponse(bool $confirm, ?string $error, array $result): array
    {
        if ($error) {
            $answer = "Je n'ai pas pu exécuter : {$error}";
            $status = 'error';
        } elseif ($confirm) {
            $answer = "C'est validé : " . ($result['summary'] ?? 'action exécutée.');
            $status = 'confirmed';
        } else {
            $answer = "Proposition annulée, rien n'a été créé.";
            $status = 'cancelled';
        }

        return [
            'answer' => $answer,
            'tools_executed' => [$confirm ? 'confirm_proposal' : 'cancel_proposal'],
            'cards' => [[
                'type' => 'action_result',
                'title' => $confirm ? 'Résultat de la validation' : 'Proposition annulée',
                'data' => array_merge($result, ['status' => $status]),
            ]],
            'model_used' => 'sentinel-guard',
        ];
    }

    protected function persistProposals(?User $user, array $response, AgentProposalService $service): array
    {
        if (empty($response['cards']) || !is_array($response['cards'])) {
            return $response;
        }
        foreach ($response['cards'] as $i => $card) {
            if (($card['type'] ?? '') !== 'action_confirmation') {
                continue;
            }
            $data = $card['data'] ?? [];
            if (!($data['complete'] ?? false)) {
                continue;
            }
            if (!$user) {
                $response['cards'][$i]['data']['login_required'] = true;
                continue;
            }
            try {
                $draft = $service->draft($user, (string) ($data['action'] ?? ''), (array) ($data['slots'] ?? []));
                $response['cards'][$i]['data']['proposal_id'] = $draft['proposal']->id;
                $response['cards'][$i]['data']['expires_at'] = $draft['proposal']->expires_at->toIso8601String();
                $response['cards'][$i]['data']['recap_rows'] = $draft['recap_rows'];
            } catch (AccessDeniedHttpException $e) {
                $response['cards'][$i]['data']['not_permitted'] = true;
                $response['cards'][$i]['data']['permission_error'] = $e->getMessage();
            } catch (ValidationException $e) {
                $response['cards'][$i]['data']['invalid'] = true;
                $response['cards'][$i]['data']['errors'] = $e->errors();
            }
        }

        return $response;
    }

    protected function maintenanceProfiles(?string $district): array
    {
        return School::query()
            ->when($district, fn ($q, $v) => $q->where('district', $v))
            ->withCount('incidents')
            ->withSum('maintenanceLogs', 'cost_amount')
            ->withSum('maintenanceLogs', 'days_without_service')
            ->take(30)->get()
            ->map(fn (School $s) => [
                'school_id' => $s->id,
                'school_name' => $s->name,
                'district' => $s->district,
                'equipment_type' => $s->equipment_type,
                'installation_year' => $s->installation_year,
                'estimated_replacement_cost' => (float) $s->estimated_replacement_cost,
                'incident_count' => (int) $s->incidents_count,
                'total_repair_cost' => (float) ($s->maintenance_logs_sum_cost_amount ?? 0),
                'total_days_without_service' => (int) ($s->maintenance_logs_sum_days_without_service ?? 0),
                'latitude' => $s->latitude,
                'longitude' => $s->longitude,
            ])->all();
    }

    protected function recentIncidentSnapshots(?string $district): array
    {
        return Incident::with('school:id,name,district')
            ->when($district, fn ($q, $v) => $q->whereHas('school', fn ($s) => $s->where('district', $v)))
            ->where('created_at', '>=', now()->subMonths(12))
            ->latest()->take(200)->get()
            ->map(fn (Incident $i) => [
                'id' => $i->id,
                'school_id' => $i->school_id,
                'reported_at' => $i->created_at->toIso8601String(),
            ])->all();
    }

    protected function maintenanceLogSnapshots(?string $district): array
    {
        return MaintenanceLog::with(['school:id,name,district', 'incident:id,reference_code,title'])
            ->when($district, fn ($q, $v) => $q->whereHas('school', fn ($s) => $s->where('district', $v)))
            ->where('created_at', '>=', now()->subDays(30))
            ->latest()->take(200)->get()
            ->map(fn (MaintenanceLog $l) => [
                'id' => $l->id,
                'school_id' => $l->school_id,
                'incident_id' => $l->incident_id,
                'incident_ref' => $l->incident?->reference_code,
                'incident_title' => $l->incident?->title,
                'school_name' => $l->school?->name,
                'cost_amount' => (float) $l->cost_amount,
                'currency' => $l->currency,
                'notes' => $l->notes,
                'created_at' => $l->created_at?->toIso8601String(),
                'repaired_at' => $l->repaired_at?->toIso8601String(),
                'days_without_service' => (int) $l->days_without_service,
            ])->all();
    }

    protected function openIncidentSnapshots(?string $district): array
    {
        return Incident::with('school:id,name,district')
            ->when($district, fn ($q, $v) => $q->whereHas('school', fn ($s) => $s->where('district', $v)))
            ->open()->latest()->take(50)->get()
            ->map(fn (Incident $i) => [
                'id' => $i->id,
                'school_id' => $i->school_id,
                'school_name' => $i->school->name,
                'district' => $i->school->district,
                'reference_code' => $i->reference_code,
                'title' => $i->title,
                'category' => $i->category,
                'issue_type' => $i->issue_type,
                'urgency' => $i->urgency,
                'status' => $i->status,
                'priority_score' => (float) $i->priority_score,
                'affected_students' => (int) $i->affected_students,
                'summary' => $i->ai_summary ?: $i->title,
                'reported_at' => $i->created_at->toIso8601String(),
            ])->all();
    }
}