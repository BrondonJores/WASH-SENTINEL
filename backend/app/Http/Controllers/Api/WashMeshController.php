<?php

namespace App\Http\Controllers\Api;

use App\Contracts\IncidentTriage;
use App\Http\Controllers\Controller;
use App\Models\MeshBundle;
use App\Models\MeshNodeKey;
use App\Models\School;
use App\Services\MeshMediaAssembler;
use App\Services\MeshSeal;
use App\Services\MeshSignature;
use Illuminate\Database\UniqueConstraintViolationException;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Log;

/**
 * Point d'entrée internet du réseau maillé (store-and-forward).
 *
 * Le premier nœud connecté uploade ici le batch de bundles qu'il transporte
 * (les siens + ceux relayés). Déduplication par bundle_id, contrôle TTL /
 * max_hops, puis triage IA normal avec source = 'mesh'.
 */
class WashMeshController extends Controller
{
    public const BATCH_MAX = 100;

    public const ORIGIN_NODE_MAX = 64;

    public const SCHOOL_CODE_MAX = 32;

    public const MESSAGE_MAX = 5000;

    public const CHANNELS = ['text', 'voice', 'photo'];

    public const CHANNEL_DEFAULT = 'text';

    public const HOPS_MAX = 21;

    public const HOP_ID_MAX = 64;

    public const MAX_HOPS_MIN = 1;

    public const MAX_HOPS_MAX = 20;

    public const CHECKSUM_MAX = 128;

    public const EID_MAX = 128;

    public const LIFETIME_MIN_SECONDS = 60;

    public const LIFETIME_MAX_SECONDS = 2592000;

    public const COPIES_MIN = 1;

    public const COPIES_MAX = 64;

    public const COPIES_DEFAULT = 8;

    public const FRAGMENT_OFFSET_MAX = 199;

    public const FRAGMENT_TOTAL_MIN = 1;

    public const FRAGMENT_TOTAL_MAX = 200;

    public const PRIORITIES = ['normal', 'high', 'alert'];

    public const PRIORITY_DEFAULT = 'normal';

    public const SIGNATURE_MAX = 128;

    public const NODE_PUBKEY_MAX = 64;

    public const SEALED_MAX = 20000;

    public const SEALED_ALG_MAX = 32;

    public const BUNDLE_GROUP_MAX = 64;

    public const CHUNK_MAX = 65536;

    public const MEDIA_MIMES = ['image/jpeg', 'image/png', 'image/webp', 'audio/webm', 'audio/mp4', 'audio/ogg', 'audio/mpeg'];

    public const MEDIA_SIZE_MIN = 1;

    public const MEDIA_SIZE_MAX = 2097152;

    public const MEDIA_SHA256_MAX = 128;

    /**
     * Ingère un bundle unique ou un batch { bundles: [...] }.
     */
    public function store(Request $request, IncidentTriage $triage)
    {
        $ingestKey = (string) config('services.mesh.ingest_key');
        if ($ingestKey !== '' && ! hash_equals($ingestKey, (string) $request->header('X-Mesh-Key'))) {
            return response()->json(['message' => 'Clé mesh manquante ou invalide.'], 401);
        }

        $incoming = $request->has('bundles')
            ? $request->validate(['bundles' => ['required', 'array', 'max:' . self::BATCH_MAX]])['bundles']
            : [$request->validate($this->rules())];

        // Validation unitaire quand c'est un batch (chaque item suit les mêmes règles).
        if ($request->has('bundles')) {
            foreach ($incoming as $i => $item) {
                validator($item, $this->rules())->validate();
                $incoming[$i] = $item;
            }
        }

        $summary = ['accepted' => 0, 'duplicates' => 0, 'expired' => 0, 'rejected' => 0, 'quota_exceeded' => 0, 'fragments' => 0, 'key_changed' => 0];
        $incidents = [];
        $assembler = app(MeshMediaAssembler::class);

        foreach ($incoming as $item) {
            // Déduplication globale : même bundle reçu via deux relais = un seul traitement.
            if (MeshBundle::where('bundle_id', $item['bundle_id'])->exists()) {
                $summary['duplicates']++;
                continue;
            }

            // Quota journalier par nœud d'origine (anti-spam).
            $cap = (int) config('services.mesh.daily_cap_per_origin', 500);
            if (MeshBundle::where('origin_node_id', $item['origin_node_id'])->whereDate('created_at', today())->count() >= $cap) {
                Log::warning('mesh.bundle.rejected', ['bundle_id' => $item['bundle_id'], 'cause' => 'quota', 'origin' => $item['origin_node_id']]);
                $summary['quota_exceeded']++;
                continue;
            }

            $hops = $item['hops'] ?? [$item['origin_node_id']];
            $hopCount = max(0, count($hops) - 1);
            $maxHops = (int) ($item['max_hops'] ?? config('wash.mesh.default_max_hops'));

            if ($hopCount > $maxHops) {
                Log::warning('mesh.bundle.rejected', ['bundle_id' => $item['bundle_id'], 'cause' => 'max_hops', 'hop_count' => $hopCount]);
                $summary['rejected']++;
                continue;
            }

            // V2 signatures : non-signés acceptés, signés-invalides rejetés.
            // Avant le déchiffrement sealed (qui remplace `message`).
            // Ne vérifie que l'upload direct (le relai reformate les bundles).
            $signatureVerified = false;
            if (! empty($item['signature'])) {
                $tsShape = $item;
                unset($tsShape['received_via_node_id'], $tsShape['previous_node_id']);
                foreach (['destination_eid' => 'destination', 'report_to_eid' => 'report_to'] as $from => $to) {
                    if (array_key_exists($from, $tsShape)) {
                        $tsShape[$to] = $tsShape[$from];
                        unset($tsShape[$from]);
                    }
                }
                if (! MeshSignature::verify($tsShape)) {
                    Log::warning('mesh.bundle.rejected', ['bundle_id' => $item['bundle_id'], 'cause' => 'bad_signature', 'origin' => $item['origin_node_id']]);
                    $summary['rejected']++;
                    continue;
                }
                $signatureVerified = true;
            }

            // V2 E2E : enveloppe scellée → déchiffrement (le serveur est le
            // destinataire ; les relais n'ont vu que les métadonnées).
            if (! empty($item['sealed'])) {
                $message = MeshSeal::open((string) $item['sealed'], $item['sealed_alg'] ?? null);
                if ($message === null) {
                    Log::warning('mesh.bundle.rejected', ['bundle_id' => $item['bundle_id'], 'cause' => 'unseal_failed']);
                    $summary['rejected']++;
                    continue;
                }
                $item['message'] = $message;
            }

            // lifetime (durée) préféré à expires_at absolu : les horloges
            // villageoises ne sont pas fiables, le serveur dérive l'expiration.
            $lifetime = isset($item['lifetime_seconds']) ? (int) $item['lifetime_seconds'] : null;
            $expiresAt = $lifetime !== null
                ? now()->addSeconds($lifetime)
                : (isset($item['expires_at']) ? now()->parse($item['expires_at']) : now()->addDays(config('wash.mesh.default_ttl_days')));
            if ($expiresAt->isPast()) {
                MeshBundle::create($this->attributes($item, $hops, $hopCount, $maxHops, $expiresAt, 'expired'));
                $summary['expired']++;
                continue;
            }

            // V2b médias : manifeste (triage immédiat, média différé) vs fragment
            // (stocké, assemblé quand le groupe est complet).
            $isFragment = ! empty($item['bundle_group']) && isset($item['fragment_offset'], $item['chunk']);
            $isManifest = isset($item['fragment_total']) && empty($item['chunk']) && empty($item['bundle_group']);
            $mixesMediaKeys = ! empty($item['bundle_group']) || isset($item['fragment_offset'], $item['chunk']) || isset($item['fragment_total']);
            if ($mixesMediaKeys && ! $isFragment && ! $isManifest) {
                Log::warning('mesh.bundle.rejected', ['bundle_id' => $item['bundle_id'], 'cause' => 'malformed_fragment']);
                $summary['rejected']++;
                continue;
            }
            if ($isManifest && empty($item['message'])) {
                Log::warning('mesh.bundle.rejected', ['bundle_id' => $item['bundle_id'], 'cause' => 'manifest_without_message']);
                $summary['rejected']++;
                continue;
            }

            $school = School::find($item['school_id']);

            if ($isFragment) {
                try {
                    $record = MeshBundle::create(
                        $this->attributes($item, $hops, $hopCount, $maxHops, $expiresAt, 'pending')
                    );
                } catch (UniqueConstraintViolationException) {
                    $summary['duplicates']++;
                    continue;
                }
                $summary['fragments']++;
                $assembler->tryAssemble((string) $item['bundle_group']);
                continue;
            }

            try {
                $bundle = DB::transaction(function () use ($item, $hops, $hopCount, $maxHops, $expiresAt, $school, $triage, $request) {
                    $record = MeshBundle::create(
                        $this->attributes($item, $hops, $hopCount, $maxHops, $expiresAt, 'delivered')
                    );

                    // Triage IA standard : le mesh ne court-circuite jamais le pipeline.
                    $result = $triage->ingest(
                        $school,
                        $item['channel'] ?? self::CHANNEL_DEFAULT,
                        $item['message'] ?? null,
                        null,
                        null,
                        $request->user(),
                        'mesh',
                    );

                    $record->update([
                        'report_id' => $result['report']->id,
                        'delivered_at' => now(),
                    ]);

                    return ['bundle' => $record, 'incident' => $result['incident']];
                });
            } catch (UniqueConstraintViolationException) {
                // Course entre le test d'existence et l'insert : c'est un doublon.
                $summary['duplicates']++;
                continue;
            }

            if ($isManifest) {
                // Les fragments ont pu arriver avant le manifeste.
                $assembler->tryAssemble($bundle['bundle']->bundle_id);
            }

            // TOFU node_pubkey : mémorisé sur signature VÉRIFIÉE uniquement,
            // jamais sur rejet. La première clé vue devient la référence ;
            // un changement est une ALERTE (log + compteur), pas un rejet :
            // refuser couperait un nœud légitime qui a régénéré sa clé.
            if ($signatureVerified) {
                $known = MeshNodeKey::where('origin_node_id', $item['origin_node_id'])->first();
                if ($known === null) {
                    MeshNodeKey::create([
                        'origin_node_id' => $item['origin_node_id'],
                        'node_pubkey' => $item['node_pubkey'],
                        'first_seen_at' => now(),
                    ]);
                } elseif ($known->node_pubkey !== $item['node_pubkey']) {
                    Log::warning('mesh.node.key_changed', [
                        'bundle_id' => $item['bundle_id'],
                        'origin' => $item['origin_node_id'],
                    ]);
                    $known->update([
                        'node_pubkey' => $item['node_pubkey'],
                        'last_changed_at' => now(),
                    ]);
                    $summary['key_changed']++;
                }
            }

            Log::info('mesh.bundle.accepted', [
                'bundle_id' => $bundle['bundle']->bundle_id,
                'origin' => $item['origin_node_id'],
                'hop_count' => $hopCount,
            ]);

            $summary['accepted']++;
            $incidents[] = [
                'bundle_id' => $bundle['bundle']->bundle_id,
                'incident_id' => $bundle['incident']->id,
                'reference_code' => $bundle['incident']->reference_code ?? null,
                'hop_count' => $hopCount,
            ];
        }

        return response()->json([
            'message' => "Lot mesh traité : {$summary['accepted']} accepté(s), {$summary['duplicates']} doublon(s).",
            'summary' => $summary,
            'incidents' => $incidents,
        ], 201);
    }

    public function pending(Request $request)
    {
        $query = MeshBundle::with(['school:id,name,district'])
            ->where('status', 'pending')
            ->latest();

        return response()->json($query->paginate(min(config('wash.pagination.max'), (int) $request->get('per_page', config('wash.pagination.default')))));
    }

    public function show(string $bundleId)
    {
        $bundle = MeshBundle::where('bundle_id', $bundleId)->with(['school', 'report'])->firstOrFail();

        return response()->json($bundle);
    }

    public function stats()
    {
        return response()->json([
            'total' => MeshBundle::count(),
            'by_status' => MeshBundle::select('status', DB::raw('count(*) as n'))->groupBy('status')->pluck('n', 'status'),
            'avg_hops' => round((float) MeshBundle::avg('hop_count'), 2),
            'relayed_share' => MeshBundle::count() > 0
                ? round(MeshBundle::where('hop_count', '>', 0)->count() / MeshBundle::count(), 3)
                : 0,
            'origins' => MeshBundle::distinct('origin_node_id')->count('origin_node_id'),
            'sealed_share' => MeshBundle::count() > 0
                ? round(MeshBundle::whereNotNull('sealed_payload')->count() / MeshBundle::count(), 3)
                : 0,
        ]);
    }

    /**
     * Clé publique E2E du serveur (libsodium sealed box).
     * 503 si non configurée : les clients retombent en clair (avertis).
     */
    public function publicKey()
    {
        $public = MeshSeal::publicKeyB64();
        if ($public === null) {
            return response()->json(['message' => 'Chiffrement mesh non configuré.'], 503);
        }

        return response()->json(['algorithm' => MeshSeal::ALG, 'public_key' => $public]);
    }

    /** @return array<string, mixed> */
    private function rules(): array
    {
        return [
            'bundle_id' => ['required', 'uuid'],
            'origin_node_id' => ['required', 'string', 'max:' . self::ORIGIN_NODE_MAX],
            'school_id' => ['required', 'exists:schools,id'],
            'school_code' => ['nullable', 'string', 'max:' . self::SCHOOL_CODE_MAX],
            'message' => ['nullable', 'string', 'max:' . self::MESSAGE_MAX],
            'channel' => ['nullable', 'in:' . implode(',', self::CHANNELS)],
            'hops' => ['nullable', 'array', 'max:' . self::HOPS_MAX],
            'hops.*' => ['string', 'max:' . self::HOP_ID_MAX],
            'max_hops' => ['nullable', 'integer', 'min:' . self::MAX_HOPS_MIN, 'max:' . self::MAX_HOPS_MAX],
            'created_at' => ['nullable', 'date'],
            'expires_at' => ['nullable', 'date'],
            'received_via_node_id' => ['nullable', 'string', 'max:' . self::ORIGIN_NODE_MAX],
            'checksum' => ['nullable', 'string', 'max:' . self::CHECKSUM_MAX],
            // v1.1 additive (tous optionnels, défauts serveur).
            'destination_eid' => ['nullable', 'string', 'max:' . self::EID_MAX],
            'report_to_eid' => ['nullable', 'string', 'max:' . self::EID_MAX],
            'lifetime_seconds' => ['nullable', 'integer', 'min:' . self::LIFETIME_MIN_SECONDS, 'max:' . self::LIFETIME_MAX_SECONDS],
            'previous_node_id' => ['nullable', 'string', 'max:' . self::ORIGIN_NODE_MAX],
            'copies_remaining' => ['nullable', 'integer', 'min:' . self::COPIES_MIN, 'max:' . self::COPIES_MAX],
            'fragment_offset' => ['nullable', 'integer', 'min:0', 'max:' . self::FRAGMENT_OFFSET_MAX],
            'fragment_total' => ['nullable', 'integer', 'min:' . self::FRAGMENT_TOTAL_MIN, 'max:' . self::FRAGMENT_TOTAL_MAX],
            'custody_requested' => ['nullable', 'boolean'],
            'priority' => ['nullable', 'in:' . implode(',', self::PRIORITIES)],
            'signature' => ['nullable', 'string', 'max:' . self::SIGNATURE_MAX],
            'node_pubkey' => ['nullable', 'string', 'max:' . self::NODE_PUBKEY_MAX],
            'v' => ['nullable', 'integer'],
            'sealed' => ['nullable', 'string', 'max:' . self::SEALED_MAX],
            'sealed_alg' => ['nullable', 'string', 'max:' . self::SEALED_ALG_MAX],
            // V2b médias différés.
            'bundle_group' => ['nullable', 'string', 'max:' . self::BUNDLE_GROUP_MAX],
            'chunk' => ['nullable', 'string', 'max:' . self::CHUNK_MAX],
            'media_mime' => ['nullable', 'in:' . implode(',', self::MEDIA_MIMES)],
            'media_size' => ['nullable', 'integer', 'min:' . self::MEDIA_SIZE_MIN, 'max:' . self::MEDIA_SIZE_MAX],
            'media_sha256' => ['nullable', 'string', 'max:' . self::MEDIA_SHA256_MAX],
            'media_sealed_alg' => ['nullable', 'string', 'max:' . self::SEALED_ALG_MAX],
        ];
    }

    /** @param array<string, mixed> $item */
    private function attributes(array $item, array $hops, int $hopCount, int $maxHops, $expiresAt, string $status): array
    {
        return [
            'bundle_id' => $item['bundle_id'],
            'bundle_group' => $item['bundle_group'] ?? null,
            'origin_node_id' => $item['origin_node_id'],
            'school_id' => $item['school_id'],
            'school_code' => $item['school_code'] ?? null,
            'channel' => $item['channel'] ?? self::CHANNEL_DEFAULT,
            'message' => $item['message'] ?? null,
            'payload' => $item,
            'hops' => $hops,
            'hop_count' => $hopCount,
            'max_hops' => $maxHops,
            'received_via_node_id' => $item['received_via_node_id'] ?? end($hops) ?: null,
            'status' => $status,
            'expires_at' => $expiresAt,
            'destination_eid' => $item['destination_eid'] ?? config('wash.mesh.default_destination_eid'),
            'report_to_eid' => $item['report_to_eid'] ?? null,
            'lifetime_seconds' => isset($item['lifetime_seconds']) ? (int) $item['lifetime_seconds'] : null,
            'previous_node_id' => $item['previous_node_id'] ?? (count($hops) >= 2 ? $hops[count($hops) - 2] : null),
            'copies_remaining' => (int) ($item['copies_remaining'] ?? self::COPIES_DEFAULT),
            'fragment_offset' => $item['fragment_offset'] ?? null,
            'fragment_total' => $item['fragment_total'] ?? null,
            'custody_requested' => (bool) ($item['custody_requested'] ?? false),
            'priority' => $item['priority'] ?? self::PRIORITY_DEFAULT,
            'signature' => $item['signature'] ?? null,
            'node_pubkey' => $item['node_pubkey'] ?? null,
            'sealed_payload' => $item['sealed'] ?? null,
            'sealed_alg' => $item['sealed_alg'] ?? null,
        ];
    }
}
