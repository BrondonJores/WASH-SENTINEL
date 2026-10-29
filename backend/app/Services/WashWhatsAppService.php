<?php

namespace App\Services;

use App\Contracts\IncidentTriage;
use App\Contracts\WhatsAppClient;
use App\Models\SchoolContact;
use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\Log;

class WashWhatsAppService
{
    public function __construct(
        protected WhatsAppClient $client,
        protected IncidentTriage $triage,
    ) {}

    public function verifySignature(string $rawBody, ?string $signature): bool
    {
        return $this->client->verifySignature($rawBody, $signature);
    }

    public function handlePayload(array $payload): array
    {
        $results = [];
        foreach ($this->client->parseWebhook($payload) as $message) {
            try {
                $results[] = $this->handleMessage($message);
            } catch (\Throwable $e) {
                Log::warning('WhatsApp message failed: ' . $e->getMessage());
                $results[] = ['status' => 'error', 'from' => $message['from'] ?? null];
            }
        }

        return $results;
    }

    protected function handleMessage(array $message): array
    {
        $from = $message['from'] ?? '';
        $contact = SchoolContact::where('phone', SchoolContact::normalizePhone($from))->first();

        if (!$contact) {
            $this->client->sendText($from, "Bonjour ! Ce numéro n'est rattaché à aucune école WASH Sentinel. Demandez à votre directeur d'enregistrer ce numéro pour signaler une panne.");

            return ['status' => 'unknown_contact', 'from' => $from];
        }

        $audio = $photo = null;
        $text = $message['text'] ?? null;
        $channel = 'text';

        if ($message['type'] === 'audio' && $message['media_id']) {
            $media = $this->client->downloadMedia($message['media_id']);
            if ($media['bytes'] === '') {
                return ['status' => 'empty_media', 'from' => $from];
            }
            $audio = $this->toUploadedFile($media);
            $channel = 'voice';
        } elseif ($message['type'] === 'image' && $message['media_id']) {
            $media = $this->client->downloadMedia($message['media_id']);
            if ($media['bytes'] === '') {
                return ['status' => 'empty_media', 'from' => $from];
            }
            $photo = $this->toUploadedFile($media);
            $channel = 'photo';
        }

        if (!$text && !$audio && !$photo) {
            return ['status' => 'unsupported', 'from' => $from];
        }

        $result = $this->triage->ingest($contact->school, $channel, $text, $audio, $photo, null, 'whatsapp');
        $incident = $result['incident'];

        $reply = $result['is_duplicate']
            ? "WASH Sentinel : signalement rattaché à l'incident {$incident->reference_code} (priorité {$incident->urgency}, {$incident->priority_score}/100)."
            : "WASH Sentinel : incident {$incident->reference_code} enregistré en priorité {$incident->urgency} ({$incident->priority_score}/100). Une équipe a été notifiée.";
        $this->client->sendText($from, $reply);

        return [
            'status' => 'triaged',
            'from' => $from,
            'incident_id' => $incident->id,
            'is_duplicate' => $result['is_duplicate'],
        ];
    }

    protected function toUploadedFile(array $media): UploadedFile
    {
        $path = tempnam(sys_get_temp_dir(), 'wash-wa-');
        file_put_contents($path, $media['bytes']);

        return new UploadedFile($path, $media['filename'], $media['mime'], null, true);
    }
}
