<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class IncidentSubscription extends Model
{
    public const CHANNEL_WHATSAPP = 'whatsapp';

    /** Transitoire (hors base) : réactivé après STOP par le dernier subscribe(). */
    public bool $was_reactivated = false;

    protected $fillable = [
        'incident_id', 'channel', 'recipient', 'locale',
        'is_active', 'last_notified_at', 'last_error',
    ];

    protected $casts = [
        'is_active' => 'boolean',
        'last_notified_at' => 'datetime',
    ];

    public function incident(): BelongsTo
    {
        return $this->belongsTo(Incident::class);
    }

    /** Abonne (ou réactive) un destinataire à un dossier. */
    public static function subscribe(Incident $incident, string $channel, string $phone, string $locale): self
    {
        $recipient = SchoolContact::normalizePhone($phone);

        /** @var self $sub */
        $sub = self::firstOrNew([
            'incident_id' => $incident->id,
            'channel' => $channel,
            'recipient' => $recipient,
        ]);
        // Réactivation après STOP (vs premier abonnement) : capturé AVANT
        // sauvegarde, exposé en propriété transitoire pour l'intake.
        $sub->was_reactivated = $sub->exists && ! $sub->is_active;
        $sub->locale = $locale;
        $sub->is_active = true;
        $sub->last_error = null;
        $sub->save();

        return $sub;
    }

    /** Désabonne un destinataire de tous ses dossiers actifs. Retourne le nombre coupé. */
    public static function unsubscribeAll(string $channel, string $phone): int
    {
        return self::where('channel', $channel)
            ->where('recipient', SchoolContact::normalizePhone($phone))
            ->where('is_active', true)
            ->update(['is_active' => false]);
    }
}
