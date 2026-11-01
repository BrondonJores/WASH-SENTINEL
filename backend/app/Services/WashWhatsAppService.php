<?php

namespace App\Services;

use App\Contracts\IncidentTriage;
use App\Contracts\WhatsAppClient;
use App\Models\Incident;
use App\Models\SchoolContact;
use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Str;

class WashWhatsAppService
{
    /** Longueur max d'une réponse WhatsApp (ton SMS). */
    protected const MAX_REPLY_LENGTH = 397;

    /** Indices eau/hygiène : un texte sans aucun est traité comme hors-sujet. */
    protected const WASH_KEYWORDS = [
        'eau', 'robinet', 'fuite', 'fuit', 'fuir', 'coul', 'goutt', 'pompe',
        'forage', 'puits', 'château', 'chateau', 'citerne', 'réservoir', 'reservoir',
        'pression', 'coupure', 'panne', 'cassé', 'cassée', 'casse', 'répar', 'repar',
        'plomb', 'tuyau', 'toilette', 'latrine', 'wc', 'douche', 'urinoir', 'chasse',
        'savon', 'lavage', 'lave-main', 'lave main', 'mains', 'hygiène', 'hygiene',
        'assainissement', 'égout', 'egout', 'évacuation', 'evacuation', 'canalisation',
        'bouch', 'débord', 'debord', 'vidange', 'fosse', 'septique', 'odeur',
        'puanteur', 'inond', 'flaque', 'mare', 'boue', 'mouche', 'moustique',
        'choléra', 'cholera', 'diarrh', 'malade', 'sanitaire', 'drainage',
        'soif', 'boire', 'fontaine', 'seau', 'javel', 'désinfect', 'desinfect',
    ];

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
                $this->safeReply(
                    $message['from'] ?? '',
                    'Oups, un problème technique nous empêche de traiter votre message. Réessayez dans quelques minutes, merci !'
                );
                $results[] = ['status' => 'error', 'from' => $message['from'] ?? null];
            }
        }

        return $results;
    }

    protected function handleMessage(array $message): array
    {
        $from = $message['from'] ?? '';
        $text = $message['text'] ?? null;
        $contact = SchoolContact::where('phone', SchoolContact::normalizePhone($from))->first();

        if (!$contact) {
            $this->reply($from, $this->unknownSchoolReply($text));

            return ['status' => 'unknown_contact', 'from' => $from];
        }

        $audio = $photo = null;
        $channel = 'text';

        if (($message['type'] ?? '') === 'audio' && ($message['media_id'] ?? null)) {
            $media = $this->safeDownload($message['media_id']);
            if (!$media) {
                $this->reply($from, "On n'a pas compris votre note vocale. Réenregistrez au calme, près du micro : dites votre école + la panne (ex. robinet cassé au bloc A). Merci !");

                return ['status' => 'unreadable_audio', 'from' => $from];
            }
            $audio = $this->toUploadedFile($media);
            $channel = 'voice';
        } elseif (($message['type'] ?? '') === 'image' && ($message['media_id'] ?? null)) {
            $media = $this->safeDownload($message['media_id']);
            if (!$media) {
                $this->reply($from, "La photo n'est pas arrivée jusqu'à nous. Renvoyez-la avec une phrase : école + panne (ex. fuite au bloc A). Merci !");

                return ['status' => 'unreadable_photo', 'from' => $from];
            }
            $photo = $this->toUploadedFile($media);
            $channel = 'photo';
        }

        if (!$text && !$audio && !$photo) {
            $this->reply($from, $this->offTopicReply());

            return ['status' => 'unsupported', 'from' => $from];
        }

        // Texte sans aucun indice eau/hygiène : hors-sujet guidé, sans incident.
        if ($channel === 'text' && !$this->looksLikeWashReport((string) $text)) {
            $this->reply($from, $this->offTopicReply());

            return ['status' => 'off_topic', 'from' => $from];
        }

        $result = $this->triage->ingest($contact->school, $channel, $text, $audio, $photo, null, 'whatsapp');
        $incident = $result['incident'];

        $this->reply($from, $result['is_duplicate']
            ? "Déjà reçu ! Incident {$incident->reference_code} suivi par nos équipes. Merci, pas besoin de renvoyer. On vous tient au courant ici."
            : $this->createdReply($incident));

        return [
            'status' => 'triaged',
            'from' => $from,
            'incident_id' => $incident->id,
            'is_duplicate' => $result['is_duplicate'],
        ];
    }

    protected function unknownSchoolReply(?string $text): string
    {
        if ($text && preg_match('/^\s*ECOLE\s+(.+?)\s*$/iu', $text, $m)) {
            $school = Str::limit(trim($m[1]), 60);

            return "Merci ! On a bien noté « {$school} ». Mais ce numéro n'est rattaché à aucune école pour l'instant : demandez au directeur de l'enregistrer, puis réécrivez-nous.";
        }

        return "Bonjour ! Ce numéro n'est rattaché à aucune école WASH Sentinel. De quelle école parlez-vous ? Envoyez : ECOLE Nom de votre école. On vous aidera à l'enregistrer.";
    }

    protected function offTopicReply(): string
    {
        return "Merci pour votre message ! Ici on signale l'eau et l'hygiène à l'école : ex. robinet qui fuit, toilettes bouchées, plus de savon. Décrivez votre panne en une phrase.";
    }

    protected function createdReply(Incident $incident): string
    {
        $summary = Str::limit((string) ($incident->ai_summary ?: $incident->title), 140);
        $urgency = ['low' => 'basse', 'medium' => 'moyenne', 'high' => 'haute', 'critical' => 'critique'][$incident->urgency]
            ?? $incident->urgency;

        return "Merci ! Incident {$incident->reference_code} enregistré : {$summary}. Priorité {$urgency}. La suite : notre équipe est notifiée, on vous écrit ici dès que ça avance.";
    }

    protected function looksLikeWashReport(string $text): bool
    {
        $lower = mb_strtolower($text);
        foreach (self::WASH_KEYWORDS as $keyword) {
            if (str_contains($lower, $keyword)) {
                return true;
            }
        }

        return false;
    }

    protected function safeDownload(string $mediaId): ?array
    {
        try {
            $media = $this->client->downloadMedia($mediaId);
        } catch (\Throwable $e) {
            Log::warning('WhatsApp media download failed: ' . $e->getMessage());

            return null;
        }

        return ($media['bytes'] ?? '') === '' ? null : $media;
    }

    /** Envoie une réponse (tronquée au format SMS), via simulateur ou live selon le client. */
    protected function reply(string $to, string $message): void
    {
        $this->client->sendText($to, Str::limit($message, self::MAX_REPLY_LENGTH, '…'));
    }

    protected function safeReply(string $to, string $message): void
    {
        if ($to === '') {
            return;
        }
        try {
            $this->reply($to, $message);
        } catch (\Throwable $e) {
            Log::warning('WhatsApp fallback reply failed: ' . $e->getMessage());
        }
    }

    protected function toUploadedFile(array $media): UploadedFile
    {
        $path = tempnam(sys_get_temp_dir(), 'wash-wa-');
        file_put_contents($path, $media['bytes']);

        return new UploadedFile($path, $media['filename'], $media['mime'], null, true);
    }
}
