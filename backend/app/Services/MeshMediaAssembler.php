<?php

namespace App\Services;

use App\Models\MeshBundle;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Facades\Storage;

/**
 * V2b médias différés : réassemble les fragments d'un groupe dès qu'il est
 * complet (chiffre-puis-découpe : on concatène, on ouvre l'enveloppe si
 * scellée, on vérifie le sha256, on stocke et on attache au signalement).
 *
 * Le manifeste crée l'incident immédiatement (texte en clair ou scellé) ;
 * le média s'y attache quand tous les fragments sont arrivés — y compris
 * dans le désordre, et même si le manifeste arrive en dernier.
 */
class MeshMediaAssembler
{
    public const EXT_BY_MIME = [
        'image/jpeg' => 'jpg',
        'image/png' => 'png',
        'image/webp' => 'webp',
        'audio/webm' => 'webm',
        'audio/mp4' => 'm4a',
        'audio/ogg' => 'ogg',
        'audio/mpeg' => 'mp3',
    ];

    /**
     * Tente l'assemblage du groupe. Retourne le manifeste complété, ou null
     * (groupe incomplet, déjà attaché, ou média corrompu — les fragments
     * sont conservés pour réessai).
     */
    public function tryAssemble(string $groupId): ?MeshBundle
    {
        $manifest = MeshBundle::where('bundle_id', $groupId)->first();
        if (! $manifest || ! $this->isManifest($manifest)) {
            return null;
        }
        $report = $manifest->report;
        if (! $report || $report->photo_path || $report->audio_path) {
            return null; // déjà attaché (idempotent)
        }

        $meta = $manifest->payload;
        $total = (int) ($meta['fragment_total'] ?? 0);
        if ($total < 1 || $total > 200) {
            return null;
        }

        $fragments = MeshBundle::where('bundle_group', $groupId)
            ->whereNotNull('payload->fragment_offset')
            ->orderBy('fragment_offset')
            ->get();
        $offsets = $fragments->map(fn ($f) => $f->payload['fragment_offset'] ?? null)
            ->filter(fn ($o) => is_int($o))->unique()->values();
        if ($offsets->count() !== $total || $offsets->min() !== 0 || $offsets->max() !== $total - 1) {
            return null; // incomplet
        }

        $chunks = [];
        foreach ($fragments as $fragment) {
            $chunks[$fragment->payload['fragment_offset']] = $fragment->payload['chunk'] ?? '';
        }
        ksort($chunks);
        $joined = implode('', $chunks);

        if (($meta['media_sealed_alg'] ?? null) !== null) {
            $joined = MeshSeal::open($joined, $meta['media_sealed_alg']);
            if ($joined === null) {
                Log::warning('mesh.media.rejected', ['group' => $groupId, 'cause' => 'unseal_failed']);

                return null;
            }
        }

        if (! hash_equals((string) ($meta['media_sha256'] ?? ''), hash('sha256', $joined))) {
            Log::warning('mesh.media.rejected', ['group' => $groupId, 'cause' => 'hash_mismatch']);

            return null;
        }

        $bytes = base64_decode($joined, true);
        if ($bytes === false) {
            return null;
        }

        $mime = (string) ($meta['media_mime'] ?? 'application/octet-stream');
        $ext = self::EXT_BY_MIME[$mime] ?? 'bin';
        $isPhoto = str_starts_with($mime, 'image/');
        $path = ($isPhoto ? 'reports/photos/' : 'reports/audio/')."mesh-{$groupId}.{$ext}";
        Storage::disk('public')->put($path, $bytes);

        $report->update($isPhoto ? ['photo_path' => $path] : ['audio_path' => $path]);
        $fragments->each(fn ($f) => $f->update(['status' => 'delivered', 'report_id' => $report->id]));

        Log::info('mesh.media.attached', ['group' => $groupId, 'path' => $path, 'bytes' => strlen($bytes)]);

        return $manifest->refresh();
    }

    private function isManifest(MeshBundle $bundle): bool
    {
        return isset($bundle->payload['fragment_total'])
            && ! isset($bundle->payload['chunk'])
            && $bundle->bundle_group === null;
    }
}
