<?php

namespace App\Services;

use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Storage;
use Illuminate\Support\Str;
use Illuminate\Validation\ValidationException;

/**
 * Persistance des affiches du dossier décideur (cartes `poster` moteur).
 *
 * Contrat moteur : {image_base64|image_url, prompt, caption}. Le base64 est
 * décodé, validé puis stocké sur le disque public ; l'URL absolue http(s)
 * remplace le base64 dans la carte (converse réécrit, jamais de 500).
 */
class DossierPosterService
{
    /** Poids max de l'image décodée (5 Mo). */
    public const MAX_BYTES = 5242880;

    /** Timeout de téléchargement d'une image distante (secondes). */
    public const DOWNLOAD_TIMEOUT_SECONDS = 20;

    /** Dossier de stockage sur le disque public. */
    public const DIRECTORY = 'reports/posters';

    /** Mimes acceptés => extension. */
    public const ALLOWED_MIMES = [
        'image/jpeg' => 'jpg',
        'image/png' => 'png',
        'image/webp' => 'webp',
    ];

    public const MESSAGE_TOO_HEAVY = "L'affiche générée est trop lourde (5 Mo maximum) : demandez une nouvelle affiche plus légère.";

    public const MESSAGE_BAD_MIME = "L'affiche reçue n'est pas une image lisible : seuls les formats JPEG, PNG ou WebP sont acceptés.";

    public const MESSAGE_MISSING = "Aucune image d'affiche à enregistrer : demandez une nouvelle affiche.";

    public const MESSAGE_DOWNLOAD_FAILED = "L'affiche distante n'a pas pu être récupérée : réessayez dans un instant ou demandez une nouvelle affiche.";

    /**
     * Persiste l'affiche et retourne son URL absolue http(s).
     *
     * @throws ValidationException Guidage FR (422) si absente, trop lourde, illisible ou non récupérée.
     */
    public function persistPoster(?string $imageBase64, ?string $imageUrl, string $slug): string
    {
        if (is_string($imageBase64) && trim($imageBase64) !== '') {
            $bytes = $this->decodeBase64($imageBase64);

            return $this->storeBytes($bytes, $slug);
        }

        if (is_string($imageUrl) && trim($imageUrl) !== '') {
            $bytes = $this->downloadRemote(trim($imageUrl));

            return $this->storeBytes($bytes, $slug);
        }

        throw $this->guidance(self::MESSAGE_MISSING);
    }

    /**
     * Nom déterministe : slug + hash du contenu (pas de doublon sur disque).
     */
    public function posterFilename(string $slug, string $bytes, string $extension): string
    {
        $clean = Str::slug($slug);
        if ($clean === '') {
            $clean = 'affiche';
        }

        return $clean . '-' . substr(sha1($bytes), 0, 12) . '.' . $extension;
    }

    protected function decodeBase64(string $raw): string
    {
        $clean = trim($raw);
        if (str_contains($clean, ',')) {
            // Préfixe data URI éventuel (data:image/png;base64,...).
            $clean = (string) substr($clean, (int) strpos($clean, ',') + 1);
        }
        $clean = preg_replace('/\s+/', '', $clean) ?? '';
        $bytes = base64_decode($clean, true);
        if ($bytes === false || $bytes === '') {
            throw $this->guidance(self::MESSAGE_BAD_MIME);
        }

        return $bytes;
    }

    protected function downloadRemote(string $url): string
    {
        if (!str_starts_with($url, 'http://') && !str_starts_with($url, 'https://')) {
            throw $this->guidance(self::MESSAGE_DOWNLOAD_FAILED);
        }
        try {
            $response = Http::timeout(self::DOWNLOAD_TIMEOUT_SECONDS)->get($url);
        } catch (\Throwable) {
            throw $this->guidance(self::MESSAGE_DOWNLOAD_FAILED);
        }
        if (!$response->successful()) {
            throw $this->guidance(self::MESSAGE_DOWNLOAD_FAILED);
        }
        $bytes = (string) $response->body();
        if ($bytes === '') {
            throw $this->guidance(self::MESSAGE_DOWNLOAD_FAILED);
        }

        return $bytes;
    }

    protected function storeBytes(string $bytes, string $slug): string
    {
        if (strlen($bytes) > self::MAX_BYTES) {
            throw $this->guidance(self::MESSAGE_TOO_HEAVY);
        }
        $mime = $this->detectMime($bytes);
        if (!isset(self::ALLOWED_MIMES[$mime])) {
            throw $this->guidance(self::MESSAGE_BAD_MIME);
        }
        $path = self::DIRECTORY . '/' . $this->posterFilename($slug, $bytes, self::ALLOWED_MIMES[$mime]);
        if (!Storage::disk('public')->exists($path)) {
            Storage::disk('public')->put($path, $bytes);
        }

        return $this->absoluteUrl($path);
    }

    protected function detectMime(string $bytes): string
    {
        if (class_exists(\finfo::class)) {
            $mime = (string) (new \finfo(FILEINFO_MIME_TYPE))->buffer($bytes);
            if ($mime !== '') {
                return $mime;
            }
        }
        $info = @getimagesizefromstring($bytes);

        return is_array($info) && isset($info['mime']) ? (string) $info['mime'] : '';
    }

    protected function absoluteUrl(string $path): string
    {
        $url = Storage::disk('public')->url($path);
        if (str_starts_with($url, '/')) {
            $url = rtrim((string) config('app.url'), '/') . $url;
        }

        return $url;
    }

    protected function guidance(string $message): ValidationException
    {
        return ValidationException::withMessages(['poster' => [$message]]);
    }
}
