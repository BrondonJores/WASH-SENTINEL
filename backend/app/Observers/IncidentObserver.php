<?php

namespace App\Observers;

use App\Models\Incident;
use App\Services\IncidentProgressNotifier;

class IncidentObserver
{
    public function __construct(protected IncidentProgressNotifier $notifier) {}

    /** Changement de statut (toutes voies : API, console, propositions) → suivi WhatsApp. */
    public function updated(Incident $incident): void
    {
        if (! $incident->wasChanged('status')) {
            return;
        }
        $this->notifier->statusChanged($incident, (string) $incident->status);
    }
}
