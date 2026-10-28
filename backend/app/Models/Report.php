<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;

class Report extends Model
{
    protected $fillable = [
        'incident_id', 'school_id', 'reporter_id', 'channel',
        'raw_content', 'audio_path', 'photo_path',
        'is_duplicate', 'duplicate_of_incident_id',
        'duplicate_similarity_score', 'raw_ai_extraction',
    ];

    protected $casts = [
        'is_duplicate' => 'boolean',
        'duplicate_similarity_score' => 'float',
        'raw_ai_extraction' => 'array',
    ];

    public function incident(): BelongsTo
    {
        return $this->belongsTo(Incident::class);
    }

    public function school(): BelongsTo
    {
        return $this->belongsTo(School::class);
    }

    public function reporter(): BelongsTo
    {
        return $this->belongsTo(User::class, 'reporter_id');
    }

    public function duplicateOf(): BelongsTo
    {
        return $this->belongsTo(Incident::class, 'duplicate_of_incident_id');
    }

    public function aiAnalyses(): HasMany
    {
        return $this->hasMany(AiAnalysis::class);
    }
}
