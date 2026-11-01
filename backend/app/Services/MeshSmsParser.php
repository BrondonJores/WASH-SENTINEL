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
    /**
     * CONTRAT GSM (LOT 7 — valeurs intouchables, volontairement en CONST et
     * PAS en config) :
     * - ACK_MAX_LENGTH = 160 : un accusé tient dans UN segment GSM 7-bit.
     *   L'augmenter casserait les modems SMSSync et doublerait les coûts.
     * - HELP : texte d'aide historique, repris tel quel dans les erreurs et
     *   renvoyé par SMS aux expéditeurs. Ne jamais reformuler sans valider
     *   avec les relais terrain (même grammaire en USSD et bundle mesh).
     */
    public const KEYWORDS = ['WASH', 'EAU'];

    public const TYPES = [
        'P' => ['label' => 'panne pompe/forage', 'words' => ['P', 'PANNE', 'POMPE', 'FORAGE']],
        'L' => ['label' => 'latrine', 'words' => ['L', 'LATRINE', 'LATRINES', 'WC', 'TOILETTE', 'TOILETTES']],
        'E' => ['label' => 'eau/qualité', 'words' => ['E', 'EAU', 'QUALITE', 'TROUBLE', 'SALE']],
        'H' => ['label' => 'hygiène', 'words' => ['H', 'HYGIENE', 'SAVON', 'LAVAGE']],
    ];

    public const HELP = 'Envoyez: WASH CODE TYPE. Ex: WASH DOU-BON-001 P (P=panne, L=latrine, E=eau, H=hygiene).';

    /** Longueur max du détail libre (caractères, troncature silencieuse). */
    public const DETAIL_MAX_LENGTH = 100;

    /** Longueur max de l'accusé (1 segment GSM 7-bit, voir contrat). */
    public const ACK_MAX_LENGTH = 160;

    /** Gabarit de l'accusé : code école, type, ticket (ordre inchangé). */
    public const ACK_TEMPLATE = 'WASH OK %s %s %s Merci!';

    /** Nombre min de mots : « WASH CODE TYPE » (détail optionnel). */
    public const MIN_TOKENS = 3;

    /** Séparateur de mots (espaces, tabulations, retours chariot). */
    public const TOKEN_SPLIT_PATTERN = '/\s+/';

    /** Gabarits d'erreur (HELP concaténé par l'appelant, inchangé). */
    public const UNKNOWN_SCHOOL_ERROR = "Code ecole '%s' inconnu. ";

    public const UNKNOWN_TYPE_ERROR = "Type '%s' inconnu (P, L, E ou H). ";

    /** Préfixes de normalisation (même forme SMS et USSD). */
    public const PREFIX_SMS = '[SMS]';

    public const PREFIX_USSD = '[USSD]';

    /** Séparateur école/label — détail dans le texte normalisé. */
    public const NORMALIZED_SEPARATOR = ' — ';

    /** Valeur d'urgence déclenchant la mention (URGENT) en USSD. */
    public const URGENT_URGENCY = 'urgente';

    /** Mention accolée au libellé quand l'urgence est 'urgente'. */
    public const URGENT_TAG = ' (URGENT)';

    /**
     * @return array{ok: bool, school: ?School, type: ?string, type_label: ?string, detail: ?string, normalized: ?string, error: ?string}
     */
    public function parse(string $raw): array
    {
        $fail = fn (string $error) => [
            'ok' => false, 'school' => null, 'type' => null, 'type_label' => null,
            'detail' => null, 'normalized' => null, 'error' => $error,
        ];

        $tokens = preg_split(self::TOKEN_SPLIT_PATTERN, trim(Str::ascii(strtoupper($raw)))) ?: [];
        $tokens = array_values(array_filter($tokens));

        if (count($tokens) < self::MIN_TOKENS) {
            return $fail(self::HELP);
        }
        if (! in_array($tokens[0], self::KEYWORDS, true)) {
            return $fail(self::HELP);
        }

        $school = $this->findSchool($tokens[1]);
        if (! $school) {
            return $fail(sprintf(self::UNKNOWN_SCHOOL_ERROR, $tokens[1]).self::HELP);
        }

        $type = $this->matchType($tokens[2]);
        if (! $type) {
            return $fail(sprintf(self::UNKNOWN_TYPE_ERROR, $tokens[2]).self::HELP);
        }

        $detail = Str::limit(trim(implode(' ', array_slice($tokens, 3))), self::DETAIL_MAX_LENGTH, '');
        $normalized = self::PREFIX_SMS." {$school->name} : ".self::TYPES[$type]['label'].($detail !== '' ? self::NORMALIZED_SEPARATOR.$detail : '');

        return [
            'ok' => true, 'school' => $school, 'type' => $type,
            'type_label' => self::TYPES[$type]['label'],
            'detail' => $detail !== '' ? $detail : null,
            'normalized' => $normalized, 'error' => null,
        ];
    }

    public function acknowledge(School $school, string $type, string $ticket): string
    {
        return Str::limit(sprintf(self::ACK_TEMPLATE, $school->code, $type, $ticket), self::ACK_MAX_LENGTH, '');
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
        $message = self::PREFIX_USSD." {$school->name} : {$label}";
        if ($urgency === self::URGENT_URGENCY) {
            $message .= self::URGENT_TAG;
        }
        $detail = trim((string) ($detail ?? ''));
        if ($detail !== '') {
            $message .= self::NORMALIZED_SEPARATOR.$detail;
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
