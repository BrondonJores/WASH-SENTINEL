/**
 * Debounce des recherches live — source unique (LOT 11 anti-valeurs-en-dur).
 * Listes admin (écoles, incidents, signalements) + widget public : même
 * délai partout pour limiter les requêtes pendant la frappe.
 */
export const SEARCH_DEBOUNCE_MS = 300;
