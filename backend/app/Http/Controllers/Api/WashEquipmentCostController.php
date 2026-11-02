<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\EquipmentCost;
use Illuminate\Http\Request;
use Illuminate\Validation\Rule;

// CRUD du référentiel prix, calqué sur WashSchoolController (constantes de
// seuils, style de validation). Routes proposées au parent (routes/api.php
// non touché) : GET publics, POST/PATCH sous permission "manage schools".
class WashEquipmentCostController extends Controller
{
    public const KEY_MAX = 64;

    public const LABEL_MAX = 255;

    public const SOURCE_MAX = 255;

    public const URL_MAX = 2048;

    public const NOTES_MAX = 5000;

    public const AMOUNT_MIN = 0;

    public function index(Request $request)
    {
        // Référentiel court : liste complète, pas de pagination.
        $items = EquipmentCost::query()
            ->when($request->category, fn ($q, $v) => $q->where('category', $v))
            ->orderBy('category')
            ->orderBy('label')
            ->get();

        return response()->json($items);
    }

    public function store(Request $request)
    {
        $validated = $request->validate([
            'equipment_key' => ['required', 'string', 'max:' . self::KEY_MAX, 'unique:equipment_costs,equipment_key'],
            'label' => ['required', 'string', 'max:' . self::LABEL_MAX],
            'category' => ['required', 'string', Rule::in(EquipmentCost::CATEGORIES)],
            'min_xaf' => ['required', 'integer', 'min:' . self::AMOUNT_MIN],
            'max_xaf' => ['required', 'integer', 'min:' . self::AMOUNT_MIN, 'gte:min_xaf'],
            'source_name' => ['required', 'string', 'max:' . self::SOURCE_MAX],
            'source_url' => ['nullable', 'url', 'max:' . self::URL_MAX],
            'observed_at' => ['nullable', 'date'],
            'notes' => ['nullable', 'string', 'max:' . self::NOTES_MAX],
        ]);

        return response()->json([
            'message' => 'Prix enregistré au référentiel.',
            'equipment_cost' => EquipmentCost::create($validated),
        ], 201);
    }

    public function show(EquipmentCost $equipmentCost)
    {
        return response()->json($equipmentCost);
    }

    public function update(Request $request, EquipmentCost $equipmentCost)
    {
        $validated = $request->validate([
            'equipment_key' => ['sometimes', 'string', 'max:' . self::KEY_MAX, Rule::unique('equipment_costs', 'equipment_key')->ignore($equipmentCost->id)],
            'label' => ['sometimes', 'string', 'max:' . self::LABEL_MAX],
            'category' => ['sometimes', 'string', Rule::in(EquipmentCost::CATEGORIES)],
            'min_xaf' => ['sometimes', 'integer', 'min:' . self::AMOUNT_MIN],
            'max_xaf' => ['sometimes', 'integer', 'min:' . self::AMOUNT_MIN],
            'source_name' => ['sometimes', 'string', 'max:' . self::SOURCE_MAX],
            'source_url' => ['nullable', 'url', 'max:' . self::URL_MAX],
            'observed_at' => ['nullable', 'date'],
            'notes' => ['nullable', 'string', 'max:' . self::NOTES_MAX],
        ]);

        // Cohérence de la fourchette sur PATCH partiel (champ absent = actuel).
        $min = $validated['min_xaf'] ?? $equipmentCost->min_xaf;
        $max = $validated['max_xaf'] ?? $equipmentCost->max_xaf;
        abort_if($max < $min, 422, 'La borne max_xaf doit être supérieure ou égale à min_xaf.');

        $equipmentCost->update($validated);

        return response()->json([
            'message' => 'Prix du référentiel mis à jour.',
            'equipment_cost' => $equipmentCost->refresh(),
        ]);
    }
}
