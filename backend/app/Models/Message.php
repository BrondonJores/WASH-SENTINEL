<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class Message extends Model
{
    protected $fillable = ['conversation_id', 'role', 'content', 'tools', 'cards', 'model', 'said_at', 'follow_ups'];

    protected $casts = [
        'tools' => 'array',
        'cards' => 'array',
        'follow_ups' => 'array',
    ];

    public function conversation(): BelongsTo
    {
        return $this->belongsTo(Conversation::class);
    }
}
