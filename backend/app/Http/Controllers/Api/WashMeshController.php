<?php

namespace App\Http\Controllers\Api;

use App\Contracts\IncidentTriage;
use App\Http\Controllers\Controller;
use App\Models\MeshBundle;
use App\Models\School;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

/**
 * Point d'entrée internet du réseau maillé (store-and-forward).
 *
 * Le premier nœud connecté uploade ici le batch de bundles qu'il transporte
 * (les siens + ceux relayés). Déduplication par bundle_id, contrôle TTL /
 * max_hops, puis triage IA normal avec source = 'mesh'.
 */
class WashMeshController extends Controller
{
    /**
     * Ingère un bundle unique ou un batch { bundles: [...] }.
     */
    public function store(Request $request, IncidentTriage $triage)
    {
        $incoming = $request->has('bundles')
            ? $request->validate(['bundles' => ['required', 'array', 'max:100']])['bundles']
            : [$request->validate($this->rules())];

        // Validation unitaire quand c'est un batch (chaque item suit les mêmes règles).
        if ($request->has('bundles')) {
            foreach ($incoming as $i => $item) {
                validator($item, $this->rules())->validate();
                $incoming[$i] = $item;
            }
        }

        $summary = ['accepted' => 0, 'duplicates' => 0, 'expired' => 0, 'rejected' => 0];
        $incidents = [];

        foreach ($incoming as $item) {
            // Déduplication globale : même bundle reçu via deux relais = un seul traitement.
            if (MeshBundle::where('bundle_id', $item['bundle_id'])->exists()) {
                $summary['duplicates']++;
                continue;
            }

            $hops = $item['hops'] ?? [$item['origin_node_id']];
            $hopCount = max(0, count($hops) - 1);
            $maxHops = (int) ($item['max_hops'] ?? 10);

            if ($hopCount > $maxHops) {
                $summary['rejected']++;
                continue;
            }

            $expiresAt = isset($item['expires_at']) ? now()->parse($item['expires_at']) : now()->addDays(7);
            if ($expiresAt->isPast()) {
                MeshBundle::create($this->attributes($item, $hops, $hopCount, $maxHops, $expiresAt, 'expired'));
                $summary['expired']++;
                continue;
            }

            $school = School::find($item['school_id']);

            $bundle = DB::transaction(function () use ($item, $hops, $hopCount, $maxHops, $expiresAt, $school, $triage, $request) {
                $record = MeshBundle::create(
                    $this->attributes($item, $hops, $hopCount, $maxHops, $expiresAt, 'delivered')
                );

                // Triage IA standard : le mesh ne court-circuite jamais le pipeline.
                $result = $triage->ingest(
                    $school,
                    'text',
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

        return response()->json($query->paginate(min(100, (int) $request->get('per_page', 20))));
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
        ]);
    }

    /** @return array<string, mixed> */
    private function rules(): array
    {
        return [
            'bundle_id' => ['required', 'uuid'],
            'origin_node_id' => ['required', 'string', 'max:64'],
            'school_id' => ['required', 'exists:schools,id'],
            'school_code' => ['nullable', 'string', 'max:32'],
            'message' => ['nullable', 'string', 'max:5000'],
            'channel' => ['nullable', 'in:text,voice,photo'],
            'hops' => ['nullable', 'array', 'max:21'],
            'hops.*' => ['string', 'max:64'],
            'max_hops' => ['nullable', 'integer', 'min:1', 'max:20'],
            'created_at' => ['nullable', 'date'],
            'expires_at' => ['nullable', 'date'],
            'received_via_node_id' => ['nullable', 'string', 'max:64'],
            'checksum' => ['nullable', 'string', 'max:64'],
        ];
    }

    /** @param array<string, mixed> $item */
    private function attributes(array $item, array $hops, int $hopCount, int $maxHops, $expiresAt, string $status): array
    {
        return [
            'bundle_id' => $item['bundle_id'],
            'origin_node_id' => $item['origin_node_id'],
            'school_id' => $item['school_id'],
            'school_code' => $item['school_code'] ?? null,
            'channel' => $item['channel'] ?? 'text',
            'message' => $item['message'] ?? null,
            'payload' => $item,
            'hops' => $hops,
            'hop_count' => $hopCount,
            'max_hops' => $maxHops,
            'received_via_node_id' => $item['received_via_node_id'] ?? end($hops) ?: null,
            'status' => $status,
            'expires_at' => $expiresAt,
        ];
    }
}
