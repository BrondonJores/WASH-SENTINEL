<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\AiAnalysis;
use App\Models\Incident;
use App\Models\School;
use App\Contracts\AiEngineClient;
use Illuminate\Http\Request;

class WashAgentController extends Controller
{
    public function copilotChat(Request $request, AiEngineClient $ai)
    {
        $validated = $request->validate([
            'user_query' => ['required', 'string', 'max:2000'],
            'district' => ['nullable', 'string', 'max:128'],
        ]);

        $schools = School::query()
            ->when($validated['district'] ?? null, fn ($q, $v) => $q->where('district', $v))
            ->withCount('incidents')
            ->withSum('maintenanceLogs', 'cost_amount')
            ->withSum('maintenanceLogs', 'days_without_service')
            ->take(30)->get();

        $schoolsData = $schools->map(fn (School $s) => [
            'school_id' => $s->id,
            'school_name' => $s->name,
            'district' => $s->district,
            'equipment_type' => $s->equipment_type,
            'installation_year' => $s->installation_year,
            'estimated_replacement_cost' => (float) $s->estimated_replacement_cost,
            'incident_count' => (int) $s->incidents_count,
            'total_repair_cost' => (float) ($s->maintenance_logs_sum_cost_amount ?? 0),
            'total_days_without_service' => (int) ($s->maintenance_logs_sum_days_without_service ?? 0),
        ])->all();

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
}
