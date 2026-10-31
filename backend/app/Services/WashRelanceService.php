<?php

namespace App\Services;

use App\Models\Incident;
use App\Models\User;
use App\Notifications\WashRelanceNotification;
use Illuminate\Support\Collection;

class WashRelanceService
{
    /**
     * Statuts "ouverts" : miroir de Incident::scopeOpen() (tout sauf
     * resolved/closed) et de l'enum de la migration incidents.
     */
    public const OPEN_STATUSES = ['reported', 'triaged', 'assigned', 'in_progress'];

    public const DEFAULT_DAYS = 7;

    /**
     * Incidents ouverts sans activité depuis au moins $days jours
     * (updated_at < now - $days), triés par priorité décroissante
     * (plus anciens en premier en cas d'égalité).
     */
    public function dormants(int $days = self::DEFAULT_DAYS): Collection
    {
        $days = max(1, $days);

        return Incident::with(['school:id,name,district', 'assignee:id,name'])
            ->whereIn('status', self::OPEN_STATUSES)
            ->where('updated_at', '<', now()->subDays($days))
            ->orderByDesc('priority_score')
            ->orderBy('updated_at')
            ->get();
    }

    /**
     * Notifie $user pour $incident via les notifications Laravel
     * standard (canal database, lu par WashNotificationController).
     * Retourne un résumé de l'envoi.
     */
    public function relancer(Incident $incident, User $user): array
    {
        $incident->loadMissing('school');

        $daysInactive = (int) ($incident->updated_at?->diffInDays(now()) ?? 0);

        $user->notify(new WashRelanceNotification($incident, $daysInactive));

        return [
            'incident_id' => $incident->id,
            'reference_code' => $incident->reference_code,
            'notified_user_id' => $user->id,
            'days_inactive' => $daysInactive,
            'sent_at' => now()->toIso8601String(),
        ];
    }

    /**
     * Relance tous les dormants : l'assigné quand l'incident en a un,
     * sinon les wash_admin + maintenance_agent (même règle d'audience
     * que la notification critique d'IncidentTriageService).
     */
    public function relancerDormants(int $days = self::DEFAULT_DAYS): array
    {
        $results = [];

        foreach ($this->dormants($days) as $incident) {
            $recipients = $incident->assignee
                ? collect([$incident->assignee])
                : User::role(['wash_admin', 'maintenance_agent'])->get();

            $notified = [];
            foreach ($recipients as $user) {
                $notified[] = $this->relancer($incident, $user);
            }

            $results[] = [
                'incident_id' => $incident->id,
                'reference_code' => $incident->reference_code,
                'notified' => $notified,
            ];
        }

        return $results;
    }
}
