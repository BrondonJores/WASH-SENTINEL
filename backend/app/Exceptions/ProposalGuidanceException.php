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

    /** LOT 6 — texte FR (locale forcée, extraction pure, textes identiques). */
    protected static function fr(string $key, array $replace = []): string
    {
        return trans('wash.' . $key, $replace, 'fr');
    }

    public static function expired(AgentProposal $proposal, string $redraftPrompt): self
    {
        return new self(
            410,
            'expired',
            self::fr('guidance.expired', ['minutes' => config('wash.proposals.expiry_minutes'), 'prompt' => $redraftPrompt]),
            ['label' => self::fr('guidance.redraft_label'), 'prompt' => $redraftPrompt],
            ['proposal_id' => $proposal->id, 'action' => $proposal->action],
        );
    }

    public static function alreadyConfirmed(AgentProposal $proposal, ?array $created): self
    {
        $ref = is_array($created) ? ($created['reference_code'] ?? null) : null;
        $summary = is_array($created) ? ($created['summary'] ?? null) : null;
        $message = self::fr('guidance.already_done')
            . ($summary ? "{$summary} " : self::fr('guidance.already_validated'))
            . ($ref ? self::fr('guidance.already_see', ['ref' => $ref]) : self::fr('guidance.already_nothing'));
        $prompt = $ref ? self::fr('guidance.already_show_prompt', ['ref' => $ref]) : null;

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
            $prompt ? ['label' => self::fr('guidance.already_show_label'), 'prompt' => $prompt] : null,
            $extra,
        );
    }

    public static function conflict(AgentProposal $proposal, string $redraftPrompt): self
    {
        return new self(
            409,
            'conflict',
            self::fr('guidance.conflict', ['prompt' => $redraftPrompt]),
            ['label' => self::fr('guidance.redraft_label'), 'prompt' => $redraftPrompt],
            ['proposal_id' => $proposal->id, 'action' => $proposal->action],
        );
    }

    public static function refused(AgentProposal $proposal, string $reason): self
    {
        return new self(
            403,
            'forbidden',
            self::fr('guidance.refused', ['reason' => $reason]),
            ['label' => self::fr('guidance.refused_label'), 'prompt' => self::fr('guidance.refused_prompt')],
            ['proposal_id' => $proposal->id, 'action' => $proposal->action],
        );
    }

    public static function ownerMismatch(AgentProposal $proposal): self
    {
        return new self(
            403,
            'forbidden',
            self::fr('guidance.owner_mismatch'),
            null,
            ['proposal_id' => $proposal->id],
        );
    }
}
