<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\Team;
use Illuminate\Http\Request;

// CRUD des équipes de maintenance (conventions WashSchoolController :
// constantes de validation, pagination bornée par wash.pagination).
class WashTeamController extends Controller
{
    public const NAME_MAX = 255;

    public const DISTRICT_MAX = 128;

    public const PHONE_MAX = 32;

    public const SPECIALTIES_MAX = 20;

    public const SPECIALTY_MAX = 64;

    public function index(Request $request)
    {
        $query = Team::query()
            ->when($request->district, fn ($q, $v) => $q->where('district', $v))
            ->when($request->search, fn ($q, $v) => $q->where('name', 'ilike', "%{$v}%"))
            ->when($request->boolean('active_only'), fn ($q) => $q->where('is_active', true))
            ->orderBy('district')
            ->orderBy('name');

        return response()->json($query->paginate(min(
            config('wash.pagination.max'),
            max(config('wash.pagination.min'), (int) $request->query('per_page', config('wash.pagination.default')))
        )));
    }

    public function store(Request $request)
    {
        $validated = $request->validate([
            'name' => ['required', 'string', 'max:' . self::NAME_MAX, 'unique:teams,name'],
            'district' => ['required', 'string', 'max:' . self::DISTRICT_MAX],
            'phone' => ['nullable', 'string', 'max:' . self::PHONE_MAX],
            'specialties' => ['nullable', 'array', 'max:' . self::SPECIALTIES_MAX],
            'specialties.*' => ['string', 'max:' . self::SPECIALTY_MAX],
            'is_active' => ['sometimes', 'boolean'],
        ]);

        return response()->json([
            'message' => 'Équipe enregistrée.',
            'team' => Team::create($validated),
        ], 201);
    }

    public function show(Team $team)
    {
        return response()->json($team);
    }

    public function update(Request $request, Team $team)
    {
        $validated = $request->validate([
            'name' => ['sometimes', 'string', 'max:' . self::NAME_MAX, 'unique:teams,name,' . $team->id],
            'district' => ['sometimes', 'string', 'max:' . self::DISTRICT_MAX],
            'phone' => ['nullable', 'string', 'max:' . self::PHONE_MAX],
            'specialties' => ['nullable', 'array', 'max:' . self::SPECIALTIES_MAX],
            'specialties.*' => ['string', 'max:' . self::SPECIALTY_MAX],
            'is_active' => ['sometimes', 'boolean'],
        ]);

        $team->update($validated);

        return response()->json([
            'message' => 'Équipe mise à jour.',
            'team' => $team->refresh(),
        ]);
    }

    public function destroy(Team $team)
    {
        $team->delete();

        return response()->json(['message' => 'Équipe supprimée.']);
    }
}
