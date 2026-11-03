<?php

namespace App\Observers;

use App\Models\MaintenanceLog;
use App\Services\IncidentProgressNotifier;

class MaintenanceLogObserver
{
    public function __construct(protected IncidentProgressNotifier $notifier) {}

    /** Intervention journalisée (manuelle ou proposition validée) → suivi WhatsApp. */
    public function created(MaintenanceLog $log): void
    {
        $this->notifier->interventionLogged($log);
    }
}
