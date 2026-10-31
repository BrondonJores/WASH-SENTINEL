<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;

class Conversation extends Model
{
    protected $fillable = ['user_id', 'project_id', 'title'];

    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }

    public function project(): BelongsTo
    {
        return $this->belongsTo(Project::class);
    }

    public function messages(): HasMany
    {
        // Ordre d'insertion stable : le replace-all recrée les lignes dans
        // l'ordre du tableau front, mais avec des created_at identiques —
        // trier par created_at rend l'ordre indéfini après un refresh.
        return $this->hasMany(Message::class)->orderBy('id');
    }
}
