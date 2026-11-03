/** Bilinguisme UI (FR/EN) — helpers uniques, sans dépendance.
 *
 * CONVENTIONS (lire avant usage) :
 * - Chrome (pages, nav, boutons, drawers) : `const ui = useUILang();`
 *   puis `pick(ui, 'fr...', 'en...')`. `ui` réabonne le composant.
 * - Contenu agent (cartes) : `pick(lang, fr, en)` avec la langue de la
 *   réponse serveur (prop `lang`, JAMAIS la langue UI).
 * - Données terrain (titres d'incidents, notes, noms d'écoles) : NE PAS
 *   traduire, ce sont des données saisies, pas de l'UI.
 * - Dates/nombres : `localeFor(lang)` (voir ./locale).
 * - Bascule : `setUILang(ui === 'en' ? 'fr' : 'en')`, persistée.
 */
import { useSyncExternalStore } from 'react';

export type UILang = 'fr' | 'en';

const STORE_KEY = 'wash.uiLang';

const listeners = new Set<() => void>();

const detect = (): UILang => {
  try {
    const stored = window.localStorage.getItem(STORE_KEY);
    if (stored === 'en' || stored === 'fr') return stored;
    return window.navigator.language.toLowerCase().startsWith('en') ? 'en' : 'fr';
  } catch {
    return 'fr';
  }
};

let current: UILang = typeof window === 'undefined' ? 'fr' : detect();

const emit = (): void => {
  listeners.forEach((l) => l());
};

/** Langue UI globale (lecture ponctuelle, hors rendu). */
export const getUILang = (): UILang => current;

/** Bascule FR/EN (persistée, réabonne les composants). */
export const setUILang = (lang: UILang): void => {
  if (lang === current) return;
  current = lang;
  try {
    window.localStorage.setItem(STORE_KEY, lang);
  } catch {
    /* stockage indisponible : préférence session uniquement */
  }
  emit();
};

const subscribe = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

/** Langue UI globale (réabonne le composant au changement). */
export const useUILang = (): UILang => useSyncExternalStore(subscribe, getUILang, getUILang);

/** Choisit la chaîne selon `lang` ('en' -> EN, tout le reste -> FR). */
export const pick = (lang: string | undefined, fr: string, en: string): string =>
  lang === 'en' ? en : fr;
