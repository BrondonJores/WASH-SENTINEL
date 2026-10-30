import { useEffect, useState } from 'react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { Icon } from './icons';
import type { IconName } from './icons';

// --- Boutons ---

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';
type ButtonSize = 'sm' | 'md';

const BTN_BASE =
  'inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-[background-color,transform] duration-150 ease-snap focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent active:scale-[0.97] motion-reduce:transition-none motion-reduce:active:scale-100 disabled:cursor-not-allowed disabled:opacity-50';

const BTN_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-primary font-semibold text-primary-foreground hover:bg-primary-strong',
  secondary:
    'border border-line bg-card text-ink-soft hover:bg-raised hover:text-ink',
  danger:
    'border border-line text-danger hover:bg-danger-soft',
  ghost: 'text-ink-soft hover:bg-raised hover:text-ink',
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
  neutral: 'bg-raised text-ink-soft',
  accent: 'bg-accent text-white dark:text-stone-950',
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
      className={`glass rounded-xl ${className}`}
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
        <h1 className="font-display text-xl font-bold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-ink-soft">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

// --- Chargement ---

export function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div aria-hidden="true" className={`animate-pulse rounded-md bg-raised ${className}`} />
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
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-raised text-accent">
        <Icon name={icon} className="h-6 w-6" />
      </span>
      <p className="mt-4 font-semibold">{title}</p>
      {description && <p className="mt-1 max-w-sm text-sm text-ink-soft">{description}</p>}
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
      {label && <span className="text-xs text-ink-soft">{label}</span>}
      <div className="h-2 w-24 overflow-hidden rounded-full bg-raised">
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-medium tabular-nums text-ink-soft">{pct} %</span>
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
      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent/10 text-xs font-bold text-accent ${className}`}
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
