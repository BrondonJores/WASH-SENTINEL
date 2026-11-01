<?php

namespace App\Notifications;

use App\Models\Incident;
use Illuminate\Bus\Queueable;
use Illuminate\Notifications\Messages\MailMessage;
use Illuminate\Notifications\Notification;
use Illuminate\Support\Facades\Route;

class WashRelanceNotification extends Notification
{
    use Queueable;

    /**
     * LOT 7 — chemin legacy de la fiche incident. La route nommée
     * 'wash.incidents.show' gagne quand elle existe (routes/api.php hors
     * périmètre du lot : aucune route nommée à ce jour, le repli url()
     * produit l'URL strictement identique à l'origine).
     */
    protected const LEGACY_INCIDENT_PATH = '/api/v1/wash/incidents/';

    /** Nom de la route fiche incident (voir LEGACY_INCIDENT_PATH). */
    protected const INCIDENT_ROUTE = 'wash.incidents.show';

    public function __construct(public Incident $incident, public int $daysInactive = 0) {}

    public function via(object $notifiable): array
    {
        return ['database', 'mail'];
    }

    public function toMail(object $notifiable): MailMessage
    {
        // LOT 7 — textes lang/fr/wash.php (locale 'fr' forcée, identiques).
        return (new MailMessage)
            ->subject(trans('wash.notifications.relance.subject', [
                'ref' => $this->incident->reference_code,
                'school' => $this->incident->school->name,
            ], 'fr'))
            ->line(trans('wash.notifications.relance.stale', [
                'ref' => $this->incident->reference_code,
                'days' => (string) $this->daysInactive,
            ], 'fr'))
            ->line(trans('wash.notifications.relance.school', [
                'school' => $this->incident->school->name,
                'district' => $this->incident->school->district,
            ], 'fr'))
            ->line(trans('wash.notifications.relance.title', [
                'title' => (string) $this->incident->title,
            ], 'fr'))
            ->line(trans('wash.notifications.relance.status', [
                'status' => (string) $this->incident->status,
                'priority' => (string) $this->incident->priority_score,
            ], 'fr'))
            ->action(trans('wash.notifications.relance.action', [], 'fr'), $this->incidentUrl());
    }

    /** URL fiche incident : route nommée si elle existe, sinon legacy url(). */
    protected function incidentUrl(): string
    {
        if (Route::has(self::INCIDENT_ROUTE)) {
            return route(self::INCIDENT_ROUTE, ['incident' => $this->incident->id]);
        }

        return url(self::LEGACY_INCIDENT_PATH.$this->incident->id);
    }

    public function toArray(object $notifiable): array
    {
        return [
            'type' => 'relance_dormant',
            'incident_id' => $this->incident->id,
            'reference_code' => $this->incident->reference_code,
            'school' => $this->incident->school->name,
            'district' => $this->incident->school->district,
            'title' => $this->incident->title,
            'status' => $this->incident->status,
            'urgency' => $this->incident->urgency,
            'priority_score' => $this->incident->priority_score,
            'days_inactive' => $this->daysInactive,
        ];
    }
}
