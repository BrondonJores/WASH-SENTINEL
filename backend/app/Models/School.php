<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasMany;

class School extends Model
{
    protected $fillable = [
        'name', 'code', 'district', 'latitude', 'longitude',
        'student_count', 'female_students', 'teacher_count', 'broken_toilets',
        'distance_from_center_km', 'equipment_type', 'installation_year',
        'estimated_replacement_cost', 'contact_phone',
    ];

    protected $casts = [
        'latitude' => 'float',
        'longitude' => 'float',
        'distance_from_center_km' => 'float',
        'estimated_replacement_cost' => 'float',
    ];

    public function incidents(): HasMany
    {
        return $this->hasMany(Incident::class);
    }

    public function openIncidents(): HasMany
    {
        return $this->hasMany(Incident::class)->whereNotIn('status', ['resolved', 'closed']);
    }

    public function reports(): HasMany
    {
        return $this->hasMany(Report::class);
    }

    public function maintenanceLogs(): HasMany
    {
        return $this->hasMany(MaintenanceLog::class);
    }
}
