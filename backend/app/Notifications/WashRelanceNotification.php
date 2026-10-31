<?php

namespace App\Notifications;

use App\Models\Incident;
use Illuminate\Bus\Queueable;
use Illuminate\Notifications\Messages\MailMessage;
use Illuminate\Notifications\Notification;

class WashRelanceNotification extends Notification
{
    use Queueable;

    public function __construct(public Incident $incident, public int $daysInactive = 0) {}

    public function via(object $notifiable): array
    {
        return ['database', 'mail'];
    }

    public function toMail(object $notifiable): MailMessage
    {
        return (new MailMessage)
            ->subject("Relance incident dormant : {$this->incident->reference_code} ({$this->incident->school->name})")
            ->line("L'incident {$this->incident->reference_code} est sans activité depuis {$this->daysInactive} jour(s).")
            ->line("École : {$this->incident->school->name} ({$this->incident->school->district})")
            ->line("Titre : {$this->incident->title}")
            ->line("Statut : {$this->incident->status} — Priorité IA : {$this->incident->priority_score}/100")
            ->action("Voir l'incident", url("/api/v1/wash/incidents/{$this->incident->id}"));
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
