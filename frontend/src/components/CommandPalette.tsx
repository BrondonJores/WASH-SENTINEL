import { useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useTheme } from '../theme';
import { NAV_ITEMS, navLabel } from '../nav';
import { Icon } from './icons';
import type { IconName } from './icons';
import { pick, useUILang } from '../lib/i18n';

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
  const ui = useUILang();

  const entries = useMemo<Entry[]>(() => {
    const pages = NAV_ITEMS.filter((i) => !i.adminOnly || isAdmin).map((item) => ({
      group: pick(ui, 'Pages', 'Pages'),
      label: navLabel(ui, item),
      icon: item.icon,
      run: () => navigate(item.path),
    }));
    return [
      ...pages,
      { group: pick(ui, 'Actions', 'Actions'), label: pick(ui, 'Basculer clair / sombre', 'Toggle light / dark'), icon: 'moon', run: toggle },
      {
        group: pick(ui, 'Actions', 'Actions'),
        label: pick(ui, 'Se déconnecter', 'Sign out'),
        icon: 'logout',
        run: () => {
          logout();
          navigate('/login', { replace: true });
        },
      },
    ];
  }, [isAdmin, navigate, logout, toggle, ui]);

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
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label={pick(ui, 'Recherche et actions', 'Search and actions')}>
      <button aria-label={pick(ui, 'Fermer', 'Close')} onClick={onClose} className="absolute inset-0 cursor-default bg-stone-950/40" />
      <div className="relative mx-auto mt-[12vh] w-[calc(100%-2rem)] max-w-lg overflow-hidden rounded-xl border border-line bg-card shadow-2xl">
        <div className="flex items-center gap-2 border-b border-line px-3">
          <span className="shrink-0 font-mono text-base font-bold text-accent">›</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={pick(ui, 'Rechercher une page ou une action…', 'Search for a page or an action…')}
            className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-stone-400 dark:placeholder:text-stone-500"
          />
          <kbd className="shrink-0 rounded border border-line bg-raised px-1.5 py-0.5 text-[11px] font-medium text-ink-soft">
            {pick(ui, 'Échap', 'Esc')}
          </kbd>
        </div>
        <div className="max-h-80 overflow-y-auto p-2">
          {filtered.length === 0 && (
            <p className="px-3 py-6 text-center text-sm text-ink-soft">{pick(ui, 'Aucun résultat.', 'No results.')}</p>
          )}
          {filtered.map((entry, i) => {
            const header = entry.group !== lastGroup ? entry.group : null;
            lastGroup = entry.group;
            return (
              <div key={`${entry.group}-${entry.label}`}>
                {header && (
                  <p className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
                    {header}
                  </p>
                )}
                <button
                  onClick={() => choose(entry)}
                  onMouseEnter={() => setCursor(i)}
                  className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm ${
                    i === cursor ? 'bg-raised' : ''
                  }`}
                >
                  <Icon
                    name={entry.icon}
                    className={`h-4 w-4 shrink-0 ${i === cursor ? 'text-accent' : 'text-ink-faint'}`}
                  />
                  {entry.label}
                </button>
              </div>
            );
          })}
        </div>
        <div className="flex items-center gap-4 border-t border-line px-3 py-2 font-mono text-[11px] text-ink-faint">
          <span>↑↓ {pick(ui, 'naviguer', 'navigate')}</span>
          <span>{pick(ui, 'Entrée ouvrir', 'Enter to open')}</span>
          <span>{pick(ui, 'Échap fermer', 'Esc to close')}</span>
        </div>
      </div>
    </div>
  );
}
