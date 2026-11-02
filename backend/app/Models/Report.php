<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;
use Illuminate\Support\Facades\Storage;

class Report extends Model
{
    /**
     * URL absolue de la photo exposée au chat (miniatures incidents).
     * Calculée depuis photo_path (disque public) : null sans photo ou si
     * le fichier a disparu (exclusion silencieuse, jamais de 404 en carte).
     */
    protected $appends = ['photo_url'];
    protected $fillable = [
        'incident_id', 'school_id', 'reporter_id', 'channel', 'source',
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

    /**
     * URL absolue ouvrable depuis le navigateur (APP_URL + /storage/...).
     * Null quand photo_path est vide ou que le fichier manque sur disque.
     */
    public function getPhotoUrlAttribute(): ?string
    {
        $path = $this->photo_path;
        if (!is_string($path) || $path === '') {
            return null;
        }
        if (!Storage::disk('public')->exists($path)) {
            return null;
        }
        $url = Storage::disk('public')->url($path);
        if (str_starts_with($url, '/')) {
            $url = rtrim((string) config('app.url'), '/') . $url;
        }

        return $url;
    }
}
