import { Icon } from './icons';

export type OrbState = 'idle' | 'thinking' | 'listening' | 'speaking';

const LABELS: Record<OrbState, string> = {
  idle: 'Sentinel en veille',
  thinking: 'Sentinel réfléchit',
  listening: 'Sentinel écoute',
  speaking: 'Sentinel répond',
};

/**
 * L'orbe Sentinel : dit toujours ce que l'agent fait.
 * États voix (listening/speaking) câblés visuellement, micro à la tranche 2.
 */
export function SentinelOrb({
  state = 'idle',
  size = 'lg',
  className = '',
}: {
  state?: OrbState;
  size?: 'lg' | 'sm';
  className?: string;
}) {
  const box = size === 'lg' ? 'h-52 w-52 sm:h-60 sm:w-60' : 'h-12 w-12';
  const core = size === 'lg' ? 'inset-10 sm:inset-12' : 'inset-1';
  const vocal = state === 'listening' || state === 'speaking';

  return (
    <div className={`relative shrink-0 ${box} ${className}`} role="img" aria-label={LABELS[state]}>
      {vocal && (
        <>
          <span className="orb-ripple absolute inset-0 rounded-full border border-teal-500/50" />
          <span
            className="orb-ripple absolute inset-0 rounded-full border border-teal-500/30"
            style={{ animationDelay: '1.1s' }}
          />
        </>
      )}
      {state === 'thinking' && (
        <span className="orb-spin-slow absolute inset-1 rounded-full border border-dashed border-teal-500/60 sm:inset-2" />
      )}
      {size === 'lg' && <span className="absolute inset-6 rounded-full bg-teal-500/15 blur-2xl sm:inset-8" />}
      <span className={`orb-core absolute rounded-full ${core} ${state === 'idle' ? 'orb-breathe' : ''}`} />
      {size === 'lg' && (
        <span className="absolute inset-0 flex items-center justify-center">
          <Icon name="droplet" className="h-8 w-8 text-white/90" />
        </span>
      )}
    </div>
  );
}
