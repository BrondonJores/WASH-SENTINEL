<?php

namespace App\Contracts;

interface WhatsAppClient
{
    /** Vérifie la signature X-Hub-Signature-256 du webhook Meta. */
    public function verifySignature(string $rawBody, ?string $signature): bool;

    /** Normalise un payload webhook en liste de messages exploitables. */
    public function parseWebhook(array $payload): array;

    /** Télécharge un média Meta. Retourne ['bytes', 'mime', 'filename']. */
    public function downloadMedia(string $mediaId): array;

    /** Envoie un message texte. Retourne la réponse Meta. */
    public function sendText(string $to, string $message): array;
}
