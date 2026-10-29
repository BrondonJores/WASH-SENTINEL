import { useEffect, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useAuth } from '../auth/AuthContext';
import { useTheme } from '../theme';
import { NAV_ITEMS } from '../nav';
import type { NavItem } from '../nav';
import { Icon } from './icons';
import CommandPalette from './CommandPalette';
import { Avatar, LiveClock, StatusDot } from './ui';

const GROUPS: { label: string; paths: string[] }[] = [
  { label: 'Opérations', paths: ['/admin', '/admin/incidents', '/admin/ecoles', '/admin/signalements'] },
  { label: 'Système', paths: ['/admin/journal', '/admin/notifications', '/admin/reglages'] },
];

const iconBtn =
  'flex h-8 w-8 items-center justify-center rounded-md text-stone-600 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-stone-800';

function navNumber(path: string): string {
  const i = NAV_ITEMS.findIndex((n) => n.path === path);
  return String(i + 1).padStart(2, '0');
}

export default function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const isAdmin = user?.roles.includes('wash_admin') ?? false;

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const quit = () => {
    logout();
    setPaletteOpen(false);
    navigate('/login', { replace: true });
  };

  const renderItem = (item: NavItem, onNavigate?: () => void) => (
    <NavLink
      key={item.path}
      to={item.path}
      end={item.path === '/admin'}
      onClick={onNavigate}
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

  const sidebar = (onNavigate?: () => void) => {
    const visible = (paths: string[]) =>
      paths
        .map((p) => NAV_ITEMS.find((n) => n.path === p))
        .filter((n): n is NavItem => !!n && (!n.adminOnly || isAdmin));
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center gap-2.5 px-4 pb-4 pt-5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-teal-800 text-white dark:bg-teal-500 dark:text-stone-950">
            <Icon name="droplet" className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <p className="text-[15px] font-bold leading-tight tracking-tight">WASH Sentinel</p>
            <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-stone-500 dark:text-stone-400">
              Console ops
            </p>
          </div>
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
                <div className="space-y-0.5">{items.map((item) => renderItem(item, onNavigate))}</div>
              </div>
            );
          })}
        </nav>
        <div className="border-t border-stone-200 p-3 dark:border-stone-800">
          <div className="flex items-center gap-3">
            <Avatar name={user?.name ?? '?'} className="h-8 w-8" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-medium">{user?.name}</p>
              <p className="truncate font-mono text-[11px] text-stone-500 dark:text-stone-400">{user?.email}</p>
            </div>
            <button onClick={quit} title="Se déconnecter" aria-label="Se déconnecter" className={iconBtn}>
              <Icon name="logout" className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-white text-stone-900 dark:bg-stone-950 dark:text-stone-100">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-60 border-r border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-950 lg:block">
        {sidebar()}
      </aside>
      {drawerOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button aria-label="Fermer le menu" onClick={() => setDrawerOpen(false)} className="absolute inset-0 bg-stone-950/40" />
          <aside className="absolute inset-y-0 left-0 w-72 border-r border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-950">
            {sidebar(() => setDrawerOpen(false))}
          </aside>
        </div>
      )}
      <div className="lg:pl-60">
        <header className="sticky top-0 z-30 border-b border-stone-200 bg-white/85 backdrop-blur dark:border-stone-800 dark:bg-stone-950/85">
          <div className="flex h-12 items-center gap-2 px-4">
            <button onClick={() => setDrawerOpen(true)} aria-label="Ouvrir le menu" className={`${iconBtn} lg:hidden`}>
              <Icon name="menu" className="h-5 w-5" />
            </button>
            <span className="hidden items-center gap-2 sm:flex" title="Heure locale">
              <StatusDot tone="live" pulse />
              <LiveClock className="text-stone-600 dark:text-stone-300" />
            </span>
            <button
              onClick={() => setPaletteOpen(true)}
              className="ml-1 flex h-8 w-full max-w-md items-center gap-2 rounded-md border border-stone-200 bg-stone-50 px-2.5 text-[13px] text-stone-500 hover:border-stone-300 dark:border-stone-800 dark:bg-stone-900 dark:text-stone-400 dark:hover:border-stone-700"
            >
              <Icon name="search" className="h-3.5 w-3.5 shrink-0" />
              <span className="flex-1 truncate text-left">Rechercher…</span>
              <kbd className="hidden shrink-0 rounded border border-stone-300 bg-white px-1.5 py-0.5 font-mono text-[10px] font-medium sm:inline dark:border-stone-700 dark:bg-stone-800">
                Ctrl K
              </kbd>
            </button>
            <div className="flex-1" />
            <button
              onClick={toggle}
              title={theme === 'dark' ? 'Passer en clair' : 'Passer en sombre'}
              aria-label="Basculer clair / sombre"
              className={iconBtn}
            >
              <Icon name={theme === 'dark' ? 'sun' : 'moon'} className="h-[18px] w-[18px]" />
            </button>
            <button
              onClick={() => navigate('/admin/notifications')}
              title="Notifications"
              aria-label="Notifications"
              className={iconBtn}
            >
              <Icon name="bell" className="h-[18px] w-[18px]" />
            </button>
            <Avatar name={user?.name ?? '?'} className="hidden h-8 w-8 sm:flex" />
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl px-4 py-5 sm:px-6">{children}</main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
