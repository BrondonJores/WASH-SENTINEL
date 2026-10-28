<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;
use Illuminate\Support\Str;

class Incident extends Model
{
    protected $fillable = [
        'school_id', 'reference_code', 'title', 'category', 'issue_type',
        'status', 'urgency', 'health_hazard', 'priority_score',
        'affected_students', 'ai_summary', 'ai_tags',
        'assigned_to_user_id', 'resolved_at',
    ];

    protected $casts = [
        'ai_tags' => 'array',
        'priority_score' => 'float',
        'resolved_at' => 'datetime',
    ];

    protected static function booted(): void
    {
        static::creating(function (Incident $incident) {
            if (empty($incident->reference_code)) {
                $incident->reference_code = 'WASH-' . date('Y') . '-' . strtoupper(Str::random(6));
            }
        });
    }

    public function school(): BelongsTo
    {
        return $this->belongsTo(School::class);
    }

    public function reports(): HasMany
    {
        return $this->hasMany(Report::class);
    }

    public function aiAnalyses(): HasMany
    {
        return $this->hasMany(AiAnalysis::class);
    }

    public function maintenanceLogs(): HasMany
    {
        return $this->hasMany(MaintenanceLog::class);
    }

    public function assignee(): BelongsTo
    {
        return $this->belongsTo(User::class, 'assigned_to_user_id');
    }

    public function scopeOpen($query)
    {
        return $query->whereNotIn('status', ['resolved', 'closed']);
    }
}
