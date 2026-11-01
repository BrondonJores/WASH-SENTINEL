<?php

namespace App\Services;

/**
 * Personnalité conversationnelle de l'assistant WhatsApp WASH Sentinel.
 *
 * Classe pure (aucune dépendance Laravel), testable directement :
 * replyFor() retourne null quand le message n'est pas conversationnel
 * (ex. un vrai signalement de panne), sinon une réponse chaleureuse
 * style SMS (courte, sans jargon).
 */
class WashWhatsAppPersonality
{
    public function replyFor(?string $text): ?string
    {
        if ($text === null) {
            return null;
        }

        $normalized = $this->normalize($text);
        if ($normalized === '') {
            return null;
        }

        if ($this->matches($normalized, $this->identityPatternsEn()) || $this->matches($normalized, $this->identityPatternsFr())) {
            return $this->matches($normalized, $this->identityPatternsEn()) ? self::IDENTITY_EN : self::IDENTITY_FR;
        }

        if ($this->matches($normalized, $this->capabilityPatternsEn()) || $this->matches($normalized, $this->capabilityPatternsFr())) {
            return $this->matches($normalized, $this->capabilityPatternsEn()) ? self::CAPABILITIES_EN : self::CAPABILITIES_FR;
        }

        if ($this->matches($normalized, $this->thanksPatternsEn()) || $this->matches($normalized, $this->thanksPatternsFr())) {
            return $this->matches($normalized, $this->thanksPatternsEn()) ? self::THANKS_EN : self::THANKS_FR;
        }

        if ($this->isGreeting($normalized)) {
            return $this->matches($normalized, $this->greetingPatternsEn()) ? self::GREETING_EN : self::GREETING_FR;
        }

        return null;
    }

    private const GREETING_FR = 'Bonjour ! Je suis Sentinel, l’assistant eau et hygiène de votre école. Pour signaler une panne, décrivez-la en une phrase avec le nom de l’école, ou envoyez une note vocale.';

    private const IDENTITY_FR = 'Je suis Sentinel, l’assistant eau et hygiène de votre école. Je reçois vos signalements (robinet, toilettes, savon...) : décrivez la panne en une phrase ou envoyez une note vocale.';

    private const CAPABILITIES_FR = 'Je suis Sentinel, l’assistant eau et hygiène de votre école. Je peux enregistrer vos pannes et suivre vos dossiers : décrivez la panne en une phrase, ou envoyez « où en est mon dossier ? » ou votre référence WASH-...';

    private const THANKS_FR = 'Avec plaisir ! Je suis Sentinel, l’assistant eau et hygiène de votre école. S’il y a une autre panne, décrivez-la en une phrase et je m’en occupe.';

    private const GREETING_EN = 'Hello! I am Sentinel, your school water and hygiene assistant. To report a problem, describe it in one sentence with the school name, or send a voice note.';

    private const IDENTITY_EN = 'I am Sentinel, your school water and hygiene assistant. I collect your reports (taps, toilets, soap...): just describe the problem in one sentence or send a voice note.';

    private const CAPABILITIES_EN = 'I am Sentinel, your school water and hygiene assistant. I can record problems and track your cases: describe the issue in one sentence, or ask "where is my case?" with your WASH-... reference.';

    private const THANKS_EN = 'You are welcome! I am Sentinel, your school water and hygiene assistant. If anything else breaks, describe it in one sentence and I will take care of it.';

    /** Normalise : minuscules, sans accents, espaces condensees. */
    private function normalize(string $text): string
    {
        $lower = mb_strtolower(trim($text), 'UTF-8');
        $lower = str_replace(['’', '‘', "'", '`'], ' ', $lower);
        $ascii = iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $lower);
        if ($ascii === false) {
            $ascii = $lower;
        }
        $ascii = preg_replace('/[^a-z0-9\s\'?!\-]/', ' ', $ascii) ?? '';
        $ascii = preg_replace('/\s+/', ' ', $ascii) ?? '';

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
            !$this->matches($normalized, $this->greetingPatternsFr())
            && !$this->matches($normalized, $this->greetingPatternsEn())
        ) {
            return false;
        }

        $stripped = $normalized;
        foreach (['bonjour', 'bonsoir', 'bonne journee', 'bonne soiree', 'salut', 'coucou', 'coukou', 'cc', 'hello', 'hi', 'hey', 'yo', 'good morning', 'good afternoon', 'good evening'] as $token) {
            $stripped = preg_replace('/\b' . preg_quote($token, '/') . '\b/', ' ', $stripped) ?? $stripped;
        }
        // Il ne reste que ponctuation / politesse courte (ex. "ça va ?").
        $compact = preg_replace('/[^a-z]/', '', $stripped) ?? '';

        if ($compact === '') {
            return true;
        }

        return in_array($compact, ['cava', 'commentcava', 'commentvastu', 'commentallezvous', 'howareyou', 'howisitgoing'], true);
    }

    /** @return string[] */
    private function greetingPatternsFr(): array
    {
        return ['/\bbonjour\b/', '/\bbonsoir\b/', '/\bsalut\b/', '/\bcoucou\b/', '/\bcoukou\b/', '/\bcc\b/'];
    }

    /** @return string[] */
    private function greetingPatternsEn(): array
    {
        return ['/\bhello\b/', '/\bhi\b/', '/\bhey\b/', '/\byo\b/', '/\bgood morning\b/', '/\bgood afternoon\b/', '/\bgood evening\b/'];
    }

    /** @return string[] */
    private function identityPatternsFr(): array
    {
        return [
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
    }

    /** @return string[] */
    private function identityPatternsEn(): array
    {
        return [
            '/\bwho are you\b/',
            '/\byour name\b/',
            '/\bwhat is sentinel\b/',
            '/\bwho is sentinel\b/',
        ];
    }

    /** @return string[] */
    private function capabilityPatternsFr(): array
    {
        return [
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
    }

    /** @return string[] */
    private function capabilityPatternsEn(): array
    {
        return [
            '/\bwhat can you do\b/',
            '/\bwhat do you do\b/',
            '/\bhow does it work\b/',
            '/\bhow do you work\b/',
            '/\bhelp\b/',
        ];
    }

    /** @return string[] */
    private function thanksPatternsFr(): array
    {
        return ['/\bmerci\b/'];
    }

    /** @return string[] */
    private function thanksPatternsEn(): array
    {
        return ['/\bthank\b/', '/\bthanks\b/', '/\bthx\b/'];
    }
}
