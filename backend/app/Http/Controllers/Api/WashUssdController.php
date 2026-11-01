<?php

namespace App\Http\Controllers\Api;

use App\Contracts\IncidentTriage;
use App\Http\Controllers\Controller;
use App\Models\MeshBundle;
use App\Models\School;
use App\Services\MeshSmsParser;
use Illuminate\Http\Request;
use Illuminate\Http\Response;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Str;

/**
 * Canal USSD (feature phones, sans data) — Chantier V2 « USSD ».
 *
 * Compatible passerelle générique style Africa's Talking : la passerelle
 * POSTe chaque interaction (sessionId, serviceCode, phoneNumber, text) et
 * attend une réponse texte brute préfixée « CON » (suite) ou « END » (fin).
 * « text » cumule les saisies séparées par « * » ; seule la dernière
 * saisie est interprétée, l'état de session vit en cache Laravel (TTL).
 *
 * Le signalement validé suit le même pipeline que le SMS : MeshBundle
 * (origin ussd:<hash>) + triage IA standard avec source = 'ussd'.
 *
 * Vie privée : le numéro d'appelant n'est persisté nulle part (ni BDD,
 * ni cache, ni logs) — seule une empreinte SHA-256 tronquée sert
 * d'identifiant d'origine pour quota et dédup.
 */
class WashUssdController extends Controller
{
    public const SESSION_TTL_MINUTES = 10;

    public const DONE_TTL_HOURS = 24;

    public const MAX_SCHOOL_ATTEMPTS = 3;

    /**
     * Réception passerelle (Africa's Talking : form-encoded).
     */
    public function handle(Request $request, IncidentTriage $triage, MeshSmsParser $parser): Response
    {
        $input = $this->validatedInput($request);

        return $this->plain($this->run(
            $input['sessionId'], $input['serviceCode'] ?? '', $input['phoneNumber'], $input['text'] ?? '',
            $triage, $parser
        ));
    }

    /**
     * Sondage GET pour tests manuels (mêmes paramètres en query string).
     */
    public function probe(Request $request, IncidentTriage $triage, MeshSmsParser $parser): Response
    {
        $input = $this->validatedInput($request);

        return $this->plain($this->run(
            $input['sessionId'], $input['serviceCode'] ?? '', $input['phoneNumber'], $input['text'] ?? '',
            $triage, $parser
        ));
    }

    /**
     * @return array{sessionId: string, serviceCode: ?string, phoneNumber: string, text: ?string}
     */
    private function validatedInput(Request $request): array
    {
        return $request->validate([
            'sessionId' => ['required', 'string', 'max:64'],
            'serviceCode' => ['nullable', 'string', 'max:32'],
            'phoneNumber' => ['required', 'string', 'max:32'],
            'text' => ['nullable', 'string', 'max:1000'],
        ]);
    }

    private function plain(string $body): Response
    {
        return response($body, 200)->header('Content-Type', 'text/plain; charset=utf-8');
    }

    private function run(string $sessionId, string $serviceCode, string $phone, ?string $text, IncidentTriage $triage, MeshSmsParser $parser): string
    {
        $sid = $this->sessionKey($sessionId);
        $text = (string) ($text ?? '');
        // Origine non réversible (pas de PII persistée) ; stable par appelant
        // pour quota et dédup.
        $origin = 'ussd:'.substr(hash('sha256', $phone), 0, 16);

        // Idempotence : la passerelle rejoue parfois la confirmation.
        $done = Cache::get("ussd:done:{$sid}");
        if (is_array($done) && isset($done['ticket'])) {
            return $this->end("Signalement deja enregistre. Ticket: {$done['ticket']}");
        }

        /** @var array{step: string, school_id: ?int, school_code: ?string, school_name: ?string, type: ?string, urgency: ?string, desc: ?string, attempts: int}|null $state */
        $state = Cache::get("ussd:session:{$sid}");

        // NB : ne pas utiliser ?: ici, la saisie « 0 » (annulation) est falsy.
        $segments = explode('*', $text);
        $input = $text === '' ? '' : trim((string) end($segments));

        if ($state === null) {
            // Nouvel appel (text vide) ou reprise tolérante : certaines
            // passerelles omettent le text vide initial.
            $state = $this->freshState();
            if ($text === '') {
                $this->saveState($sid, $state);

                return $this->con($this->homeMenu());
            }
        }

        return match ($state['step']) {
            'home' => $this->stepHome($sid, $state, $input),
            'school' => $this->stepSchool($sid, $state, $input, $parser),
            'type' => $this->stepType($sid, $state, $input, $parser),
            'urgency' => $this->stepUrgency($sid, $state, $input),
            'desc' => $this->stepDesc($sid, $state, $input),
            'confirm' => $this->stepConfirm($sid, $state, $input, $origin, $serviceCode, $triage, $parser),
            default => $this->abort($sid, 'Session invalide. Recomposez le code USSD.'),
        };
    }

    // ------------------------------------------------------------------
    // Étapes du menu
    // ------------------------------------------------------------------

    /** @param array<string, mixed> $state */
    private function stepHome(string $sid, array $state, string $input): string
    {
        if ($input === '1') {
            $state['step'] = 'school';
            $state['attempts'] = 0;
            $this->saveState($sid, $state);

            return $this->con("Entrez le code ecole (ex: CE042):\n0. Annuler");
        }
        if ($input === '0') {
            return $this->abort($sid, 'Session terminee. Merci!');
        }

        return $this->con("Choix invalide.\n".$this->homeMenu(), $sid, $state);
    }

    /** @param array<string, mixed> $state */
    private function stepSchool(string $sid, array $state, string $input, MeshSmsParser $parser): string
    {
        if ($input === '0') {
            return $this->abort($sid, 'Session terminee. Merci!');
        }

        $school = $input === '' ? null : $parser->findSchoolByCode($input);
        if (! $school) {
            $state['attempts']++;
            if ($state['attempts'] >= self::MAX_SCHOOL_ATTEMPTS) {
                return $this->abort($sid, "Code ecole '{$input}' introuvable. Recommencez plus tard.");
            }
            $this->saveState($sid, $state);

            return $this->con("Code '{$input}' inconnu. Reessayez (ex: CE042):\n0. Annuler");
        }

        $state['school_id'] = $school->id;
        $state['school_code'] = $school->code;
        $state['school_name'] = $school->name;
        $state['step'] = 'type';
        $state['attempts'] = 0;
        $this->saveState($sid, $state);

        return $this->con($this->typeMenu());
    }

    /** @param array<string, mixed> $state */
    private function stepType(string $sid, array $state, string $input, MeshSmsParser $parser): string
    {
        if ($input === '0') {
            return $this->abort($sid, 'Session terminee. Merci!');
        }

        $type = $parser->ussdChoiceToType($input);
        if (! $type) {
            return $this->con("Choix invalide.\n".$this->typeMenu(), $sid, $state);
        }

        $state['step'] = 'urgency';
        $state['type'] = $type;
        $this->saveState($sid, $state);

        return $this->con($this->urgencyMenu());
    }

    /** @param array<string, mixed> $state */
    private function stepUrgency(string $sid, array $state, string $input): string
    {
        if ($input === '0') {
            return $this->abort($sid, 'Session terminee. Merci!');
        }

        $urgency = match ($input) {
            '1' => 'normale',
            '2' => 'urgente',
            default => null,
        };
        if (! $urgency) {
            return $this->con("Choix invalide.\n".$this->urgencyMenu(), $sid, $state);
        }

        $state['step'] = 'desc';
        $state['urgency'] = $urgency;
        $this->saveState($sid, $state);

        return $this->con("Breve description (max 100 car.):\n9. Passer\n0. Annuler");
    }

    /** @param array<string, mixed> $state */
    private function stepDesc(string $sid, array $state, string $input): string
    {
        if ($input === '0') {
            return $this->abort($sid, 'Session terminee. Merci!');
        }
        if ($input === '9') {
            $state['desc'] = null;
        } else {
            $clean = Str::limit(trim(preg_replace('/\s+/', ' ', strip_tags($input)) ?? ''), 100, '');
            if ($clean === '') {
                return $this->con('Description vide. Reessayez ou 9 pour passer:', $sid, $state);
            }
            $state['desc'] = $clean;
        }

        $state['step'] = 'confirm';
        $this->saveState($sid, $state);

        return $this->con($this->confirmMenu($state));
    }

    /** @param array<string, mixed> $state */
    private function stepConfirm(string $sid, array $state, string $input, string $origin, string $serviceCode, IncidentTriage $triage, MeshSmsParser $parser): string
    {
        if ($input === '0') {
            return $this->abort($sid, 'Signalement annule. Merci!');
        }
        if ($input !== '1') {
            return $this->con("Choix invalide.\n".$this->confirmMenu($state), $sid, $state);
        }

        $school = School::find($state['school_id']);
        if (! $school) {
            return $this->abort($sid, 'Ecole introuvable. Recommencez le signalement.');
        }

        $quota = (int) config('services.mesh.sms_quota_per_sender', 10);
        if (MeshBundle::where('origin_node_id', $origin)->whereDate('created_at', today())->count() >= $quota) {
            Log::warning('mesh.ussd.rejected', ['cause' => 'quota', 'origin' => $origin]);
            $this->forget($sid);

            return $this->end('Quota journalier depasse pour cet appelant.');
        }

        $normalized = $parser->buildUssdMessage($school, (string) $state['type'], $state['urgency'], $state['desc']);

        // Dédup : même appelant (empreinte) + même texte normalisé sur 24 h.
        $recent = MeshBundle::where('origin_node_id', $origin)
            ->where('message', $normalized)
            ->where('created_at', '>', now()->subDay())
            ->with('report.incident')
            ->first();
        if ($recent) {
            $ticket = $recent->report?->incident?->reference_code ?? "#{$recent->report?->incident?->id}";
            $this->forget($sid);

            return $this->end("Signalement deja recu. Ticket: {$ticket}");
        }

        // Même pipeline que le SMS : MeshBundle puis triage standard.
        $result = DB::transaction(function () use ($state, $normalized, $origin, $serviceCode, $triage, $school) {
            $bundle = MeshBundle::create([
                'bundle_id' => (string) Str::uuid(),
                'origin_node_id' => $origin,
                'school_id' => $school->id,
                'school_code' => $school->code,
                'channel' => 'text',
                'message' => $normalized,
                'payload' => [
                    'ussd_service_code' => $serviceCode !== '' ? $serviceCode : null,
                    'ussd_type' => $state['type'],
                    'ussd_urgency' => $state['urgency'],
                    'ussd_desc' => $state['desc'],
                ],
                'hops' => [$origin],
                'hop_count' => 0,
                'copies_remaining' => 1,
                'destination_eid' => 'dtn://wash-sentinel/ingest',
                'received_via_node_id' => $origin,
                'status' => 'delivered',
                'expires_at' => now()->addDays(7),
                'delivered_at' => now(),
            ]);

            $ingested = $triage->ingest($school, 'text', $normalized, null, null, null, 'ussd');
            $bundle->update(['report_id' => $ingested['report']->id]);

            return ['bundle' => $bundle, 'incident' => $ingested['incident']];
        });

        $ticket = $result['incident']->reference_code ?? "#{$result['incident']->id}";

        Log::info('mesh.ussd.accepted', [
            'bundle_id' => $result['bundle']->bundle_id,
            'origin' => $origin,
            'school_id' => $school->id,
            'ticket' => $ticket,
        ]);

        Cache::put("ussd:done:{$sid}", ['ticket' => $ticket], now()->addHours(self::DONE_TTL_HOURS));
        $this->forget($sid);

        return $this->end("Merci! Signalement enregistre. Ticket: {$ticket}");
    }

    // ------------------------------------------------------------------
    // Menus (FR, sans accents : GSM 7-bit, 1 écran ≤ 160 car.)
    // ------------------------------------------------------------------

    private function homeMenu(): string
    {
        return "Bienvenue WASH-SENTINEL\n1. Signaler une panne\n0. Quitter";
    }

    private function typeMenu(): string
    {
        return "Type de panne:\n1. Pompe/forage\n2. Latrine\n3. Eau/qualite\n4. Hygiene\n0. Annuler";
    }

    private function urgencyMenu(): string
    {
        return "Urgence:\n1. Normale\n2. Urgente (pas d'eau / risque sante)\n0. Annuler";
    }

    /** @param array<string, mixed> $state */
    private function confirmMenu(array $state): string
    {
        $label = MeshSmsParser::TYPES[(string) $state['type']]['label'] ?? (string) $state['type'];

        return 'Confirmer?'."\n"
            ."Ecole: {$state['school_code']}\n"
            ."Type: {$label}\n"
            ."Urgence: {$state['urgency']}\n"
            .'Desc: '.($state['desc'] ?? '-')."\n"
            .'1. Confirmer'."\n"
            .'0. Annuler';
    }

    // ------------------------------------------------------------------
    // Session cache + réponses
    // ------------------------------------------------------------------

    /** @return array{step: string, school_id: ?int, school_code: ?string, school_name: ?string, type: ?string, urgency: ?string, desc: ?string, attempts: int} */
    private function freshState(): array
    {
        return [
            'step' => 'home',
            'school_id' => null,
            'school_code' => null,
            'school_name' => null,
            'type' => null,
            'urgency' => null,
            'desc' => null,
            'attempts' => 0,
        ];
    }

    /** @param array<string, mixed> $state */
    private function saveState(string $sid, array $state): void
    {
        Cache::put("ussd:session:{$sid}", $state, now()->addMinutes(self::SESSION_TTL_MINUTES));
    }

    private function forget(string $sid): void
    {
        Cache::forget("ussd:session:{$sid}");
    }

    private function sessionKey(string $sessionId): string
    {
        $safe = preg_replace('/[^A-Za-z0-9_.:-]/', '_', trim($sessionId)) ?: '';

        return $safe !== '' ? Str::limit($safe, 64, '') : sha1($sessionId);
    }

    /** @param array<string, mixed>|null $state */
    private function con(string $message, ?string $sid = null, ?array $state = null): string
    {
        if ($sid !== null && $state !== null) {
            $this->saveState($sid, $state);
        }

        return 'CON '.$message;
    }

    private function end(string $message): string
    {
        return 'END '.$message;
    }

    private function abort(string $sid, string $message): string
    {
        $this->forget($sid);

        return $this->end($message);
    }
}
