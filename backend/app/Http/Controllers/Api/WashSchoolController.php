<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\School;
use Illuminate\Http\Request;

class WashSchoolController extends Controller
{
    public function index(Request $request)
    {
        $query = School::query()
            ->withCount(['openIncidents', 'reports'])
            ->when($request->district, fn ($q, $v) => $q->where('district', $v))
            ->when($request->search, fn ($q, $v) => $q->where('name', 'ilike', "%{$v}%"))
            ->orderBy('name');

        return response()->json($query->paginate(20));
    }

    public function store(Request $request)
    {
        $validated = $request->validate([
            'name' => ['required', 'string', 'max:255'],
            'code' => ['required', 'string', 'max:64', 'unique:schools,code'],
            'district' => ['required', 'string', 'max:128'],
            'latitude' => ['nullable', 'numeric'],
            'longitude' => ['nullable', 'numeric'],
            'student_count' => ['nullable', 'integer', 'min:0'],
            'female_students' => ['nullable', 'integer', 'min:0'],
            'teacher_count' => ['nullable', 'integer', 'min:0'],
            'distance_from_center_km' => ['nullable', 'numeric', 'min:0'],
            'equipment_type' => ['nullable', 'string', 'max:64'],
            'installation_year' => ['nullable', 'integer', 'min:1950', 'max:2100'],
            'estimated_replacement_cost' => ['nullable', 'numeric', 'min:0'],
            'contact_phone' => ['nullable', 'string', 'max:32'],
        ]);

        return response()->json([
            'message' => 'École enregistrée.',
            'school' => School::create($validated),
        ], 201);
    }

    public function show(School $school)
    {
        return response()->json($school->load([
            'openIncidents' => fn ($q) => $q->orderByDesc('priority_score'),
            'maintenanceLogs' => fn ($q) => $q->latest()->take(10),
        ])->loadCount(['reports', 'maintenanceLogs']));
    }
}
