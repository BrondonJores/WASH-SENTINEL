<?php

namespace App\Exceptions;

use App\Models\AgentProposal;
use Symfony\Component\HttpKernel\Exception\HttpException;

/**
 * Erreur de confirmation de proposition avec guidage FR structuré.
 *
 * Le front n'affiche jamais un code brut (409/410) : il reçoit toujours
 * { status, message, next_action } + le prompt de relance éventuel.
 */
class ProposalGuidanceException extends HttpException
{
    public function __construct(
        int $statusCode,
        private string $guidanceStatus,
        string $message,
        private ?array $nextAction = null,
        private array $extra = [],
    ) {
        parent::__construct($statusCode, $message);
    }

    public function guidanceStatus(): string
    {
        return $this->guidanceStatus;
    }

    public function nextAction(): ?array
    {
        return $this->nextAction;
    }

    public function guidance(): array
    {
        return array_merge([
            'status' => $this->guidanceStatus,
            'message' => $this->getMessage(),
            'next_action' => $this->nextAction,
        ], $this->extra);
    }

    public function render($request)
    {
        return response()->json($this->guidance(), $this->getStatusCode());
    }

    public static function expired(AgentProposal $proposal, string $redraftPrompt): self
    {
        return new self(
            410,
            'expired',
            "Ce dossier a expiré (30 min). Redemandez un récapitulatif : « {$redraftPrompt} ».",
            ['label' => 'Refaire la demande', 'prompt' => $redraftPrompt],
            ['proposal_id' => $proposal->id, 'action' => $proposal->action],
        );
    }

    public static function alreadyConfirmed(AgentProposal $proposal, ?array $created): self
    {
        $ref = is_array($created) ? ($created['reference_code'] ?? null) : null;
        $summary = is_array($created) ? ($created['summary'] ?? null) : null;
        $message = 'Déjà enregistré ! '
            . ($summary ? "{$summary} " : 'Cette demande a déjà été validée. ')
            . ($ref ? "Voir : {$ref}." : 'Rien de plus à valider.');
        $prompt = $ref ? "Affiche le dossier {$ref}" : null;

        $extra = ['proposal_id' => $proposal->id, 'action' => $proposal->action];
        foreach (['reference_code', 'incident_id', 'report_id', 'log_id'] as $key) {
            if (is_array($created) && isset($created[$key])) {
                $extra[$key] = $created[$key];
            }
        }

        return new self(
            409,
            'already_confirmed',
            trim($message),
            $prompt ? ['label' => 'Voir le dossier', 'prompt' => $prompt] : null,
            $extra,
        );
    }

    public static function conflict(AgentProposal $proposal, string $redraftPrompt): self
    {
        return new self(
            409,
            'conflict',
            "Quelqu'un l'a déjà traité : cette demande a été annulée et rien n'a été créé. "
                . "Si besoin, refaites la demande : « {$redraftPrompt} ».",
            ['label' => 'Refaire la demande', 'prompt' => $redraftPrompt],
            ['proposal_id' => $proposal->id, 'action' => $proposal->action],
        );
    }

    public static function refused(AgentProposal $proposal, string $reason): self
    {
        return new self(
            403,
            'forbidden',
            "Action refusée : {$reason} Rien n'a été créé. "
                . 'Vérifiez votre rôle ou demandez à un administrateur.',
            ['label' => 'Voir mes actions possibles', 'prompt' => 'Que puis-je faire avec mon rôle ?'],
            ['proposal_id' => $proposal->id, 'action' => $proposal->action],
        );
    }

    public static function ownerMismatch(AgentProposal $proposal): self
    {
        return new self(
            403,
            'forbidden',
            "Cette proposition appartient à un autre utilisateur. Rien n'a été créé sur votre compte.",
            null,
            ['proposal_id' => $proposal->id],
        );
    }
}
