<?php

namespace App\Notifications;

use App\Models\Incident;
use Illuminate\Bus\Queueable;
use Illuminate\Notifications\Messages\MailMessage;
use Illuminate\Notifications\Notification;

class CriticalIncidentNotification extends Notification
{
    use Queueable;

    public function __construct(public Incident $incident) {}

    public function via(object $notifiable): array
    {
        return ['database', 'mail'];
    }

    public function toMail(object $notifiable): MailMessage
    {
        return (new MailMessage)
            ->subject("Incident CRITIQUE : {$this->incident->school->name} ({$this->incident->reference_code})")
            ->line("Un incident critique vient d'être signalé et trié par l'IA.")
            ->line("École : {$this->incident->school->name} ({$this->incident->school->district})")
            ->line("Résumé : {$this->incident->ai_summary}")
            ->line("Élèves affectés : {$this->incident->affected_students} — Priorité IA : {$this->incident->priority_score}/100")
            ->action("Voir l'incident", url("/api/v1/wash/incidents/{$this->incident->id}"));
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
