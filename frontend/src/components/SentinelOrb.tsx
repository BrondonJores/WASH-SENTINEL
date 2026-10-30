import { Icon } from './icons';

export type OrbState = 'idle' | 'thinking' | 'listening' | 'speaking';

const LABELS: Record<OrbState, string> = {
  idle: 'Sentinel en veille',
  thinking: 'Sentinel réfléchit',
  listening: 'Sentinel écoute',
  speaking: 'Sentinel répond',
};

// Vitesse du flux interne selon l'état : l'orbe dit ce que l'agent fait.
const SWIRL_SPEED: Record<OrbState, string> = {
  idle: '16s',
  thinking: '5s',
  listening: '8s',
  speaking: '3.5s',
};

const EQ_BARS = 12;

/**
 * L'orbe Sentinel : un rond vivant façon mode vocal.
 * États voix câblés visuellement, micro réel à la tranche 2.
 */
export function SentinelOrb({
  state = 'idle',
  size = 'lg',
  className = '',
}: {
  state?: OrbState;
  size?: 'hero' | 'xl' | 'lg' | 'sm';
  className?: string;
}) {
  const box =
    size === 'hero'
      ? 'h-[clamp(280px,42vh,440px)] w-[clamp(280px,42vh,440px)]'
      : size === 'xl'
        ? 'h-72 w-72 sm:h-80 sm:w-80'
        : size === 'lg'
          ? 'h-52 w-52 sm:h-60 sm:w-60'
          : 'h-12 w-12';
  const core =
    size === 'hero' ? 'inset-[12%]' : size === 'xl' ? 'inset-12 sm:inset-14' : size === 'lg' ? 'inset-10 sm:inset-12' : 'inset-1';
  const vocal = state === 'listening' || state === 'speaking';
  const coreAnim = state === 'idle' ? 'orb-breathe' : state === 'speaking' ? 'orb-talk' : '';

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
      {size === 'hero' && (
        <>
          <span
            className="orb-ripple absolute inset-0 rounded-full border border-teal-500/40"
            style={{ animationDuration: '5s' }}
          />
          <span
            className="orb-ripple absolute inset-0 rounded-full border border-teal-500/25"
            style={{ animationDuration: '5s', animationDelay: '2.5s' }}
          />
        </>
      )}
      {state === 'thinking' && (
        <span className="orb-spin-slow absolute inset-1 rounded-full border border-dashed border-teal-500/60 sm:inset-2" />
      )}
      {size !== 'sm' && vocal && (
        <span className="absolute inset-0" aria-hidden="true">
          {Array.from({ length: EQ_BARS }, (_, i) => (
            <span
              key={i}
              className="absolute inset-0"
              style={{ transform: `rotate(${(360 / EQ_BARS) * i}deg)` }}
            >
              <span
                className="orb-eq absolute left-1/2 top-[3px] h-3.5 w-1 -translate-x-1/2 rounded-full bg-teal-500/90 dark:bg-teal-300/80"
                style={{ animationDelay: `${(i * 90) % 1100}ms` }}
              />
            </span>
          ))}
        </span>
      )}
      {size !== 'sm' && (
        <span className="absolute inset-6 rounded-full bg-teal-500/15 blur-2xl sm:inset-8" />
      )}
      <span className={`absolute overflow-hidden rounded-full ${core} ${coreAnim}`}>
        <span
          className="orb-swirl absolute -inset-[35%]"
          style={{
            background:
              'conic-gradient(from 0deg, #14b8a6, #0f766e, #5eead4, #115e59, #99f6e4, #14b8a6)',
            animationDuration: SWIRL_SPEED[state],
          }}
        />
        <span className="orb-core absolute inset-0 rounded-full opacity-90" />
        <span className="absolute left-[22%] top-[14%] h-[22%] w-[30%] rounded-full bg-white/25 blur-md" />
      </span>
      {(size === 'lg' || size === 'xl') && (
        <span className="absolute inset-0 flex items-center justify-center">
          <Icon
            name={state === 'thinking' ? 'chat' : 'droplet'}
            className={size === 'xl' ? 'h-10 w-10 text-white/90' : 'h-8 w-8 text-white/90'}
          />
        </span>
      )}
    </div>
  );
}
