/** Locale d'affichage unique du frontend (dates, nombres, heures). */
export const LOCALE = 'fr-FR';

/** Locale d'affichage selon la langue de réponse (défaut fr-FR). */
export const localeFor = (lang?: string): string =>
  lang === 'en' ? 'en-US' : LOCALE;
