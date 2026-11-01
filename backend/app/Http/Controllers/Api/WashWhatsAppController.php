<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Jobs\ProcessWhatsAppMessage;
use App\Services\WashWhatsAppService;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Cache;

class WashWhatsAppController extends Controller
{
    public const LAST_WEBHOOK_TTL_SECONDS = 86400;

    protected function verifyToken(): string
    {
        $token = (string) config('whatsapp.verify_token', '');
        if ($token === '') {
            $token = (string) config('services.whatsapp.verify_token', '');
        }

        return $token;
    }

    protected function isSimulator(): bool
    {
        return (bool) config('whatsapp.simulator', config('services.whatsapp.simulator', false));
    }

    public function verify(Request $request)
    {
        $mode = $request->query('hub_mode');
        $token = (string) $request->query('hub_verify_token', '');
        $challenge = $request->query('hub_challenge');

        if ($mode === 'subscribe' && $challenge && hash_equals($this->verifyToken(), $token)) {
            return response($challenge, 200)->header('Content-Type', 'text/plain');
        }

        abort(403, 'Webhook verification failed.');
    }

    public function receive(Request $request, WashWhatsAppService $service)
    {
        if (!(bool) config('whatsapp.enabled', true)) {
            abort(503, 'WhatsApp channel disabled.');
        }

        if (!$this->isSimulator()
            && !$service->verifySignature($request->getContent(), $request->header('X-Hub-Signature-256'))) {
            abort(403, 'Invalid webhook signature.');
        }

        $payload = $request->all();
        // Diagnostics : horodaté à CHAQUE livraison, relivraisons Meta incluses.
        Cache::put('wash.whatsapp.last_webhook_at', now()->toIso8601String(), self::LAST_WEBHOOK_TTL_SECONDS);

        // Relivraison Meta (retry) déjà traitée : accusé sans triage ni envoi.
        if ($service->isDuplicateDelivery($payload)) {
            return response()->json(['received' => true, 'status' => 'duplicate_delivery']);
        }

        ProcessWhatsAppMessage::dispatch($payload);

        return response()->json(['received' => true]);
    }

    public function diagnostics()
    {
        $accessToken = (string) config('whatsapp.token', '');
        if ($accessToken === '') {
            $accessToken = (string) config('services.whatsapp.access_token', '');
        }

        return response()->json([
            'enabled' => (bool) config('whatsapp.enabled', true),
            'verify_token_configured' => $this->verifyToken() !== '',
            'app_token_configured' => $accessToken !== '',
            'phone_number_id_configured' => (string) config('whatsapp.phone_number_id', config('services.whatsapp.phone_number_id', '')) !== '',
            'voice_confirmation' => (bool) config('whatsapp.voice_confirmation', true),
            'confirmation_template' => (string) config('whatsapp.confirmation_template', 'wash_confirmation'),
            'webhook_url_hint' => rtrim((string) config('app.url', ''), '/') . '/api/v1/whatsapp/webhook',
            'queue_connection' => (string) config('queue.default', 'database'),
            'last_webhook_at' => Cache::get('wash.whatsapp.last_webhook_at'),
        ]);
    }
}
