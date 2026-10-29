import { useEffect, useState } from 'react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { Icon } from './icons';
import type { IconName } from './icons';

// --- Boutons ---

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';
type ButtonSize = 'sm' | 'md';

const BTN_BASE =
  'inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600 disabled:cursor-not-allowed disabled:opacity-50';

const BTN_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-teal-800 font-semibold text-white hover:bg-teal-900 dark:bg-teal-500 dark:text-stone-950 dark:hover:bg-teal-400',
  secondary:
    'border border-stone-300 text-stone-700 hover:bg-stone-100 dark:border-stone-700 dark:text-stone-200 dark:hover:bg-stone-800',
  danger:
    'border border-stone-300 text-red-700 hover:bg-red-50 dark:border-stone-700 dark:text-red-400 dark:hover:bg-red-950/50',
  ghost: 'text-stone-600 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-stone-800',
};

const BTN_SIZES: Record<ButtonSize, string> = {
  sm: 'px-2.5 py-1.5 text-[13px]',
  md: 'px-3.5 py-2 text-sm',
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function Button({ variant = 'secondary', size = 'md', className = '', ...rest }: ButtonProps) {
  return <button className={`${BTN_BASE} ${BTN_VARIANTS[variant]} ${BTN_SIZES[size]} ${className}`} {...rest} />;
}

// --- Badges ---

type BadgeTone = 'neutral' | 'accent' | 'success' | 'warn' | 'danger' | 'info';

const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: 'bg-stone-100 text-stone-700 dark:bg-stone-800 dark:text-stone-300',
  accent: 'bg-teal-800 text-white dark:bg-teal-500 dark:text-stone-950',
  success: 'bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300',
  warn: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300',
  danger: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300',
  info: 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300',
};

export function Badge({
  tone = 'neutral',
  className = '',
  children,
}: {
  tone?: BadgeTone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${BADGE_TONES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

// --- Carte ---

export function Card({ className = '', children }: { className?: string; children: ReactNode }) {
  return (
    <div
      className={`rounded-lg border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900 ${className}`}
    >
      {children}
    </div>
  );
}

// --- En-tête de page ---

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-xl font-bold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-stone-600 dark:text-stone-400">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

// --- Chargement ---

export function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div aria-hidden="true" className={`animate-pulse rounded-md bg-stone-200 dark:bg-stone-800 ${className}`} />
  );
}

// --- État vide ---

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: IconName;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-stone-100 text-teal-800 dark:bg-stone-800 dark:text-teal-400">
        <Icon name={icon} className="h-6 w-6" />
      </span>
      <p className="mt-4 font-semibold">{title}</p>
      {description && <p className="mt-1 max-w-sm text-sm text-stone-600 dark:text-stone-400">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

// --- Jauge de confiance IA (cœur du "vérifier avant de croire") ---

export function ConfidenceMeter({ value, label }: { value: number; label?: string }) {
  const pct = Math.max(0, Math.min(100, Math.round(value)));
  const bar = pct >= 70 ? 'bg-teal-600 dark:bg-teal-500' : pct >= 40 ? 'bg-amber-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2" title={`Confiance IA : ${pct} %`}>
      {label && <span className="text-xs text-stone-600 dark:text-stone-400">{label}</span>}
      <div className="h-2 w-24 overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800">
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-medium tabular-nums text-stone-700 dark:text-stone-300">{pct} %</span>
    </div>
  );
}

// --- Avatar initiales ---

export function Avatar({ name, className = '' }: { name: string; className?: string }) {
  const initials =
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase() ?? '')
      .join('') || '?';
  return (
    <span
      aria-hidden="true"
      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-teal-800/10 text-xs font-bold text-teal-900 dark:bg-teal-500/15 dark:text-teal-300 ${className}`}
    >
      {initials}
    </span>
  );
}

// --- Pastille de statut ---

export function StatusDot({
  tone = 'live',
  pulse = false,
  className = '',
}: {
  tone?: 'live' | 'idle' | 'error';
  pulse?: boolean;
  className?: string;
}) {
  const color = tone === 'live' ? 'bg-teal-500' : tone === 'idle' ? 'bg-stone-400' : 'bg-red-500';
  return (
    <span className={`relative flex h-2 w-2 shrink-0 ${className}`}>
      {pulse && (
        <span className={`absolute inline-flex h-full w-full rounded-full opacity-60 motion-safe:animate-ping ${color}`} />
      )}
      <span className={`relative inline-flex h-2 w-2 rounded-full ${color}`} />
    </span>
  );
}

// --- Horloge live (données réelles, tick chaque seconde) ---

export function LiveClock({ className = '' }: { className?: string }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    <span
      className={`font-mono text-xs tabular-nums ${className}`}
      title={now.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
    >
      {pad(now.getHours())}:{pad(now.getMinutes())}:{pad(now.getSeconds())}
    </span>
  );
}
