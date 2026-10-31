<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class MeshBundle extends Model
{
    protected $fillable = [
        'bundle_id', 'origin_node_id', 'school_id', 'school_code',
        'channel', 'message', 'payload', 'hops', 'hop_count', 'max_hops',
        'received_via_node_id', 'status', 'report_id', 'expires_at', 'delivered_at',
        'destination_eid', 'report_to_eid', 'lifetime_seconds', 'previous_node_id',
        'copies_remaining', 'fragment_offset', 'fragment_total',
        'custody_requested', 'priority', 'signature',
    ];

    protected $casts = [
        'payload' => 'array',
        'hops' => 'array',
        'hop_count' => 'integer',
        'max_hops' => 'integer',
        'expires_at' => 'datetime',
        'delivered_at' => 'datetime',
        'lifetime_seconds' => 'integer',
        'copies_remaining' => 'integer',
        'fragment_offset' => 'integer',
        'fragment_total' => 'integer',
        'custody_requested' => 'boolean',
    ];

    public function school(): BelongsTo
    {
        return $this->belongsTo(School::class);
    }

    public function report(): BelongsTo
    {
        return $this->belongsTo(Report::class);
    }

    public function isExpired(): bool
    {
        return $this->expires_at !== null && $this->expires_at->isPast();
    }
}
