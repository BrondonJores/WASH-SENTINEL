<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;
use Illuminate\Support\Str;

class Incident extends Model
{
    /**
     * LOT 6 — source unique des statuts "ouverts" (tout sauf resolved/closed,
     * cf. enum de la migration incidents). Référencée par scopeOpen(),
     * School::openIncidents() et WashRelanceService. Les listes Python
     * (ai-engine) sont des miroirs documentés, hors lot.
     */
    public const OPEN_STATUSES = ['reported', 'triaged', 'assigned', 'in_progress'];

    /** LOT 6 — génération de reference_code (année dynamique). */
    public const REFERENCE_PREFIX = 'WASH-';

    public const REFERENCE_RANDOM_LENGTH = 6;

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
                $incident->reference_code = self::generateReferenceCode();
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

    /**
     * Génère une référence compatible avec le pattern de suivi
     * WashWhatsAppService::SUIVI_REFERENCE_PATTERN (/WASH-\d{4}-[A-Z0-9]{4,}/i).
     * Parité ancrée par tests/Feature/WashLot6ParityTest.php.
     */
    public static function generateReferenceCode(): string
    {
        return self::REFERENCE_PREFIX . date('Y') . '-' . strtoupper(Str::random(self::REFERENCE_RANDOM_LENGTH));
    }

    public function scopeOpen($query)
    {
        // Équivalent à whereNotIn(resolved/closed) via l'enum migration (6 statuts).
        return $query->whereIn('status', self::OPEN_STATUSES);
    }
}
