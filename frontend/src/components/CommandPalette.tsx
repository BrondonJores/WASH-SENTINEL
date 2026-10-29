import { useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useTheme } from '../theme';
import { NAV_ITEMS } from '../nav';
import { Icon } from './icons';
import type { IconName } from './icons';

interface Entry {
  group: string;
  label: string;
  icon: IconName;
  run: () => void;
}

export default function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { toggle } = useTheme();
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const [prevOpen, setPrevOpen] = useState(open);
  const [prevQuery, setPrevQuery] = useState(query);
  const inputRef = useRef<HTMLInputElement>(null);
  const isAdmin = user?.roles.includes('wash_admin') ?? false;

  const entries = useMemo<Entry[]>(() => {
    const pages = NAV_ITEMS.filter((i) => !i.adminOnly || isAdmin).map((item) => ({
      group: 'Pages',
      label: item.label,
      icon: item.icon,
      run: () => navigate(item.path),
    }));
    return [
      ...pages,
      { group: 'Actions', label: 'Basculer clair / sombre', icon: 'moon', run: toggle },
      {
        group: 'Actions',
        label: 'Se déconnecter',
        icon: 'logout',
        run: () => {
          logout();
          navigate('/login', { replace: true });
        },
      },
    ];
  }, [isAdmin, navigate, logout, toggle]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((e) => e.label.toLowerCase().includes(q));
  }, [entries, query]);

  // Ajustements pendant le rendu (pattern React recommandé, sans effet).
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setQuery('');
      setCursor(0);
    }
  }
  if (query !== prevQuery) {
    setPrevQuery(query);
    setCursor(0);
  }

  useEffect(() => {
    if (open) {
      const frame = requestAnimationFrame(() => inputRef.current?.focus());
      return () => cancelAnimationFrame(frame);
    }
  }, [open ]);

  if (!open) return null;

  const choose = (entry: Entry | undefined) => {
    if (!entry) return;
    onClose();
    entry.run();
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setCursor((c) => Math.min(c + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setCursor((c) => Math.max(c - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      choose(filtered[cursor]);
    } else if (e.key === 'Escape') {
      onClose();
    }
  };

  let lastGroup = '';
  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Recherche et actions">
      <button aria-label="Fermer" onClick={onClose} className="absolute inset-0 cursor-default bg-stone-950/40" />
      <div className="relative mx-auto mt-[12vh] w-[calc(100%-2rem)] max-w-lg overflow-hidden rounded-xl border border-stone-200 bg-white shadow-2xl dark:border-stone-800 dark:bg-stone-900">
        <div className="flex items-center gap-2 border-b border-stone-200 px-3 dark:border-stone-800">
          <span className="shrink-0 font-mono text-base font-bold text-teal-700 dark:text-teal-400">›</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Rechercher une page ou une action…"
            className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-stone-400 dark:placeholder:text-stone-500"
          />
          <kbd className="shrink-0 rounded border border-stone-300 bg-stone-50 px-1.5 py-0.5 text-[11px] font-medium text-stone-500 dark:border-stone-700 dark:bg-stone-800 dark:text-stone-400">
            Échap
          </kbd>
        </div>
        <div className="max-h-80 overflow-y-auto p-2">
          {filtered.length === 0 && (
            <p className="px-3 py-6 text-center text-sm text-stone-500 dark:text-stone-400">Aucun résultat.</p>
          )}
          {filtered.map((entry, i) => {
            const header = entry.group !== lastGroup ? entry.group : null;
            lastGroup = entry.group;
            return (
              <div key={`${entry.group}-${entry.label}`}>
                {header && (
                  <p className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-stone-500 dark:text-stone-400">
                    {header}
                  </p>
                )}
                <button
                  onClick={() => choose(entry)}
                  onMouseEnter={() => setCursor(i)}
                  className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm ${
                    i === cursor ? 'bg-stone-100 dark:bg-stone-800' : ''
                  }`}
                >
                  <Icon
                    name={entry.icon}
                    className={`h-4 w-4 shrink-0 ${i === cursor ? 'text-teal-700 dark:text-teal-400' : 'text-stone-500 dark:text-stone-400'}`}
                  />
                  {entry.label}
                </button>
              </div>
            );
          })}
        </div>
        <div className="flex items-center gap-4 border-t border-stone-200 px-3 py-2 font-mono text-[11px] text-stone-500 dark:border-stone-800 dark:text-stone-400">
          <span>↑↓ naviguer</span>
          <span>Entrée ouvrir</span>
          <span>Échap fermer</span>
        </div>
      </div>
    </div>
  );
}
