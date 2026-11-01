<?php

namespace App\Services;

use App\Contracts\IncidentTriage;
use App\Exceptions\ProposalGuidanceException;
use App\Models\AgentProposal;
use App\Models\AiAnalysis;
use App\Models\Incident;
use App\Models\MaintenanceLog;
use App\Models\School;
use App\Models\User;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use Illuminate\Validation\ValidationException;
use Symfony\Component\HttpKernel\Exception\AccessDeniedHttpException;

class AgentProposalService
{
    /**
     * LOT 6 — valeurs conservées comme replis ; sources uniques :
     * config/wash.php (durées, listes, bornes) et lang/{fr,en}/wash.php
     * (libellés FR/EN). Textes FR lus avec locale 'fr' forcée (inchangés).
     */
    public const EXPIRY_MINUTES = 30;

    public const PERMISSIONS = [
        'create_report' => 'create reports',
        'create_incident' => 'edit incidents',
        'create_maintenance_log' => 'update incident status',
    ];

    public const CATEGORIES = ['water_point', 'toilets_latrines', 'handwashing', 'sewage_drainage'];
    public const URGENCIES = ['low', 'medium', 'high', 'critical'];

    public function __construct(protected IncidentTriage $triage) {}

    /** Texte FR (locale forcée, extraction pure). */
    protected function fr(string $key, array $replace = []): string
    {
        return trans('wash.' . $key, $replace, 'fr');
    }

    protected function categoryLabel(string $code): string
    {
        $label = $this->fr('categories.' . $code);

        return $label === 'wash.categories.' . $code ? $code : $label;
    }

    protected function urgencyLabel(string $code): string
    {
        $label = $this->fr('urgencies.' . $code);

        return $label === 'wash.urgencies.' . $code ? $code : $label;
    }

    public function draft(User $user, string $action, array $slots): array
    {
        $this->requirePermission($user, $action);
        $payload = $this->validateSlots($action, $slots);
        $proposal = AgentProposal::create([
            'user_id' => $user->id,
            'action' => $action,
            'payload' => $payload,
            'status' => AgentProposal::STATUS_PENDING,
            'expires_at' => now()->addMinutes(config('wash.proposals.expiry_minutes', self::EXPIRY_MINUTES)),
        ]);

        return ['proposal' => $proposal, 'recap_rows' => $this->recapRows($action, $payload)];
    }

    public function confirm(User $user, AgentProposal $proposal): array
    {
        $fresh = AgentProposal::findOrFail($proposal->id);
        if ($fresh->user_id !== $user->id) {
            throw ProposalGuidanceException::ownerMismatch($fresh);
        }
        if ($fresh->status === AgentProposal::STATUS_PENDING && $fresh->isExpired()) {
            $fresh->update(['status' => AgentProposal::STATUS_EXPIRED]);
        }

        return DB::transaction(function () use ($user, $proposal) {
            $proposal = AgentProposal::whereKey($proposal->id)->lockForUpdate()->firstOrFail();
            if ($proposal->user_id !== $user->id) {
                throw ProposalGuidanceException::ownerMismatch($proposal);
            }
            if ($proposal->status === AgentProposal::STATUS_EXPIRED || $proposal->isExpired()) {
                if ($proposal->status !== AgentProposal::STATUS_EXPIRED) {
                    $proposal->update(['status' => AgentProposal::STATUS_EXPIRED]);
                }
                throw ProposalGuidanceException::expired($proposal, $this->redraftPrompt($proposal));
            }
            if ($proposal->status === AgentProposal::STATUS_CONFIRMED) {
                throw ProposalGuidanceException::alreadyConfirmed($proposal, $this->createdRecord($proposal));
            }
            if ($proposal->status !== AgentProposal::STATUS_PENDING) {
                throw ProposalGuidanceException::conflict($proposal, $this->redraftPrompt($proposal));
            }
            try {
                $this->requirePermission($user, $proposal->action);
            } catch (AccessDeniedHttpException $e) {
                throw ProposalGuidanceException::refused($proposal, $e->getMessage());
            }
            $result = $this->execute($user, $proposal);
            $proposal->update(['status' => AgentProposal::STATUS_CONFIRMED]);
            AiAnalysis::create([
                'analysis_type' => 'agent_action',
                'input_payload' => [
                    'proposal_id' => $proposal->id,
                    'action' => $proposal->action,
                    'payload' => $proposal->payload,
                    'user_id' => $user->id,
                ],
                'output_payload' => $result,
                'model_used' => 'sentinel-guard',
            ]);

            return $result;
        });
    }

    public function cancel(User $user, AgentProposal $proposal): array
    {
        if ($proposal->user_id !== $user->id) {
            throw ProposalGuidanceException::ownerMismatch($proposal);
        }
        if ($proposal->status === AgentProposal::STATUS_CONFIRMED) {
            throw ProposalGuidanceException::alreadyConfirmed($proposal, $this->createdRecord($proposal));
        }
        $proposal->update(['status' => AgentProposal::STATUS_CANCELLED]);

        return [
            'status' => 'cancelled',
            'action' => $proposal->action,
            'summary' => $this->fr('proposal.cancelled'),
            'next_action' => ['label' => $this->fr('proposal.redraft_label'), 'prompt' => $this->redraftPrompt($proposal)],
        ];
    }

    /**
     * Prompt de relance pré-rempli pour refaire la demande en un clic.
     */
    protected function redraftPrompt(AgentProposal $proposal): string
    {
        $p = is_array($proposal->payload) ? $proposal->payload : [];
        $school = isset($p['school_name']) && is_string($p['school_name']) && $p['school_name'] !== ''
            ? $p['school_name']
            : null;

        return match ($proposal->action) {
            'create_report' => trim($this->fr('proposal.redraft_report', [
                'where' => $school ? $this->fr('proposal.redraft_at_school', ['school' => $school]) : $this->fr('proposal.redraft_a_problem'),
                'description' => Str::limit((string) ($p['description'] ?? $this->fr('proposal.redraft_a_problem')), config('wash.proposals.redraft_description_limit')),
            ])),
            'create_incident' => trim($this->fr('proposal.redraft_incident', [
                'where' => $school ? $this->fr('proposal.redraft_at_school', ['school' => $school]) : '',
                'title' => Str::limit((string) ($p['title'] ?? $this->fr('proposal.redraft_no_title')), config('wash.proposals.redraft_title_limit')),
            ])),
            'create_maintenance_log' => trim($this->fr('proposal.redraft_log', [
                'cost' => number_format((float) ($p['cost_amount'] ?? 0), 0, ',', ' '),
                'ref' => (string) ($p['incident_ref'] ?? $this->fr('proposal.redraft_the_incident')),
            ])),
            default => $this->fr('proposal.redraft_default'),
        };
    }

    /**
     * Retrouve l'objet créé par une proposition déjà confirmée (pour « Voir : … »).
     */
    protected function createdRecord(AgentProposal $proposal): ?array
    {
        $row = AiAnalysis::where('analysis_type', 'agent_action')
            ->where('input_payload->proposal_id', $proposal->id)
            ->latest()
            ->first();
        $out = $row?->output_payload;

        return is_array($out) ? $out : null;
    }

    protected function requirePermission(User $user, string $action): void
    {
        $perm = self::PERMISSIONS[$action] ?? null;
        if (!$perm) {
            throw ValidationException::withMessages(['action' => $this->fr('proposal.unknown_action')]);
        }
        if (!$user->can($perm)) {
            throw new AccessDeniedHttpException($this->fr('proposal.permission_required', ['permission' => $perm]));
        }
    }

    protected function validateSlots(string $action, array $slots): array
    {
        return match ($action) {
            'create_report' => $this->validateReport($slots),
            'create_incident' => $this->validateIncident($slots),
            'create_maintenance_log' => $this->validateLog($slots),
            default => throw ValidationException::withMessages(['action' => $this->fr('proposal.unknown_action')]),
        };
    }

    protected function validateReport(array $s): array
    {
        $school = $this->needSchool($s);
        $description = trim((string) ($s['description'] ?? ''));
        $descMax = config('wash.proposals.description_max_chars');
        if ($description === '' || mb_strlen($description) > $descMax) {
            throw ValidationException::withMessages(['description' => $this->fr('proposal.description_required', ['max' => $descMax])]);
        }

        return [
            'school_id' => $school->id,
            'school_name' => $school->name,
            'description' => $description,
            'category' => $this->needEnum($s, 'category', config('wash.categories', self::CATEGORIES)),
            'urgency' => $this->needEnum($s, 'urgency', config('wash.urgencies', self::URGENCIES)),
            'affected_students' => $this->needInt($s, 'affected_students', config('wash.proposals.affected_students_min'), config('wash.proposals.affected_students_max')),
        ];
    }

    protected function validateIncident(array $s): array
    {
        $school = $this->needSchool($s);
        $title = trim((string) ($s['title'] ?? ''));
        $titleMin = config('wash.proposals.title_min_chars');
        $titleMax = config('wash.proposals.title_max_chars');
        if (mb_strlen($title) < $titleMin || mb_strlen($title) > $titleMax) {
            throw ValidationException::withMessages(['title' => $this->fr('proposal.title_required', ['min' => $titleMin, 'max' => $titleMax])]);
        }

        return [
            'school_id' => $school->id,
            'school_name' => $school->name,
            'title' => $title,
            'category' => $this->needEnum($s, 'category', config('wash.categories', self::CATEGORIES)),
            'urgency' => $this->needEnum($s, 'urgency', config('wash.urgencies', self::URGENCIES)),
            'affected_students' => $this->needInt($s, 'affected_students', config('wash.proposals.affected_students_min'), config('wash.proposals.affected_students_max')),
        ];
    }

    protected function validateLog(array $s): array
    {
        $incident = null;
        if (isset($s['incident_id']) && is_numeric($s['incident_id'])) {
            $incident = Incident::find((int) $s['incident_id']);
        }
        if (!$incident && isset($s['incident_ref']) && is_string($s['incident_ref'])) {
            $incident = Incident::where('reference_code', trim($s['incident_ref']))->first();
        }
        if (!$incident) {
            throw ValidationException::withMessages(['incident' => $this->fr('proposal.incident_not_found')]);
        }
        if (!isset($s['cost_amount']) || !is_numeric($s['cost_amount']) || (float) $s['cost_amount'] < config('wash.proposals.cost_min') || (float) $s['cost_amount'] > config('wash.proposals.cost_max')) {
            throw ValidationException::withMessages(['cost_amount' => $this->fr('proposal.cost_required')]);
        }
        $notes = isset($s['notes']) ? trim((string) $s['notes']) : null;
        $notesMax = config('wash.proposals.notes_max_chars');
        if ($notes !== null && mb_strlen($notes) > $notesMax) {
            throw ValidationException::withMessages(['notes' => $this->fr('proposal.notes_too_long', ['max' => $notesMax])]);
        }
        $days = $s['days_without_service'] ?? null;
        if ($days !== null && (!is_numeric($days) || (int) $days < config('wash.proposals.days_without_service_min') || (int) $days > config('wash.proposals.days_without_service_max'))) {
            throw ValidationException::withMessages(['days_without_service' => $this->fr('proposal.days_invalid')]);
        }

        return [
            'incident_id' => $incident->id,
            'incident_ref' => $incident->reference_code,
            'incident_title' => $incident->title,
            'school_id' => $incident->school_id,
            'school_name' => $incident->school?->name,
            'cost_amount' => (float) $s['cost_amount'],
            'notes' => $notes ?: null,
            'days_without_service' => $days !== null ? (int) $days : null,
        ];
    }

    protected function needSchool(array $s): School
    {
        $school = isset($s['school_id']) && is_numeric($s['school_id'])
            ? School::find((int) $s['school_id'])
            : null;
        if (!$school) {
            throw ValidationException::withMessages(['school_id' => $this->fr('proposal.school_not_found')]);
        }

        return $school;
    }

    protected function needEnum(array $s, string $key, array $allowed): string
    {
        $value = $s[$key] ?? null;
        if (!is_string($value) || !in_array($value, $allowed, true)) {
            throw ValidationException::withMessages([$key => $this->fr('proposal.enum_invalid', ['key' => $key])]);
        }

        return $value;
    }

    protected function needInt(array $s, string $key, int $min, int $max): int
    {
        $value = $s[$key] ?? null;
        if (!is_numeric($value) || (int) $value < $min || (int) $value > $max) {
            throw ValidationException::withMessages([$key => $this->fr('proposal.int_invalid', ['key' => $key])]);
        }

        return (int) $value;
    }

    protected function execute(User $user, AgentProposal $proposal): array
    {
        $p = $proposal->payload;

        return match ($proposal->action) {
            'create_report' => $this->executeReport($user, $p),
            'create_incident' => $this->executeIncident($user, $p),
            'create_maintenance_log' => $this->executeLog($user, $p),
        };
    }

    protected function executeReport(User $user, array $p): array
    {
        $school = School::findOrFail($p['school_id']);
        $out = $this->triage->ingest($school, 'text', $p['description'], null, null, $user, 'agent', [
            'category' => $p['category'],
            'urgency' => $p['urgency'],
            'affected_students' => $p['affected_students'],
        ]);
        $report = $out['report'];
        $incident = $out['incident'];

        return [
            'status' => 'confirmed',
            'action' => 'create_report',
            'summary' => $out['is_duplicate']
                ? $this->fr('proposal.report_attached', ['id' => $report->id, 'ref' => $incident->reference_code])
                : $this->fr('proposal.report_created', ['id' => $report->id, 'ref' => $incident->reference_code, 'urgency' => $incident->urgency]),
            'report_id' => $report->id,
            'incident_id' => $incident->id,
            'reference_code' => $incident->reference_code,
            'is_duplicate' => $out['is_duplicate'],
        ];
    }

    protected function executeIncident(User $user, array $p): array
    {
        $school = School::findOrFail($p['school_id']);
        $incident = $this->triage->createManualIncident($school, $p, $user);

        return [
            'status' => 'confirmed',
            'action' => 'create_incident',
            'summary' => $this->fr('proposal.incident_created', ['ref' => $incident->reference_code, 'title' => $incident->title]),
            'incident_id' => $incident->id,
            'reference_code' => $incident->reference_code,
        ];
    }

    protected function executeLog(User $user, array $p): array
    {
        $incident = Incident::findOrFail($p['incident_id']);
        $log = MaintenanceLog::create([
            'incident_id' => $incident->id,
            'school_id' => $incident->school_id,
            'performed_by' => $user->id,
            'cost_amount' => $p['cost_amount'],
            'currency' => 'XAF',
            'repaired_at' => now(),
            'days_without_service' => $p['days_without_service'] ?? 0,
            'notes' => $p['notes'],
        ]);

        return [
            'status' => 'confirmed',
            'action' => 'create_maintenance_log',
            'summary' => $this->fr('proposal.log_created', ['ref' => $incident->reference_code, 'cost' => number_format($log->cost_amount, 0, ',', ' ')]),
            'log_id' => $log->id,
            'incident_id' => $incident->id,
            'reference_code' => $incident->reference_code,
        ];
    }

    protected function recapRows(string $action, array $p): array
    {
        $rows = [['label' => $this->fr('proposal.recap_school'), 'value' => (string) ($p['school_name'] ?? $this->fr('proposal.recap_missing'))]];
        if ($action === 'create_report') {
            $rows[] = ['label' => $this->fr('proposal.recap_description'), 'value' => Str::limit((string) $p['description'], config('wash.proposals.recap_limit'))];
            $rows[] = ['label' => $this->fr('proposal.recap_category'), 'value' => $this->categoryLabel($p['category'])];
            $rows[] = ['label' => $this->fr('proposal.recap_urgency'), 'value' => $this->urgencyLabel($p['urgency'])];
            $rows[] = ['label' => $this->fr('proposal.recap_affected'), 'value' => (string) $p['affected_students']];
        } elseif ($action === 'create_incident') {
            $rows[] = ['label' => $this->fr('proposal.recap_title'), 'value' => (string) $p['title']];
            $rows[] = ['label' => $this->fr('proposal.recap_category'), 'value' => $this->categoryLabel($p['category'])];
            $rows[] = ['label' => $this->fr('proposal.recap_urgency'), 'value' => $this->urgencyLabel($p['urgency'])];
            $rows[] = ['label' => $this->fr('proposal.recap_affected'), 'value' => (string) $p['affected_students']];
        } else {
            $rows[] = ['label' => $this->fr('proposal.recap_incident'), 'value' => "{$p['incident_ref']} — {$p['incident_title']}"];
            $rows[] = ['label' => $this->fr('proposal.recap_cost'), 'value' => number_format((float) $p['cost_amount'], 0, ',', ' ') . ' XAF'];
            if (!empty($p['notes'])) {
                $rows[] = ['label' => $this->fr('proposal.recap_notes'), 'value' => Str::limit((string) $p['notes'], config('wash.proposals.recap_limit'))];
            }
            if ($p['days_without_service'] !== null) {
                $rows[] = ['label' => $this->fr('proposal.recap_days'), 'value' => (string) $p['days_without_service']];
            }
        }

        return $rows;
    }
}
