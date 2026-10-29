<?php

namespace App\Providers;

use App\Contracts\AiEngineClient;
use App\Contracts\IncidentTriage;
use App\Contracts\WhatsAppClient;
use App\Services\IncidentTriageService;
use App\Services\MetaWhatsAppService;
use App\Services\WashAiEngineService;
use Illuminate\Support\ServiceProvider;

class AppServiceProvider extends ServiceProvider
{
    /**
     * Register any application services.
     */
    public function register(): void
    {
        $this->app->bind(AiEngineClient::class, WashAiEngineService::class);
        $this->app->bind(IncidentTriage::class, IncidentTriageService::class);
        $this->app->bind(WhatsAppClient::class, MetaWhatsAppService::class);
    }

    /**
     * Bootstrap any application services.
     */
    public function boot(): void
    {
        //
    }
}
