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
     * LOT 7 — valeurs en dur extraites (inchangées). Les clés payload
     * (fragment_total, fragment_offset, chunk, media_*) sont le CONTRAT
     * avec les clients mesh : ne jamais les renommer sans portage
     * coordonné (SDK TS, appli terrain).
     */
    /** Plafond de fragments par groupe média (garde-fou). */
    public const MAX_FRAGMENTS = 200;

    /** MIME supposé quand le manifeste n'en annonce aucun. */
    public const DEFAULT_MIME = 'application/octet-stream';

    /** Extension de repli pour un MIME inconnu. */
    public const DEFAULT_EXT = 'bin';

    /** Préfixe MIME des photos (sinon : fichier audio). */
    public const IMAGE_MIME_PREFIX = 'image/';

    /** Dossiers de stockage (disque 'public', comme les reports). */
    public const PHOTO_DIR = 'reports/photos/';

    public const AUDIO_DIR = 'reports/audio/';

    /** Préfixe du nom de fichier assemblé (suffixe : groupId + ext). */
    public const FILE_PREFIX = 'mesh-';

    /** Statut posé sur les fragments une fois le média attaché. */
    public const STATUS_DELIVERED = 'delivered';

    /** Clés payload du protocole fragments (contrat client, voir ci-dessus). */
    public const FIELD_FRAGMENT_TOTAL = 'fragment_total';

    public const FIELD_FRAGMENT_OFFSET = 'fragment_offset';

    public const FIELD_CHUNK = 'chunk';

    public const FIELD_MEDIA_SEALED_ALG = 'media_sealed_alg';

    public const FIELD_MEDIA_SHA256 = 'media_sha256';

    public const FIELD_MEDIA_MIME = 'media_mime';

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
        $total = (int) ($meta[self::FIELD_FRAGMENT_TOTAL] ?? 0);
        if ($total < 1 || $total > self::MAX_FRAGMENTS) {
            return null;
        }

        $fragments = MeshBundle::where('bundle_group', $groupId)
            ->whereNotNull('payload->'.self::FIELD_FRAGMENT_OFFSET)
            ->orderBy('fragment_offset')
            ->get();
        $offsets = $fragments->map(fn ($f) => $f->payload[self::FIELD_FRAGMENT_OFFSET] ?? null)
            ->filter(fn ($o) => is_int($o))->unique()->values();
        if ($offsets->count() !== $total || $offsets->min() !== 0 || $offsets->max() !== $total - 1) {
            return null; // incomplet
        }

        $chunks = [];
        foreach ($fragments as $fragment) {
            $chunks[$fragment->payload[self::FIELD_FRAGMENT_OFFSET]] = $fragment->payload[self::FIELD_CHUNK] ?? '';
        }
        ksort($chunks);
        $joined = implode('', $chunks);

        if (($meta[self::FIELD_MEDIA_SEALED_ALG] ?? null) !== null) {
            $joined = MeshSeal::open($joined, $meta[self::FIELD_MEDIA_SEALED_ALG]);
            if ($joined === null) {
                Log::warning('mesh.media.rejected', ['group' => $groupId, 'cause' => 'unseal_failed']);

                return null;
            }
        }

        if (! hash_equals((string) ($meta[self::FIELD_MEDIA_SHA256] ?? ''), hash('sha256', $joined))) {
            Log::warning('mesh.media.rejected', ['group' => $groupId, 'cause' => 'hash_mismatch']);

            return null;
        }

        $bytes = base64_decode($joined, true);
        if ($bytes === false) {
            return null;
        }

        $mime = (string) ($meta[self::FIELD_MEDIA_MIME] ?? self::DEFAULT_MIME);
        $ext = self::EXT_BY_MIME[$mime] ?? self::DEFAULT_EXT;
        $isPhoto = str_starts_with($mime, self::IMAGE_MIME_PREFIX);
        $path = ($isPhoto ? self::PHOTO_DIR : self::AUDIO_DIR).self::FILE_PREFIX."{$groupId}.{$ext}";
        Storage::disk('public')->put($path, $bytes);

        $report->update($isPhoto ? ['photo_path' => $path] : ['audio_path' => $path]);
        $fragments->each(fn ($f) => $f->update(['status' => self::STATUS_DELIVERED, 'report_id' => $report->id]));

        Log::info('mesh.media.attached', ['group' => $groupId, 'path' => $path, 'bytes' => strlen($bytes)]);

        return $manifest->refresh();
    }

    private function isManifest(MeshBundle $bundle): bool
    {
        return isset($bundle->payload[self::FIELD_FRAGMENT_TOTAL])
            && ! isset($bundle->payload[self::FIELD_CHUNK])
            && $bundle->bundle_group === null;
    }
}
