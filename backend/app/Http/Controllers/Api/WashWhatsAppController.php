<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Jobs\ProcessWhatsAppMessage;
use App\Services\WashWhatsAppService;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Cache;

class WashWhatsAppController extends Controller
{
    public function verify(Request $request)
    {
        $mode = $request->query('hub_mode');
        $token = (string) $request->query('hub_verify_token', '');
        $challenge = $request->query('hub_challenge');

        if ($mode === 'subscribe' && $challenge && hash_equals((string) config('services.whatsapp.verify_token', ''), $token)) {
            return response($challenge, 200)->header('Content-Type', 'text/plain');
        }

        abort(403, 'Webhook verification failed.');
    }

    public function receive(Request $request, WashWhatsAppService $service)
    {
        if (!config('services.whatsapp.simulator', false)
            && !$service->verifySignature($request->getContent(), $request->header('X-Hub-Signature-256'))) {
            abort(403, 'Invalid webhook signature.');
        }

        ProcessWhatsAppMessage::dispatch($request->all());
        Cache::put('wash.whatsapp.last_webhook_at', now()->toIso8601String(), 86400);

        return response()->json(['received' => true]);
    }

    public function diagnostics()
    {
        return response()->json([
            'verify_token_configured' => (string) config('services.whatsapp.verify_token', '') !== '',
            'app_token_configured' => (string) config('services.whatsapp.access_token', '') !== '',
            'webhook_url_hint' => rtrim((string) config('app.url', ''), '/') . '/api/v1/whatsapp/webhook',
            'queue_connection' => (string) config('queue.default', 'database'),
            'last_webhook_at' => Cache::get('wash.whatsapp.last_webhook_at'),
        ]);
    }
}
