<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\Report;
use App\Models\School;
use App\Services\IncidentTriageService;
use Illuminate\Http\Request;

class WashReportController extends Controller
{
    public function index(Request $request)
    {
        $query = Report::with(['school:id,name,district', 'incident:id,reference_code,title,urgency,status'])
            ->when($request->school_id, fn ($q, $v) => $q->where('school_id', $v))
            ->when($request->incident_id, fn ($q, $v) => $q->where('incident_id', $v))
            ->latest();

        return response()->json($query->paginate(20));
    }

    public function store(Request $request, IncidentTriageService $triage)
    {
        $validated = $request->validate([
            'school_id' => ['required', 'exists:schools,id'],
            'channel' => ['nullable', 'in:voice,text,photo,webrtc_call'],
            'message' => ['nullable', 'string', 'max:5000'],
            'audio' => ['nullable', 'file', 'mimes:mp3,ogg,wav,webm,m4a,mpga', 'max:20480'],
            'photo' => ['nullable', 'image', 'max:10240'],
        ]);

        if (empty($validated['message']) && !$request->hasFile('audio') && !$request->hasFile('photo')) {
            return response()->json(['message' => 'Un message, un audio ou une photo est requis.'], 422);
        }

        $school = School::findOrFail($validated['school_id']);
        $channel = $validated['channel'] ?? ($request->hasFile('audio') ? 'voice' : ($request->hasFile('photo') ? 'photo' : 'text'));

        $result = $triage->ingest(
            $school,
            $channel,
            $validated['message'] ?? null,
            $request->file('audio'),
            $request->file('photo'),
            $request->user(),
        );

        return response()->json([
            'message' => $result['is_duplicate'] ? 'Signalement rattaché à un incident existant.' : 'Incident créé et trié par IA.',
            'is_duplicate' => $result['is_duplicate'],
            'report' => $result['report'],
            'incident' => $result['incident'],
            'extraction' => $result['extraction'],
            'visual' => $result['visual'],
        ], 201);
    }

    public function show(Report $report)
    {
        return response()->json($report->load(['school', 'incident', 'aiAnalyses']));
    }
}
