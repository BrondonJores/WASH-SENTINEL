// Synchronisation d'arrière-plan de l'outbox mesh (best-effort).
//
// Android/desktop (Chromium) : Background Sync (`registration.sync`) notifie la
// page via le SW même si l'onglet était fermé au moment du retour réseau.
// iOS/Safari : pas de Background Sync → la page réessaie elle-même sur
// `online` / `visibilitychange` / minuteur (voir MeshFieldPage).

export const MESH_SYNC_TAG = 'wash-mesh-upload';
/** Message qu'un SW personnalisé posterait vers les onglets après un `sync`.
 *  (Avec vite-plugin-pwa/generateSW, aucun handler n'est branché : la page
 *  réessaie via online/visibilitychange/minuteur. Gardé pour compat future.) */
export const MESH_SYNC_MESSAGE = 'wash-mesh-sync';

interface SyncManagerLike {
  register: (tag: string) => Promise<void>;
}

interface ServiceWorkerRegistrationLike {
  sync?: SyncManagerLike;
}

export type SyncRegisterOutcome = 'registered' | 'unsupported' | 'failed';

/**
 * Demande un Background Sync. Ne rejette jamais : l'appelant (ajout outbox)
 * ne doit pas échouer si le navigateur ne supporte pas l'API.
 */
export async function registerMeshSync(): Promise<SyncRegisterOutcome> {
  try {
    if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) {
      return 'unsupported';
    }
    const reg = (await navigator.serviceWorker.ready) as unknown as ServiceWorkerRegistrationLike;
    if (!reg.sync || typeof reg.sync.register !== 'function') return 'unsupported';
    await reg.sync.register(MESH_SYNC_TAG);
    return 'registered';
  } catch {
    return 'failed';
  }
}

export interface FlushDecisionInput {
  /** `navigator.onLine` (ou état online suivi par la page). */
  online: boolean;
  /** Nombre de bundles encore dans l'outbox. */
  pendingCount: number;
  /** Un flush est déjà en cours. */
  flushInFlight: boolean;
}

/**
 * Pure : faut-il tenter un upload maintenant ?
 * Utilisée par tous les déclencheurs (online, visibilitychange, minuteur, SW).
 */
export function shouldFlushOutbox(input: FlushDecisionInput): boolean {
  return input.online && input.pendingCount > 0 && !input.flushInFlight;
}
