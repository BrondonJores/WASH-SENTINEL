/**
 * Scénario de démo figé (FR) : 3 échanges rejoués à volonté.
 *
 * Chaque étape envoie sa question au VRAI backend via `api.converse`
 * (aucun mock) : la réponse et les cartes sont celles du moment.
 * `expectTools` est une info jury (non bloquante).
 */
export interface DemoStep {
  /** Question envoyée au backend. */
  ask: string;
  /** Outils attendus (titre affiché sous la question). */
  expectTools?: string[];
  /** Titre court de l'étape, affiché pendant la lecture. */
  caption: string;
}

export const DEMO_SCRIPT: DemoStep[] = [
  {
    ask: 'Signale une fuite à Bonanjo',
    expectTools: ['prepare_incident'],
    caption: 'Étape 1 sur 3 : signaler une fuite',
  },
  {
    ask: 'Quelles écoles ont le plus besoin d’aide ?',
    expectTools: ['rank_schools_by_need'],
    caption: 'Étape 2 sur 3 : voir où aider en premier',
  },
  {
    ask: 'Tendances de Bonanjo sur 3 mois',
    expectTools: ['repair_trends'],
    caption: 'Étape 3 sur 3 : voir ce qui change',
  },
];

/** Pause après chaque question, pour laisser le jury lire (0 si calm). */
export const DEMO_ASK_PAUSE_MS = 900;

/** Pause entre deux échanges (0 si calm). */
export const DEMO_STEP_PAUSE_MS = 1800;
