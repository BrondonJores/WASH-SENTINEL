<?php

namespace App\Services;

use App\Contracts\AiEngineClient;
use App\Contracts\IncidentTriage;
use App\Contracts\WhatsAppClient;
use App\Models\Incident;
use App\Models\IncidentSubscription;
use App\Models\Report;
use App\Models\School;
use App\Models\SchoolContact;
use Carbon\Carbon;
use Illuminate\Http\Client\RequestException;
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

    /** Longueur max d'un texte entrant traité (anti saturation triage/IA). */
    protected const MAX_INCOMING_TEXT_LENGTH = 2000;

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

    /** Même déclaration en anglais : « SCHOOL Nom… » (une ligne). */
    protected const UNKNOWN_SCHOOL_SCHOOL_PATTERN = '/^\s*SCHOOL\s+(.+?)\s*$/iu';

    /** Mots-clés d'intention suivi (FR + EN), testés AVANT le filtre hors-sujet. */
    protected const SUIVI_KEYWORDS = [
        'suivi', 'suivre', 'statut', 'status', 'où en est', 'ou en est',
        'mon signalement', 'mes signalements', 'mon dossier',
        'avancé', 'avance', 'réparé', 'reparé', 'répare', 'repare',
        'where is', 'my report', 'track', 'tracking',
        'follow up', 'follow-up', 'followup',
        'update', 'my incident', 'my case',
    ];

    // Marqueurs de langue (suivi + signalement) : pilotés par données,
    // voir config/wash_languages.php — aucune liste de mots en dur ici.

    /** Étapes du suivi guidé (état cache wash.whatsapp.suivi.<tél>). */
    protected const SUIVI_STEP_AWAITING_ID = 'awaiting_id';

    protected const SUIVI_STEP_AWAITING_SCHOOL = 'awaiting_school';

    protected const SUIVI_STEP_AWAITING_DATE = 'awaiting_date';

    protected const SUIVI_STEP_AWAITING_CHOICE = 'awaiting_choice';

    /** Propositions max dans la liste de choix (ton SMS). */
    protected const SUIVI_MAX_PROPOSALS = 5;

    /** Mots courants (sans accents) jamais traités comme fragment de code. */
    protected const SUIVI_PARTIAL_STOPWORDS = [
        'suivi', 'suivre', 'dossier', 'dossiers', 'signalement', 'signaler',
        'statut', 'status', 'ecole', 'ecoles', 'college', 'lycee', 'school',
        'bonjour', 'bonsoir', 'salut', 'merci',
        'hier', 'aujourdhui', 'today', 'yesterday', 'demain',
        'janvier', 'fevrier', 'mars', 'avril', 'mai', 'juin', 'juillet',
        'aout', 'septembre', 'octobre', 'novembre', 'decembre',
        'january', 'february', 'march', 'april', 'june', 'july', 'august',
        'september', 'october', 'november', 'december',
        'janv', 'fevr', 'avr', 'juil', 'sept', 'oct', 'nov', 'dec',
        'jan', 'feb', 'mar', 'apr', 'jun', 'aug', 'sep',
        'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche',
    ];

    /** Issues de détection d'un texte : FR, EN ou INCERTAIN (aucun marqueur net). */
    protected const LANG_FR = 'fr';

    protected const LANG_EN = 'en';

    protected const LANG_UNCERTAIN = 'uncertain';

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
        protected WashPhrasebook $phrasebook = new WashPhrasebook,
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
                $this->safeReply($message['from'] ?? '', $this->t('whatsapp.error_technical', $this->messageEnglish($message)));
                $results[] = ['status' => 'error', 'from' => $message['from'] ?? null];
            }
        }

        return $results;
    }

    protected function handleMessage(array $message): array
    {
        $from = $message['from'] ?? '';
        if (!is_string($from) || $from === '') {
            // Message malformé sans expéditeur : rien à qui répondre, on ignore.
            Log::info('WhatsApp message without sender ignored.');

            return ['status' => 'ignored', 'from' => null];
        }
        $text = $message['text'] ?? null;
        $text = is_string($text) ? $text : null;
        $contact = SchoolContact::where('phone', SchoolContact::normalizePhone($from))->first();

        if (!$contact) {
            $this->reply($from, $this->unknownSchoolReply($text));

            return ['status' => 'unknown_contact', 'from' => $from];
        }

        // Double opt-in, 2e cran : numéro enregistré mais pas encore validé
        // par le directeur → guidage, aucun incident créé.
        if (!$contact->is_verified) {
            $this->reply($from, $this->t('whatsapp.unverified', $this->messageEnglish($message)));

            return ['status' => 'unverified_contact', 'from' => $from];
        }

        // Type non supporté (sticker, réaction, localisation...) : guidage.
        if (($message['type'] ?? '') === 'unsupported') {
            $this->reply($from, $this->t('whatsapp.unsupported', $this->conversationEnglish($from)));

            return ['status' => 'unsupported', 'from' => $from];
        }

        // Clic sur un bouton interactif (Oui/Non) : pas de triage, juste la suite.
        if (($message['type'] ?? '') === 'interactive') {
            return $this->handleButtonClick($from, (string) ($message['button_id'] ?? ''));
        }

        $audio = $photo = null;
        $channel = 'text';
        $voiceDetected = null;
        $langChoiceFreshEn = false;
        $voiceNativeLang = null;

        if (($message['type'] ?? '') === 'audio' && ($message['media_id'] ?? null)) {
            $download = $this->downloadMediaChecked($message['media_id']);
            if ($download['outcome'] === 'oversized') {
                $this->reply($from, $this->oversizedAudioReply($this->conversationEnglish($from)));

                return ['status' => 'oversized_media', 'from' => $from];
            }
            $media = $download['media'];
            if (!$media) {
                $this->reply($from, $this->t('whatsapp.unreadable_audio', $this->conversationEnglish($from)));

                return ['status' => 'unreadable_audio', 'from' => $from];
            }
            $audio = $this->toUploadedFile($media);
            $channel = 'voice';
            // Transcription explicite (profil STT actif + langue locale de l'école).
            // En cas d'échec on garde l'audio seul : le triage fera sa propre STT.
            // Langue DÉTECTÉE par le moteur (fr/en) : mémorisée aussitôt, elle
            // reflète le locuteur (les marqueurs du transcript affinent après).
            $voiceMeta = $this->transcribeVoiceWithMeta($audio, $contact->school->default_language ?? null);
            $transcript = $voiceMeta['transcript'];
            if (is_string($transcript) && $transcript !== '') {
                $text = $transcript;
            }
            $detected = $voiceMeta['language_detected'];
            if ($detected === self::LANG_FR || $detected === self::LANG_EN) {
                $voiceDetected = $detected;
                $this->rememberLang($from, $detected === self::LANG_EN);
            } elseif ($this->phrasebook->isNativeLang($detected)) {
                // Vocal en langue locale (bbj/dua...) : mémoire FR/EN
                // INTOUCHÉE (jamais de bascule), mais la réponse pourra
                // préfixer la phrase native VALIDÉE (phrasebook humain).
                $voiceNativeLang = $detected;
            }
        } elseif (($message['type'] ?? '') === 'image' && ($message['media_id'] ?? null)) {
            $download = $this->downloadMediaChecked($message['media_id']);
            if ($download['outcome'] === 'oversized') {
                $this->reply($from, $this->oversizedPhotoReply($this->conversationEnglish($from)));

                return ['status' => 'oversized_media', 'from' => $from];
            }
            $media = $download['media'];
            if (!$media) {
                $this->reply($from, $this->t('whatsapp.unreadable_photo', $this->conversationEnglish($from)));

                return ['status' => 'unreadable_photo', 'from' => $from];
            }
            $photo = $this->toUploadedFile($media);
            $channel = 'photo';
        }

        // Texte démesuré (copié-collé, test) : plafonné avant triage/suivi.
        $text = $this->capIncomingText($text);
        if (is_string($text) && trim($text) !== '') {
            $this->rememberLangFromText($from, $text);
        }

        if (!$text && !$audio && !$photo) {
            $this->reply($from, $this->offTopicReply(null, $this->conversationEnglish($from)));

            return ['status' => 'unsupported', 'from' => $from];
        }

        // STOP : lu AVANT tout état (clarification, suivi, pending) pour que
        // la sortie marche même en plein milieu d'un flow. Match strict sur
        // tout le texte : un signalement contenant « stop » ne déclenche pas.
        if ($channel === 'text' && is_string($text) && $this->isStopCommand($text)) {
            $this->forgetClarification($from);
            $this->forgetSuivi($from);
            $this->forgetPending($from);
            IncidentSubscription::unsubscribeAll(IncidentSubscription::CHANNEL_WHATSAPP, $from);
            $english = $this->messageEnglish($message);
            $this->reply($from, $this->t('notifications.progress.stopped', $english));

            return ['status' => 'unsubscribed', 'from' => $from];
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
                    $clarifyEn = is_string($text) && $text !== ''
                        ? $this->stepEnglish($text, (string) ($clarify['lang'] ?? 'fr'))
                        : ($clarify['lang'] ?? 'fr') === 'en';
                    $this->rememberClarification($from, (int) $clarify['incident_id'], $clarifyEn ? 'en' : 'fr');

                    return $this->applyClarification($from, $contact->school, $pendingIncident, $channel, $text, $audio, $photo, $clarifyEn);
                }
                // Incident pending disparu (supprimé) : repli triage normal + note FR.
                // (Clé expirée/silence = plus rien en cache : triage normal pur.)
                $this->forgetClarification($from);
                $staleClarification = true;
            }
        }

        // SUIVI GUIDÉ en cours : lu AVANT l'intention suivi et AVANT le triage
        // (un slot — ID, école, date, choix — n'est ni hors-sujet ni une panne).
        // Retourne null si l'usager signale une NOUVELLE panne (interruption :
        // l'état suivi est oublié, le triage normal reprend).
        if (($channel === 'text' || $channel === 'voice') && $text) {
            $suiviState = $this->suivi($from);
            if ($suiviState) {
                $suiviStep = $this->handleSuiviStep($from, $contact, (string) $text, $suiviState);
                if ($suiviStep !== null) {
                    return $suiviStep;
                }
            }
        }

        // Réponse FR/EN au choix de langue : on rejoue le texte mis en attente
        // (l'usager ne retape rien). Placé APRÈS les états en cours
        // (clarification/suivi : un slot ne doit jamais être rejoué) mais
        // AVANT les intentions : « EN » seul rejoue le vrai texte au lieu de
        // partir en hors-sujet. Canal texte uniquement (le vocal a sa
        // détection acoustique).
        if ($channel === 'text' && is_string($text)) {
            $awaitingText = Cache::get($this->langAwaitKey($from));
            if (is_string($awaitingText) && $awaitingText !== '') {
                Cache::forget($this->langAwaitKey($from));
                if ($this->rememberLangChoice($from, $text)) {
                    $text = $awaitingText;
                    // Le texte rejoué est incertain par construction : la
                    // réponse suit le choix frais, pas les marqueurs.
                    $langChoiceFreshEn = $this->rememberedLang($from) === self::LANG_EN;
                }
                // Nouveau contenu au lieu du choix : on avance avec, sans
                // reposer la question (le flag asked reste, anti-boucle).
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
            $this->forgetSuivi($from);
            $this->reply($from, $this->offTopicReply((string) $text, $this->messageEnglish($message)));

            return ['status' => 'off_topic', 'from' => $from];
        }

        // Choix de langue demandé uniquement pour un texte incertain SANS
        // langue mémorisée (jamais demandé deux fois : flag asked). Placé
        // APRÈS intentions suivi et filtre hors-sujet : une référence WASH
        // seule ou un bonjour ne déclenchent jamais la question.
        if ($channel === 'text' && is_string($text)
            && $this->needsLangChoice($from, $text)
            && !Cache::get($this->langAskedKey($from))) {
            Cache::put($this->langAwaitKey($from), $text, self::DEFAULT_PENDING_TTL);
            Cache::put($this->langAskedKey($from), true, self::DEFAULT_PENDING_TTL);
            $this->reply($from, $this->langChoiceReply());

            return ['status' => 'lang_choice_asked', 'from' => $from];
        }

        // Plus de clarification ni de suivi en attente à ce stade : message normal.
        // Le pending Oui/Non est oublié aussi : un nouveau signalement interrompt
        // la confirmation précédente (un vieux « Oui » ne doit plus confirmer).
        $this->forgetClarification($from);
        $this->forgetSuivi($from);
        $this->forgetPending($from);

        try {
            $result = $this->triage->ingest($contact->school, $channel, $text, $audio, $photo, null, 'whatsapp');
        } catch (\Throwable $e) {
            // Vocal inaudible des deux côtés (STT explicite + triage) :
            // on guide (réenregistrer), on ne crée RIEN (pas de doublon
            // fantôme). Toute autre panne remonte au garde générique.
            if (!str_starts_with($e->getMessage(), 'VOICE_STT_FAILED')) {
                throw $e;
            }
            $this->reply($from, $this->t('whatsapp.unreadable_audio', $this->conversationEnglish($from)));

            return ['status' => 'voice_stt_failed', 'from' => $from];
        }
        $incident = $result['incident'];
        // Langue de RÉPONSE : marqueurs du texte usager (transcript vocal ou
        // texte), ou langue acoustique DÉTECTÉE (jamais language_effective
        // STT : la requête force souvent fr).
        $english = (is_string($text) && $text !== '' && $this->isEnglishReply($text))
            || $voiceDetected === self::LANG_EN
            || $langChoiceFreshEn;
        // Suivi promis (« on vous écrit ici dès que ça avance ») : abonne le
        // directeur au dossier, silencieusement (la réponse standard promet
        // déjà le suivi). Réactivation après STOP → on le confirme.
        $subscription = IncidentSubscription::subscribe(
            $incident, IncidentSubscription::CHANNEL_WHATSAPP, $from, $english ? 'en' : 'fr');
        $reactivatedNotice = (bool) ($subscription->was_reactivated ?? false)
            ? $this->t('notifications.progress.subscribed', $english, ['ref' => $incident->reference_code]) . "\n\n"
            : '';
        $staleNote = $staleClarification ? $this->staleClarificationNote($english) : '';

        if ($result['is_duplicate']) {
            $this->reply($from, $reactivatedNotice . $staleNote . $this->duplicateReply($incident, $english));

            return [
                'status' => 'triaged',
                'from' => $from,
                'incident_id' => $incident->id,
                'is_duplicate' => true,
            ];
        }

        // Flow vocal : récap texte + boutons Oui/Non + note vocale TTS.
        if ($channel === 'voice' && (bool) config('whatsapp.voice_confirmation', true)) {
            $this->reply($from, $reactivatedNotice . $staleNote . $this->createdReply($incident, $english, $voiceNativeLang, $text));
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

        $this->reply($from, $reactivatedNotice . $staleNote . $this->createdReply($incident, $english, $voiceNativeLang, $channel === 'voice' ? $text : null));

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

        $this->reply($from, $this->offTopicReply(null, $this->conversationEnglish($from)));

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
    /** Commande STOP (FR/EN) : tout le texte, tolère ponctuation et accents. */
    protected function isStopCommand(string $text): bool
    {
        return (bool) preg_match('/^\s*(stop|arrets?|arrêts?|unsubscribe)\s*[.!]*\s*$/iu', $text);
    }

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
     * True si la réponse au signalement doit être en anglais : au moins
     * min_markers marqueurs EN génériques, et PAS de veto FR (mélange FR/EN
     * → français, langue par défaut). Ne dépend jamais de language_effective STT.
     */
    protected function isEnglishReply(string $text): bool
    {
        return $this->detectFluxLang('reply', $text) === self::LANG_EN;
    }

    /** Marqueur borné par des frontières de mot (unicode) : 'tap' ≠ 'taper'. */
    protected function containsMarker(string $lower, string $marker): bool
    {
        return preg_match('/\b' . preg_quote(mb_strtolower($marker), '/') . '\b/iu', $lower) === 1;
    }

    /** True si le message de suivi est en anglais (marqueurs EN, aucun FR). */
    protected function isEnglishSuivi(string $text): bool
    {
        return $this->detectFluxLang('suivi', $text) === self::LANG_EN;
    }

    /**
     * Détection d'un texte : 'fr', 'en' ou 'uncertain' (aucun marqueur net).
     * EN si marqueurs anglais (reply OU suivi, veto FR respecté) ; FR si
     * marqueur FR explicite ; sinon INCERTAIN — jamais de bascule au hasard
     * (l'appelant garde alors la langue mémorisée, ou demande si aucune).
     */
    protected function detectTextLang(string $text): string
    {
        if ($this->isEnglishReply($text) || $this->isEnglishSuivi($text)) {
            return self::LANG_EN;
        }
        if ($this->countFluxMarkers('reply', 'fr', $text) >= $this->langMinMarkers()) {
            return self::LANG_FR;
        }

        return self::LANG_UNCERTAIN;
    }

    /**
     * Détection d'un flux ('reply' ou 'suivi') : 'fr', 'en' ou 'uncertain'.
     * Les deux langues au seuil → le veto tranche (config wash_languages.veto).
     */
    protected function detectFluxLang(string $flux, string $text): string
    {
        $min = $this->langMinMarkers();
        $french = $this->countFluxMarkers($flux, 'fr', $text) >= $min;
        $english = $this->countFluxMarkers($flux, 'en', $text) >= $min;
        if ($french && $english) {
            return $this->langVeto();
        }
        if ($english) {
            return self::LANG_EN;
        }
        if ($french) {
            return self::LANG_FR;
        }

        return self::LANG_UNCERTAIN;
    }

    /** Nb de marqueurs DISTINCTS d'un flux/langue présents dans le texte. */
    protected function countFluxMarkers(string $flux, string $lang, string $text): int
    {
        $markers = $this->langMarkers($flux, $lang);
        if ($text === '' || $markers === []) {
            return 0;
        }
        $mode = $this->langMatchMode($flux);
        $lower = mb_strtolower($text);
        $count = 0;
        foreach ($markers as $marker) {
            $found = $mode === 'contains'
                ? str_contains($lower, mb_strtolower($marker))
                : $this->containsMarker($lower, $marker);
            if ($found) {
                $count++;
            }
        }

        return $count;
    }

    /** Marqueurs d'un flux/langue, lus depuis config/wash_languages.php. */
    protected function langMarkers(string $flux, string $lang): array
    {
        $key = $lang === self::LANG_EN ? 'english_markers' : 'french_markers';
        $markers = config("wash_languages.{$flux}.{$key}", []);

        return is_array($markers) ? array_values(array_filter($markers, 'is_string')) : [];
    }

    /**
     * Mode d'appariement d'un flux : 'word' (frontières de mot, signalement :
     * 'bloc' ≠ 'block') ou 'contains' (sous-chaîne, suivi historique).
     */
    protected function langMatchMode(string $flux): string
    {
        return config("wash_languages.{$flux}.match") === 'contains' ? 'contains' : 'word';
    }

    /** Nb min de marqueurs distincts pour trancher (seuil piloté par données). */
    protected function langMinMarkers(): int
    {
        $min = (int) config('wash_languages.min_markers', 1);

        return $min > 0 ? $min : 1;
    }

    /** Veto : gagnant quand les deux langues ont des marqueurs ('fr' historique). */
    protected function langVeto(): string
    {
        return config('wash_languages.veto') === self::LANG_EN ? self::LANG_EN : self::LANG_FR;
    }

    /**
     * Fiche statut SMS (≤ MAX_REPLY_LENGTH via reply()). Avec référence :
     * incident par reference_code (école du contact d'abord, sinon global).
     * Sans référence : SUIVI GUIDÉ (demande d'ID → école/date → choix
     * numérotés), état persisté par numéro. Ne crée ni incident ni Report ;
     * statut retourné 'suivi'.
     */
    protected function handleSuivi(string $from, SchoolContact $contact, string $text, ?string $reference): array
    {
        $english = $this->isEnglishSuivi($text);

        if ($reference !== null) {
            $incident = $this->findIncidentByReference($contact->school_id, $reference);

            if (!$incident) {
                $this->reply($from, $this->suiviUnknownReferenceReply($reference, $english));
                // L'usager peut renvoyer le bon code au message suivant.
                $this->rememberSuivi($from, ['step' => self::SUIVI_STEP_AWAITING_ID, 'lang' => $english ? 'en' : 'fr']);

                return ['status' => 'suivi', 'from' => $from, 'reference' => $reference];
            }

            $this->forgetSuivi($from);
            $this->reply($from, $this->suiviStatusReply($incident, $english));

            return ['status' => 'suivi', 'from' => $from, 'incident_id' => $incident->id];
        }

        // École sans aucun incident : réponse guidée directe, rien à chercher.
        if (!Incident::where('school_id', $contact->school_id)->exists()) {
            $this->reply($from, $this->suiviEmptyReply($english));

            return ['status' => 'suivi', 'from' => $from];
        }

        $this->rememberSuivi($from, ['step' => self::SUIVI_STEP_AWAITING_ID, 'lang' => $english ? 'en' : 'fr']);
        $this->reply($from, $this->t('whatsapp.suivi.ask_id', $english));

        return ['status' => 'suivi', 'from' => $from, 'step' => self::SUIVI_STEP_AWAITING_ID];
    }

    /** Incident par référence exacte, école du contact d'abord, sinon global. */
    protected function findIncidentByReference(int $schoolId, string $reference): ?Incident
    {
        return Incident::where('school_id', $schoolId)
            ->whereRaw('UPPER(reference_code) = ?', [$reference])
            ->first()
            ?? Incident::whereRaw('UPPER(reference_code) = ?', [$reference])->first();
    }

    /** Fiche statut : référence + résumé + statut + urgence + école + date + prochaine étape. */
    protected function suiviStatusReply(Incident $incident, bool $english): string
    {
        $summary = rtrim(Str::limit((string) ($incident->ai_summary ?: $incident->title), 90), '.');
        $terminal = in_array($incident->status, ['resolved', 'closed'], true);
        $since = $terminal ? '' : $this->t('whatsapp.suivi.since', $english, [
            'date' => $english
                ? $this->englishDay($incident->updated_at ?? now())
                : $this->frenchDay($incident->updated_at ?? now()),
        ]);

        $card = $this->t('whatsapp.suivi.card', $english, [
            'ref' => $incident->reference_code,
            'summary' => $summary,
            'human' => $this->statusHuman($incident->status, $english),
            'since' => $since,
        ]);

        return $card . $this->t('whatsapp.suivi.details', $english, [
            'school' => (string) ($incident->school?->name ?? ''),
            'date' => $english
                ? $this->englishDay($incident->created_at ?? now())
                : $this->frenchDay($incident->created_at ?? now()),
            'urgency' => $this->urgencyLabel($incident->urgency, $english),
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

    // ------------------------------------------------------------------
    // SUIVI GUIDÉ : ID → (école → date → choix numéroté) → fiche statut.
    // Un message = un slot, état persisté en cache par numéro de téléphone.
    // ------------------------------------------------------------------

    protected function suiviKey(string $from): string
    {
        return 'wash.whatsapp.suivi.' . SchoolContact::normalizePhone($from);
    }

    /**
     * Langue d'un slot en cours : le message courant l'emporte quand sa
     * langue est certaine, sinon on garde la langue stockée au 1er tour.
     */
    protected function stepEnglish(string $text, string $storedLang): bool
    {
        $detected = $this->detectTextLang($text);
        if ($detected === self::LANG_EN) {
            return true;
        }
        if ($detected === self::LANG_FR) {
            return false;
        }

        return $storedLang === 'en';
    }

    protected function rememberSuivi(string $from, array $state): void
    {
        Cache::put($this->suiviKey($from), $state, (int) config('whatsapp.pending_ttl', self::DEFAULT_PENDING_TTL));
    }

    protected function suivi(string $from): ?array
    {
        $state = Cache::get($this->suiviKey($from));

        return is_array($state) && isset($state['step']) ? $state : null;
    }

    protected function forgetSuivi(string $from): void
    {
        Cache::forget($this->suiviKey($from));
    }

    /**
     * Suite du suivi guidé (un message usager = un slot).
     * Retourne null pour laisser passer une NOUVELLE panne (interruption :
     * l'état suivi est oublié, le triage normal reprend).
     */
    protected function handleSuiviStep(string $from, SchoolContact $contact, string $text, array $state): ?array
    {
        // Le message courant prime sur la langue stockée (doctrine) : un
        // directeur peut changer de langue en cours de suivi.
        $english = $this->stepEnglish($text, (string) ($state['lang'] ?? 'fr'));
        $state['lang'] = $english ? 'en' : 'fr';
        $this->rememberSuivi($from, $state);
        $step = (string) ($state['step'] ?? '');

        if ($this->isSuiviCancel($text)) {
            $this->forgetSuivi($from);
            $this->reply($from, $this->t('whatsapp.suivi.cancelled', $english));

            return ['status' => 'suivi', 'from' => $from, 'step' => 'cancelled'];
        }

        if ($this->isSuiviRestart($text)) {
            $this->rememberSuivi($from, ['step' => self::SUIVI_STEP_AWAITING_ID, 'lang' => $english ? 'en' : 'fr']);
            $this->reply($from, $this->t('whatsapp.suivi.ask_id', $english));

            return ['status' => 'suivi', 'from' => $from, 'step' => self::SUIVI_STEP_AWAITING_ID];
        }

        // Référence complète à tout moment : résolution directe.
        if (preg_match(self::SUIVI_REFERENCE_PATTERN, $text, $m)) {
            $incident = $this->findIncidentByReference($contact->school_id, strtoupper($m[0]));
            if ($incident) {
                return $this->resolveSuivi($from, $incident, $english);
            }
            // Code inconnu : on reste sur l'étape en cours.
            $this->reply($from, $step === self::SUIVI_STEP_AWAITING_CHOICE
                ? $this->suiviProposalReply($state, $english, true)
                : $this->suiviUnknownReferenceReply(strtoupper($m[0]), $english));

            return ['status' => 'suivi', 'from' => $from, 'step' => $step];
        }

        // Code partiel (« TEST01 ») : exploitation aux étapes ID et choix
        // uniquement (jamais sur une réponse de date : « 2026 » y est une année).
        $partial = ($step === self::SUIVI_STEP_AWAITING_ID || $step === self::SUIVI_STEP_AWAITING_CHOICE)
            ? $this->matchSuiviPartial($contact->school_id, $text)
            : null;
        if ($partial !== null && count($partial) === 1) {
            return $this->resolveSuivi($from, $partial[0], $english);
        }

        // Phrases « je ne sais pas » / « mon école » : valables seulement hors
        // signalement de panne (un long texte avec « non »/« perdu » + fuite
        // reste une NOUVELLE panne, pas un slot).
        $slotPhrase = !$this->looksLikeWashReport($text) || mb_strlen(trim($text)) <= 20;

        switch ($step) {
            case self::SUIVI_STEP_AWAITING_ID:
                // ID partiel ambigu : on propose la liste.
                if ($partial !== null && count($partial) > 1) {
                    return $this->proposeSuivi($from, $partial, $english, $state);
                }
                // « Je ne sais pas » → on cherche par école puis date.
                if ($slotPhrase && $this->isSuiviUnknownId($text)) {
                    $this->rememberSuivi($from, ['step' => self::SUIVI_STEP_AWAITING_SCHOOL, 'lang' => $english ? 'en' : 'fr']);
                    $this->reply($from, $this->t('whatsapp.suivi.ask_school', $english));

                    return ['status' => 'suivi', 'from' => $from, 'step' => self::SUIVI_STEP_AWAITING_SCHOOL];
                }
                // École donnée directement (« c'est l'école de Bonanjo ») → date.
                $schools = $this->matchSuiviSchools($text);
                if (count($schools) === 1) {
                    return $this->askSuiviDate($from, $schools[0], $english);
                }
                if (count($schools) > 1) {
                    return $this->askSuiviSchoolPrecision($from, $schools, $english);
                }
                // Date donnée directement (« hier ») → dossiers de l'école du contact.
                $day = $this->parseSuiviDate($text);
                if ($day !== null) {
                    return $this->proposeSuiviForDay($from, $this->suiviDateState($contact, $english), $day, $english);
                }
                if ($this->interruptSuiviForNewReport($from, $text)) {
                    return null;
                }
                $this->reply($from, $this->t('whatsapp.suivi.ask_id', $english));

                return ['status' => 'suivi', 'from' => $from, 'step' => $step];

            case self::SUIVI_STEP_AWAITING_SCHOOL:
                // « Mon école » / « je ne sais pas » → école du contact.
                if ($slotPhrase && ($this->isSuiviSameSchool($text) || $this->isSuiviUnknownId($text))) {
                    return $this->askSuiviDate($from, $contact->school, $english);
                }
                $schools = $this->matchSuiviSchools($text);
                if (count($schools) === 1) {
                    return $this->askSuiviDate($from, $schools[0], $english);
                }
                if (count($schools) > 1) {
                    return $this->askSuiviSchoolPrecision($from, $schools, $english);
                }
                // Date donnée sans école (« hier ») → école du contact.
                $day = $this->parseSuiviDate($text);
                if ($day !== null) {
                    return $this->proposeSuiviForDay($from, $this->suiviDateState($contact, $english), $day, $english);
                }
                if ($this->interruptSuiviForNewReport($from, $text)) {
                    return null;
                }
                $this->reply($from, $this->t('whatsapp.suivi.ask_school_retry', $english));

                return ['status' => 'suivi', 'from' => $from, 'step' => $step];

            case self::SUIVI_STEP_AWAITING_DATE:
                $day = $this->parseSuiviDate($text);
                if ($day !== null) {
                    return $this->proposeSuiviForDay($from, $state, $day, $english);
                }
                if ($this->interruptSuiviForNewReport($from, $text)) {
                    return null;
                }
                $this->reply($from, $this->t('whatsapp.suivi.ask_date_retry', $english));

                return ['status' => 'suivi', 'from' => $from, 'step' => $step];

            case self::SUIVI_STEP_AWAITING_CHOICE:
                // « Aucun » : retour arrière (date si école connue, sinon école).
                if (preg_match('/\baucun\b|\bnone\b/', $this->asciiLower($text))) {
                    return $this->backSuiviAfterChoice($from, $state, $english);
                }
                $candidates = $this->refreshSuiviCandidates($from, $state);
                $state['candidates'] = $candidates;
                if ($candidates === []) {
                    return $this->backSuiviAfterChoice($from, $state, $english);
                }
                // Numéro du choix (« 2 », « le 2 », « choix 2 »).
                if (preg_match('/\b([1-9])\b/', $text, $m) && isset($candidates[(int) $m[1] - 1])) {
                    $incident = Incident::find($candidates[(int) $m[1] - 1]);
                    if ($incident) {
                        return $this->resolveSuivi($from, $incident, $english);
                    }
                }
                // Code partiel restreint aux propositions, sinon global unique.
                if ($partial !== null && count($partial) >= 1) {
                    $inList = array_values(array_filter($partial, fn (Incident $i) => in_array($i->id, $candidates, true)));
                    if (count($inList) === 1) {
                        return $this->resolveSuivi($from, $inList[0], $english);
                    }
                    if ($inList === [] && count($partial) === 1) {
                        return $this->resolveSuivi($from, $partial[0], $english);
                    }
                }
                if ($this->interruptSuiviForNewReport($from, $text)) {
                    return null;
                }
                $this->reply($from, $this->suiviProposalReply($state, $english, true));

                return ['status' => 'suivi', 'from' => $from, 'step' => $step];

            default:
                // État corrompu : on repart de la demande d'ID.
                $this->rememberSuivi($from, ['step' => self::SUIVI_STEP_AWAITING_ID, 'lang' => $english ? 'en' : 'fr']);
                $this->reply($from, $this->t('whatsapp.suivi.ask_id', $english));

                return ['status' => 'suivi', 'from' => $from, 'step' => self::SUIVI_STEP_AWAITING_ID];
        }
    }

    /** Nouvelle panne en cours de suivi : état oublié, triage normal (true). */
    protected function interruptSuiviForNewReport(string $from, string $text): bool
    {
        if ($this->looksLikeWashReport($text)) {
            $this->forgetSuivi($from);

            return true;
        }

        return false;
    }

    /** Étape date avec l'école du contact (raccourcis « hier » sans école). */
    protected function suiviDateState(SchoolContact $contact, bool $english): array
    {
        return [
            'step' => self::SUIVI_STEP_AWAITING_DATE,
            'lang' => $english ? 'en' : 'fr',
            'school_id' => $contact->school_id,
            'school_name' => $contact->school->name,
        ];
    }

    protected function resolveSuivi(string $from, Incident $incident, bool $english): array
    {
        $this->forgetSuivi($from);
        $this->reply($from, $this->suiviStatusReply($incident, $english));

        return ['status' => 'suivi', 'from' => $from, 'incident_id' => $incident->id];
    }

    /**
     * @param  School[]  $schools
     */
    protected function askSuiviSchoolPrecision(string $from, array $schools, bool $english): array
    {
        $this->rememberSuivi($from, ['step' => self::SUIVI_STEP_AWAITING_SCHOOL, 'lang' => $english ? 'en' : 'fr']);
        $names = array_slice(array_map(fn (School $s) => (string) $s->name, $schools), 0, 3);
        $this->reply($from, $this->t('whatsapp.suivi.ask_school_precision', $english, ['schools' => implode(', ', $names)]));

        return ['status' => 'suivi', 'from' => $from, 'step' => self::SUIVI_STEP_AWAITING_SCHOOL];
    }

    /** Retour arrière : date si l'école est connue, sinon école. */
    protected function backSuiviAfterChoice(string $from, array $state, bool $english): array
    {
        if (isset($state['school_id'])) {
            $this->rememberSuivi($from, [
                'step' => self::SUIVI_STEP_AWAITING_DATE,
                'lang' => $english ? 'en' : 'fr',
                'school_id' => $state['school_id'],
            ]);
            $this->reply($from, $this->t('whatsapp.suivi.ask_date', $english));

            return ['status' => 'suivi', 'from' => $from, 'step' => self::SUIVI_STEP_AWAITING_DATE];
        }
        $this->rememberSuivi($from, ['step' => self::SUIVI_STEP_AWAITING_SCHOOL, 'lang' => $english ? 'en' : 'fr']);
        $this->reply($from, $this->t('whatsapp.suivi.ask_school', $english));

        return ['status' => 'suivi', 'from' => $from, 'step' => self::SUIVI_STEP_AWAITING_SCHOOL];
    }

    protected function askSuiviDate(string $from, School $school, bool $english): array
    {
        $this->rememberSuivi($from, [
            'step' => self::SUIVI_STEP_AWAITING_DATE,
            'lang' => $english ? 'en' : 'fr',
            'school_id' => $school->id,
            'school_name' => $school->name,
        ]);
        $this->reply($from, $this->t('whatsapp.suivi.ask_date', $english));

        return ['status' => 'suivi', 'from' => $from, 'step' => self::SUIVI_STEP_AWAITING_DATE];
    }

    /** Dossiers de l'école au jour donné : proposition, ou autre date si aucun. */
    protected function proposeSuiviForDay(string $from, array $state, Carbon $day, bool $english): array
    {
        $school = isset($state['school_id']) ? School::find($state['school_id']) : null;
        if (!$school) {
            // École perdue (supprimée ?) : on la redemande.
            $this->rememberSuivi($from, ['step' => self::SUIVI_STEP_AWAITING_SCHOOL, 'lang' => $english ? 'en' : 'fr']);
            $this->reply($from, $this->t('whatsapp.suivi.ask_school', $english));

            return ['status' => 'suivi', 'from' => $from, 'step' => self::SUIVI_STEP_AWAITING_SCHOOL];
        }

        $found = Incident::where('school_id', $school->id)
            ->whereDate('created_at', $day->toDateString())
            ->latest('id')->take(self::SUIVI_MAX_PROPOSALS)->get();

        if ($found->isEmpty()) {
            $this->rememberSuivi($from, [
                'step' => self::SUIVI_STEP_AWAITING_DATE,
                'lang' => $english ? 'en' : 'fr',
                'school_id' => $school->id,
                'school_name' => $school->name,
            ]);
            $this->reply($from, $this->t('whatsapp.suivi.no_match', $english, [
                'school' => $school->name,
                'date' => $english ? $this->englishDay($day) : $this->frenchDay($day),
            ]));

            return ['status' => 'suivi', 'from' => $from, 'step' => self::SUIVI_STEP_AWAITING_DATE];
        }

        return $this->proposeSuivi($from, $found->all(), $english, $state, $school->name, $day);
    }

    /**
     * @param  Incident[]  $incidents
     */
    protected function proposeSuivi(string $from, array $incidents, bool $english, array $state, ?string $schoolName = null, ?Carbon $day = null): array
    {
        $incidents = array_values($incidents);
        $next = [
            'step' => self::SUIVI_STEP_AWAITING_CHOICE,
            'lang' => $english ? 'en' : 'fr',
            'candidates' => array_map(fn (Incident $i) => $i->id, $incidents),
        ];
        if (isset($state['school_id'])) {
            $next['school_id'] = $state['school_id'];
        }
        if ($schoolName !== null) {
            $next['school_name'] = $schoolName;
        }
        if ($day !== null) {
            $next['day'] = $day->toDateString();
        }
        $this->rememberSuivi($from, $next);
        $this->reply($from, $this->suiviProposalReply($next, $english, false));

        return ['status' => 'suivi', 'from' => $from, 'step' => self::SUIVI_STEP_AWAITING_CHOICE];
    }

    /** Ids des incidents proposés, dans l'ordre d'affichage. */
    protected function suiviCandidates(array $state): array
    {
        $ids = $state['candidates'] ?? [];
        if (!is_array($ids)) {
            return [];
        }

        return array_map('intval', array_values(array_filter($ids, fn ($id) => is_int($id) || (is_string($id) && ctype_digit($id)))));
    }

    /**
     * Candidats encore en base (incident supprimé entre-temps = retiré),
     * état resynchronisé pour garder la numérotation affichée.
     */
    protected function refreshSuiviCandidates(string $from, array $state): array
    {
        $stored = $this->suiviCandidates($state);
        if ($stored === []) {
            return [];
        }
        $alive = Incident::whereIn('id', $stored)->pluck('id')->all();
        $fresh = array_values(array_filter($stored, fn ($id) => in_array($id, $alive, true)));
        if ($fresh !== $stored) {
            $state['candidates'] = $fresh;
            $this->rememberSuivi($from, $state);
        }

        return $fresh;
    }

    /**
     * Liste numérotée « 1) WASH-… — résumé » + consigne de réponse.
     * Tient en un SMS : les résumés sont raccourcis si besoin (jamais la consigne).
     */
    protected function suiviProposalReply(array $state, bool $english, bool $invalid): string
    {
        $candidates = $this->suiviCandidates($state);
        $incidents = $candidates === []
            ? collect()
            : Incident::whereIn('id', $candidates)->get()->sortBy(fn (Incident $i) => array_search($i->id, $candidates, true))->values();
        if ($incidents->isEmpty()) {
            return $this->t('whatsapp.suivi.ask_date', $english);
        }

        if ($invalid) {
            $head = $this->t('whatsapp.suivi.invalid_choice', $english);
        } elseif (!isset($state['day'], $state['school_name'])) {
            $head = $this->t('whatsapp.suivi.propose_intro_generic', $english);
        } else {
            $day = Carbon::parse($state['day']);
            $head = $this->t('whatsapp.suivi.propose_intro', $english, [
                'count' => $incidents->count(),
                'school' => $state['school_name'],
                'date' => $english ? $this->englishDay($day) : $this->frenchDay($day),
            ]) . ' ' . $this->t('whatsapp.suivi.propose_hint', $english);
        }

        $summaryLen = 30;
        do {
            $lines = [];
            foreach ($incidents as $num => $incident) {
                $lines[] = '*' . ($num + 1) . ') ' . $incident->reference_code . '* — ' . Str::limit((string) ($incident->ai_summary ?: $incident->title), $summaryLen);
            }
            $body = $head . "\n" . implode("\n", $lines);
            if (mb_strlen($body) <= self::MAX_REPLY_LENGTH || $summaryLen <= 12) {
                break;
            }
            $summaryLen -= 6;
        } while (true);

        return $body;
    }

    /**
     * Code partiel (ex. « TEST01 », « RCLD5U ») : incidents dont la référence
     * contient le fragment (école du contact d'abord, sinon global).
     * null = aucun fragment exploitable dans le texte.
     *
     * @return Incident[]|null
     */
    protected function matchSuiviPartial(int $schoolId, string $text): ?array
    {
        $tokens = preg_split('/[^A-Za-z0-9]+/', $text, -1, PREG_SPLIT_NO_EMPTY) ?: [];
        $fragments = [];
        foreach ($tokens as $token) {
            $upper = mb_strtoupper($token);
            if (strlen($upper) < 4) {
                continue;
            }
            // Année ou jour (« 2026 », « 02 ») : jamais un fragment de code.
            if (ctype_digit($upper) && strlen($upper) < 6) {
                continue;
            }
            $ascii = $this->asciiLower($upper);
            // Fragment « code » : avec chiffre, ou long mot non courant.
            if (!preg_match('/\d/', $upper) && (strlen($upper) < 6 || in_array($ascii, self::SUIVI_PARTIAL_STOPWORDS, true))) {
                continue;
            }
            if (in_array($ascii, self::SUIVI_PARTIAL_STOPWORDS, true)) {
                continue;
            }
            $fragments[] = $upper;
        }
        $fragments = array_values(array_unique($fragments));
        if ($fragments === []) {
            return null;
        }

        foreach ($fragments as $fragment) {
            $found = Incident::where('school_id', $schoolId)
                ->whereRaw('UPPER(reference_code) LIKE ?', ['%' . $fragment . '%'])
                ->latest('id')->take(self::SUIVI_MAX_PROPOSALS)->get()->all();
            if ($found === []) {
                $found = Incident::whereRaw('UPPER(reference_code) LIKE ?', ['%' . $fragment . '%'])
                    ->latest('id')->take(self::SUIVI_MAX_PROPOSALS)->get()->all();
            }
            if ($found !== []) {
                return $found;
            }
        }

        return [];
    }

    /**
     * Écoles dont le nom correspond au texte (« Bonanjo », « c'est l'école
     * de Bonanjo »). Comparaison sans accents, dans les deux sens.
     *
     * @return School[]
     */
    protected function matchSuiviSchools(string $text): array
    {
        $needle = $this->suiviSchoolNeedle($text);
        if (mb_strlen($needle) < 3 || in_array($needle, ['ecole', 'ecoles', 'college', 'lycee', 'school'], true)) {
            return [];
        }

        $matches = [];
        foreach (School::query()->orderBy('name')->get() as $school) {
            $norm = $this->asciiLower((string) $school->name);
            if (mb_strlen($norm) < 3) {
                continue;
            }
            if (str_contains($norm, $needle) || str_contains($needle, $norm)) {
                $matches[] = $school;
                continue;
            }
            // Tous les mots du texte retrouvés dans le nom (« Bonanjo Douala »).
            $words = preg_split('/\s+/', $needle, -1, PREG_SPLIT_NO_EMPTY) ?: [];
            if (count($words) > 1) {
                $all = true;
                foreach ($words as $word) {
                    if (mb_strlen($word) < 3 || !str_contains($norm, $word)) {
                        $all = false;
                        break;
                    }
                }
                if ($all) {
                    $matches[] = $school;
                }
            }
        }

        return $matches;
    }

    /** Nom d'école brut : préfixes déclaratifs retirés, sans accents. */
    protected function suiviSchoolNeedle(string $text): string
    {
        $norm = $this->asciiLower($text);
        $norm = (string) preg_replace('/^(c est|ces|cest|ceci est|il s agit de)\s+/', '', $norm);
        $norm = (string) preg_replace('/^(l|la|le|les|une|mon|ma|notre)\s+/', '', $norm);
        $norm = (string) preg_replace('/^(ecole|ecoles|college|lycee|school|groupe scolaire)\s+(de|du|des|d)?\s*/', '', $norm);
        $norm = (string) preg_replace('/^(de|du|des|d)\s+/', '', $norm);
        $norm = trim((string) preg_replace('/[^\p{L}\p{N}\s-]+/u', ' ', $norm));

        return trim((string) preg_replace('/\s+/', ' ', $norm));
    }

    /** « Mon école », « ici », « la même »... : école du contact. */
    protected function isSuiviSameSchool(string $text): bool
    {
        return preg_match('/\b(mon ecole|ma ecole|notre ecole|la meme|meme ecole|meme que|chez nous|ici|my school|same school|pareil)\b/', $this->asciiLower($text)) === 1;
    }

    /** « Je ne sais pas », « non », « oublié »... : ID inconnu. */
    protected function isSuiviUnknownId(string $text): bool
    {
        return preg_match('/\b(non|no)\b|\b(ne|n) (sais|connais) pas\b|\bsais pas\b|\bconnais pas\b|aucune idee|no idea|dont know|do not know|oublie|perdu|pas de (numero|code)|je n ai pas/', $this->asciiLower($text)) === 1;
    }

    /** « Annuler », « stop »... : fin du suivi. */
    protected function isSuiviCancel(string $text): bool
    {
        return preg_match('/\b(annuler|annule|stop|laisse tomber|abandonner|abandonne|cancel|arreter|arrete)\b/', $this->asciiLower($text)) === 1;
    }

    /** « Recommencer » : on repart de la demande d'ID. */
    protected function isSuiviRestart(string $text): bool
    {
        return preg_match('/recommenc|restart|repartir|tout reprendre/', $this->asciiLower($text)) === 1;
    }

    /**
     * Jour visé (« hier », « le 2 », « 02/11 », « 2 novembre »...), null sinon.
     * « le N » seul = le plus récent jour N passé (aujourd'hui inclus).
     */
    protected function parseSuiviDate(string $text): ?Carbon
    {
        $norm = ' ' . $this->asciiLower($text) . ' ';
        $today = now()->startOfDay();

        if (str_contains($norm, 'avant hier') || str_contains($norm, 'avant-hier')) {
            return $today->copy()->subDays(2);
        }
        if (preg_match('/\bhier\b/', $norm) || str_contains($norm, 'yesterday')) {
            return $today->copy()->subDay();
        }
        // « aujourd'hui » : l'apostrophe est une espace après asciiLower().
        if (str_contains(str_replace([' ', '-'], '', $norm), 'aujourdhui') || preg_match('/\btoday\b/', $norm)) {
            return $today->copy();
        }
        if (preg_match('/il y a (\d{1,3}) jours?/', $norm, $m) || preg_match('/\b(\d{1,3}) jours?\b/', $norm, $m)) {
            return $today->copy()->subDays(min((int) $m[1], 3650));
        }
        if (str_contains($norm, 'semaine derniere') || str_contains($norm, 'last week')) {
            return $today->copy()->subWeek();
        }
        // JJ/MM(/AAAA), JJ-MM(-AAAA), JJ.MM(.AAAA).
        if (preg_match('/\b(\d{1,2})[\/.\-](\d{1,2})(?:[\/.\-](\d{2,4}))?\b/', $norm, $m)) {
            $day = (int) $m[1];
            $month = (int) $m[2];
            $year = isset($m[3]) && $m[3] !== '' ? (int) $m[3] : (int) $today->year;
            if ($year < 100) {
                $year += 2000;
            }
            $date = $this->safeSuiviDay($year, $month, $day);
            if ($date === null) {
                return null;
            }
            // Sans année et dans le futur : même jour l'an passé.
            if ((!isset($m[3]) || $m[3] === '') && $date->gt($today)) {
                $date->subYear();
            }

            return $date;
        }
        // « 2 novembre » / « le 2 nov » (+ année optionnelle).
        if (preg_match('/\b(\d{1,2})\s*([a-z]+)(?:\s*(\d{4}))?\b/', $norm, $m) && isset($this->suiviMonths()[$m[2]])) {
            $date = $this->safeSuiviDay(
                isset($m[3]) && $m[3] !== '' ? (int) $m[3] : (int) $today->year,
                $this->suiviMonths()[$m[2]],
                (int) $m[1]
            );
            if ($date === null) {
                return null;
            }
            if ((!isset($m[3]) || $m[3] === '') && $date->gt($today)) {
                $date->subYear();
            }

            return $date;
        }
        // Ordre anglais « november 2 ».
        if (preg_match('/\b([a-z]+)\s*(\d{1,2})\b/', $norm, $m) && isset($this->suiviMonths()[$m[1]])) {
            $date = $this->safeSuiviDay((int) $today->year, $this->suiviMonths()[$m[1]], (int) $m[2]);
            if ($date === null) {
                return null;
            }
            if ($date->gt($today)) {
                $date->subYear();
            }

            return $date;
        }
        // Jour seul (« le 2 », « 2 ») : pas sur une phrase de panne.
        if ($this->looksLikeWashReport($text)
            && !preg_match('/hier|aujourdhui|today|yesterday|semaine|\ble\b|\bjour\b|janv|fevr|mars|avr|mai|juin|juil|aout|sept|oct|nov|dec|\d[\/.\-]\d/', $norm)) {
            return null;
        }
        if (preg_match('/\b(\d{1,2})\b/', $norm, $m)) {
            $day = (int) $m[1];
            if ($day >= 1 && $day <= 31) {
                $date = $today->copy()->day(min($day, $today->daysInMonth));
                if ($date->gt($today)) {
                    $date->subMonthNoOverflow();
                    $date->day(min($day, $date->daysInMonth));
                }

                return $date->startOfDay();
            }
        }

        return null;
    }

    /** Mois FR/EN (clés sans accents) → numéro. */
    protected function suiviMonths(): array
    {
        return [
            'janvier' => 1, 'janv' => 1, 'jan' => 1, 'january' => 1,
            'fevrier' => 2, 'fevr' => 2, 'fev' => 2, 'february' => 2, 'feb' => 2,
            'mars' => 3, 'mar' => 3, 'march' => 3,
            'avril' => 4, 'avr' => 4, 'april' => 4, 'apr' => 4,
            'mai' => 5, 'may' => 5,
            'juin' => 6, 'jun' => 6, 'june' => 6,
            'juillet' => 7, 'juil' => 7, 'jul' => 7, 'july' => 7,
            'aout' => 8, 'aug' => 8, 'august' => 8,
            'septembre' => 9, 'sept' => 9, 'sep' => 9, 'september' => 9,
            'octobre' => 10, 'oct' => 10, 'october' => 10,
            'novembre' => 11, 'nov' => 11, 'november' => 11,
            'decembre' => 12, 'dec' => 12, 'december' => 12,
        ];
    }

    /** Jour calendaire sûr (null si inexistant : 30 février...). */
    protected function safeSuiviDay(int $year, int $month, int $day): ?Carbon
    {
        if ($month < 1 || $month > 12 || $day < 1 || $day > 31) {
            return null;
        }
        try {
            $date = Carbon::create($year, $month, $day, 0, 0, 0)->startOfDay();
        } catch (\Throwable) {
            return null;
        }

        return ($date->year === $year && $date->month === $month && $date->day === $day) ? $date : null;
    }

    /** Minuscules sans accents (comparaisons robustes aux transcriptions vocales). */
    protected function asciiLower(string $text): string
    {
        $lower = mb_strtolower(trim($text), 'UTF-8');
        $lower = str_replace(['’', '‘', "'", '`'], ' ', $lower);
        $ascii = iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $lower);

        return trim((string) ($ascii === false ? $lower : $ascii));
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
        return $this->transcribeVoiceWithMeta($audio, $language)['transcript'];
    }

    /**
     * Transcription + langue DÉTECTÉE par le moteur (fr/en/bbj.../null).
     * Le détecté non fr/en ne bascule AUCUNE mémoire (phrasebook à venir) :
     * il transite juste pour le guidage et les tests.
     *
     * @return array{transcript: ?string, language_detected: ?string}
     */
    protected function transcribeVoiceWithMeta(UploadedFile $audio, ?string $language): array
    {
        $empty = ['transcript' => null, 'language_detected' => null];
        if (!$this->ai) {
            return $empty;
        }
        try {
            $result = $this->ai->transcribe($audio->getRealPath(), $language ?: null);
            $transcript = trim((string) ($result['transcript'] ?? ''));
        } catch (\Throwable $e) {
            Log::info('WhatsApp transcribe fallback to triage STT: ' . $e->getMessage());

            return $empty;
        }
        $detected = $result['language_detected'] ?? null;
        // Observabilité : quel moteur STT a transcrit (utile au débogage :
        // vérifier que le profil cloud actif est bien honoré).
        Log::info('WhatsApp STT transcribed', [
            'driver' => $result['driver'] ?? null,
            'detected' => $detected,
            'cloud_error' => $result['detection']['cloud_error'] ?? null,
        ]);

        return [
            'transcript' => $transcript === '' ? null : $transcript,
            'language_detected' => is_string($detected) && $detected !== '' ? $detected : null,
        ];
    }

    protected function langAwaitKey(string $from): string
    {
        return 'wash.whatsapp.langawait.' . SchoolContact::normalizePhone($from);
    }

    protected function langAskedKey(string $from): string
    {
        return 'wash.whatsapp.langasked.' . SchoolContact::normalizePhone($from);
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
    // Langue de conversation mémorisée (repli des échecs sans texte).
    // ------------------------------------------------------------------

    protected function langKey(string $from): string
    {
        return 'wash.whatsapp.lang.' . SchoolContact::normalizePhone($from);
    }

    protected function rememberLang(string $from, bool $english): void
    {
        Cache::put($this->langKey($from), $english ? 'en' : 'fr', self::SEEN_TTL);
    }

    /**
     * Mémorise la langue d'un texte usager : EN si marqueurs anglais, FR si
     * marqueurs français, sinon on garde la langue mémorisée (un slot neutre
     * — « 2 », « NON », nom d'école — n'écrase pas une conversation EN).
     * Texte INCERTAIN : aucune bascule, la mémoire est inchangée.
     */
    protected function rememberLangFromText(string $from, string $text): void
    {
        $lang = $this->detectTextLang($text);
        if ($lang === self::LANG_UNCERTAIN) {
            return;
        }
        $this->rememberLang($from, $lang === self::LANG_EN);
    }

    /** True si la conversation mémorisée est en anglais ('fr' par défaut). */
    protected function conversationEnglish(string $from): bool
    {
        return $this->rememberedLang($from) === self::LANG_EN;
    }

    /**
     * Langue mémorisée ('fr' ou 'en'), ou null si AUCUNE (à la différence de
     * conversationEnglish, aucun défaut ici : null veut dire « jamais vue »).
     */
    protected function rememberedLang(string $from): ?string
    {
        if ($from === '') {
            return null;
        }
        $lang = Cache::get($this->langKey($from));

        return $lang === self::LANG_EN || $lang === self::LANG_FR ? $lang : null;
    }

    /**
     * Langue d'un message brut : marqueurs EN du texte courant → EN ;
     * marqueur FR explicite → FR (le message courant gagne sur le mémorisé) ;
     * sinon langue de la conversation mémorisée ('fr' par défaut).
     */
    protected function messageEnglish(array $message): bool
    {
        $text = $message['text'] ?? null;
        if (is_string($text) && trim($text) !== '') {
            $lang = $this->detectTextLang($text);
            if ($lang !== self::LANG_UNCERTAIN) {
                return $lang === self::LANG_EN;
            }
        }
        $from = $message['from'] ?? '';

        return $this->conversationEnglish(is_string($from) ? $from : '');
    }

    /**
     * True si le texte est INCERTAIN et qu'AUCUNE langue n'est mémorisée :
     * c'est le seul cas où il faut demander poliment (langChoiceReply),
     * partout ailleurs on garde la langue mémorisée ou le défaut FR.
     */
    protected function needsLangChoice(string $from, string $text): bool
    {
        return $this->rememberedLang($from) === null
            && $this->detectTextLang($text) === self::LANG_UNCERTAIN;
    }

    /**
     * Demande polie de langue (FR simple + EN), texte piloté par données
     * (config wash_languages.ask ; repli justifié si config absente).
     */
    protected function langChoiceReply(): string
    {
        $ask = config('wash_languages.ask', '');
        if (!is_string($ask) || trim($ask) === '') {
            // Repli de survie (config absente) : même phrase qu'en config.
            $ask = 'En quelle langue préférez-vous continuer ? Répondez FR ou EN. / Which language do you prefer? Reply FR or EN.';
        }

        return $ask;
    }

    /**
     * Choix de langue explicite (réponse FR/EN au guidage, insensible à la
     * casse et aux espaces) : persisté, retourne true. Texte libre → false,
     * rien n'est mémorisé. Codes stables (config wash_languages.codes).
     */
    protected function rememberLangChoice(string $from, string $text): bool
    {
        $codes = config('wash_languages.codes', [self::LANG_FR, self::LANG_EN]);
        if (!is_array($codes) || $codes === []) {
            $codes = [self::LANG_FR, self::LANG_EN];
        }
        $answer = mb_strtolower(trim($text));
        foreach ($codes as $code) {
            if (is_string($code) && $answer === mb_strtolower($code)) {
                $this->rememberLang($from, mb_strtolower($code) === self::LANG_EN);

                return true;
            }
        }

        return false;
    }

    /** Tronque un texte entrant démesuré (notes copiées-collées, tests). */
    protected function capIncomingText(?string $text): ?string
    {
        if ($text === null || mb_strlen($text) <= self::MAX_INCOMING_TEXT_LENGTH) {
            return $text;
        }

        return mb_substr($text, 0, self::MAX_INCOMING_TEXT_LENGTH);
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
        if ($text && preg_match(self::UNKNOWN_SCHOOL_SCHOOL_PATTERN, $text, $m)) {
            $school = Str::limit(trim($m[1]), 60);

            return $this->t('whatsapp.unknown_school_ecole', true, ['school' => $school]);
        }
        $english = is_string($text) && ($this->isEnglishReply($text) || $this->isEnglishSuivi($text));

        return $this->t('whatsapp.unknown_school', $english);
    }

    protected function offTopicReply(?string $text = null, ?bool $english = null): string
    {
        // Intention conversationnelle (bonjour, qui es-tu, aide...) : réponse
        // chaleureuse de Sentinel ; sinon guidage signalement générique,
        // dans la langue du texte (ou de la conversation si imposée).
        $personality = (new WashWhatsAppPersonality)->replyFor($text);
        if ($personality !== null) {
            return $personality;
        }
        $english ??= is_string($text) && trim($text) !== ''
            && ($this->isEnglishReply($text) || $this->isEnglishSuivi($text));

        return $this->t('whatsapp.off_topic', $english);
    }

    protected function createdReply(Incident $incident, bool $english = false, ?string $nativeLang = null, ?string $voiceTranscript = null): string
    {
        // Vocal : le récap répercute les mots de l'usager (transcript, non
        // traduit) — il se relit/vérifie, même sans lire le français
        // technique. Texte : résumé de l'extracteur, conservé tel quel.
        $summary = Str::limit((string) (
            ($voiceTranscript !== null && trim($voiceTranscript) !== '')
                ? $voiceTranscript
                : ($incident->ai_summary ?: $incident->title)
        ), 140);

        $base = $this->t('whatsapp.created', $english, [
            'ref' => $incident->reference_code,
            'summary' => $summary,
            'urgency' => $this->urgencyLabel($incident->urgency, $english),
        ]);

        // Vocal natif + phrase VALIDÉE par un locuteur : l'usager reçoit
        // SA langue d'abord, puis le FR/EN standard (bilingue, sans risque).
        // Rien de validé → FR/EN seul (comportement inchangé).
        $native = is_string($nativeLang)
            ? $this->phrasebook->render($nativeLang, 'thanks_case', ['ref' => $incident->reference_code])
            : null;

        return $native !== null ? $native."\n\n".$base : $base;
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
            // 401/403 = token expiré ou invalide : erreur exploitable côté ops,
            // même guidage usager (le texte d'envoi peut encore passer en file).
            if ($e instanceof RequestException && $e->response && in_array($e->response->status(), [401, 403], true)) {
                Log::error('WhatsApp media download refused (token expiré ou invalide ?) : ' . $e->getMessage());
            } else {
                Log::warning('WhatsApp media download failed: ' . $e->getMessage());
            }

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

    protected function oversizedAudioReply(bool $english = false): string
    {
        return $this->t('whatsapp.oversized_audio', $english);
    }

    protected function oversizedPhotoReply(bool $english = false): string
    {
        return $this->t('whatsapp.oversized_photo', $english);
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
        file_put_contents($path, $media['bytes'] ?? '');

        return new UploadedFile($path, $media['filename'] ?? 'whatsapp-media', $media['mime'] ?? 'application/octet-stream', null, true);
    }
}
