import { useId } from 'react';

/**
 * Emblème Sentinel : une goutte d'eau gardienne abritant un œil vigilant.
 * Géométrique, lisible de 16 px (favicon) à 300 px. IDs de dégradés uniques
 * par instance pour rester valides quand l'avatar apparaît plusieurs fois.
 */
export function SentinelAvatar({ className = 'h-6 w-6' }: { className?: string }) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, '');
  const drop = `sg-drop-${uid}`;
  const core = `sg-core-${uid}`;
  return (
    <svg viewBox="0 0 64 64" fill="none" className={className} role="img" aria-label="Sentinel">
      <defs>
        <linearGradient id={drop} x1="14" y1="4" x2="50" y2="58" gradientUnits="userSpaceOnUse">
          <stop stopColor="#5eead4" />
          <stop offset="1" stopColor="#0f766e" />
        </linearGradient>
        <radialGradient id={core} cx="0.35" cy="0.3" r="0.95">
          <stop stopColor="#99f6e4" />
          <stop offset="1" stopColor="#0e7490" />
        </radialGradient>
      </defs>
      <path
        d="M32 4 C20 20 14 28 14 38 a18 18 0 0 0 36 0 C50 28 44 20 32 4 Z"
        fill={`url(#${drop})`}
      />
      <circle cx="32" cy="38" r="10.5" fill={`url(#${core})`} />
      <circle cx="32" cy="38" r="10.5" stroke="#ffffff" strokeOpacity="0.65" strokeWidth="2.5" />
      <circle cx="32" cy="38" r="4" fill="#042f2e" />
      <circle cx="29" cy="35" r="1.8" fill="#ffffff" fillOpacity="0.9" />
    </svg>
  );
}
