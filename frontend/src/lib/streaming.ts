/** AXE 6 — Streaming UX progressif, sans SSE (converse classique + rendu progressif).
 *
 * Le SSE a été volontairement supprimé (multiplicateur de pannes) : ce module
 * ne fait que de la présentation côté front — étapes d'attente basées sur le
 * temps écoulé, et seuil d'attente explicite.
 */

/**
 * DOC — seuils UX (présentation pure, jamais bloquants) :
 * - UX_WAIT_TIMEOUT_MS : au-delà de ce délai, l'UI propose explicitement quoi
 *   faire (patienter / reformuler) sans rien perdre ; la requête continue.
 * - STEP_AT_MS : seuils d'entrée (ms) des WAITING_STEPS, indicatifs.
 */
import { pick } from './i18n';

export const UX_WAIT_TIMEOUT_MS = 90_000;

export interface WaitingStep {
  id: string;
  label: string;
  detail: string;
  labelEn: string;
  detailEn: string;
}

/** Étapes affichées pendant l'attente d'une réponse converse. FR/EN. */
export const WAITING_STEPS: WaitingStep[] = [
  { id: 'receive', label: 'Réception', detail: 'Message bien reçu.', labelEn: 'Received', detailEn: 'Message received.' },
  { id: 'analyze', label: 'Analyse', detail: 'Sentinel comprend la demande.', labelEn: 'Understanding', detailEn: 'Sentinel is understanding the request.' },
  { id: 'tools', label: 'Outils', detail: 'Sentinel consulte les données.', labelEn: 'Checking', detailEn: 'Sentinel is checking the data.' },
  { id: 'answer', label: 'Réponse', detail: 'Sentinel prépare la réponse.', labelEn: 'Answering', detailEn: 'Sentinel is preparing the answer.' },
];

/** Étapes d'attente avec libellés dans la langue UI. */
export function waitingSteps(lang: string | undefined): { id: string; label: string; detail: string }[] {
  return WAITING_STEPS.map((s) => ({
    id: s.id,
    label: pick(lang, s.label, s.labelEn),
    detail: pick(lang, s.detail, s.detailEn),
  }));
}

/** Seuil d'entrée (ms) de chaque étape. Indicatif : jamais bloquant. */
const STEP_AT_MS = [0, 3_000, 12_000, 40_000];

export function stepIndexForElapsed(elapsedMs: number): number {
  let idx = 0;
  for (let i = 0; i < STEP_AT_MS.length; i++) {
    if (elapsedMs >= (STEP_AT_MS[i] ?? 0)) idx = i;
  }
  return Math.min(idx, WAITING_STEPS.length - 1);
}
