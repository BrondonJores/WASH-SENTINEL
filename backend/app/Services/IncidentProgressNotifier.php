<?php

namespace App\Services;

use App\Contracts\WhatsAppClient;
use App\Models\Incident;
use App\Models\IncidentSubscription;
use App\Models\MaintenanceLog;
use Illuminate\Support\Facades\Log;

class IncidentProgressNotifier
{
    /** Fenêtre Meta 24h fermée : free-form refusé, template obligatoire. */
    protected const WINDOW_ERROR = '131047';

    public function __construct(protected WhatsAppClient $client) {}

    /** Un statut a changé : on écrit à chaque abonné actif du dossier. */
    public function statusChanged(Incident $incident, string $newStatus): void
    {
        $incident->loadMissing('school');
        $school = (string) ($incident->school?->name ?? '');

        foreach ($this->activeSubscriptions($incident) as $sub) {
            $message = trans('wash.notifications.progress.status', [
                'ref' => $incident->reference_code,
                'status' => $this->statusLabel($newStatus, $sub->locale),
                'detail' => $this->statusDetail($newStatus, $sub->locale),
                'school' => $school,
            ], $sub->locale);
            $this->sendTo($sub, $message, [$incident->reference_code, $this->statusLabel($newStatus, $sub->locale)]);
        }
    }

    /** Une intervention est journalisée (manuelle ou proposition validée). */
    public function interventionLogged(MaintenanceLog $log): void
    {
        $log->loadMissing(['incident.school']);
        $incident = $log->incident;
        if (! $incident) {
            return;
        }
        $notes = trim((string) ($log->notes ?? ''));
        $cost = number_format((float) $log->cost_amount, 0, ',', ' ');

        foreach ($this->activeSubscriptions($incident) as $sub) {
            $message = trans('wash.notifications.progress.intervention', [
                'ref' => $incident->reference_code,
                'notes' => $notes !== '' ? $notes : '—',
                'cost' => $cost,
                'school' => (string) ($incident->school?->name ?? ''),
            ], $sub->locale);
            $this->sendTo($sub, $message, [$incident->reference_code, $cost]);
        }
    }

    /** @return iterable<IncidentSubscription> */
    protected function activeSubscriptions(Incident $incident): iterable
    {
        return IncidentSubscription::where('incident_id', $incident->id)
            ->where('channel', IncidentSubscription::CHANNEL_WHATSAPP)
            ->where('is_active', true)
            ->get();
    }

    protected function statusLabel(string $status, string $locale): string
    {
        $key = "wash.notifications.progress.status_{$status}";

        return trans()->has($key, $locale)
            ? trans($key, [], $locale)
            : $status;
    }

    protected function statusDetail(string $status, string $locale): string
    {
        $key = "wash.notifications.progress.detail_{$status}";

        return trans()->has($key, $locale)
            ? trans($key, [], $locale)
            : trans('wash.notifications.progress.detail_default', [], $locale);
    }

    /**
     * Envoi best-effort : ne lève JAMAIS (un suivi raté ne doit pas casser
     * la requête). Fenêtre 24h fermée (131047) + template configuré → repli
     * template. Chaque issue est tracée sur l'abonnement.
     */
    protected function sendTo(IncidentSubscription $sub, string $message, array $templateParams): void
    {
        try {
            $this->client->sendText($sub->recipient, $message);
            $sub->forceFill(['last_notified_at' => now(), 'last_error' => null])->save();
        } catch (\Throwable $e) {
            if ($this->isWindowError($e) && $this->sendTemplateFallback($sub, $templateParams)) {
                $sub->forceFill(['last_notified_at' => now(), 'last_error' => null])->save();

                return;
            }
            $sub->forceFill(['last_error' => mb_substr($e->getMessage(), 0, 200)])->save();
            Log::warning('Suivi WhatsApp non envoyé.', [
                'subscription' => $sub->id,
                'incident' => $sub->incident_id,
                'error' => $e->getMessage(),
            ]);
        }
    }

    protected function isWindowError(\Throwable $e): bool
    {
        return str_contains($e->getMessage(), self::WINDOW_ERROR);
    }

    protected function sendTemplateFallback(IncidentSubscription $sub, array $templateParams): bool
    {
        $template = (string) config('whatsapp.progress_template', '');
        if ($template === '') {
            return false;
        }
        try {
            $this->client->sendTemplate(
                $sub->recipient, $template,
                (string) config('whatsapp.progress_template_language', $sub->locale),
                array_map(strval(...), $templateParams),
            );

            return true;
        } catch (\Throwable $e) {
            Log::warning('Repli template suivi WhatsApp échoué.', [
                'subscription' => $sub->id,
                'error' => $e->getMessage(),
            ]);

            return false;
        }
    }
}
