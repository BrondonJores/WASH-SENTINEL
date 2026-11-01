<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\AiAnalysis;
use App\Models\Incident;
use App\Models\School;
use App\Models\User;
use App\Contracts\AiEngineClient;
use App\Services\WashRelanceService;
use Illuminate\Http\Request;
use Illuminate\Support\Str;

class WashIncidentController extends Controller
{
    /** Statuts du cycle de vie acceptés par updateStatus (LOT 8 : 'assigned.in_progress' corrigé en deux valeurs). */
    public const STATUSES = ['reported', 'triaged', 'assigned', 'in_progress', 'resolved', 'closed'];

    public const CLOSED_STATUSES = ['resolved', 'closed'];

    public const PRIORITY_SCORE_MIN = 0;

    public const PRIORITY_SCORE_MAX = 100;

    public const MAINTENANCE_COST_MIN = 0;

    public const MAINTENANCE_CURRENCY_MAX = 8;

    public const MAINTENANCE_DAYS_MIN = 0;

    public const MAINTENANCE_NOTES_MAX = 2000;

    public const RELANCE_DAYS_MIN = 1;

    public const RELANCE_DAYS_MAX = 90;

    public const RELANCE_DAYS_DEFAULT = 7;

    public function index(Request $request)
    {
        $sorts = [
            'created_at' => ['created_at', 'asc'],
            '-created_at' => ['created_at', 'desc'],
            'priority_score' => ['priority_score', 'asc'],
            '-priority_score' => ['priority_score', 'desc'],
            'affected_students' => ['affected_students', 'asc'],
            '-affected_students' => ['affected_students', 'desc'],
        ];
        $sort = $sorts[$request->query('sort', '')] ?? null;

        $query = Incident::with(['school:id,name,district', 'assignee:id,name'])
            ->withCount('reports')
            ->when($request->school_id, fn ($q, $v) => $q->where('school_id', $v))
            ->when($request->status, fn ($q, $v) => $q->where('status', $v))
            ->when($request->urgency, fn ($q, $v) => $q->where('urgency', $v))
            ->when($request->category, fn ($q, $v) => $q->where('category', $v))
            ->when($request->district, fn ($q, $v) => $q->whereHas('school', fn ($s) => $s->where('district', $v)))
            ->when($request->search, function ($q, $v) {
                $like = '%' . mb_strtolower((string) $v, 'UTF-8') . '%';
                $q->where(function ($w) use ($like) {
                    $w->whereRaw('LOWER(title) LIKE ?', [$like])
                        ->orWhereRaw('LOWER(reference_code) LIKE ?', [$like])
                        ->orWhereHas('school', fn ($s) => $s->whereRaw('LOWER(name) LIKE ?', [$like]));
                });
            })
            ->when($sort, fn ($q) => $q->orderBy($sort[0], $sort[1]))
            ->when(! $sort, fn ($q) => $q->orderByDesc('priority_score')->latest());

        return response()->json($query->paginate(min(
            config('wash.pagination.max'),
            max(config('wash.pagination.min'), (int) $request->query('per_page', config('wash.pagination.default')))
        )));
    }

    public function overview()
    {
        $open = Incident::open();

        return response()->json([
            'open_incidents' => (clone $open)->count(),
            'affected_students' => (clone $open)->sum('affected_students'),
            'critical_incidents' => (clone $open)->where('urgency', 'critical')->count(),
            'schools_tracked' => School::count(),
            'schools_with_open' => (clone $open)->distinct()->count('school_id'),
        ]);
    }

    public function show(Request $request, Incident $incident, AiEngineClient $ai)
    {
        $incident->load(['school', 'reports', 'aiAnalyses', 'maintenanceLogs', 'assignee']);
        $payload = ['incident' => $incident];

        if (Str::contains((string) $request->query('include', ''), 'repair_plan')) {
            try {
                $plan = $ai->repairPlan(
                    $incident->ai_summary ?: $incident->title,
                    $incident->category, $incident->issue_type, $incident->urgency,
                );
                AiAnalysis::create([
                    'incident_id' => $incident->id,
                    'analysis_type' => 'repair',
                    'output_payload' => $plan,
                ]);
                $payload['repair_plan'] = $plan;
            } catch (\Throwable $e) {
                $payload['repair_plan_error'] = 'Moteur IA indisponible.';
            }
        }

        return response()->json($payload);
    }

    public function updateStatus(Request $request, Incident $incident)
    {
        $validated = $request->validate([
            'status' => ['required', 'in:' . implode(',', self::STATUSES)],
        ]);

        $incident->update([
            'status' => $validated['status'],
            'resolved_at' => in_array($validated['status'], self::CLOSED_STATUSES) ? now() : null,
        ]);

        return response()->json(['message' => 'Statut mis à jour.', 'incident' => $incident->fresh()]);
    }

    public function assign(Request $request, Incident $incident)
    {
        $validated = $request->validate(['user_id' => ['required', 'exists:users,id']]);

        $incident->update(['assigned_to_user_id' => $validated['user_id'], 'status' => 'assigned']);

        return response()->json(['message' => 'Incident assigné.', 'incident' => $incident->fresh('assignee')]);
    }

    public function overridePriority(Request $request, Incident $incident)
    {
        $validated = $request->validate([
            'priority_score' => ['required', 'numeric', 'min:' . self::PRIORITY_SCORE_MIN, 'max:' . self::PRIORITY_SCORE_MAX],
            'urgency' => ['nullable', 'in:' . implode(',', config('wash.urgencies'))],
        ]);

        $incident->update($validated);

        return response()->json(['message' => 'Priorité ajustée par le superviseur.', 'incident' => $incident->fresh()]);
    }

    public function storeMaintenanceLog(Request $request, Incident $incident)
    {
        $validated = $request->validate([
            'cost_amount' => ['required', 'numeric', 'min:' . self::MAINTENANCE_COST_MIN],
            'currency' => ['nullable', 'string', 'max:' . self::MAINTENANCE_CURRENCY_MAX],
            'repaired_at' => ['nullable', 'date'],
            'days_without_service' => ['nullable', 'integer', 'min:' . self::MAINTENANCE_DAYS_MIN],
            'notes' => ['nullable', 'string', 'max:' . self::MAINTENANCE_NOTES_MAX],
        ]);

        $validated['days_without_service'] ??= self::MAINTENANCE_DAYS_MIN;
        $log = $incident->maintenanceLogs()->create([
            ...$validated,
            'school_id' => $incident->school_id,
            'performed_by' => $request->user()?->id,
        ]);

        return response()->json(['message' => 'Intervention journalisée.', 'log' => $log], 201);
    }

    public function assignableUsers()
    {
        $users = User::role(['maintenance_agent', 'wash_admin'])
            ->orderBy('name')
            ->get(['id', 'name']);

        return response()->json($users);
    }

    public function relance(Request $request, WashRelanceService $relances)
    {
        $validated = $request->validate([
            'days' => ['nullable', 'integer', 'min:' . self::RELANCE_DAYS_MIN, 'max:' . self::RELANCE_DAYS_MAX],
            'dry_run' => ['nullable', 'boolean'],
        ]);

        $days = (int) ($validated['days'] ?? self::RELANCE_DAYS_DEFAULT);
        $dryRun = $request->boolean('dry_run', true);

        $dormants = $relances->dormants($days);

        if ($dryRun) {
            return response()->json([
                'count' => $dormants->count(),
                'days' => $days,
                'dry_run' => true,
                'incidents' => $dormants->map(fn (Incident $incident) => [
                    'id' => $incident->id,
                    'reference_code' => $incident->reference_code,
                    'title' => $incident->title,
                    'status' => $incident->status,
                    'urgency' => $incident->urgency,
                    'priority_score' => $incident->priority_score,
                    'days_inactive' => (int) ($incident->updated_at?->diffInDays(now()) ?? 0),
                    'school' => $incident->school ? [
                        'id' => $incident->school->id,
                        'name' => $incident->school->name,
                        'district' => $incident->school->district,
                    ] : null,
                    'assignee' => $incident->assignee ? [
                        'id' => $incident->assignee->id,
                        'name' => $incident->assignee->name,
                    ] : null,
                    'updated_at' => $incident->updated_at?->toIso8601String(),
                ])->values(),
            ]);
        }

        $results = $relances->relancerDormants($days);
        $sent = array_sum(array_map(fn ($r) => count($r['notified']), $results));

        return response()->json([
            'count' => $dormants->count(),
            'sent' => $sent,
            'days' => $days,
            'dry_run' => false,
            'incidents' => $results,
        ]);
    }
}
