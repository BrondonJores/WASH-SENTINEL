/**
 * Limites du dialogue agent — source unique (LOT 11 anti-valeurs-en-dur).
 *
 * MIROIR BACKEND (ne pas modifier sans synchroniser) :
 * AGENT_INPUT_MAX_CHARS = 2000 ↔ WashAgentController::QUERY_MAX_CHARS
 * (validation `message` de /v1/wash/agent/converse + message FR 422).
 * Le garde vocal MAX_VOICE_MESSAGE (voice-limits.ts) reste volontairement
 * en dessous (1800 + suffixe).
 */
export const AGENT_INPUT_MAX_CHARS = 2000;
