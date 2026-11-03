<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\AiAnalysis;
use App\Models\EquipmentCost;
use App\Models\Incident;
use App\Models\MaintenanceLog;
use App\Models\School;
use App\Models\Team;
use App\Contracts\AiEngineClient;
use App\Exceptions\ProposalGuidanceException;
use App\Models\AgentProposal;
use App\Models\User;
use App\Services\AgentProposalService;
use App\Services\DossierPosterService;
use GuzzleHttp\Exception\ConnectException as GuzzleConnectException;
use Illuminate\Http\Client\ConnectionException;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\RateLimiter;
use Illuminate\Validation\ValidationException;
use Symfony\Component\HttpKernel\Exception\AccessDeniedHttpException;
use Illuminate\Http\Request;

class WashAgentController extends Controller
{
    public const DISTRICT_MAX_CHARS = 128;

    public const QUERY_MAX_CHARS = 2000;

    public const DISPATCH_SCHOOL_LIMIT = 30;

    public const MONTHS_SINCE_LAST_INTERVENTION_DEFAULT = 12;

    public const EPIDEMIC_WINDOW_DAYS = 7;

    public const EPIDEMIC_INCIDENT_LIMIT = 50;

    public const TRANSLATE_TEXTS_MAX = 20;

    public const TRANSLATE_TEXT_MAX_CHARS = 2000;

    public const TRANSLATE_CACHE_TTL_SECONDS = 2592000;

    public const CONVERSE_HISTORY_MAX = 20;

    public const CONVERSE_HISTORY_MESSAGE_MAX = 2000;

    public const HISTORY_ROLES = ['user', 'assistant', 'tool'];

    public const AGENT_RETRY_DELAY_SECONDS = 1;

    public const SOFT_THROTTLE_MAX_ATTEMPTS = 20;

    public const SOFT_THROTTLE_DECAY_SECONDS = 60;

    public const VOTE_MAX_CHARS = 40;

    public const MAINTENANCE_PROFILE_LIMIT = 30;

    public const RECENT_INCIDENT_WINDOW_MONTHS = 12;

    public const RECENT_INCIDENT_LIMIT = 200;

    public const MAINTENANCE_LOG_WINDOW_DAYS = 30;

    public const MAINTENANCE_LOG_LIMIT = 200;

    public const OPEN_INCIDENT_LIMIT = 50;

    /** Miniatures max par incident (contexte converse + cartes). */
    public const INCIDENT_PHOTOS_LIMIT = 4;

    /** Légende photo quand le titre incident est vide. */
    public const INCIDENT_PHOTO_CAPTION_FALLBACK = 'Photo du signalement';

    public function copilotChat(Request $request, AiEngineClient $ai)
    {
        $validated = $request->validate([
            'user_query' => ['required', 'string', 'max:' . self::QUERY_MAX_CHARS],
            'district' => ['nullable', 'string', 'max:' . self::DISTRICT_MAX_CHARS],
        ]);

        $schoolsData = $this->maintenanceProfiles($validated['district'] ?? null);

        $response = $ai->copilotChat($validated['user_query'], $validated['district'] ?? null, $schoolsData);

        AiAnalysis::create([
            'analysis_type' => 'copilot',
            'input_payload' => ['query' => $validated['user_query'], 'district' => $validated['district'] ?? null],
            'output_payload' => $response,
        ]);

        return response()->json($response);
    }

    public function replaceVsRepair(School $school, AiEngineClient $ai)
    {
        $history = [
            'school_id' => $school->id,
            'school_name' => $school->name,
            'district' => $school->district,
            'equipment_type' => $school->equipment_type,
            'installation_year' => $school->installation_year,
            'estimated_replacement_cost' => (float) $school->estimated_replacement_cost,
            'incident_count' => $school->incidents()->count(),
            'total_repair_cost' => (float) $school->maintenanceLogs()->sum('cost_amount'),
            'total_days_without_service' => (int) $school->maintenanceLogs()->sum('days_without_service'),
        ];

        return response()->json($ai->replaceVsRepair($history));
    }

    public function dispatchPlan(Request $request, AiEngineClient $ai)
    {
        $validated = $request->validate(['district' => ['required', 'string', 'max:' . self::DISTRICT_MAX_CHARS]]);

        $schools = School::where('district', $validated['district'])->with(['openIncidents', 'maintenanceLogs'])->take(self::DISPATCH_SCHOOL_LIMIT)->get();

        $profiles = $schools->map(function (School $s) {
            $open = $s->openIncidents;
            $oldest = $open->sortBy('created_at')->first();
            $latest = $open->sortByDesc('created_at')->first();
            $lastFix = $s->maintenanceLogs->sortByDesc('repaired_at')->first();
            $urgencies = ['low' => 0, 'medium' => 1, 'high' => 2, 'critical' => 3];
            $maxUrgency = $open->sortByDesc(fn ($i) => $urgencies[$i->urgency] ?? 0)->first()?->urgency ?? 'low';

            return [
                'school_id' => $s->id,
                'school_name' => $s->name,
                'district' => $s->district,
                'distance_from_center_km' => (float) $s->distance_from_center_km,
                'days_without_water' => $oldest ? (int) $oldest->created_at->diffInDays(now()) : 0,
                'total_students' => (int) $s->student_count,
                'female_students' => (int) $s->female_students,
                'broken_toilets' => (int) $s->broken_toilets,
                'months_since_last_intervention' => $lastFix?->repaired_at
                    ? (int) $lastFix->repaired_at->diffInMonths(now())
                    : self::MONTHS_SINCE_LAST_INTERVENTION_DEFAULT,
                'urgency_level' => $maxUrgency,
                'issue_summary' => (string) ($latest?->ai_summary ?? $latest?->title ?? ''),
                'lat' => $s->latitude ? (float) $s->latitude : null,
                'lng' => $s->longitude ? (float) $s->longitude : null,
            ];
        })->all();

        $response = $ai->dispatchPlan($validated['district'], $profiles);

        AiAnalysis::create([
            'analysis_type' => 'equity',
            'input_payload' => ['district' => $validated['district'], 'schools' => count($profiles)],
            'output_payload' => $response,
        ]);

        return response()->json($response);
    }

    public function epidemicScan(Request $request, AiEngineClient $ai)
    {
        $validated = $request->validate(['district' => ['required', 'string', 'max:' . self::DISTRICT_MAX_CHARS]]);

        $recent = Incident::with('school:id,name,district')
            ->whereHas('school', fn ($q) => $q->where('district', $validated['district']))
            ->where('created_at', '>=', now()->subDays(self::EPIDEMIC_WINDOW_DAYS))
            ->latest()->take(self::EPIDEMIC_INCIDENT_LIMIT)->get()
            ->map(fn (Incident $i) => [
                'id' => $i->id,
                'school_name' => $i->school->name,
                'district' => $i->school->district,
                'category' => $i->category,
                'summary' => $i->ai_summary ?: $i->title,
                'reported_at' => $i->created_at->toIso8601String(),
            ])->all();

        $response = $ai->epidemicScan($validated['district'], $recent);

        AiAnalysis::create([
            'analysis_type' => 'epidemic',
            'input_payload' => ['district' => $validated['district'], 'incidents' => count($recent)],
            'output_payload' => $response,
        ]);

        return response()->json($response);
    }

    // Langues vocales : wash.voice.languages, miroir de
    // SUPPORTED_VOICE_LANGUAGES du moteur (fr, en, dua_Latn, bassa, ewondo,
    // bbj_Latn). Le Cameroun est bilingue FR/EN : schools.default_language
    // peut aussi valoir 'en' pour une école anglophone (le relais transmet
    // alors language=en au moteur).
    public function synthesize(Request $request, AiEngineClient $ai)
    {
        $validated = $request->validate([
            'text' => ['required', 'string', 'max:' . config('wash.voice.text_max_chars')],
            'voice' => ['nullable', 'string', 'max:' . config('wash.voice.voice_max_chars')],
            'language' => ['nullable', 'string', 'max:' . config('wash.voice.language_max_chars'), 'in:' . implode(',', config('wash.voice.languages'))],
        ]);

        return response()->json($ai->synthesize(
            $validated['text'],
            $validated['voice'] ?? config('wash.voice.default_tts_voice'),
            $validated['language'] ?? config('wash.voice.default_language'),
        ));
    }

    public function transcribe(Request $request, AiEngineClient $ai)
    {
        $validated = $request->validate([
            'audio' => 'required|file|max:' . config('wash.voice.audio_max_kb'),
            'language' => 'nullable|string|max:' . config('wash.voice.language_max_chars') . '|in:' . implode(',', config('wash.voice.languages')),
        ]);

        return response()->json($ai->transcribe(
            $validated['audio']->getRealPath(),
            $validated['language'] ?? null,
        ));
    }
    /**
     * Traduit des libellés terrain pour affichage (titres, résumés saisis).
     * Cache par hash source : un seul appel moteur par texte inédit, réponse
     * alignée sur l'ordre reçu. La source en base n'est jamais modifiée.
     */
    public function translate(Request $request, AiEngineClient $ai)
    {
        $validated = $request->validate([
            'texts' => ['required', 'array', 'min:1', 'max:' . self::TRANSLATE_TEXTS_MAX],
            'texts.*' => ['required', 'string', 'max:' . self::TRANSLATE_TEXT_MAX_CHARS],
            'target' => ['required', 'string', 'in:en,fr'],
        ]);
        $target = $validated['target'];
        $misses = [];
        $cached = [];
        foreach (array_values($validated['texts']) as $text) {
            $key = 'wash.translate.' . $target . '.' . sha1($text);
            $hit = Cache::get($key);
            if (is_string($hit) && $hit !== '') {
                $cached[$text] = $hit;
            } else {
                $misses[] = $text;
            }
        }
        $fresh = [];
        $unique = array_values(array_unique($misses));
        if ($unique !== []) {
            $response = $ai->translate($unique, $target);
            $got = is_array($response['translations'] ?? null) ? array_values($response['translations']) : [];
            foreach ($unique as $i => $text) {
                $translated = isset($got[$i]) && is_string($got[$i]) && $got[$i] !== '' ? $got[$i] : $text;
                $fresh[$text] = $translated;
                Cache::put('wash.translate.' . $target . '.' . sha1($text), $translated, self::TRANSLATE_CACHE_TTL_SECONDS);
            }
        }
        $out = [];
        foreach (array_values($validated['texts']) as $text) {
            $out[] = $fresh[$text] ?? $cached[$text] ?? $text;
        }

        return response()->json(['translations' => $out]);
    }

    public function converse(Request $request, AiEngineClient $ai, AgentProposalService $proposals)
    {
        // Rate-limit doux : répond en guidage 200 avant le throttle:30,1 dur (429).
        if ($soft = $this->softThrottleResponse($request)) {
            return response()->json($soft);
        }

        $validated = $request->validate([
            // Photo seule acceptée (multipart) : le texte reste requis sans image (JSON inchangé).
            'message' => ['required_without:image', 'nullable', 'string', 'max:' . self::QUERY_MAX_CHARS],
            // Plafond photo réutilisé (wash.photo.max_kb, miroir de WashReportController::PHOTO_MAX_KB).
            'image' => ['nullable', 'file', 'image', 'mimes:' . implode(',', config('wash.photo.mimes')), 'max:' . config('wash.photo.max_kb', WashReportController::PHOTO_MAX_KB)],
            'history' => ['nullable', 'array', 'max:' . self::CONVERSE_HISTORY_MAX],
            'history.*.role' => ['required_with:history', 'in:' . implode(',', self::HISTORY_ROLES)],
            'history.*.content' => ['required_with:history', 'string', 'max:' . self::CONVERSE_HISTORY_MESSAGE_MAX],
            'district' => ['nullable', 'string', 'max:' . self::DISTRICT_MAX_CHARS],
            'guided' => ['nullable', 'boolean'],
        ], [
            'message.required_without' => "Dites-moi en quelques mots ce dont vous avez besoin, par exemple « Signale une fuite au forage ».",
            'message.required' => "Dites-moi en quelques mots ce dont vous avez besoin, par exemple « Signale une fuite au forage ».",
            'image.file' => 'La photo doit être un fichier image.',
            'image.image' => "Ce fichier n'est pas une photo lisible : choisissez une image JPEG, PNG ou WebP.",
            'image.mimes' => 'Format de photo accepté : JPEG, PNG ou WebP uniquement.',
            'image.max' => 'Votre photo est trop lourde (10 Mo maximum) : essayez une photo plus légère.',
            'image.uploaded' => "La photo n'a pas pu être envoyée : réessayez avec une photo de moins de 10 Mo.",
            'message.string' => 'Votre message doit être un texte simple.',
            'message.max' => 'Votre message est un peu long (2000 caractères maximum) : essayez de le raccourcir.',
            'history.array' => "L'historique de conversation doit être une liste de messages.",
            'history.max' => "L'historique est limité aux 20 derniers messages.",
            'history.*.role.required_with' => "Chaque message d'historique doit préciser son rôle (user, assistant ou tool).",
            'history.*.role.in' => "Le rôle d'un message d'historique doit être user, assistant ou tool.",
            'history.*.content.required_with' => "Chaque message d'historique doit avoir un contenu.",
            'history.*.content.string' => "Le contenu d'un message d'historique doit être un texte.",
            'history.*.content.max' => 'Un message d’historique dépasse 2000 caractères.',
            'district.string' => 'Le district doit être un texte.',
            'district.max' => 'Le nom du district est trop long (128 caractères maximum).',
            'guided.boolean' => 'Le mode guidé doit être vrai ou faux.',
        ]);

        $message = (string) ($validated['message'] ?? '');
        $imageBase64 = null;
        $imageMime = null;
        if ($request->hasFile('image')) {
            $file = $request->file('image');
            $imageBase64 = base64_encode((string) file_get_contents($file->getRealPath()));
            $imageMime = $file->getMimeType() ?: $file->getClientMimeType();
            $validated['has_image'] = true;
        }

        $user = $this->optionalUser($request);
        if ($user && ($vote = $this->interceptVote($user, $message, $proposals)) !== null) {
            return response()->json($vote);
        }

        // Jamais de 500 brut : moteur IA injoignable => 200 + guidage chaleureux.
        try {
            $response = $this->agentChatResilient($ai, $validated, $message, $imageBase64, $imageMime);
        } catch (ConnectionException|GuzzleConnectException $e) {
            return response()->json($this->degradedGuidance());
        } catch (\Throwable $e) {
            report($e);

            return response()->json($this->degradedGuidance());
        }

        // Le moteur ne recopie pas (encore) les photos du contexte vers ses
        // cartes incident_detail/incident_picker (champs filtrés côté Python) :
        // Laravel réinjecte ici les miniatures faisant foi (URLs absolues
        // vérifiées sur disque), pour que le chat les affiche sans attendre.
        $response = $this->enrichIncidentCardPhotos($response);

        // Dossier décideur : le base64 des cartes `poster` est persisté sur
        // disque et remplacé par une URL absolue ; `dossier_report` passe tel
        // quel. Affiche absente ou corrompue => carte + note guidée, 200.
        $response = $this->rewritePosterCards($response);

        $response = $this->persistProposals($user, $response, $proposals);

        AiAnalysis::create([
            'analysis_type' => 'agent',
            'input_payload' => ['message' => $message, 'has_image' => $imageBase64 !== null],
            'output_payload' => $response,
        ]);

        return response()->json($response);
    }

    /**
     * Appel moteur avec une 2e chance sur panne de connexion franche.
     *
     * Couvre le moteur froid / conteneur en redémarrage (refus de connexion
     * transitoire). Pas de retry sur timeout : l'utilisateur a déjà attendu
     * 120 s, on guide au lieu de faire attendre 120 s de plus. Sûr côté
     * doublons : la persistance (propositions, AiAnalysis) a lieu une seule
     * fois après le succès, dans converse().
     */
    protected function agentChatResilient(AiEngineClient $ai, array $validated, string $message, ?string $imageBase64 = null, ?string $imageMime = null): array
    {
        $context = [
            'schools' => $this->maintenanceProfiles($validated['district'] ?? null),
            'incidents' => $this->openIncidentSnapshots($validated['district'] ?? null),
            'recent_incidents' => $this->recentIncidentSnapshots($validated['district'] ?? null),
            'maintenance_logs' => $this->maintenanceLogSnapshots($validated['district'] ?? null),
            'teams' => $this->teamSnapshots($validated['district'] ?? null),
            'equipment_costs' => $this->equipmentCostSnapshots(),
        ];
        // Map incident_id -> categorie pour les incidents liés aux journaux
        // (même résolus/clos ou hors fenêtre recent) : le moteur ventile
        // les coûts budget_compare sans bucket "unknown" parasite.
        // Construite depuis les snapshots déjà chargés (zéro requête).
        $context['incident_categories'] = [];
        foreach ($context['maintenance_logs'] as $log) {
            if (! empty($log['incident_id']) && ! empty($log['category'])) {
                $context['incident_categories'][$log['incident_id']] = $log['category'];
            }
        }

        $guided = (bool) ($validated['guided'] ?? false);

        try {
            return $ai->agentChat($message, $validated['history'] ?? [], $context, $guided, $imageBase64, $imageMime);
        } catch (ConnectionException|GuzzleConnectException $e) {
            if ($this->isTimeoutFailure($e)) {
                throw $e;
            }
            sleep(self::AGENT_RETRY_DELAY_SECONDS);
            return $ai->agentChat($message, $validated['history'] ?? [], $context, $guided, $imageBase64, $imageMime);
        }
    }

    protected function isTimeoutFailure(\Throwable $e): bool
    {
        $message = strtolower($e->getMessage());

        return str_contains($message, 'curl error 28') || str_contains($message, 'timed out');
    }

    protected function softThrottleResponse(Request $request): ?array
    {
        $key = 'wash.converse.soft:' . ($request->ip() ?? 'unknown');
        if (RateLimiter::tooManyAttempts($key, self::SOFT_THROTTLE_MAX_ATTEMPTS)) {
            $retryAfter = RateLimiter::availableIn($key);

            return [
                'answer' => "Trop de questions d'un coup — marquez une pause de {$retryAfter} secondes puis réessayez. Votre conversation est gardée.",
                'tools_executed' => [],
                'cards' => [],
                'model_used' => '',
                'follow_ups' => ['Voir les incidents ouverts ?'],
                'degraded' => true,
            ];
        }
        RateLimiter::hit($key, self::SOFT_THROTTLE_DECAY_SECONDS);

        return null;
    }

    protected function degradedGuidance(): array
    {
        return [
            'answer' => "Le moteur Sentinel met trop longtemps à répondre. Réessayez dans un instant — si ça persiste, reposez votre question plus simplement, par exemple « Résume le district Mvila ».",
            'tools_executed' => [],
            'cards' => [],
            'model_used' => '',
            'follow_ups' => ['Réessayer ?', 'Voir les incidents ouverts ?'],
            'degraded' => true,
        ];
    }

    protected function optionalUser(Request $request): ?User
    {
        try {
            return auth('sanctum')->user();
        } catch (\Throwable) {
            return null;
        }
    }

    protected function interceptVote(User $user, string $message, AgentProposalService $service): ?array
    {
        $text = mb_strtolower(trim($message));
        if (mb_strlen($text) > self::VOTE_MAX_CHARS) {
            return null;
        }
        $confirm = (bool) preg_match("/^(oui|ouais|ok|okay|confirmer?|je confirme|vas-?y|allons-?y|valider?|je valide|d'accord|d’accord)[.! ]*$/u", $text);
        $cancel = !$confirm && (bool) preg_match("/^(non|annuler?|annule|stop|laisse tomber|oublie)[.! ]*$/u", $text);
        if (!$confirm && !$cancel) {
            return null;
        }
        $pending = AgentProposal::where('user_id', $user->id)
            ->where('status', AgentProposal::STATUS_PENDING)
            ->where('expires_at', '>', now())
            ->latest()->get();
        if ($pending->count() !== 1) {
            return null;
        }
        try {
            if ($confirm) {
                $result = $service->confirm($user, $pending->first());
                return $this->voteResponse(true, null, $result);
            }
            $result = $service->cancel($user, $pending->first());
            return $this->voteResponse(false, null, $result);
        } catch (ProposalGuidanceException $e) {
            return $this->voteResponse($confirm, $e->getMessage(), [
                'guidance_status' => $e->guidanceStatus(),
                'next_action' => $e->nextAction(),
            ]);
        } catch (\Throwable $e) {
            return $this->voteResponse($confirm, $e->getMessage(), []);
        }
    }

    protected function voteResponse(bool $confirm, ?string $error, array $result): array
    {
        if ($error) {
            $answer = "Je n'ai pas pu exécuter : {$error}";
            $status = 'error';
        } elseif ($confirm) {
            $answer = "C'est validé : " . ($result['summary'] ?? 'action exécutée.');
            $status = 'confirmed';
        } else {
            $answer = "Proposition annulée, rien n'a été créé.";
            $status = 'cancelled';
        }

        return [
            'answer' => $answer,
            'tools_executed' => [$confirm ? 'confirm_proposal' : 'cancel_proposal'],
            'cards' => [[
                'type' => 'action_result',
                'title' => $confirm ? 'Résultat de la validation' : 'Proposition annulée',
                'data' => array_merge($result, ['status' => $status]),
            ]],
            'model_used' => 'sentinel-guard',
        ];
    }

    protected function persistProposals(?User $user, array $response, AgentProposalService $service): array
    {
        if (empty($response['cards']) || !is_array($response['cards'])) {
            return $response;
        }
        foreach ($response['cards'] as $i => $card) {
            if (($card['type'] ?? '') !== 'action_confirmation') {
                continue;
            }
            $data = $card['data'] ?? [];
            if (!($data['complete'] ?? false)) {
                continue;
            }
            if (!$user) {
                $response['cards'][$i]['data']['login_required'] = true;
                continue;
            }
            try {
                $draft = $service->draft($user, (string) ($data['action'] ?? ''), (array) ($data['slots'] ?? []));
                $response['cards'][$i]['data']['proposal_id'] = $draft['proposal']->id;
                $response['cards'][$i]['data']['expires_at'] = $draft['proposal']->expires_at->toIso8601String();
                $response['cards'][$i]['data']['recap_rows'] = $draft['recap_rows'];
            } catch (AccessDeniedHttpException $e) {
                $response['cards'][$i]['data']['not_permitted'] = true;
                $response['cards'][$i]['data']['permission_error'] = $e->getMessage();
            } catch (ValidationException $e) {
                $response['cards'][$i]['data']['invalid'] = true;
                $response['cards'][$i]['data']['errors'] = $e->errors();
            }
        }

        return $response;
    }

    protected function maintenanceProfiles(?string $district): array
    {
        return School::query()
            ->when($district, fn ($q, $v) => $q->where('district', $v))
            ->withCount('incidents')
            ->withSum('maintenanceLogs', 'cost_amount')
            ->withSum('maintenanceLogs', 'days_without_service')
            ->take(self::MAINTENANCE_PROFILE_LIMIT)->get()
            ->map(fn (School $s) => [
                'school_id' => $s->id,
                'school_name' => $s->name,
                'district' => $s->district,
                'equipment_type' => $s->equipment_type,
                'installation_year' => $s->installation_year,
                'estimated_replacement_cost' => (float) $s->estimated_replacement_cost,
                'incident_count' => (int) $s->incidents_count,
                'total_repair_cost' => (float) ($s->maintenance_logs_sum_cost_amount ?? 0),
                'total_days_without_service' => (int) ($s->maintenance_logs_sum_days_without_service ?? 0),
                'latitude' => $s->latitude,
                'longitude' => $s->longitude,
            ])->all();
    }

    protected function recentIncidentSnapshots(?string $district): array
    {
        return Incident::with('school:id,name,district')
            ->when($district, fn ($q, $v) => $q->whereHas('school', fn ($s) => $s->where('district', $v)))
            ->where('created_at', '>=', now()->subMonths(self::RECENT_INCIDENT_WINDOW_MONTHS))
            ->latest()->take(self::RECENT_INCIDENT_LIMIT)->get()
            ->map(fn (Incident $i) => [
                'id' => $i->id,
                'school_id' => $i->school_id,
                // Catégorie incluse (tous statuts, même résolus/clos) : le
                // moteur ventile les coûts budget_compare par catégorie même
                // quand l'incident lié n'est plus dans les ouverts.
                'category' => $i->category,
                'status' => $i->status,
                'reported_at' => $i->created_at->toIso8601String(),
            ])->all();
    }

    // Équipes actives pour le dispatch IA (prepare_intervention,
    // maintenance_team) : filtrées par district si demandé.
    protected function teamSnapshots(?string $district): array
    {
        return Team::query()
            ->where('is_active', true)
            ->when($district, fn ($q, $v) => $q->where('district', $v))
            ->orderBy('district')->orderBy('name')->get()
            ->map(fn (Team $t) => [
                'id' => $t->id,
                'name' => $t->name,
                'district' => $t->district,
                'phone' => $t->phone,
                'specialties' => $t->specialties ?? [],
                'is_active' => (bool) $t->is_active,
            ])->all();
    }

    protected function equipmentCostSnapshots(): array
    {
        return EquipmentCost::query()
            ->orderBy('category')->orderBy('label')->get()
            ->map(fn (EquipmentCost $c) => [
                'equipment_key' => $c->equipment_key,
                'label' => $c->label,
                'category' => $c->category,
                'min_xaf' => (int) $c->min_xaf,
                'max_xaf' => (int) $c->max_xaf,
                'source_name' => $c->source_name,
                'source_url' => $c->source_url,
            ])->all();
    }

    protected function maintenanceLogSnapshots(?string $district): array
    {
        return MaintenanceLog::with(['school:id,name,district', 'incident:id,reference_code,title,category'])
            ->when($district, fn ($q, $v) => $q->whereHas('school', fn ($s) => $s->where('district', $v)))
            ->where('created_at', '>=', now()->subDays(self::MAINTENANCE_LOG_WINDOW_DAYS))
            ->latest()->take(self::MAINTENANCE_LOG_LIMIT)->get()
            ->map(fn (MaintenanceLog $l) => [
                'id' => $l->id,
                'school_id' => $l->school_id,
                'incident_id' => $l->incident_id,
                'incident_ref' => $l->incident?->reference_code,
                'incident_title' => $l->incident?->title,
                // Catégorie de l'incident lié (même résolu/clos) : repli de
                // ventilation budget_compare quand l'incident est hors pool.
                'category' => $l->incident?->category,
                'school_name' => $l->school?->name,
                'cost_amount' => (float) $l->cost_amount,
                'currency' => $l->currency,
                'notes' => $l->notes,
                'created_at' => $l->created_at?->toIso8601String(),
                'repaired_at' => $l->repaired_at?->toIso8601String(),
                'days_without_service' => (int) $l->days_without_service,
            ])->all();
    }

    protected function openIncidentSnapshots(?string $district): array
    {
        return Incident::with([
            'school:id,name,district',
            'reports' => fn ($q) => $q->whereNotNull('photo_path')->orderBy('id'),
        ])
            ->when($district, fn ($q, $v) => $q->whereHas('school', fn ($s) => $s->where('district', $v)))
            ->open()->latest()->take(self::OPEN_INCIDENT_LIMIT)->get()
            ->map(fn (Incident $i) => [
                'id' => $i->id,
                'school_id' => $i->school_id,
                'school_name' => $i->school->name,
                'district' => $i->school->district,
                'reference_code' => $i->reference_code,
                'title' => $i->title,
                'category' => $i->category,
                'issue_type' => $i->issue_type,
                'urgency' => $i->urgency,
                'status' => $i->status,
                'priority_score' => (float) $i->priority_score,
                'affected_students' => (int) $i->affected_students,
                'summary' => $i->ai_summary ?: $i->title,
                'reported_at' => $i->created_at->toIso8601String(),
                'photos' => $this->incidentPhotos($i),
            ])->all();
    }

    /**
     * Miniatures d'un incident depuis ses signalements avec photo.
     *
     * Chaque entrée : url absolue http(s) ouvrable au navigateur, caption
     * (titre incident, repli 'Photo du signalement'), reported_at ISO8601
     * du signalement. Capé à INCIDENT_PHOTOS_LIMIT, fichiers manquants
     * exclus silencieusement (Report::photo_url -> null), [] sans photo.
     */
    protected function incidentPhotos(Incident $incident): array
    {
        $caption = is_string($incident->title) && $incident->title !== ''
            ? $incident->title
            : self::INCIDENT_PHOTO_CAPTION_FALLBACK;
        $photos = [];
        foreach ($incident->reports as $report) {
            if (count($photos) >= self::INCIDENT_PHOTOS_LIMIT) {
                break;
            }
            $url = $report->photo_url;
            if (!is_string($url) || $url === '') {
                continue;
            }
            $photos[] = [
                'url' => $url,
                'caption' => $caption,
                'reported_at' => $report->created_at?->toIso8601String(),
            ];
        }

        return $photos;
    }

    /**
     * Réécrit les cartes `poster` : image_base64 persistée sur disque puis
     * remplacée par image_url absolue (DossierPosterService). Jamais de 500 :
     * affiche absente, corrompue ou non récupérée => le base64 est retiré et
     * une note guidée FR est ajoutée à la carte, en réponse 200.
     */
    protected function rewritePosterCards(array $response): array
    {
        if (empty($response['cards']) || !is_array($response['cards'])) {
            return $response;
        }
        $service = app(DossierPosterService::class);
        foreach ($response['cards'] as $i => $card) {
            if (!is_array($card) || ($card['type'] ?? '') !== 'poster') {
                continue;
            }
            $data = $card['data'] ?? null;
            if (!is_array($data)) {
                $response['cards'][$i]['data'] = ['note' => DossierPosterService::MESSAGE_MISSING];
                continue;
            }
            $slug = 'affiche';
            foreach (['caption', 'prompt'] as $key) {
                if (isset($data[$key]) && is_string($data[$key]) && trim($data[$key]) !== '') {
                    $slug = $data[$key];
                    break;
                }
            }
            if (isset($card['title']) && is_string($card['title']) && $slug === 'affiche' && trim($card['title']) !== '') {
                $slug = $card['title'];
            }
            try {
                $url = $service->persistPoster(
                    isset($data['image_base64']) && is_string($data['image_base64']) ? $data['image_base64'] : null,
                    isset($data['image_url']) && is_string($data['image_url']) ? $data['image_url'] : null,
                    $slug,
                );
                unset($response['cards'][$i]['data']['image_base64']);
                $response['cards'][$i]['data']['image_url'] = $url;
            } catch (ValidationException $e) {
                $note = collect($e->errors())->flatten()->first();
                unset($response['cards'][$i]['data']['image_base64']);
                $response['cards'][$i]['data']['note'] = is_string($note) && $note !== ''
                    ? $note
                    : DossierPosterService::MESSAGE_DOWNLOAD_FAILED;
            } catch (\Throwable $e) {
                report($e);
                unset($response['cards'][$i]['data']['image_base64']);
                $response['cards'][$i]['data']['note'] = "L'affiche n'a pas pu être préparée : demandez une nouvelle affiche.";
            }
        }

        return $response;
    }

    /**
     * Réinjecte les photos dans les cartes incident_detail / incident_picker.
     *
     * Le moteur construit ces cartes depuis des listes de champs fermées
     * (agent_tools.py : tool_explain_incident, _candidate_card) et ne fait
     * donc pas transiter les photos du contexte : on complète ici chaque
     * carte/candidat identifiable par id, [] quand l'incident est inconnu
     * ou sans photo. Zéro requête sans carte incidente.
     */
    protected function enrichIncidentCardPhotos(array $response): array
    {
        if (empty($response['cards']) || !is_array($response['cards'])) {
            return $response;
        }
        $ids = [];
        foreach ($response['cards'] as $card) {
            if (!is_array($card)) {
                continue;
            }
            $type = $card['type'] ?? '';
            if ($type === 'incident_detail' && isset($card['data']['id']) && is_numeric($card['data']['id'])) {
                $ids[] = (int) $card['data']['id'];
            } elseif ($type === 'incident_picker' && is_array($card['data']['candidates'] ?? null)) {
                foreach ($card['data']['candidates'] as $candidate) {
                    if (is_array($candidate) && isset($candidate['id']) && is_numeric($candidate['id'])) {
                        $ids[] = (int) $candidate['id'];
                    }
                }
            }
        }
        $ids = array_values(array_unique($ids));
        $byId = [];
        if ($ids !== []) {
            $incidents = Incident::with([
                'reports' => fn ($q) => $q->whereNotNull('photo_path')->orderBy('id'),
            ])->whereIn('id', $ids)->get()->keyBy('id');
            foreach ($incidents as $id => $incident) {
                $byId[$id] = $this->incidentPhotos($incident);
            }
        }
        foreach ($response['cards'] as $i => $card) {
            if (!is_array($card)) {
                continue;
            }
            $type = $card['type'] ?? '';
            if ($type === 'incident_detail') {
                $id = isset($card['data']['id']) && is_numeric($card['data']['id']) ? (int) $card['data']['id'] : null;
                $response['cards'][$i]['data']['photos'] = $id !== null ? ($byId[$id] ?? []) : ($card['data']['photos'] ?? []);
            } elseif ($type === 'incident_picker' && is_array($card['data']['candidates'] ?? null)) {
                foreach ($card['data']['candidates'] as $j => $candidate) {
                    if (!is_array($candidate)) {
                        continue;
                    }
                    $id = isset($candidate['id']) && is_numeric($candidate['id']) ? (int) $candidate['id'] : null;
                    $response['cards'][$i]['data']['candidates'][$j]['photos'] = $id !== null ? ($byId[$id] ?? []) : ($candidate['photos'] ?? []);
                }
            }
        }

        return $response;
    }
}