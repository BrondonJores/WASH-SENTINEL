<?php

namespace App\Http\Controllers\Api\Admin;

use App\Http\Controllers\Controller;
use App\Models\AiAnalysis;
use Illuminate\Http\Request;

class WashAiAnalysisController extends Controller
{
    public function index(Request $request)
    {
        $query = AiAnalysis::with([
            'incident:id,reference_code,title,school_id',
            'incident.school:id,name,district',
            'report:id,school_id,channel,is_duplicate',
        ])
            ->when($request->analysis_type, fn ($q, $v) => $q->where('analysis_type', $v))
            ->when($request->incident_id, fn ($q, $v) => $q->where('incident_id', $v))
            ->latest();

        return response()->json($query->paginate(20));
    }
}
