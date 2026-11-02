<?php

namespace App\Services;

/**
 * Phrasebook natif : rend des phrases VALIDÉES par des locuteurs humains.
 *
 * Le LLM ne parle pas ghomala'/douala — il inventerait. Donc : aucune
 * génération ici, que du lookup déterministe sur config/wash_phrasebook.
 * Une intention n'est rendue que si `native` ET `validator` sont non vides ;
 * sinon null (l'appelant garde son FR/EN standard). Slots :render remplace
 * :ref, :status... passés en paramètres.
 */
class WashPhrasebook
{
    /**
     * Langues natives servies (clés de config/wash_phrasebook entries).
     */
    public function nativeLangs(): array
    {
        return array_keys((array) config('wash_phrasebook.entries', []));
    }

    public function isNativeLang(?string $lang): bool
    {
        return is_string($lang) && $lang !== '' && in_array($lang, $this->nativeLangs(), true);
    }

    /**
     * Intention validée (native + validateur humains présents) ?
     */
    public function has(string $lang, string $intent): bool
    {
        $entry = $this->entry($lang, $intent);

        return is_string($entry['native'] ?? null) && ($entry['native'] ?? '') !== ''
            && is_string($entry['validator'] ?? null) && ($entry['validator'] ?? '') !== '';
    }

    /**
     * Rend l'intention native (slots :xxx remplacés) ou null si non validée.
     */
    public function render(string $lang, string $intent, array $slots = []): ?string
    {
        if (!$this->has($lang, $intent)) {
            return null;
        }
        $text = (string) $this->entry($lang, $intent)['native'];
        foreach ($slots as $key => $value) {
            $text = str_replace(':'.$key, (string) $value, $text);
        }

        return $text;
    }

    /**
     * Intentions restant à faire traduire par un locuteur (questionnaire).
     */
    public function missing(string $lang): array
    {
        $entries = (array) config("wash_phrasebook.entries.{$lang}", []);
        $missing = [];
        foreach ($entries as $intent => $entry) {
            if (!$this->has($lang, (string) $intent)) {
                $missing[] = (string) $intent;
            }
        }

        return $missing;
    }

    protected function entry(string $lang, string $intent): array
    {
        $entry = config("wash_phrasebook.entries.{$lang}.{$intent}", []);

        return is_array($entry) ? $entry : [];
    }
}
