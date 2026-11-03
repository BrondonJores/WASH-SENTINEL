/**
 * Scénario de démo figé (FR/EN) : 3 échanges rejoués à volonté.
 *
 * Chaque étape envoie sa question au VRAI backend via `api.converse`
 * (aucun mock) : la réponse et les cartes sont celles du moment.
 * `expectTools` est une info jury (non bloquante).
 * La question suit la langue UI (`demoAsk`) pour que la démo EN
 * interroge l'agent en anglais.
 */
export interface DemoStep {
  /** Question envoyée au backend (FR). */
  ask: string;
  /** Question envoyée au backend (EN). */
  askEn: string;
  /** Outils attendus (titre affiché sous la question). */
  expectTools?: string[];
  /** Titre court de l'étape, affiché pendant la lecture (FR). */
  caption: string;
  /** Titre court de l'étape (EN). */
  captionEn: string;
}

export const DEMO_SCRIPT: DemoStep[] = [
  {
    ask: 'Signale une fuite à Bonanjo',
    askEn: 'Report a leak in Bonanjo',
    expectTools: ['prepare_incident'],
    caption: 'Étape 1 sur 3 : signaler une fuite',
    captionEn: 'Step 1 of 3: report a leak',
  },
  {
    ask: 'Quelles écoles ont le plus besoin d’aide ?',
    askEn: 'Which schools need help most?',
    expectTools: ['rank_schools_by_need'],
    caption: 'Étape 2 sur 3 : voir où aider en premier',
    captionEn: 'Step 2 of 3: see where to help first',
  },
  {
    ask: 'Tendances de Bonanjo sur 3 mois',
    askEn: 'Bonanjo trends over 3 months',
    expectTools: ['repair_trends'],
    caption: 'Étape 3 sur 3 : voir ce qui change',
    captionEn: 'Step 3 of 3: see what is changing',
  },
];

/** Pause après chaque question, pour laisser le jury lire (0 si calm). */
export const DEMO_ASK_PAUSE_MS = 900;

/** Pause entre deux échanges (0 si calm). */
export const DEMO_STEP_PAUSE_MS = 1800;
