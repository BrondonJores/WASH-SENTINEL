<?php

namespace App\Services;

use App\Models\School;
use Illuminate\Support\Str;

/**
 * Grammaire SMS commune mesh + passerelles (dossier Phase 0) :
 *
 *   WASH <CODE_ECOLE> <TYPE> [DETAIL...]      (1 segment, ≤160 car.)
 *
 * TYPE : P (panne pompe/forage), L (latrine), E (eau/qualité), H (hygiène).
 * Même grammaire réutilisable en USSD et en bundle mesh (champ sms_text).
 */
class MeshSmsParser
{
    public const KEYWORDS = ['WASH', 'EAU'];

    public const TYPES = [
        'P' => ['label' => 'panne pompe/forage', 'words' => ['P', 'PANNE', 'POMPE', 'FORAGE']],
        'L' => ['label' => 'latrine', 'words' => ['L', 'LATRINE', 'LATRINES', 'WC', 'TOILETTE', 'TOILETTES']],
        'E' => ['label' => 'eau/qualité', 'words' => ['E', 'EAU', 'QUALITE', 'TROUBLE', 'SALE']],
        'H' => ['label' => 'hygiène', 'words' => ['H', 'HYGIENE', 'SAVON', 'LAVAGE']],
    ];

    public const HELP = 'Envoyez: WASH CODE TYPE. Ex: WASH DOU-BON-001 P (P=panne, L=latrine, E=eau, H=hygiene).';

    /**
     * @return array{ok: bool, school: ?School, type: ?string, type_label: ?string, detail: ?string, normalized: ?string, error: ?string}
     */
    public function parse(string $raw): array
    {
        $fail = fn (string $error) => [
            'ok' => false, 'school' => null, 'type' => null, 'type_label' => null,
            'detail' => null, 'normalized' => null, 'error' => $error,
        ];

        $tokens = preg_split('/\s+/', trim(Str::ascii(strtoupper($raw)))) ?: [];
        $tokens = array_values(array_filter($tokens));

        if (count($tokens) < 3) {
            return $fail(self::HELP);
        }
        if (! in_array($tokens[0], self::KEYWORDS, true)) {
            return $fail(self::HELP);
        }

        $school = $this->findSchool($tokens[1]);
        if (! $school) {
            return $fail("Code ecole '{$tokens[1]}' inconnu. ".self::HELP);
        }

        $type = $this->matchType($tokens[2]);
        if (! $type) {
            return $fail("Type '{$tokens[2]}' inconnu (P, L, E ou H). ".self::HELP);
        }

        $detail = Str::limit(trim(implode(' ', array_slice($tokens, 3))), 100, '');
        $normalized = "[SMS] {$school->name} : ".self::TYPES[$type]['label'].($detail !== '' ? " — {$detail}" : '');

        return [
            'ok' => true, 'school' => $school, 'type' => $type,
            'type_label' => self::TYPES[$type]['label'],
            'detail' => $detail !== '' ? $detail : null,
            'normalized' => $normalized, 'error' => null,
        ];
    }

    public function acknowledge(School $school, string $type, string $ticket): string
    {
        return Str::limit("WASH OK {$school->code} {$type} {$ticket} Merci!", 160, '');
    }

    /**
     * Extensions USSD (chantier V2) : le menu saisit le code école puis un
     * choix numérique, sans la grammaire « WASH CODE TYPE » complète.
     */
    public const USSD_TYPE_CHOICES = ['1' => 'P', '2' => 'L', '3' => 'E', '4' => 'H'];

    public function findSchoolByCode(string $code): ?School
    {
        $code = strtoupper(trim($code));
        if ($code === '') {
            return null;
        }

        return School::where('code', $code)->first()
            ?? School::where('code', str_replace('-', '', $code))->first()
            ?? School::whereRaw('UPPER(REPLACE(code, ?, ?)) = ?', ['-', '', str_replace('-', '', $code)])->first();
    }

    /**
     * Choix numérique USSD (1-4) ou lettre/mot-clé SMS (P, L, E, H…).
     */
    public function ussdChoiceToType(string $input): ?string
    {
        $token = strtoupper(trim($input));

        return self::USSD_TYPE_CHOICES[$token] ?? $this->matchType($token);
    }

    /**
     * Texte normalisé d'un signalement USSD (même forme que le SMS,
     * préfixe [USSD] + mention (URGENT) le cas échéant).
     */
    public function buildUssdMessage(School $school, string $type, ?string $urgency, ?string $detail): string
    {
        $label = self::TYPES[$type]['label'] ?? $type;
        $message = "[USSD] {$school->name} : {$label}";
        if ($urgency === 'urgente') {
            $message .= ' (URGENT)';
        }
        $detail = trim((string) ($detail ?? ''));
        if ($detail !== '') {
            $message .= " — {$detail}";
        }

        return $message;
    }

    private function findSchool(string $code): ?School
    {
        return $this->findSchoolByCode($code);
    }

    private function matchType(string $token): ?string
    {
        $token = strtoupper(trim($token));
        foreach (self::TYPES as $letter => $def) {
            if (in_array($token, $def['words'], true)) {
                return $letter;
            }
        }

        return null;
    }
}
