<?php

namespace App\Services;

use App\Contracts\AiEngineClient;
use App\Contracts\IncidentTriage;
use App\Contracts\WhatsAppClient;
use App\Models\Incident;
use App\Models\Report;
use App\Models\School;
use App\Models\SchoolContact;
use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Str;

/*
 * CANAL 2 — WhatsApp vocal de bout en bout.
 *
 * Flow vocal (note vocale entrante) :
 *   1. téléchargement du média via Graph API (MetaWhatsAppService::downloadMedia)
 *   2. transcription explicite via le profil STT ACTIF (langue = default_language
 *      de l'école : fr, dua_Latn, bassa, ewondo — le header X-STT-Language du
 *      profil est repris en repli quand l'école n'a pas de langue)
 *   3. triage/extraction via IncidentTriageService (canal "voice")
 *   4. réponse FR simple : récap texte + boutons interactifs Oui/Non
 *      + note vocale TTS de confirmation (best-effort)
 *   5. clic Oui -> incident confirmé ; clic Non -> UNE question courte,
 *      la clarification suivante est RATTACHÉE à l'incident pending
 *      (jamais triée en neuf : ni « Déjà reçu », ni hors-sujet),
 *      puis re-confirmation Oui/Non.
 *
 * RÈGLE META DES 24H : tout message free-form (texte, boutons, audio) n'est
 * accepté que sous 24h après le DERNIER message de l'usager. Nos réponses
 * directes au webhook sont toujours dans la fenêtre (quelques secondes).
 * Hors fenêtre (relance proactive), il faut un TEMPLATE approuvé côté Meta
 * (voir sendFollowup() + docs/WHATSAPP_BRANCHEMENT.md § templates).
 * Le clic Oui/Non compte comme message usager et ROUVRE 24h.
 */
class WashWhatsAppService
{
    /** Longueur max d'une réponse WhatsApp (ton SMS). */
    protected const MAX_REPLY_LENGTH = 397;

    /** TTL (secondes) de la marque « message déjà vu » : 48h > fenêtre retry Meta. */
    protected const SEEN_TTL = 172800;

    /** Plafond média par défaut (octets) si la config est absente/invalide : 10 Mo. */
    protected const DEFAULT_MAX_MEDIA_BYTES = 10485760;

    /** Ids stables des boutons de confirmation (reçus dans button_reply.id). */
    public const BUTTON_YES = 'wash_oui';

    public const BUTTON_NO = 'wash_non';

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
        protected ?AiEngineClient $ai = null,
    ) {}

    public function verifySignature(string $rawBody, ?string $signature): bool
    {
        return $this->client->verifySignature($rawBody, $signature);
    }

    public function handlePayload(array $payload): array
    {
        $results = [];
        foreach ($this->client->parseWebhook($payload) as $message) {
            // Idempotence relivraisons Meta : même wamid = déjà traité.
            // Cache::add atomique : un seul traitement gagne en cas de doublon.
            $wamid = $this->wamidOf($message);
            if ($wamid !== '' && !Cache::add($this->seenKey($wamid), now()->toIso8601String(), self::SEEN_TTL)) {
                $results[] = ['status' => 'duplicate_delivery', 'from' => $message['from'] ?? null, 'wamid' => $wamid];
                continue;
            }
            // Chaque message usager (reçu) rouvre la fenêtre free-form de 24h.
            $this->stampUserMessage($message['from'] ?? '');
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

        // Clic sur un bouton interactif (Oui/Non) : pas de triage, juste la suite.
        if (($message['type'] ?? '') === 'interactive') {
            return $this->handleButtonClick($from, (string) ($message['button_id'] ?? ''));
        }

        $audio = $photo = null;
        $channel = 'text';

        if (($message['type'] ?? '') === 'audio' && ($message['media_id'] ?? null)) {
            $download = $this->downloadMediaChecked($message['media_id']);
            if ($download['outcome'] === 'oversized') {
                $this->reply($from, $this->oversizedAudioReply());

                return ['status' => 'oversized_media', 'from' => $from];
            }
            $media = $download['media'];
            if (!$media) {
                $this->reply($from, "On n'a pas compris votre note vocale. Réenregistrez au calme, près du micro : dites votre école + la panne (ex. robinet cassé au bloc A). Merci !");

                return ['status' => 'unreadable_audio', 'from' => $from];
            }
            $audio = $this->toUploadedFile($media);
            $channel = 'voice';
            // Transcription explicite (profil STT actif + langue locale de l'école).
            // En cas d'échec on garde l'audio seul : le triage fera sa propre STT.
            $transcript = $this->transcribeVoice($audio, $contact->school->default_language ?? null);
            if (is_string($transcript) && $transcript !== '') {
                $text = $transcript;
            }
        } elseif (($message['type'] ?? '') === 'image' && ($message['media_id'] ?? null)) {
            $download = $this->downloadMediaChecked($message['media_id']);
            if ($download['outcome'] === 'oversized') {
                $this->reply($from, $this->oversizedPhotoReply());

                return ['status' => 'oversized_media', 'from' => $from];
            }
            $media = $download['media'];
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

        // Clarification en attente (après Non) : lue AVANT le filtre hors-sujet
        // et AVANT le triage. Une correction ne doit JAMAIS partir en hors-sujet
        // (même sans mot-clé eau/hygiène) ni en doublon « Déjà reçu ».
        $staleClarification = false;
        if (($channel === 'text' || $channel === 'voice') && ($text || $audio)) {
            $clarifyIncidentId = Cache::get($this->clarifyKey($from));
            if ($clarifyIncidentId) {
                $pendingIncident = Incident::find($clarifyIncidentId);
                if ($pendingIncident) {
                    return $this->applyClarification($from, $contact->school, $pendingIncident, $channel, $text, $audio, $photo);
                }
                // Incident pending disparu (supprimé) : repli triage normal + note FR.
                // (Clé expirée/silence = plus rien en cache : triage normal pur.)
                $this->forgetClarification($from);
                $staleClarification = true;
            }
        }

        // Texte sans aucun indice eau/hygiène : hors-sujet guidé, sans incident.
        if ($channel === 'text' && !$this->looksLikeWashReport((string) $text)) {
            $this->forgetClarification($from);
            $this->reply($from, $this->offTopicReply());

            return ['status' => 'off_topic', 'from' => $from];
        }

        // Plus de clarification en attente à ce stade : message normal.
        $this->forgetClarification($from);

        $result = $this->triage->ingest($contact->school, $channel, $text, $audio, $photo, null, 'whatsapp');
        $incident = $result['incident'];
        $staleNote = $staleClarification ? $this->staleClarificationNote() : '';

        if ($result['is_duplicate']) {
            $this->reply($from, $staleNote . "Déjà reçu ! Incident {$incident->reference_code} suivi par nos équipes. Merci, pas besoin de renvoyer. On vous tient au courant ici.");

            return [
                'status' => 'triaged',
                'from' => $from,
                'incident_id' => $incident->id,
                'is_duplicate' => true,
            ];
        }

        // Flow vocal : récap texte + boutons Oui/Non + note vocale TTS.
        if ($channel === 'voice' && (bool) config('whatsapp.voice_confirmation', true)) {
            $this->reply($from, $staleNote . $this->createdReply($incident));
            $this->rememberPending($from, $incident);
            $this->sendConfirmationButtons($from);
            $this->sendVoiceConfirmation($from, $incident);

            return [
                'status' => 'triaged_pending_confirmation',
                'from' => $from,
                'incident_id' => $incident->id,
                'is_duplicate' => false,
            ];
        }

        $this->reply($from, $staleNote . $this->createdReply($incident));

        return [
            'status' => 'triaged',
            'from' => $from,
            'incident_id' => $incident->id,
            'is_duplicate' => $result['is_duplicate'],
        ];
    }

    /** Clic Oui/Non : Oui confirme l'incident, Non repose UNE question courte. */
    protected function handleButtonClick(string $from, string $buttonId): array
    {
        if ($buttonId === self::BUTTON_YES) {
            return $this->confirmPending($from);
        }

        if ($buttonId === self::BUTTON_NO) {
            return $this->askClarification($from);
        }

        $this->reply($from, $this->offTopicReply());

        return ['status' => 'unsupported_button', 'from' => $from];
    }

    protected function confirmPending(string $from): array
    {
        $pending = $this->pending($from);
        $this->forgetPending($from);
        $this->forgetClarification($from);

        $incident = $pending ? Incident::find($pending['incident_id'] ?? null) : null;
        if (!$incident) {
            $this->reply($from, 'Merci ! Votre signalement est bien enregistré. Pour un autre problème, envoyez une note vocale ou décrivez-le en une phrase.');

            return ['status' => 'confirmed_stale', 'from' => $from];
        }

        $tags = $incident->ai_tags ?? [];
        if (!in_array('confirme-usager', $tags, true)) {
            $tags[] = 'confirme-usager';
            $incident->update(['ai_tags' => $tags]);
        }

        $this->reply($from, "Parfait, c'est confirmé ! Incident {$incident->reference_code} suivi par nos équipes. On vous écrit ici dès que ça avance.");

        return ['status' => 'confirmed', 'from' => $from, 'incident_id' => $incident->id];
    }

    protected function askClarification(string $from): array
    {
        $pending = $this->pending($from);
        $this->forgetPending($from);
        if ($pending && isset($pending['incident_id'])) {
            Cache::put($this->clarifyKey($from), $pending['incident_id'], 86400);
        }

        // UNE seule question courte : la réponse suivante (texte/vocal)
        // corrigera l'incident pending (applyClarification), pas un triage neuf.
        $this->reply($from, 'Désolé ! Que dois-je corriger ? Répondez en une phrase : quoi + où.');

        return ['status' => 'clarification_asked', 'from' => $from];
    }

    /**
     * Correction après Non : rattachée à l'incident pending, JAMAIS triée en neuf.
     * IncidentTriageService::ingest n'offre aucun override pour forcer l'incident
     * (applyOverrides ne gère que category/urgency/affected_students), donc on suit
     * ses patterns via les modèles : Report lié (is_duplicate=false) + résumé à jour.
     * Re-confirmation : boutons Oui/Non renvoyés, pending + clarification conservés.
     */
    protected function applyClarification(string $from, School $school, Incident $incident, string $channel, ?string $text, ?UploadedFile $audio, ?UploadedFile $photo): array
    {
        $correction = trim((string) $text);
        $rawText = $correction !== '' ? $correction : '[message vocal]';
        $audioPath = $audio ? $audio->store('reports/audio', 'public') : null;
        $photoPath = $photo ? $photo->store('reports/photos', 'public') : null;

        Report::create([
            'school_id' => $school->id,
            'incident_id' => $incident->id,
            'channel' => $channel,
            'source' => 'whatsapp',
            'raw_content' => $rawText,
            'audio_path' => $audioPath,
            'photo_path' => $photoPath,
            'is_duplicate' => false,
            'raw_ai_extraction' => ['clarification_of_incident_id' => $incident->id],
        ]);

        if ($correction !== '') {
            $incident->update([
                'title' => Str::limit($correction, 120, '…'),
                'ai_summary' => Str::limit($correction, 200, '…'),
            ]);
        }
        $incident = $incident->fresh() ?? $incident;

        // Re-confirmation : pending conservé + clarification conservée + boutons.
        $this->rememberPending($from, $incident);
        Cache::put($this->clarifyKey($from), $incident->id, 86400);
        $summary = Str::limit((string) ($incident->ai_summary ?: $incident->title), 140);
        $this->reply($from, "Merci ! J'ai corrigé : {$summary}. C'est bien ça ?");
        $this->sendConfirmationButtons($from);
        Log::info("WhatsApp clarification applied to incident {$incident->id}.", ['from' => $from]);

        return ['status' => 'clarification_applied', 'from' => $from, 'incident_id' => $incident->id, 'is_duplicate' => false];
    }

    protected function staleClarificationNote(): string
    {
        return "Je n'ai pas retrouvé votre signalement précédent, je traite votre message comme un nouveau signalement. ";
    }

    protected function sendConfirmationButtons(string $to): void
    {
        try {
            $this->client->sendInteractiveButtons($to, "C'est bien ça ? Touchez Oui ou Non.", [
                ['id' => self::BUTTON_YES, 'title' => 'Oui'],
                ['id' => self::BUTTON_NO, 'title' => 'Non'],
            ]);
        } catch (\Throwable $e) {
            Log::warning('WhatsApp buttons failed: ' . $e->getMessage());
        }
    }

    /** Note vocale TTS de confirmation (best-effort : jamais bloquante). */
    protected function sendVoiceConfirmation(string $to, Incident $incident): void
    {
        if (!(bool) config('whatsapp.voice_note', true) || !$this->ai) {
            return;
        }
        try {
            $summary = Str::limit((string) ($incident->ai_summary ?: $incident->title), 140);
            $tts = $this->ai->synthesize(
                "Merci ! Incident {$incident->reference_code} enregistré : {$summary}. On vous tient au courant.",
                (string) config('whatsapp.tts_voice', 'fr_FR-upmc-medium'),
                'fr'
            );
            $base64 = $tts['audio_base64'] ?? null;
            if (!is_string($base64) || $base64 === '') {
                return;
            }
            $mediaId = $this->client->uploadMedia(
                (string) base64_decode($base64),
                (string) ($tts['mime_type'] ?? 'audio/wav'),
                'confirmation.wav'
            );
            if ($mediaId !== '') {
                $this->client->sendAudio($to, $mediaId);
            }
        } catch (\Throwable $e) {
            Log::info('WhatsApp voice note skipped: ' . $e->getMessage());
        }
    }

    /**
     * Transcription explicite via le profil STT actif.
     * $language = langue locale de l'école (fr, dua_Latn, bassa, ewondo...) :
     * le moteur applique requête > profil > fr. Retourne null en cas d'échec
     * (le triage retentera sa propre STT sur l'audio).
     */
    protected function transcribeVoice(UploadedFile $audio, ?string $language): ?string
    {
        if (!$this->ai) {
            return null;
        }
        try {
            $result = $this->ai->transcribe($audio->getRealPath(), $language ?: null);
            $transcript = trim((string) ($result['transcript'] ?? ''));
        } catch (\Throwable $e) {
            Log::info('WhatsApp transcribe fallback to triage STT: ' . $e->getMessage());

            return null;
        }

        return $transcript === '' ? null : $transcript;
    }

    // ------------------------------------------------------------------
    // Idempotence relivraisons Meta (même wamid livré 2+ fois).
    // ------------------------------------------------------------------

    /** Id Meta (wamid) d'un message normalisé, '' si absent (pas de dédup possible). */
    protected function wamidOf(array $message): string
    {
        $wamid = $message['wamid'] ?? $message['message_id'] ?? '';

        return is_string($wamid) ? $wamid : '';
    }

    protected function seenKey(string $wamid): string
    {
        return 'wash.whatsapp.seen.' . $wamid;
    }

    /**
     * True si TOUS les messages du payload sont des relivraisons déjà vues.
     * Utilisé par le contrôleur pour accuser réception sans ré-enfiler le job
     * (ni triage, ni envoi) ; last_webhook_at reste mis à jour dans tous les cas.
     */
    public function isDuplicateDelivery(array $payload): bool
    {
        $messages = $this->client->parseWebhook($payload);
        if ($messages === []) {
            return false;
        }
        foreach ($messages as $message) {
            $wamid = $this->wamidOf($message);
            if ($wamid === '' || !Cache::has($this->seenKey($wamid))) {
                return false;
            }
        }

        return true;
    }

    // ------------------------------------------------------------------
    // Fenêtre free-form 24h (voir entête de classe).
    // ------------------------------------------------------------------

    protected function lastUserMessageKey(string $from): string
    {
        return 'wash.whatsapp.last_user_msg_at.' . SchoolContact::normalizePhone($from);
    }

    protected function stampUserMessage(string $from): void
    {
        if ($from === '') {
            return;
        }
        Cache::put($this->lastUserMessageKey($from), now()->toIso8601String(), 172800);
    }

    /** True si on peut envoyer du free-form (fenêtre 24h ouverte). */
    public function isWithinFreeformWindow(string $phone): bool
    {
        $at = Cache::get($this->lastUserMessageKey($phone));
        if (!$at) {
            return false;
        }

        try {
            return now()->diffInHours($at, true) < 24;
        } catch (\Throwable) {
            return false;
        }
    }

    /**
     * Envoi hors webhook (relance proactive) : free-form sous 24h, sinon
     * TEMPLATE approuvé (Meta refuse le free-form hors fenêtre, erreur 131047).
     */
    public function sendFollowup(string $to, string $message): array
    {
        if ($this->isWithinFreeformWindow($to)) {
            return ['via' => 'text', 'response' => $this->client->sendText($to, $message)];
        }

        return ['via' => 'template', 'response' => $this->client->sendTemplate(
            $to,
            (string) config('whatsapp.confirmation_template', 'wash_confirmation'),
            (string) config('whatsapp.confirmation_language', 'fr'),
            [Str::limit($message, 200)]
        )];
    }

    // ------------------------------------------------------------------
    // Confirmation en attente (Oui/Non) + clarification.
    // ------------------------------------------------------------------

    protected function pendingKey(string $from): string
    {
        return 'wash.whatsapp.pending.' . SchoolContact::normalizePhone($from);
    }

    protected function clarifyKey(string $from): string
    {
        return 'wash.whatsapp.clarify.' . SchoolContact::normalizePhone($from);
    }

    protected function rememberPending(string $from, Incident $incident): void
    {
        Cache::put($this->pendingKey($from), [
            'incident_id' => $incident->id,
            'reference' => $incident->reference_code,
            'summary' => (string) ($incident->ai_summary ?: $incident->title),
        ], (int) config('whatsapp.pending_ttl', 86400));
    }

    protected function pending(string $from): ?array
    {
        $pending = Cache::get($this->pendingKey($from));

        return is_array($pending) ? $pending : null;
    }

    protected function forgetPending(string $from): void
    {
        Cache::forget($this->pendingKey($from));
    }

    protected function forgetClarification(string $from): void
    {
        Cache::forget($this->clarifyKey($from));
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

    protected function maxMediaBytes(): int
    {
        $max = (int) config('whatsapp.max_media_bytes', self::DEFAULT_MAX_MEDIA_BYTES);

        return $max > 0 ? $max : self::DEFAULT_MAX_MEDIA_BYTES;
    }

    /**
     * Télécharge un média en respectant le plafond whatsapp.max_media_bytes.
     * Retourne ['outcome' => 'ok'|'unreadable'|'oversized', 'media' => ?array].
     * 'oversized' : taille déclarée (métadonnées, quand dispo AVANT le corps)
     * ou corps reçu > plafond → RIEN n'est stocké (pas de fichier temp).
     */
    protected function downloadMediaChecked(string $mediaId): array
    {
        try {
            $media = $this->client->downloadMedia($mediaId);
        } catch (\Throwable $e) {
            Log::warning('WhatsApp media download failed: ' . $e->getMessage());

            return ['outcome' => 'unreadable', 'media' => null];
        }

        $max = $this->maxMediaBytes();

        // Taille déclarée par Meta (métadonnées, sans le corps) quand dispo :
        // rejet AVANT tout stockage.
        foreach (['file_size', 'size', 'content_length', 'content-length'] as $key) {
            if (isset($media[$key]) && (int) $media[$key] > $max) {
                Log::info("WhatsApp media oversized (declared {$key}): {$media[$key]} > {$max} bytes.", ['media_id' => $mediaId]);

                return ['outcome' => 'oversized', 'media' => null];
            }
        }

        $bytes = $media['bytes'] ?? '';
        if ($bytes === '') {
            return ['outcome' => 'unreadable', 'media' => null];
        }
        if (strlen($bytes) > $max) {
            Log::info('WhatsApp media oversized (body ' . strlen($bytes) . " > {$max} bytes), dropped before storage.", ['media_id' => $mediaId]);

            return ['outcome' => 'oversized', 'media' => null];
        }

        return ['outcome' => 'ok', 'media' => $media];
    }

    protected function safeDownload(string $mediaId): ?array
    {
        return $this->downloadMediaChecked($mediaId)['media'];
    }

    protected function oversizedAudioReply(): string
    {
        return 'Note trop lourde, renvoie plus court : réenregistre ta note vocale au calme, près du micro — école + panne en une phrase (ex. robinet cassé au bloc A). Merci !';
    }

    protected function oversizedPhotoReply(): string
    {
        return 'Photo trop lourde, renvoie une photo plus légère avec une phrase : école + panne (ex. fuite au bloc A). Merci !';
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
