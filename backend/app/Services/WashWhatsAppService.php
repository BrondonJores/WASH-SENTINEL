<?php

namespace App\Services;

use App\Contracts\AiEngineClient;
use App\Contracts\IncidentTriage;
use App\Contracts\WhatsAppClient;
use App\Models\Incident;
use App\Models\Report;
use App\Models\School;
use App\Models\SchoolContact;
use Carbon\Carbon;
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

    /**
     * TTL (secondes) des marques WhatsApp : « message déjà vu » (idempotence
     * relivraisons) et horodatage du dernier message usager : 48h, soit le
     * double de la fenêtre free-form, > fenêtre retry Meta. (LOT 7 : source
     * unique, remplace les 172800 bruts.)
     */
    protected const SEEN_TTL = 172800;

    /** Repli (secondes) de config whatsapp.pending_ttl : Oui/Non + clarification, 24h. */
    protected const DEFAULT_PENDING_TTL = 86400;

    /** Fenêtre free-form Meta (heures) après le dernier message usager. */
    protected const FREEFORM_WINDOW_HOURS = 24;

    /** Plafond média par défaut (octets) si la config est absente/invalide : 10 Mo. */
    protected const DEFAULT_MAX_MEDIA_BYTES = 10485760;

    /** Ids stables des boutons de confirmation (reçus dans button_reply.id). */
    public const BUTTON_YES = 'wash_oui';

    public const BUTTON_NO = 'wash_non';

    /** Référence explicite d'incident (ex. WASH-2026-RCLD5U) : intention suivi. */
    protected const SUIVI_REFERENCE_PATTERN = '/WASH-\d{4}-[A-Z0-9]{4,}/i';

    /** Déclaration d'école par un numéro inconnu : « ECOLE Nom… » (une ligne). */
    protected const UNKNOWN_SCHOOL_ECOLE_PATTERN = '/^\s*ECOLE\s+(.+?)\s*$/iu';

    /** Mots-clés d'intention suivi (FR + EN), testés AVANT le filtre hors-sujet. */
    protected const SUIVI_KEYWORDS = [
        'suivi', 'suivre', 'statut', 'status', 'où en est', 'ou en est',
        'mon signalement', 'mes signalements', 'mon dossier',
        'avancé', 'avance', 'réparé', 'reparé', 'répare', 'repare',
        'where is', 'my report', 'track', 'tracking',
        'follow up', 'follow-up', 'followup',
    ];

    /** Marqueurs FR : présents → fiche en français (prioritaire sur l'anglais). */
    protected const SUIVI_FRENCH_MARKERS = [
        'suivi', 'suivre', 'statut', 'où en est', 'ou en est',
        'mon signalement', 'mes signalements', 'mon dossier',
        'avancé', 'avance', 'réparé', 'reparé', 'répare', 'repare',
    ];

    /** Marqueurs uniquement-EN : présents (sans marqueur FR) → fiche en anglais. */
    protected const SUIVI_ENGLISH_MARKERS = [
        'where is', 'my report', 'track', 'tracking',
        'follow up', 'follow-up', 'followup',
    ];

    /**
     * Marqueurs EN génériques (signalement) : présents, SANS aucun marqueur FR
     * (SUIVI_FRENCH_MARKERS réutilisée en veto) → TOUTE la réponse en anglais.
     * Même pattern que le suivi, généralisé au flux de création. 'fr' par défaut.
     * Appariés par frontières de mot (containsMarker) : 'toilet' ≠ 'toilettes'.
     */
    protected const REPLY_ENGLISH_MARKERS = [
        'hello', 'good morning', 'good afternoon', 'good evening',
        'this is', 'thank', 'thanks', 'please', 'sorry',
        'school', 'pupil', 'pupils', 'student', 'students', 'teacher',
        'water', 'tap', 'taps', 'leak', 'leaks', 'leaking', 'leakage',
        'toilet', 'toilets', 'pipe', 'pipes', 'pump', 'borehole',
        'soap', 'drink', 'drinking', 'flush', 'tank',
        'block', 'blocks', 'broken', 'dirty', 'smell', 'shortage',
        'hygiene', 'sanitation', 'sewage',
    ];

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
        // Mêmes indices en anglais : un signalement texte EN doit passer le filtre.
        'water', 'tap', 'leak', 'toilet', 'pipe', 'pump', 'soap', 'drink',
        'sanitation', 'sewage', 'drain', 'borehole', 'tank', 'flush', 'well',
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
                $this->safeReply($message['from'] ?? '', $this->fr('whatsapp.error_technical'));
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
                $this->reply($from, $this->fr('whatsapp.unreadable_audio'));

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
                $this->reply($from, $this->fr('whatsapp.unreadable_photo'));

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
            $clarify = $this->clarify($from);
            if ($clarify) {
                $pendingIncident = Incident::find($clarify['incident_id']);
                if ($pendingIncident) {
                    return $this->applyClarification($from, $contact->school, $pendingIncident, $channel, $text, $audio, $photo, $clarify['lang'] === 'en');
                }
                // Incident pending disparu (supprimé) : repli triage normal + note FR.
                // (Clé expirée/silence = plus rien en cache : triage normal pur.)
                $this->forgetClarification($from);
                $staleClarification = true;
            }
        }

        // SUIVI : détecté AVANT le filtre hors-sujet et AVANT le triage, pour
        // texte ET vocal-transcrit. Ne crée JAMAIS d'incident ni de Report.
        // (La clarification en attente ci-dessus garde priorité : le suivi
        // attend le tour suivant.)
        if (($channel === 'text' || $channel === 'voice') && $text) {
            $suivi = $this->suiviIntent((string) $text);
            if ($suivi['is_suivi']) {
                return $this->handleSuivi($from, $contact, (string) $text, $suivi['reference']);
            }
        }

        // Texte sans aucun indice eau/hygiène : personnalité d'abord
        // (bonjour, qui es-tu...), sinon hors-sujet guidé, sans incident.
        if ($channel === 'text' && !$this->looksLikeWashReport((string) $text)) {
            $this->forgetClarification($from);
            $this->reply($from, $this->offTopicReply((string) $text));

            return ['status' => 'off_topic', 'from' => $from];
        }

        // Plus de clarification en attente à ce stade : message normal.
        $this->forgetClarification($from);

        $result = $this->triage->ingest($contact->school, $channel, $text, $audio, $photo, null, 'whatsapp');
        $incident = $result['incident'];
        // Langue de RÉPONSE depuis le texte usager (transcript vocal ou texte,
        // jamais language_effective STT : la requête force souvent fr).
        $english = is_string($text) && $text !== '' && $this->isEnglishReply($text);
        $staleNote = $staleClarification ? $this->staleClarificationNote($english) : '';

        if ($result['is_duplicate']) {
            $this->reply($from, $staleNote . $this->duplicateReply($incident, $english));

            return [
                'status' => 'triaged',
                'from' => $from,
                'incident_id' => $incident->id,
                'is_duplicate' => true,
            ];
        }

        // Flow vocal : récap texte + boutons Oui/Non + note vocale TTS.
        if ($channel === 'voice' && (bool) config('whatsapp.voice_confirmation', true)) {
            $this->reply($from, $staleNote . $this->createdReply($incident, $english));
            $this->rememberPending($from, $incident, $english);
            $this->sendConfirmationButtons($from, $english);
            $this->sendVoiceConfirmation($from, $incident, $english);

            return [
                'status' => 'triaged_pending_confirmation',
                'from' => $from,
                'incident_id' => $incident->id,
                'is_duplicate' => false,
            ];
        }

        $this->reply($from, $staleNote . $this->createdReply($incident, $english));

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
        $english = ($pending['lang'] ?? 'fr') === 'en';

        $incident = $pending ? Incident::find($pending['incident_id'] ?? null) : null;
        if (!$incident) {
            $this->reply($from, $this->t('whatsapp.confirmed_stale', $english));

            return ['status' => 'confirmed_stale', 'from' => $from];
        }

        $tags = $incident->ai_tags ?? [];
        if (!in_array('confirme-usager', $tags, true)) {
            $tags[] = 'confirme-usager';
            $incident->update(['ai_tags' => $tags]);
        }

        $this->reply($from, $this->t('whatsapp.confirmed', $english, ['ref' => $incident->reference_code]));

        return ['status' => 'confirmed', 'from' => $from, 'incident_id' => $incident->id];
    }

    protected function askClarification(string $from): array
    {
        $pending = $this->pending($from);
        $lang = $pending['lang'] ?? 'fr';
        $this->forgetPending($from);
        if ($pending && isset($pending['incident_id'])) {
            $this->rememberClarification($from, (int) $pending['incident_id'], $lang);
        }

        // UNE seule question courte : la réponse suivante (texte/vocal)
        // corrigera l'incident pending (applyClarification), pas un triage neuf.
        $this->reply($from, $this->t('whatsapp.clarify_ask', $lang === 'en'));

        return ['status' => 'clarification_asked', 'from' => $from];
    }

    /**
     * Correction après Non : rattachée à l'incident pending, JAMAIS triée en neuf.
     * IncidentTriageService::ingest n'offre aucun override pour forcer l'incident
     * (applyOverrides ne gère que category/urgency/affected_students), donc on suit
     * ses patterns via les modèles : Report lié (is_duplicate=false) + résumé à jour.
     * Re-confirmation : boutons Oui/Non renvoyés, pending + clarification conservés.
     */
    protected function applyClarification(string $from, School $school, Incident $incident, string $channel, ?string $text, ?UploadedFile $audio, ?UploadedFile $photo, bool $english = false): array
    {
        $correction = trim((string) $text);
        $rawText = $correction !== '' ? $correction : $this->fr('whatsapp.voice_placeholder');
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
        $this->rememberPending($from, $incident, $english);
        $this->rememberClarification($from, $incident->id, $english ? 'en' : 'fr');
        $summary = Str::limit((string) ($incident->ai_summary ?: $incident->title), 140);
        $this->reply($from, $this->t('whatsapp.clarify_applied', $english, ['summary' => $summary]));
        $this->sendConfirmationButtons($from, $english);
        Log::info("WhatsApp clarification applied to incident {$incident->id}.", ['from' => $from]);

        return ['status' => 'clarification_applied', 'from' => $from, 'incident_id' => $incident->id, 'is_duplicate' => false];
    }

    // ------------------------------------------------------------------
    // SUIVI d'incident (FR + EN) : fiche statut, zéro création.
    // ------------------------------------------------------------------

    /** Intention suivi : référence explicite WASH-… ou mot-clé FR/EN. */
    protected function suiviIntent(string $text): array
    {
        $reference = null;
        if (preg_match(self::SUIVI_REFERENCE_PATTERN, $text, $m)) {
            $reference = strtoupper($m[0]);
        }

        $lower = mb_strtolower($text);
        $hasKeyword = false;
        foreach (self::SUIVI_KEYWORDS as $keyword) {
            if (str_contains($lower, $keyword)) {
                $hasKeyword = true;
                break;
            }
        }

        return ['is_suivi' => $reference !== null || $hasKeyword, 'reference' => $reference];
    }

    /**
     * True si la réponse au signalement doit être en anglais : au moins un
     * marqueur EN générique, et AUCUN marqueur FR (veto, const réutilisée).
     * 'fr' par défaut. Ne dépend jamais de language_effective STT.
     */
    protected function isEnglishReply(string $text): bool
    {
        $lower = mb_strtolower($text);
        foreach (self::SUIVI_FRENCH_MARKERS as $marker) {
            if ($this->containsMarker($lower, $marker)) {
                return false;
            }
        }
        foreach (self::REPLY_ENGLISH_MARKERS as $marker) {
            if ($this->containsMarker($lower, $marker)) {
                return true;
            }
        }

        return false;
    }

    /** Marqueur borné par des frontières de mot (unicode) : 'tap' ≠ 'taper'. */
    protected function containsMarker(string $lower, string $marker): bool
    {
        return preg_match('/\b' . preg_quote(mb_strtolower($marker), '/') . '\b/iu', $lower) === 1;
    }

    /** True si le message de suivi est en anglais (marqueurs EN, aucun FR). */
    protected function isEnglishSuivi(string $text): bool
    {
        $lower = mb_strtolower($text);
        foreach (self::SUIVI_FRENCH_MARKERS as $marker) {
            if (str_contains($lower, $marker)) {
                return false;
            }
        }
        foreach (self::SUIVI_ENGLISH_MARKERS as $marker) {
            if (str_contains($lower, $marker)) {
                return true;
            }
        }

        return false;
    }

    /**
     * Fiche statut SMS (≤ MAX_REPLY_LENGTH via reply()). Avec référence :
     * incident par reference_code (école du contact d'abord, sinon global).
     * Sans référence : DERNIER incident de l'école du contact. Ne crée ni
     * incident ni Report ; statut retourné 'suivi'.
     */
    protected function handleSuivi(string $from, SchoolContact $contact, string $text, ?string $reference): array
    {
        $english = $this->isEnglishSuivi($text);

        if ($reference !== null) {
            $incident = Incident::where('school_id', $contact->school_id)
                ->whereRaw('UPPER(reference_code) = ?', [$reference])
                ->first()
                ?? Incident::whereRaw('UPPER(reference_code) = ?', [$reference])->first();

            if (!$incident) {
                $this->reply($from, $this->suiviUnknownReferenceReply($reference, $english));

                return ['status' => 'suivi', 'from' => $from, 'reference' => $reference];
            }

            $this->reply($from, $this->suiviStatusReply($incident, $english));

            return ['status' => 'suivi', 'from' => $from, 'incident_id' => $incident->id];
        }

        $incident = Incident::where('school_id', $contact->school_id)->latest('id')->first();
        if (!$incident) {
            $this->reply($from, $this->suiviEmptyReply($english));

            return ['status' => 'suivi', 'from' => $from];
        }

        $this->reply($from, $this->suiviStatusReply($incident, $english));

        return ['status' => 'suivi', 'from' => $from, 'incident_id' => $incident->id];
    }

    /** Fiche statut : référence + résumé court + statut humain + prochaine étape. */
    protected function suiviStatusReply(Incident $incident, bool $english): string
    {
        $summary = rtrim(Str::limit((string) ($incident->ai_summary ?: $incident->title), 90), '.');
        $terminal = in_array($incident->status, ['resolved', 'closed'], true);
        $since = $terminal ? '' : $this->t('whatsapp.suivi.since', $english, [
            'date' => $english
                ? $this->englishDay($incident->updated_at ?? now())
                : $this->frenchDay($incident->updated_at ?? now()),
        ]);

        return $this->t('whatsapp.suivi.card', $english, [
            'ref' => $incident->reference_code,
            'summary' => $summary,
            'human' => $this->statusHuman($incident->status, $english),
            'since' => $since,
            'next' => $this->statusNext($incident->status, $english),
        ]);
    }

    protected function suiviEmptyReply(bool $english): string
    {
        return $this->t('whatsapp.suivi.empty', $english);
    }

    protected function suiviUnknownReferenceReply(string $reference, bool $english): string
    {
        return $this->t('whatsapp.suivi.unknown_reference', $english, ['ref' => $reference]);
    }

    protected function staleClarificationNote(bool $english = false): string
    {
        return $this->t('whatsapp.stale_note', $english);
    }

    protected function sendConfirmationButtons(string $to, bool $english = false): void
    {
        try {
            // Ids wash_oui/wash_non INCHANGÉS (contrat button_reply.id), seuls les titres changent.
            $this->client->sendInteractiveButtons($to, $this->t('whatsapp.buttons_body', $english), [
                ['id' => self::BUTTON_YES, 'title' => $this->t('whatsapp.button_yes', $english)],
                ['id' => self::BUTTON_NO, 'title' => $this->t('whatsapp.button_no', $english)],
            ]);
        } catch (\Throwable $e) {
            Log::warning('WhatsApp buttons failed: ' . $e->getMessage());
        }
    }

    /** Note vocale TTS de confirmation (best-effort : jamais bloquante). */
    protected function sendVoiceConfirmation(string $to, Incident $incident, bool $english = false): void
    {
        if (!(bool) config('whatsapp.voice_note', true) || !$this->ai) {
            return;
        }
        try {
            $summary = Str::limit((string) ($incident->ai_summary ?: $incident->title), 140);
            $text = $this->t('whatsapp.tts_confirm', $english, [
                'ref' => $incident->reference_code,
                'summary' => $summary,
            ]);
            // EN : voix 'en-medium' = registre ai-engine (BUILTIN_VOICE_REGISTRY['en']),
            // servie en MMS eng quand le moteur tourne avec TTS_DRIVER=mms.
            $tts = $english
                ? $this->ai->synthesize($text, (string) config('whatsapp.tts_voice_en', 'en-medium'), 'en')
                : $this->ai->synthesize($text, (string) config('whatsapp.tts_voice', 'fr_FR-upmc-medium'), 'fr');
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
        Cache::put($this->lastUserMessageKey($from), now()->toIso8601String(), self::SEEN_TTL);
    }

    /** True si on peut envoyer du free-form (fenêtre 24h ouverte). */
    public function isWithinFreeformWindow(string $phone): bool
    {
        $at = Cache::get($this->lastUserMessageKey($phone));
        if (!$at) {
            return false;
        }

        try {
            return now()->diffInHours($at, true) < self::FREEFORM_WINDOW_HOURS;
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

    protected function rememberPending(string $from, Incident $incident, bool $english = false): void
    {
        Cache::put($this->pendingKey($from), [
            'incident_id' => $incident->id,
            'reference' => $incident->reference_code,
            'summary' => (string) ($incident->ai_summary ?: $incident->title),
            'lang' => $english ? 'en' : 'fr',
        ], (int) config('whatsapp.pending_ttl', self::DEFAULT_PENDING_TTL));
    }

    /** Clarification en attente + langue persistée (Oui/Non/correction restent EN). */
    protected function rememberClarification(string $from, int $incidentId, string $lang): void
    {
        Cache::put($this->clarifyKey($from), [
            'incident_id' => $incidentId,
            'lang' => $lang === 'en' ? 'en' : 'fr',
        ], (int) config('whatsapp.pending_ttl', self::DEFAULT_PENDING_TTL));
    }

    /** Lecture normalisée : tableau neuf, ou id brut (legacy) → lang 'fr'. */
    protected function clarify(string $from): ?array
    {
        $raw = Cache::get($this->clarifyKey($from));
        if (is_array($raw) && isset($raw['incident_id'])) {
            return ['incident_id' => (int) $raw['incident_id'], 'lang' => ($raw['lang'] ?? 'fr') === 'en' ? 'en' : 'fr'];
        }
        if (is_int($raw) || (is_string($raw) && ctype_digit($raw))) {
            return ['incident_id' => (int) $raw, 'lang' => 'fr'];
        }

        return null;
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

    // ------------------------------------------------------------------
    // LOT 7 — textes lang/{fr,en}/wash.php (extraction pure, locale forcée,
    // textes octet-identiques aux littéraux d'origine).
    // ------------------------------------------------------------------

    /** Réponse FR/EN selon la langue détectée ($english). */
    protected function t(string $key, bool $english, array $replace = []): string
    {
        return trans('wash.'.$key, $replace, $english ? 'en' : 'fr');
    }

    /** Texte FR-only (comportement inchangé : pas de variante EN). */
    protected function fr(string $key, array $replace = []): string
    {
        return trans('wash.'.$key, $replace, 'fr');
    }

    /** Libellé statut lisible, repli code brut si statut inconnu (inchangé). */
    protected function statusHuman(string $status, bool $english): string
    {
        $label = $this->t('whatsapp.suivi.status.'.$status, $english);

        return $label === 'wash.whatsapp.suivi.status.'.$status ? $status : $label;
    }

    /** Prochaine étape lisible, repli générique si statut inconnu (inchangé). */
    protected function statusNext(string $status, bool $english): string
    {
        $label = $this->t('whatsapp.suivi.next.'.$status, $english);

        return $label === 'wash.whatsapp.suivi.next.'.$status
            ? $this->t('whatsapp.suivi.next_fallback', $english)
            : $label;
    }

    /** Priorité inline, repli code brut si urgence inconnue (inchangé). */
    protected function urgencyLabel(?string $urgency, bool $english): string
    {
        if ($urgency === null || $urgency === '') {
            // Origine : FR interpole vide (?? $incident->urgency), EN force 'medium'.
            return $english ? 'medium' : (string) $urgency;
        }
        $label = $this->t('whatsapp.urgency.'.$urgency, $english);

        return $label === 'wash.whatsapp.urgency.'.$urgency ? $urgency : $label;
    }

    /** Jour + mois FR abrégé (ex. « 2 nov. ») — Carbon localisé (LOT 7). */
    protected function frenchDay(\DateTimeInterface $date): string
    {
        return $this->shortDay($date, false);
    }

    /** Jour + mois EN abrégé (ex. « Nov 2 ») — Carbon localisé (LOT 7). */
    protected function englishDay(\DateTimeInterface $date): string
    {
        return $this->shortDay($date, true);
    }

    /**
     * Date courte localisée via Carbon::isoFormat, octet-identique aux rendus
     * d'origine (mois FR manuels et format('M j') vérifiés mois par mois —
     * voir WashLot7CanauxTest). Carbon::instance() copie : l'instance
     * Eloquent d'origine (ex. $incident->updated_at) n'est jamais mutée.
     */
    protected function shortDay(\DateTimeInterface $date, bool $english): string
    {
        return Carbon::instance($date)->locale($english ? 'en' : 'fr')->isoFormat($english ? 'MMM D' : 'D MMM');
    }

    protected function unknownSchoolReply(?string $text): string
    {
        if ($text && preg_match(self::UNKNOWN_SCHOOL_ECOLE_PATTERN, $text, $m)) {
            $school = Str::limit(trim($m[1]), 60);

            return $this->fr('whatsapp.unknown_school_ecole', ['school' => $school]);
        }

        return $this->fr('whatsapp.unknown_school');
    }

    protected function offTopicReply(?string $text = null): string
    {
        // Intention conversationnelle (bonjour, qui es-tu, aide...) : réponse
        // chaleureuse de Sentinel ; sinon guidage signalement générique.
        return (new WashWhatsAppPersonality)->replyFor($text)
            ?? $this->fr('whatsapp.off_topic');
    }

    protected function createdReply(Incident $incident, bool $english = false): string
    {
        $summary = Str::limit((string) ($incident->ai_summary ?: $incident->title), 140);

        return $this->t('whatsapp.created', $english, [
            'ref' => $incident->reference_code,
            'summary' => $summary,
            'urgency' => $this->urgencyLabel($incident->urgency, $english),
        ]);
    }

    protected function duplicateReply(Incident $incident, bool $english = false): string
    {
        return $this->t('whatsapp.duplicate', $english, ['ref' => $incident->reference_code]);
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
        return $this->fr('whatsapp.oversized_audio');
    }

    protected function oversizedPhotoReply(): string
    {
        return $this->fr('whatsapp.oversized_photo');
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
