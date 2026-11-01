<?php

namespace App\Notifications;

use App\Models\Incident;
use Illuminate\Bus\Queueable;
use Illuminate\Notifications\Messages\MailMessage;
use Illuminate\Notifications\Notification;
use Illuminate\Support\Facades\Route;

class CriticalIncidentNotification extends Notification
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

    public function __construct(public Incident $incident) {}

    public function via(object $notifiable): array
    {
        return ['database', 'mail'];
    }

    public function toMail(object $notifiable): MailMessage
    {
        // LOT 7 — textes lang/fr/wash.php (locale 'fr' forcée, identiques).
        return (new MailMessage)
            ->subject(trans('wash.notifications.critical.subject', [
                'school' => $this->incident->school->name,
                'ref' => $this->incident->reference_code,
            ], 'fr'))
            ->line(trans('wash.notifications.critical.intro', [], 'fr'))
            ->line(trans('wash.notifications.critical.school', [
                'school' => $this->incident->school->name,
                'district' => $this->incident->school->district,
            ], 'fr'))
            ->line(trans('wash.notifications.critical.summary', [
                'summary' => (string) $this->incident->ai_summary,
            ], 'fr'))
            ->line(trans('wash.notifications.critical.priority', [
                'affected' => (string) $this->incident->affected_students,
                'priority' => (string) $this->incident->priority_score,
            ], 'fr'))
            ->action(trans('wash.notifications.critical.action', [], 'fr'), $this->incidentUrl());
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
            'incident_id' => $this->incident->id,
            'reference_code' => $this->incident->reference_code,
            'school' => $this->incident->school->name,
            'district' => $this->incident->school->district,
            'title' => $this->incident->title,
            'urgency' => $this->incident->urgency,
            'priority_score' => $this->incident->priority_score,
            'affected_students' => $this->incident->affected_students,
            'ai_summary' => $this->incident->ai_summary,
        ];
    }
}
