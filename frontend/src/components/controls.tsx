import type { ChangeEvent, ReactNode } from 'react';
import { Icon } from './icons';

// Contrôles custom du design system (zéro dépendance).
// - Tokens du kit (border-line, bg-card, accent, radius rounded-md).
// - Anneau focus-visible partout, clavier natif conservé.
// - Hover actif uniquement au pointeur fin (souris/trackpad).
// - Transitions < 200 ms, coupées sous motion-reduce.

/** Préfixe Tailwind : n'active le hover que sous (hover:hover) and (pointer:fine). */
const FINE = '[@media(hover:hover)_and_(pointer:fine)]';

const RING =
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent';

const PRESSABLE =
  'transition-transform duration-150 ease-out active:scale-[0.98] motion-reduce:transition-none motion-reduce:active:scale-100';

// --- Case à cocher ---

export interface CheckboxProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  /** Libellé visible. Si absent, `ariaLabel` devient obligatoire pour nommer le contrôle. */
  label?: ReactNode;
  ariaLabel?: string;
  id?: string;
  className?: string;
}

export function Checkbox({
  checked,
  onChange,
  disabled = false,
  label,
  ariaLabel,
  id,
  className = '',
}: CheckboxProps) {
  return (
    <label
      className={`inline-flex w-fit items-center gap-2 text-sm text-ink ${PRESSABLE} ${
        disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'
      } ${className}`}
    >
      <input
        type="checkbox"
        id={id}
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        aria-label={label === undefined ? ariaLabel : undefined}
        className="peer sr-only"
      />
      <span
        aria-hidden="true"
        className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-[background-color,border-color,opacity] duration-150 ease-out motion-reduce:transition-none peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent ${
          checked
            ? `border-accent bg-accent text-white dark:text-stone-950 ${FINE}:hover:border-primary-strong ${FINE}:hover:bg-primary-strong`
            : `border-line bg-card text-transparent ${FINE}:hover:border-accent`
        }`}
      >
        <Icon
          name="check"
          className={`h-3.5 w-3.5 transition-[opacity,transform] duration-150 ease-out motion-reduce:transition-none ${
            checked ? 'scale-100 opacity-100' : 'scale-50 opacity-0'
          }`}
        />
      </span>
      {label !== undefined && <span className="select-none">{label}</span>}
    </label>
  );
}

// --- Bouton radio (même pattern que Checkbox, rond) ---

export interface RadioProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  label?: ReactNode;
  ariaLabel?: string;
  /** Nom du groupe (navigation flèches native quand plusieurs radios partagent le même nom). */
  name?: string;
  value?: string;
  id?: string;
  className?: string;
}

export function Radio({
  checked,
  onChange,
  disabled = false,
  label,
  ariaLabel,
  name,
  value,
  id,
  className = '',
}: RadioProps) {
  return (
    <label
      className={`inline-flex w-fit items-center gap-2 text-sm text-ink ${PRESSABLE} ${
        disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'
      } ${className}`}
    >
      <input
        type="radio"
        id={id}
        name={name}
        value={value}
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        aria-label={label === undefined ? ariaLabel : undefined}
        className="peer sr-only"
      />
      <span
        aria-hidden="true"
        className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border transition-[background-color,border-color,opacity] duration-150 ease-out motion-reduce:transition-none peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent ${
          checked
            ? `border-accent bg-accent text-white dark:text-stone-950 ${FINE}:hover:border-primary-strong ${FINE}:hover:bg-primary-strong`
            : `border-line bg-card text-transparent ${FINE}:hover:border-accent`
        }`}
      >
        <span
          className={`h-2 w-2 rounded-full bg-current transition-[opacity,transform] duration-150 ease-out motion-reduce:transition-none ${
            checked ? 'scale-100 opacity-100' : 'scale-50 opacity-0'
          }`}
        />
      </span>
      {label !== undefined && <span className="select-none">{label}</span>}
    </label>
  );
}

// --- Interrupteur ---

export interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  /** Libellé visible cliquable. Si absent, `ariaLabel` devient obligatoire. */
  label?: ReactNode;
  ariaLabel?: string;
  id?: string;
  className?: string;
}

export function Toggle({
  checked,
  onChange,
  disabled = false,
  label,
  ariaLabel,
  id,
  className = '',
}: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      id={id}
      aria-checked={checked}
      aria-label={label === undefined ? ariaLabel : undefined}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`inline-flex w-fit cursor-pointer items-center gap-2 ${RING} ${PRESSABLE} rounded-md ${
        disabled ? 'cursor-not-allowed opacity-50' : ''
      } ${className}`}
    >
      <span
        aria-hidden="true"
        className={`flex h-6 w-11 shrink-0 items-center rounded-full border px-0.5 transition-[background-color,border-color] duration-150 ease-out motion-reduce:transition-none ${
          checked
            ? `border-accent bg-accent ${FINE}:hover:border-primary-strong ${FINE}:hover:bg-primary-strong`
            : `border-line bg-raised ${FINE}:hover:border-accent`
        }`}
      >
        <span
          className={`h-5 w-5 rounded-full bg-white shadow transition-transform duration-150 ease-out motion-reduce:transition-none ${
            checked ? 'translate-x-[18px]' : 'translate-x-0'
          }`}
        />
      </span>
      {label !== undefined && <span className="text-sm text-ink select-none">{label}</span>}
    </button>
  );
}

// --- Liste déroulante (select NATIF stylé, pas de dropdown maison) ---

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps {
  value: string;
  /** Même signature qu'un select natif : substituable en 1 ligne. */
  onChange: (e: ChangeEvent<HTMLSelectElement>) => void;
  options: SelectOption[];
  /** Optionnel quand le Select est déjà nommé par un <label> visible. */
  ariaLabel?: string;
  disabled?: boolean;
  id?: string;
  className?: string;
}

export function Select({
  value,
  onChange,
  options,
  ariaLabel,
  disabled = false,
  id,
  className = '',
}: SelectProps) {
  return (
    <span
      className={`relative inline-flex items-center transition-transform duration-150 ease-out active:scale-[0.99] motion-reduce:transition-none motion-reduce:active:scale-100 ${
        disabled ? 'opacity-50' : ''
      } ${className}`}
    >
      <select
        id={id}
        value={value}
        onChange={onChange}
        aria-label={ariaLabel}
        disabled={disabled}
        className={`w-full appearance-none rounded-md border border-line bg-card py-2 pr-9 pl-3 text-sm text-ink transition-[background-color,border-color] duration-150 ease-out [color-scheme:light] motion-reduce:transition-none focus:border-accent dark:[color-scheme:dark] ${RING} ${
          disabled ? 'cursor-not-allowed' : `cursor-pointer ${FINE}:hover:border-accent`
        }`}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <Icon
        name="chevron-down"
        className="pointer-events-none absolute top-1/2 right-3 h-4 w-4 -translate-y-1/2 shrink-0 text-ink-faint"
      />
    </span>
  );
}
