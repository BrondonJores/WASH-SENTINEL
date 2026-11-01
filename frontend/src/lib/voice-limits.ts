/* ============================================================================
 * Limites vocales partagées — source unique pour VoiceMode.tsx et
 * VoiceControls.tsx (LOT 10 anti-valeurs-en-dur : une seule définition).
 * ========================================================================== */

/**
 * Seuil de garde vocal : au-delà, la transcription est coupée proprement
 * côté appelant (dernière fin de phrase + suffixe FR). Marge volontaire
 * SOUS la limite backend de 2000 caractères : 1800 + suffixe reste
 * accepté, jamais de 422, jamais de message perdu.
 */
export const MAX_VOICE_MESSAGE = 1800;

/** Durée maximale d'une dictée avant arrêt automatique (2 minutes). */
export const MAX_RECORD_MS = 120_000;

/** Poids maximal d'une dictée acceptée (10 Mo, miroir de la validation Laravel). */
export const MAX_RECORD_BYTES = 10 * 1024 * 1024;

/** Longueur maximale du texte nettoyé envoyé à la synthèse vocale. */
export const SPEECH_TEXT_MAX_LEN = 1000;

/** Pas du chrono d'attente (stepper transcribe + converse). */
export const ELAPSED_TICK_MS = 500;
