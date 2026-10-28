<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class AiAnalysis extends Model
{
    protected $fillable = [
        'incident_id', 'report_id', 'analysis_type',
        'input_payload', 'output_payload',
        'model_used', 'confidence', 'processing_ms',
    ];

    protected $casts = [
        'input_payload' => 'array',
        'output_payload' => 'array',
        'confidence' => 'float',
    ];

    public function incident(): BelongsTo
    {
        return $this->belongsTo(Incident::class);
    }

    public function report(): BelongsTo
    {
        return $this->belongsTo(Report::class);
    }
}
