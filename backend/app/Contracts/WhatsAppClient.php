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

    /**
     * Envoie un message interactif à boutons (confirmation Oui/Non).
     * $buttons = [['id' => 'wash_oui', 'title' => 'Oui'], ...] (max 3).
     * Free-form : uniquement sous 24h après le dernier message usager.
     */
    public function sendInteractiveButtons(string $to, string $body, array $buttons): array;

    /** Téléverse des octets média chez Meta. Retourne le media id. */
    public function uploadMedia(string $bytes, string $mime, ?string $filename = null): string;

    /** Envoie une note vocale / audio déjà téléversé (media id). */
    public function sendAudio(string $to, string $mediaId): array;

    /**
     * Envoie un TEMPLATE approuvé (obligatoire hors fenêtre 24h, erreur
     * Meta 131047 sinon). $bodyParams remplit les {{1}}, {{2}}... du corps.
     */
    public function sendTemplate(string $to, string $template, string $language, array $bodyParams = []): array;
}
