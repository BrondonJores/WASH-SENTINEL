import { useEffect, useRef, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useTheme } from '../theme';
import { NAV_ITEMS } from '../nav';
import type { NavItem } from '../nav';
import { Icon } from './icons';
import { Avatar } from './ui';

const GROUPS: { label: string; paths: string[] }[] = [
  { label: 'Opérations', paths: ['/', '/admin/incidents', '/admin/ecoles', '/admin/signalements'] },
  { label: 'Système', paths: ['/admin/journal', '/admin/notifications', '/admin/reglages'] },
];

const iconBtn =
  'flex h-8 w-8 items-center justify-center rounded-md text-stone-600 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-stone-800';

function navNumber(path: string): string {
  const i = NAV_ITEMS.findIndex((n) => n.path === path);
  return String(i + 1).padStart(2, '0');
}

export default function EdgeDock({ onSearch }: { onSearch: () => void }) {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const handleRef = useRef<HTMLButtonElement>(null);
  const isAdmin = user?.roles.includes('wash_admin') ?? false;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        setOpen(false);
        handleRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const quit = () => {
    logout();
    navigate('/login', { replace: true });
  };

  const close = () => setOpen(false);

  const visible = (paths: string[]) =>
    paths
      .map((p) => NAV_ITEMS.find((n) => n.path === p))
      .filter((n): n is NavItem => !!n && (!n.adminOnly || isAdmin));

  const renderItem = (item: NavItem) => (
    <NavLink
      key={item.path}
      to={item.path}
      end={item.path === '/'}
      onClick={close}
      className={({ isActive }) =>
        `flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13px] ${
          isActive
            ? 'bg-stone-100 font-semibold text-stone-900 dark:bg-stone-800 dark:text-stone-50'
            : 'text-stone-600 hover:bg-stone-100/70 hover:text-stone-900 dark:text-stone-400 dark:hover:bg-stone-800/60 dark:hover:text-stone-100'
        }`
      }
    >
      {({ isActive }) => (
        <>
          <span
            className={`w-5 shrink-0 font-mono text-[10px] tabular-nums ${
              isActive ? 'text-teal-700 dark:text-teal-400' : 'text-stone-400 dark:text-stone-500'
            }`}
          >
            {navNumber(item.path)}
          </span>
          <Icon name={item.icon} className="h-4 w-4 shrink-0" />
          <span className="flex-1 truncate">{item.label}</span>
        </>
      )}
    </NavLink>
  );

  return (
    <>
      <div
        aria-hidden="true"
        onMouseEnter={() => setOpen(true)}
        className="fixed inset-y-0 left-0 z-40 hidden w-3 [@media(hover:hover)]:block"
      />
      <button
        ref={handleRef}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={open ? 'Fermer le menu' : 'Ouvrir le menu'}
        className="fixed left-0 top-1/2 z-40 flex h-16 w-6 -translate-y-1/2 items-center justify-center rounded-r-lg border border-l-0 border-stone-200 bg-white/90 text-stone-500 shadow-sm backdrop-blur hover:text-stone-900 dark:border-stone-800 dark:bg-stone-950/90 dark:text-stone-400 dark:hover:text-stone-100"
      >
        <Icon name="menu" className="h-4 w-4" />
      </button>
      <aside
        onMouseLeave={close}
        inert={!open}
        aria-label="Navigation principale"
        className={`dock-panel fixed bottom-2 left-2 top-2 z-50 flex w-72 flex-col rounded-xl border border-stone-200 bg-white shadow-xl dark:border-stone-800 dark:bg-stone-950 ${
          open ? 'visible translate-x-0' : 'invisible -translate-x-[110%]'
        }`}
      >
        <div className="flex items-center gap-2.5 px-4 pb-4 pt-5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-teal-800 text-white dark:bg-teal-500 dark:text-stone-950">
            <Icon name="droplet" className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[15px] font-bold leading-tight tracking-tight">WASH Sentinel</p>
            <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-stone-500 dark:text-stone-400">
              Console ops
            </p>
          </div>
          <button onClick={close} title="Fermer" aria-label="Fermer le menu" className={iconBtn}>
            <Icon name="x" className="h-4 w-4" />
          </button>
        </div>
        <div className="px-3 pb-2">
          <button
            onClick={() => {
              close();
              onSearch();
            }}
            className="flex h-8 w-full items-center gap-2 rounded-md border border-stone-200 bg-stone-50 px-2.5 text-[13px] text-stone-500 hover:border-stone-300 dark:border-stone-800 dark:bg-stone-900 dark:text-stone-400 dark:hover:border-stone-700"
          >
            <Icon name="search" className="h-3.5 w-3.5 shrink-0" />
            <span className="flex-1 truncate text-left">Rechercher…</span>
            <kbd className="shrink-0 rounded border border-stone-300 bg-white px-1.5 py-0.5 font-mono text-[10px] font-medium dark:border-stone-700 dark:bg-stone-800">
              Ctrl K
            </kbd>
          </button>
        </div>
        <nav className="flex-1 space-y-3 overflow-y-auto px-3 py-2">
          {GROUPS.map((g, gi) => {
            const items = visible(g.paths);
            if (items.length === 0) return null;
            return (
              <div key={g.label}>
                <p
                  className={`px-2.5 pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-stone-500 dark:text-stone-500 ${
                    gi > 0 ? 'pt-2' : ''
                  }`}
                >
                  {g.label}
                </p>
                <div className="space-y-0.5">{items.map(renderItem)}</div>
              </div>
            );
          })}
        </nav>
        <div className="border-t border-stone-200 p-3 dark:border-stone-800">
          <div className="flex items-center gap-2">
            <Avatar name={user?.name ?? '?'} className="h-8 w-8" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-medium">{user?.name}</p>
              <p className="truncate font-mono text-[11px] text-stone-500 dark:text-stone-400">{user?.email}</p>
            </div>
            <button
              onClick={toggle}
              title={theme === 'dark' ? 'Passer en clair' : 'Passer en sombre'}
              aria-label="Basculer clair / sombre"
              className={iconBtn}
            >
              <Icon name={theme === 'dark' ? 'sun' : 'moon'} className="h-[18px] w-[18px]" />
            </button>
            <button onClick={quit} title="Se déconnecter" aria-label="Se déconnecter" className={iconBtn}>
              <Icon name="logout" className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
