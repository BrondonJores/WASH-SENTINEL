<?php

namespace App\Services;

/**
 * Personnalité conversationnelle de l'assistant WhatsApp WASH Sentinel.
 *
 * replyFor() retourne null quand le message n'est pas conversationnel
 * (ex. un vrai signalement de panne), sinon une réponse chaleureuse
 * style SMS (courte, sans jargon).
 *
 * LOT 7 : les 8 textes vivent dans lang/{fr,en}/wash.php ('personality.*',
 * locale forcée selon la langue détectée, textes strictement identiques
 * aux littéraux d'origine) ; les patterns de détection sont des
 * constantes ci-dessous (valeurs inchangées).
 */
class WashWhatsAppPersonality
{
    /** Salutations FR/EN (match “…contient…”, voir isGreeting pour le tri). */
    private const GREETING_PATTERNS_FR = ['/\bbonjour\b/', '/\bbonsoir\b/', '/\bsalut\b/', '/\bcoucou\b/', '/\bcoukou\b/', '/\bcc\b/'];

    private const GREETING_PATTERNS_EN = ['/\bhello\b/', '/\bhi\b/', '/\bhey\b/', '/\byo\b/', '/\bgood morning\b/', '/\bgood afternoon\b/', '/\bgood evening\b/'];

    /** « Qui es-tu ? » (texte normalisé : minuscules, sans accents). */
    private const IDENTITY_PATTERNS_FR = [
        '/\bqui es[ -]?tu\b/',
        '/\bqui etes[ -]?vous\b/',
        '/\bton nom\b/',
        '/\bton prenom\b/',
        '/\bvotre nom\b/',
        '/tu t appelle/',
        '/vous vous appelez/',
        '/vous etes qui/',
        '/t es qui/',
        '/c est quoi sentinel/',
        '/sentinel c est quoi/',
        '/qui est sentinel/',
        '/c quoi sentinel/',
        '/qu est ce que sentinel/',
        '/presente toi/',
        '/presentez vous/',
    ];

    private const IDENTITY_PATTERNS_EN = [
        '/\bwho are you\b/',
        '/\byour name\b/',
        '/\bwhat is sentinel\b/',
        '/\bwho is sentinel\b/',
    ];

    /** « Que sais-tu faire ? / aide » (texte normalisé). */
    private const CAPABILITY_PATTERNS_FR = [
        '/\bque fais[ -]?tu\b/',
        '/\bque faites[ -]?vous\b/',
        '/\ba quoi tu sers\b/',
        '/\ba quoi vous servez\b/',
        '/\bque peux[ -]?tu faire\b/',
        '/\bque pouvez[ -]?vous faire\b/',
        '/\bque sais[ -]?tu faire\b/',
        '/\btu sers a quoi\b/',
        '/\bvous servez a quoi\b/',
        '/\baide\b/',
        '/\baidez[ -]?moi\b/',
        '/comment ca marche/',
        '/comment fonctionne/',
        '/\bmode d emploi\b/',
    ];

    private const CAPABILITY_PATTERNS_EN = [
        '/\bwhat can you do\b/',
        '/\bwhat do you do\b/',
        '/\bhow does it work\b/',
        '/\bhow do you work\b/',
        '/\bhelp\b/',
    ];

    /** Remerciements (texte normalisé). */
    private const THANKS_PATTERNS_FR = ['/\bmerci\b/'];

    private const THANKS_PATTERNS_EN = ['/\bthank\b/', '/\bthanks\b/', '/\bthx\b/'];

    /** Mots retirés pour décider « salutation pure » (texte normalisé). */
    private const GREETING_TOKENS = ['bonjour', 'bonsoir', 'bonne journee', 'bonne soiree', 'salut', 'coucou', 'coukou', 'cc', 'hello', 'hi', 'hey', 'yo', 'good morning', 'good afternoon', 'good evening'];

    /** Restes autorisés après retrait des salutations (« ça va ? », …). */
    private const POLITENESS_COMPACTS = ['cava', 'commentcava', 'commentvastu', 'commentallezvous', 'howareyou', 'howisitgoing'];

    /** Apostrophes/accents graves neutralisés par normalize(). */
    private const NORMALIZE_APOSTROPHES = ['’', '‘', "'", '`'];

    /** Garde [a-z0-9 + ponctuation SMS] pendant normalize(). */
    private const NORMALIZE_KEEP_PATTERN = '/[^a-z0-9\s\'?!\-]/';

    private const NORMALIZE_SPACES_PATTERN = '/\s+/';

    /** Ne garde que les lettres pour comparer aux formules de politesse. */
    private const POLITENESS_STRIP_PATTERN = '/[^a-z]/';

    public function replyFor(?string $text): ?string
    {
        if ($text === null) {
            return null;
        }

        $normalized = $this->normalize($text);
        if ($normalized === '') {
            return null;
        }

        if ($this->matches($normalized, self::IDENTITY_PATTERNS_EN) || $this->matches($normalized, self::IDENTITY_PATTERNS_FR)) {
            return $this->text('identity', $this->matches($normalized, self::IDENTITY_PATTERNS_EN));
        }

        if ($this->matches($normalized, self::CAPABILITY_PATTERNS_EN) || $this->matches($normalized, self::CAPABILITY_PATTERNS_FR)) {
            return $this->text('capabilities', $this->matches($normalized, self::CAPABILITY_PATTERNS_EN));
        }

        if ($this->matches($normalized, self::THANKS_PATTERNS_EN) || $this->matches($normalized, self::THANKS_PATTERNS_FR)) {
            return $this->text('thanks', $this->matches($normalized, self::THANKS_PATTERNS_EN));
        }

        if ($this->isGreeting($normalized)) {
            return $this->text('greeting', $this->matches($normalized, self::GREETING_PATTERNS_EN));
        }

        return null;
    }

    /** Texte lang/{fr,en}/wash.php (locale forcée, extraction pure). */
    private function text(string $key, bool $english): string
    {
        return trans('wash.personality.'.$key, [], $english ? 'en' : 'fr');
    }

    /** Normalise : minuscules, sans accents, espaces condensees. */
    private function normalize(string $text): string
    {
        $lower = mb_strtolower(trim($text), 'UTF-8');
        $lower = str_replace(self::NORMALIZE_APOSTROPHES, ' ', $lower);
        $ascii = iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $lower);
        if ($ascii === false) {
            $ascii = $lower;
        }
        $ascii = preg_replace(self::NORMALIZE_KEEP_PATTERN, ' ', $ascii) ?? '';
        $ascii = preg_replace(self::NORMALIZE_SPACES_PATTERN, ' ', $ascii) ?? '';

        return trim($ascii);
    }

    /** @param string[] $patterns */
    private function matches(string $normalized, array $patterns): bool
    {
        foreach ($patterns as $pattern) {
            if (preg_match($pattern, $normalized) === 1) {
                return true;
            }
        }

        return false;
    }

    /**
     * Salutation pure uniquement (pas un signalement qui commence par
     * "bonjour...") : le message ne contient que des salutations et
     * eventuellement une formule de politesse courte.
     */
    private function isGreeting(string $normalized): bool
    {
        if (
            !$this->matches($normalized, self::GREETING_PATTERNS_FR)
            && !$this->matches($normalized, self::GREETING_PATTERNS_EN)
        ) {
            return false;
        }

        $stripped = $normalized;
        foreach (self::GREETING_TOKENS as $token) {
            $stripped = preg_replace('/\b' . preg_quote($token, '/') . '\b/', ' ', $stripped) ?? $stripped;
        }
        // Il ne reste que ponctuation / politesse courte (ex. "ça va ?").
        $compact = preg_replace(self::POLITENESS_STRIP_PATTERN, '', $stripped) ?? '';

        if ($compact === '') {
            return true;
        }

        return in_array($compact, self::POLITENESS_COMPACTS, true);
    }
}
