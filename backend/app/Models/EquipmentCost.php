<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

// Ligne du référentiel prix : fourchette min/max en XAF + source observée.
// Le détail des observations (2e source, taux de conversion) vit en notes.
class EquipmentCost extends Model
{
    public const CATEGORIES = [
        'water_point',
        'toilets_latrines',
        'handwashing',
        'sewage_drainage',
    ];

    protected $fillable = [
        'equipment_key', 'label', 'category', 'min_xaf', 'max_xaf',
        'source_name', 'source_url', 'observed_at', 'notes',
    ];

    protected $casts = [
        'min_xaf' => 'integer',
        'max_xaf' => 'integer',
        'observed_at' => 'date',
    ];
}
