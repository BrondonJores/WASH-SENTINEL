<?php

namespace App\Jobs;

use App\Services\WashWhatsAppService;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Queue\Queueable;

class ProcessWhatsAppMessage implements ShouldQueue
{
    use Queueable;

    public function __construct(public array $payload) {}

    public function handle(WashWhatsAppService $service): void
    {
        $service->handlePayload($this->payload);
    }
}
