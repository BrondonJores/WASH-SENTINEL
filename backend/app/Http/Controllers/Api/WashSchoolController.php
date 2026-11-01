<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\School;
use Illuminate\Http\Request;

class WashSchoolController extends Controller
{
    public const NAME_MAX = 255;

    public const CODE_MAX = 64;

    public const DISTRICT_MAX = 128;

    public const COUNT_MIN = 0;

    public const EQUIPMENT_MAX = 64;

    public const INSTALLATION_YEAR_MIN = 1950;

    public const INSTALLATION_YEAR_MAX = 2100;

    public const CONTACT_PHONE_MAX = 32;

    public const RECENT_LOGS_LIMIT = 10;

    public function index(Request $request)
    {
        $query = School::query()
            ->withCount(['openIncidents', 'reports'])
            ->when($request->district, fn ($q, $v) => $q->where('district', $v))
            ->when($request->search, fn ($q, $v) => $q->where('name', 'ilike', "%{$v}%"))
            ->orderBy('name');

        return response()->json($query->paginate(min(
            config('wash.pagination.max'),
            max(config('wash.pagination.min'), (int) $request->query('per_page', config('wash.pagination.default')))
        )));
    }

    public function store(Request $request)
    {
        $validated = $request->validate([
            'name' => ['required', 'string', 'max:' . self::NAME_MAX],
            'code' => ['required', 'string', 'max:' . self::CODE_MAX, 'unique:schools,code'],
            'district' => ['required', 'string', 'max:' . self::DISTRICT_MAX],
            'latitude' => ['nullable', 'numeric'],
            'longitude' => ['nullable', 'numeric'],
            'student_count' => ['nullable', 'integer', 'min:' . self::COUNT_MIN],
            'female_students' => ['nullable', 'integer', 'min:' . self::COUNT_MIN],
            'teacher_count' => ['nullable', 'integer', 'min:' . self::COUNT_MIN],
            'distance_from_center_km' => ['nullable', 'numeric', 'min:' . self::COUNT_MIN],
            'equipment_type' => ['nullable', 'string', 'max:' . self::EQUIPMENT_MAX],
            'installation_year' => ['nullable', 'integer', 'min:' . self::INSTALLATION_YEAR_MIN, 'max:' . self::INSTALLATION_YEAR_MAX],
            'estimated_replacement_cost' => ['nullable', 'numeric', 'min:' . self::COUNT_MIN],
            'contact_phone' => ['nullable', 'string', 'max:' . self::CONTACT_PHONE_MAX],
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
            'maintenanceLogs' => fn ($q) => $q->latest()->take(self::RECENT_LOGS_LIMIT),
        ])->loadCount(['reports', 'maintenanceLogs']));
    }
}
