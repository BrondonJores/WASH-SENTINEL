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
    public const EXPIRY_MINUTES = 30;

    public const PERMISSIONS = [
        'create_report' => 'create reports',
        'create_incident' => 'edit incidents',
        'create_maintenance_log' => 'update incident status',
    ];

    public const CATEGORIES = ['water_point', 'toilets_latrines', 'handwashing', 'sewage_drainage'];
    public const URGENCIES = ['low', 'medium', 'high', 'critical'];

    public const CATEGORY_FR = [
        'water_point' => "Point d'eau",
        'toilets_latrines' => 'Toilettes / latrines',
        'handwashing' => 'Lavage des mains',
        'sewage_drainage' => 'Évacuation / drainage',
    ];

    public const URGENCY_FR = [
        'low' => 'Basse',
        'medium' => 'Moyenne',
        'high' => 'Haute',
        'critical' => 'Critique',
    ];

    public function __construct(protected IncidentTriage $triage) {}

    public function draft(User $user, string $action, array $slots): array
    {
        $this->requirePermission($user, $action);
        $payload = $this->validateSlots($action, $slots);
        $proposal = AgentProposal::create([
            'user_id' => $user->id,
            'action' => $action,
            'payload' => $payload,
            'status' => AgentProposal::STATUS_PENDING,
            'expires_at' => now()->addMinutes(self::EXPIRY_MINUTES),
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
            'summary' => "Proposition annulée, rien n'a été créé.",
            'next_action' => ['label' => 'Refaire la demande', 'prompt' => $this->redraftPrompt($proposal)],
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
            'create_report' => trim(sprintf(
                'Signale %s: %s',
                $school ? "à {$school}" : 'un problème',
                Str::limit((string) ($p['description'] ?? 'un problème'), 120)
            )),
            'create_incident' => trim(sprintf(
                'Crée une intervention %s: %s',
                $school ? "à {$school}" : '',
                Str::limit((string) ($p['title'] ?? 'sans titre'), 100)
            )),
            'create_maintenance_log' => trim(sprintf(
                'Journalise %s XAF sur %s',
                number_format((float) ($p['cost_amount'] ?? 0), 0, ',', ' '),
                (string) ($p['incident_ref'] ?? "l'incident")
            )),
            default => 'Refais ma demande',
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
            throw ValidationException::withMessages(['action' => 'Action inconnue.']);
        }
        if (!$user->can($perm)) {
            throw new AccessDeniedHttpException("Permission « {$perm} » requise.");
        }
    }

    protected function validateSlots(string $action, array $slots): array
    {
        return match ($action) {
            'create_report' => $this->validateReport($slots),
            'create_incident' => $this->validateIncident($slots),
            'create_maintenance_log' => $this->validateLog($slots),
            default => throw ValidationException::withMessages(['action' => 'Action inconnue.']),
        };
    }

    protected function validateReport(array $s): array
    {
        $school = $this->needSchool($s);
        $description = trim((string) ($s['description'] ?? ''));
        if ($description === '' || mb_strlen($description) > 2000) {
            throw ValidationException::withMessages(['description' => 'Description requise (2000 caractères max).']);
        }

        return [
            'school_id' => $school->id,
            'school_name' => $school->name,
            'description' => $description,
            'category' => $this->needEnum($s, 'category', self::CATEGORIES),
            'urgency' => $this->needEnum($s, 'urgency', self::URGENCIES),
            'affected_students' => $this->needInt($s, 'affected_students', 0, 100000),
        ];
    }

    protected function validateIncident(array $s): array
    {
        $school = $this->needSchool($s);
        $title = trim((string) ($s['title'] ?? ''));
        if (mb_strlen($title) < 3 || mb_strlen($title) > 120) {
            throw ValidationException::withMessages(['title' => 'Titre requis (3 à 120 caractères).']);
        }

        return [
            'school_id' => $school->id,
            'school_name' => $school->name,
            'title' => $title,
            'category' => $this->needEnum($s, 'category', self::CATEGORIES),
            'urgency' => $this->needEnum($s, 'urgency', self::URGENCIES),
            'affected_students' => $this->needInt($s, 'affected_students', 0, 100000),
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
            throw ValidationException::withMessages(['incident' => 'Incident introuvable, précisez son numéro ou sa référence.']);
        }
        if (!isset($s['cost_amount']) || !is_numeric($s['cost_amount']) || (float) $s['cost_amount'] < 0 || (float) $s['cost_amount'] > 1000000000) {
            throw ValidationException::withMessages(['cost_amount' => 'Coût requis, en XAF, positif.']);
        }
        $notes = isset($s['notes']) ? trim((string) $s['notes']) : null;
        if ($notes !== null && mb_strlen($notes) > 2000) {
            throw ValidationException::withMessages(['notes' => 'Notes limitées à 2000 caractères.']);
        }
        $days = $s['days_without_service'] ?? null;
        if ($days !== null && (!is_numeric($days) || (int) $days < 0 || (int) $days > 3650)) {
            throw ValidationException::withMessages(['days_without_service' => 'Jours sans service invalides.']);
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
            throw ValidationException::withMessages(['school_id' => 'École introuvable, précisez son nom.']);
        }

        return $school;
    }

    protected function needEnum(array $s, string $key, array $allowed): string
    {
        $value = $s[$key] ?? null;
        if (!is_string($value) || !in_array($value, $allowed, true)) {
            throw ValidationException::withMessages([$key => 'Valeur invalide pour ' . $key . '.']);
        }

        return $value;
    }

    protected function needInt(array $s, string $key, int $min, int $max): int
    {
        $value = $s[$key] ?? null;
        if (!is_numeric($value) || (int) $value < $min || (int) $value > $max) {
            throw ValidationException::withMessages([$key => "Nombre invalide pour {$key}."]);
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
                ? "Signalement #{$report->id} rattaché à l'incident {$incident->reference_code} (doublon détecté)."
                : "Signalement #{$report->id} créé, incident {$incident->reference_code} ({$incident->urgency}).",
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
            'summary' => "Intervention {$incident->reference_code} créée : {$incident->title}.",
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
            'summary' => "Intervention journalisée sur {$incident->reference_code} : " . number_format($log->cost_amount, 0, ',', ' ') . ' XAF.',
            'log_id' => $log->id,
            'incident_id' => $incident->id,
            'reference_code' => $incident->reference_code,
        ];
    }

    protected function recapRows(string $action, array $p): array
    {
        $rows = [['label' => 'École', 'value' => (string) ($p['school_name'] ?? '—')]];
        if ($action === 'create_report') {
            $rows[] = ['label' => 'Description', 'value' => Str::limit((string) $p['description'], 200)];
            $rows[] = ['label' => 'Catégorie', 'value' => self::CATEGORY_FR[$p['category']] ?? $p['category']];
            $rows[] = ['label' => 'Urgence', 'value' => self::URGENCY_FR[$p['urgency']] ?? $p['urgency']];
            $rows[] = ['label' => 'Élèves affectés', 'value' => (string) $p['affected_students']];
        } elseif ($action === 'create_incident') {
            $rows[] = ['label' => 'Titre', 'value' => (string) $p['title']];
            $rows[] = ['label' => 'Catégorie', 'value' => self::CATEGORY_FR[$p['category']] ?? $p['category']];
            $rows[] = ['label' => 'Urgence', 'value' => self::URGENCY_FR[$p['urgency']] ?? $p['urgency']];
            $rows[] = ['label' => 'Élèves affectés', 'value' => (string) $p['affected_students']];
        } else {
            $rows[] = ['label' => 'Incident', 'value' => "{$p['incident_ref']} — {$p['incident_title']}"];
            $rows[] = ['label' => 'Coût', 'value' => number_format((float) $p['cost_amount'], 0, ',', ' ') . ' XAF'];
            if (!empty($p['notes'])) {
                $rows[] = ['label' => 'Notes', 'value' => Str::limit((string) $p['notes'], 200)];
            }
            if ($p['days_without_service'] !== null) {
                $rows[] = ['label' => 'Jours sans service', 'value' => (string) $p['days_without_service']];
            }
        }

        return $rows;
    }
}
