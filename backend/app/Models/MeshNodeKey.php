<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

/**
 * Clé publique TOFU (Trust On First Use) d'un nœud mesh d'origine.
 *
 * La première `node_pubkey` vue pour un `origin_node_id` devient la
 * référence ; tout changement ultérieur est signalé (log + compteur
 * `key_changed`) mais n'entraîne jamais un rejet du bundle.
 */
class MeshNodeKey extends Model
{
    protected $fillable = [
        'origin_node_id', 'node_pubkey', 'first_seen_at', 'last_changed_at',
    ];

    protected $casts = [
        'first_seen_at' => 'datetime',
        'last_changed_at' => 'datetime',
    ];
}
