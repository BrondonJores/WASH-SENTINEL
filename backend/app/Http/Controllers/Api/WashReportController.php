<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\Report;
use App\Models\School;
use App\Contracts\IncidentTriage;
use Illuminate\Http\Request;

class WashReportController extends Controller
{
    public const CHANNELS = ['voice', 'text', 'photo', 'webrtc_call'];

    public const MESSAGE_MAX_CHARS = 5000;

    public const AUDIO_MIMES = ['mp3', 'ogg', 'wav', 'webm', 'm4a', 'mpga'];

    /** Photo 10 Mo — inchangé (seul l'audio est unifié à 12 Mo, cf. wash.voice.audio_max_kb). */
    public const PHOTO_MAX_KB = 10240;

    public function index(Request $request)
    {
        $query = Report::with(['school:id,name,district', 'incident:id,reference_code,title,urgency,status'])
            ->when($request->school_id, fn ($q, $v) => $q->where('school_id', $v))
            ->when($request->incident_id, fn ($q, $v) => $q->where('incident_id', $v))
            ->when($request->channel, fn ($q, $v) => in_array($v, self::CHANNELS, true) ? $q->where('channel', $v) : $q)
            ->when($request->query('is_duplicate') === '1', fn ($q) => $q->where('is_duplicate', true))
            ->when($request->query('is_duplicate') === '0', fn ($q) => $q->where('is_duplicate', false))
            ->latest();

        return response()->json($query->paginate(min(
            config('wash.pagination.max'),
            max(config('wash.pagination.min'), (int) $request->query('per_page', config('wash.pagination.default')))
        )));
    }

    public function store(Request $request, IncidentTriage $triage)
    {
        $validated = $request->validate([
            'school_id' => ['required', 'exists:schools,id'],
            'channel' => ['nullable', 'in:' . implode(',', self::CHANNELS)],
            'message' => ['nullable', 'string', 'max:' . self::MESSAGE_MAX_CHARS],
            'audio' => ['nullable', 'file', 'mimes:' . implode(',', self::AUDIO_MIMES), 'max:' . config('wash.voice.audio_max_kb')],
            'photo' => ['nullable', 'image', 'max:' . self::PHOTO_MAX_KB],
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
