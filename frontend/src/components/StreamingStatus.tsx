import { WAITING_STEPS, stepIndexForElapsed } from '../lib/streaming';

/**
 * Indicateur d'étape animé pendant converse.
 * Pur visuel (jamais bloquant). La zone aria-live annonce uniquement les
 * changements d'étape ; le compteur de secondes est masqué aux lecteurs
 * d'écran pour ne pas les spammer.
 */
export function WaitingSteps({ elapsedMs, calm }: { elapsedMs: number; calm: boolean }) {
  const current = stepIndexForElapsed(elapsedMs);
  const step = WAITING_STEPS[current] ?? WAITING_STEPS[0];
  const seconds = Math.max(0, Math.floor(elapsedMs / 1000));
  return (
    <div className="min-w-0 flex-1">
      <ol aria-hidden="true" className="flex items-center gap-1.5">
        {WAITING_STEPS.map((s, i) => {
          const done = i < current;
          const active = i === current;
          return (
            <li key={s.id} className="flex items-center gap-1.5">
              <span
                className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold ${
                  done
                    ? 'bg-teal-700 text-white dark:bg-teal-500 dark:text-teal-950'
                    : active
                      ? `bg-teal-700/15 text-teal-800 dark:bg-teal-300/20 dark:text-teal-200${calm ? '' : ' motion-safe:animate-pulse'}`
                      : 'bg-stone-200 text-stone-500 dark:bg-stone-800 dark:text-stone-400'
                }`}
              >
                {done ? '✓' : i + 1}
              </span>
              <span
                className={`hidden text-[12px] font-medium sm:inline ${
                  active
                    ? 'text-teal-800 dark:text-teal-200'
                    : done
                      ? 'text-ink-soft'
                      : 'text-ink-faint'
                }`}
              >
                {s.label}
              </span>
              {i < WAITING_STEPS.length - 1 && (
                <span
                  aria-hidden="true"
                  className={`mx-1 h-px w-4 sm:w-6 ${done ? 'bg-teal-600' : 'bg-stone-300 dark:bg-stone-700'}`}
                />
              )}
            </li>
          );
        })}
      </ol>
      <p role="status" aria-live="polite" className="mt-1.5 text-sm text-ink-soft">
        {step.detail}{' '}
        <span aria-hidden="true" className="font-mono text-[12px] text-ink-faint">
          ({seconds} s)
        </span>
      </p>
    </div>
  );
}

/**
 * Panneau d'attente explicite au-delà de 90 s.
 * Les trois actions gardent le message saisi (bulle + brouillon conservés).
 */
export function SlowWaitActions({
  elapsedSec,
  onKeepWaiting,
  onRetry,
  onSeeIncidents,
}: {
  elapsedSec: number;
  onKeepWaiting: () => void;
  onRetry: () => void;
  onSeeIncidents: () => void;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="rounded-xl border border-amber-500/40 bg-amber-50 px-4 py-3 dark:bg-amber-950/40"
    >
      <p className="text-sm font-semibold text-amber-900 dark:text-amber-100">
        Sentinel met plus de {elapsedSec} secondes à répondre.
      </p>
      <p className="mt-0.5 text-sm text-amber-800 dark:text-amber-200">
        Votre message est gardé. Que voulez-vous faire ?
      </p>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        <button
          type="button"
          onClick={onKeepWaiting}
          className="rounded-full bg-amber-600 px-3 py-1.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
        >
          Continuer d&apos;attendre
        </button>
        <button
          type="button"
          onClick={onRetry}
          className="rounded-full border border-line bg-card px-3 py-1.5 text-[13px] font-medium text-ink transition-[border-color] hover:border-accent"
        >
          Réessayer
        </button>
        <button
          type="button"
          onClick={onSeeIncidents}
          className="rounded-full border border-line bg-card px-3 py-1.5 text-[13px] font-medium text-ink transition-[border-color] hover:border-accent"
        >
          Voir les incidents
        </button>
      </div>
    </div>
  );
}
