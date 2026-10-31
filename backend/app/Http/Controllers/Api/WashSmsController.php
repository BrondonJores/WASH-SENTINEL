<?php

namespace App\Http\Controllers\Api;

use App\Contracts\IncidentTriage;
use App\Http\Controllers\Controller;
use App\Models\MeshBundle;
use App\Services\MeshSmsParser;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Str;

/**
 * Canal SMS/USSD (feature phones, 2G sans data) — Phase 0.
 *
 * Compatible passerelle type SMSSync : un Android villageois POSTe chaque
 * SMS reçu vers cet endpoint dès qu'une data intermittente est dispo.
 * Le SMS devient un MeshBundle (origin sms:<sender>) puis suit le triage
 * IA standard avec source = 'sms' — dédup et stats unifiées avec le mesh.
 */
class WashSmsController extends Controller
{
    public function store(Request $request, IncidentTriage $triage, MeshSmsParser $parser)
    {
        $validated = $request->validate([
            'secret' => ['required', 'string'],
            'from' => ['required', 'string', 'max:32'],
            'message' => ['required', 'string', 'max:1600'],
            'sent_at' => ['nullable', 'date'],
        ]);

        $secret = (string) config('services.mesh.sms_secret');
        if ($secret === '' || ! hash_equals($secret, $validated['secret'])) {
            Log::warning('mesh.sms.rejected', ['cause' => 'bad_secret', 'from' => $validated['from']]);

            return response()->json(['message' => 'Secret passerelle invalide.'], 403);
        }

        $allowlist = array_filter(array_map('trim', explode(',', (string) config('services.mesh.sms_allowlist'))));
        if ($allowlist !== [] && ! in_array($validated['from'], $allowlist, true)) {
            Log::warning('mesh.sms.rejected', ['cause' => 'not_allowlisted', 'from' => $validated['from']]);

            return response()->json(['message' => 'Expéditeur non autorisé.'], 403);
        }

        $origin = 'sms:'.$validated['from'];
        $quota = (int) config('services.mesh.sms_quota_per_sender', 10);
        if (MeshBundle::where('origin_node_id', $origin)->whereDate('created_at', today())->count() >= $quota) {
            Log::warning('mesh.sms.rejected', ['cause' => 'quota', 'from' => $validated['from']]);

            return response()->json(['message' => 'Quota journalier dépassé pour cet expéditeur.'], 429);
        }

        $parsed = $parser->parse($validated['message']);
        if (! $parsed['ok']) {
            return response()->json([
                'message' => 'Format SMS invalide.',
                'error' => $parsed['error'],
                'reply' => Str::limit($parsed['error'] ?? MeshSmsParser::HELP, 160, ''),
            ], 422);
        }

        // Dédup : même expéditeur + même texte normalisé sur 24 h (double envoi).
        $recent = MeshBundle::where('origin_node_id', $origin)
            ->where('message', $parsed['normalized'])
            ->where('created_at', '>', now()->subDay())
            ->with('report.incident')
            ->first();
        if ($recent) {
            return response()->json([
                'message' => 'Signalement déjà reçu.',
                'duplicate' => true,
                'ticket' => $recent->report?->incident?->reference_code,
            ]);
        }

        $result = DB::transaction(function () use ($validated, $parsed, $origin, $triage, $request) {
            $bundle = MeshBundle::create([
                'bundle_id' => (string) Str::uuid(),
                'origin_node_id' => $origin,
                'school_id' => $parsed['school']->id,
                'school_code' => $parsed['school']->code,
                'channel' => 'text',
                'message' => $parsed['normalized'],
                'payload' => [
                    'sms_text' => $validated['message'],
                    'sms_from' => $validated['from'],
                    'sms_type' => $parsed['type'],
                    'sent_at' => $validated['sent_at'] ?? null,
                ],
                'hops' => [$origin],
                'hop_count' => 0,
                'copies_remaining' => 1,
                'destination_eid' => 'dtn://wash-sentinel/ingest',
                'received_via_node_id' => $origin,
                'status' => 'delivered',
                'expires_at' => now()->addDays(7),
                'delivered_at' => now(),
            ]);

            $ingested = $triage->ingest(
                $parsed['school'], 'text', $parsed['normalized'],
                null, null, $request->user(), 'sms',
            );
            $bundle->update(['report_id' => $ingested['report']->id]);

            return ['bundle' => $bundle, 'incident' => $ingested['incident']];
        });

        $ticket = $result['incident']->reference_code ?? "#{$result['incident']->id}";

        Log::info('mesh.sms.accepted', [
            'bundle_id' => $result['bundle']->bundle_id,
            'from' => $validated['from'],
            'school_id' => $parsed['school']->id,
            'ticket' => $ticket,
        ]);

        return response()->json([
            'message' => 'Signalement SMS enregistré.',
            'ticket' => $ticket,
            'incident_id' => $result['incident']->id,
            'reply' => $parser->acknowledge($parsed['school'], $parsed['type'], $ticket),
        ], 201);
    }
}
