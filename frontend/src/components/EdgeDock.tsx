import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useTheme } from '../theme';
import { NAV_ITEMS } from '../nav';
import { Icon } from './icons';
import type { IconName } from './icons';
import { SentinelAvatar } from './SentinelAvatar';
import { Avatar } from './ui';
import { useDialogues } from '../dialogues/context';
import { fmtWhen } from '../lib/dialogues';
import type { ChatItem } from '../lib/dialogues';

const iconBtn =
  'flex h-8 w-8 items-center justify-center rounded-md text-ink-soft transition-[background-color,transform] duration-150 ease-snap hover:bg-raised active:scale-[0.97] motion-reduce:transition-none motion-reduce:active:scale-100';

function NameEditor({
  initial,
  placeholder,
  onCommit,
  onCancel,
}: {
  initial: string;
  placeholder: string;
  onCommit: (value: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const done = useRef(false);
  const commit = (v: string) => {
    if (done.current) return;
    done.current = true;
    onCommit(v);
  };
  return (
    <input
      autoFocus
      value={value}
      maxLength={60}
      placeholder={placeholder}
      aria-label={placeholder}
      onChange={(e) => setValue(e.target.value)}
      onBlur={() => commit(value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit(value);
        if (e.key === 'Escape') {
          done.current = true;
          onCancel();
        }
      }}
      onFocus={(e) => e.target.select()}
      className="h-8 w-full rounded-md border border-accent bg-card px-2 text-[13px] text-ink focus:outline-none"
    />
  );
}

interface FanEntry {
  key: string;
  label: string;
  num: string | null;
  icon: IconName;
  active: boolean;
  badge: number;
  onSelect: () => void;
}

export default function EdgeDock({ onSearch }: { onSearch: () => void }) {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const {
    chats,
    projects,
    activeChatId,
    loaded,
    openChat,
    newChat,
    deleteChat,
    createProject,
    renameProject,
    deleteProject,
  } = useDialogues();
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [editingProject, setEditingProject] = useState<number | null>(null);
  const [creatingProject, setCreatingProject] = useState(false);
  const [draft, setDraft] = useState('');
  const [fanOpen, setFanOpen] = useState(false);
  const [canHover] = useState(() => window.matchMedia?.('(hover: hover)').matches ?? false);
  const discRef = useRef<HTMLButtonElement>(null);
  const closeTimer = useRef<number | null>(null);
  const isAdmin = user?.roles.includes('wash_admin') ?? false;

  useEffect(() => {
    if (!open && !fanOpen) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      if (open) {
        setOpen(false);
        discRef.current?.focus();
      } else {
        setFanOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, fanOpen]);

  const quit = () => {
    logout();
    navigate('/login', { replace: true });
  };

  const close = () => setOpen(false);

  const goConsole = () => {
    close();
    if (location.pathname !== '/') navigate('/');
  };
  const openAndGo = (id: number) => {
    openChat(id);
    goConsole();
  };
  const newAndGo = (projectId: number | null) => {
    newChat(projectId);
    goConsole();
  };
  const sortedChats = [...chats].sort((a, b) => b.updatedAt - a.updatedAt);
  const unfiled = sortedChats.filter((c) => !c.projectId);
  const chatsOf = (projectId: number) => sortedChats.filter((c) => c.projectId === projectId);

  const renderChat = (c: ChatItem) => (
    <div
      key={c.id}
      className={`group flex items-center gap-0.5 rounded-md transition-colors duration-150 ${
        c.id === activeChatId ? 'bg-raised' : 'hover:bg-raised'
      }`}
    >
      <button
        onClick={() => openAndGo(c.id)}
        title={c.title}
        className="flex min-w-0 flex-1 items-center gap-2 px-2 py-[7px] text-left"
      >
        <Icon
          name="chat"
          className={`h-4 w-4 shrink-0 ${c.id === activeChatId ? 'text-accent' : 'text-ink-faint'}`}
        />
        <span
          className={`flex-1 truncate text-[13px] ${
            c.id === activeChatId ? 'font-semibold text-ink' : 'text-ink-soft'
          }`}
        >
          {c.title}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-ink-faint">{fmtWhen(c.updatedAt)}</span>
      </button>
      <button
        onClick={() => deleteChat(c.id)}
        title={`Supprimer « ${c.title} »`}
        aria-label={`Supprimer ${c.title}`}
        className="mr-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ink-faint opacity-0 transition-opacity hover:bg-raised hover:text-danger focus-visible:opacity-100 group-hover:opacity-100"
      >
        <Icon name="trash" className="h-3.5 w-3.5" />
      </button>
    </div>
  );

  const cancelClose = () => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  };
  const scheduleClose = () => {
    cancelClose();
    closeTimer.current = window.setTimeout(() => setFanOpen(false), 450);
  };

  const fanNav = useMemo(() => NAV_ITEMS.filter((n) => !n.adminOnly || isAdmin), [isAdmin]);

  const fanEntries = useMemo<FanEntry[]>(
    () => [
      ...fanNav.map((n) => ({
        key: n.path,
        label: n.label,
        num: String(NAV_ITEMS.indexOf(n) + 1).padStart(2, '0'),
        icon: n.icon,
        active: location.pathname === n.path,
        badge: 0,
        onSelect: () => navigate(n.path),
      })),
      {
        key: '__library',
        label: 'Bibliothèque',
        num: null,
        icon: 'chat',
        active: false,
        badge: chats.length,
        onSelect: () => setOpen(true),
      },
      {
        key: '__search',
        label: 'Rechercher',
        num: null,
        icon: 'search',
        active: false,
        badge: 0,
        onSelect: () => onSearch(),
      },
    ],
    [fanNav, location.pathname, navigate, chats.length, onSearch],
  );

  const baseR = window.innerHeight < 720 ? 140 : 212;
  const fanR = Math.max(120, Math.min(baseR, window.innerWidth - 260));
  const fanSpan = 2 * fanR * 0.99;
  const fanPitch = fanEntries.length > 1 ? fanSpan / (fanEntries.length - 1) : fanSpan;
  const bubbleSize = fanPitch >= 50 ? 44 : Math.max(28, Math.floor(fanPitch - 6));
  const fanPos = (i: number, n: number) => {
    const deg = n <= 1 ? 0 : -80 + (160 * i) / (n - 1);
    const rad = (deg * Math.PI) / 180;
    const y = n <= 1 ? 0 : Math.round(-fanSpan / 2 + (fanSpan * i) / (n - 1));
    return { x: Math.round(190 + fanR * Math.cos(rad)), y };
  };

  return (
    <>
      <div className="pointer-events-none fixed inset-y-0 left-0 z-40 w-[480px]">
        <button
          ref={discRef}
          onClick={() => setFanOpen((v) => !v)}
          onMouseEnter={() => {
            if (canHover) {
              cancelClose();
              setFanOpen(true);
            }
          }}
          onMouseLeave={() => {
            if (canHover) scheduleClose();
          }}
          aria-expanded={fanOpen}
          aria-label={fanOpen ? 'Fermer le menu' : 'Ouvrir le menu'}
          title={fanOpen ? undefined : 'Menu'}
          style={{ filter: fanOpen ? 'drop-shadow(0 0 18px rgb(20 184 166 / 0.55))' : undefined }}
          className="glass pointer-events-auto absolute left-0 top-1/2 flex h-44 w-[52px] -translate-y-1/2 items-center justify-center rounded-r-full focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-accent focus-visible:outline-offset-2"
        >
          <span
            aria-hidden="true"
            className="orb-ripple pointer-events-none absolute inset-0 rounded-r-full border border-teal-400/50 motion-reduce:hidden"
          />
          <span
            aria-hidden="true"
            style={{ animationDelay: '1.1s' }}
            className="orb-ripple pointer-events-none absolute inset-0 rounded-r-full border border-teal-400/30 motion-reduce:hidden"
          />
          <span
            className={`transition-transform duration-300 ease-snap motion-reduce:transition-none ${
              fanOpen ? 'rotate-90 scale-110' : ''
            }`}
          >
            <SentinelAvatar className="h-9 w-9" />
          </span>
        </button>
        {fanOpen && canHover && (
          <div
            aria-hidden="true"
            onMouseEnter={cancelClose}
            onMouseLeave={() => scheduleClose()}
            style={{
              left: 52,
              top: '50%',
              width: 190 + fanR + 70,
              height: 2 * (Math.round(fanR * 0.99) + 62),
              transform: 'translateY(-50%)',
            }}
            className="pointer-events-auto absolute"
          />
        )}
        <nav aria-label="Navigation" className="pointer-events-none absolute inset-0">
          {fanEntries.map((e, i) => {
            const p = fanPos(i, fanEntries.length);
            const r = bubbleSize / 2;
            const size = bubbleSize;
            const bubbleLeft = Math.max(26 + p.x - r, 214 + 48);
            const gap = bubbleLeft - 214;
            return (
              <button
                key={e.key}
                onClick={() => {
                  e.onSelect();
                  setFanOpen(false);
                }}
                onMouseEnter={cancelClose}
                onMouseLeave={() => {
                  if (canHover) scheduleClose();
                }}
                title={e.label}
                aria-label={e.label}
                tabIndex={fanOpen ? 0 : -1}
                style={{
                  left: 0,
                  top: '50%',
                  width: bubbleLeft + size,
                  transform: fanOpen
                    ? `translate(0px, calc(-50% + ${p.y}px))`
                    : `translate(-24px, calc(-50% + ${p.y}px))`,
                  opacity: fanOpen ? 1 : 0,
                  transitionDelay: fanOpen ? `${i * 30}ms` : '0ms',
                }}
                className={`group absolute flex items-center rounded-2xl transition-all duration-300 ease-snap motion-reduce:transition-none focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-accent focus-visible:outline-offset-2 ${
                  fanOpen ? 'pointer-events-auto' : 'pointer-events-none'
                }`}
              >
                <span
                  aria-hidden="true"
                  style={{ transitionDelay: fanOpen ? `${i * 30}ms` : '0ms' }}
                  className={`ml-[64px] w-[150px] shrink-0 truncate rounded-full px-3 py-1 text-left text-[12px] font-medium transition-all duration-300 motion-reduce:transition-none ${
                    fanOpen ? 'text-ink opacity-100' : 'opacity-0'
                  }`}
                >
                  {e.num ? (
                    <span className="mr-1.5 font-mono text-[10px] text-ink-faint">{e.num}</span>
                  ) : null}
                  {e.label}
                </span>
                <span
                  aria-hidden="true"
                  style={{ width: gap, transitionDelay: fanOpen ? `${i * 30 + 30}ms` : '0ms' }}
                  className={`flex shrink-0 items-center px-1 transition-opacity duration-300 motion-reduce:transition-none ${
                    fanOpen ? 'opacity-100' : 'opacity-0'
                  }`}
                >
                  <span className="w-full border-t-2 border-dotted border-teal-500/50" />
                </span>
                <span
                  style={{ width: size, height: size, transitionDelay: fanOpen ? `${i * 30 + 60}ms` : '0ms' }}
                  className={`glass bubble-aqua relative flex shrink-0 items-center justify-center rounded-full transition-all duration-300 ease-snap motion-reduce:transition-none ${
                    e.active
                      ? 'bubble-active drop-shadow-[0_0_12px_rgb(20_184_166/0.7)]'
                      : 'text-ink-soft group-hover:text-ink'
                  } ${fanOpen ? 'scale-100' : 'scale-[0.3]'}`}
                >
                  <Icon name={e.icon} className={bubbleSize < 36 ? 'h-4 w-4' : 'h-5 w-5'} />
                  {e.badge > 0 && (
                    <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-accent px-1 font-mono text-[10px] font-bold text-white">
                      {e.badge > 99 ? '99+' : e.badge}
                    </span>
                  )}
                </span>
              </button>
            );
          })}
        </nav>
      </div>
      <button
        aria-label="Fermer le menu"
        aria-hidden={!fanOpen}
        tabIndex={-1}
        onClick={() => setFanOpen(false)}
        onMouseEnter={() => {
          if (canHover) scheduleClose();
        }}
        className={`fixed inset-0 z-30 cursor-default bg-[#02181f]/35 backdrop-blur-[3px] transition-opacity duration-300 motion-reduce:transition-none ${
          fanOpen ? 'opacity-100' : 'pointer-events-none opacity-0'
        }`}
      />
      {open && (
        <button
          aria-label="Fermer le panneau"
          onClick={close}
          className="fixed inset-0 z-40 cursor-default bg-transparent"
        />
      )}
      <aside
        inert={!open}
        aria-label="Bibliothèque"
        className={`dock-panel fixed bottom-2 left-2 top-2 z-50 flex w-72 flex-col glass rounded-xl ${
          open ? 'visible translate-x-0' : 'invisible -translate-x-[110%]'
        }`}
      >
        <div className="flex items-center gap-2.5 px-4 pb-4 pt-5">
          <SentinelAvatar className="h-9 w-9 shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="text-[15px] font-bold leading-tight tracking-tight">WASH Sentinel</p>
            <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-faint">
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
            className="flex h-8 w-full items-center gap-2 rounded-md border border-line bg-raised px-2.5 text-[13px] text-ink-soft hover:border-accent"
          >
            <Icon name="search" className="h-3.5 w-3.5 shrink-0" />
            <span className="flex-1 truncate text-left">Rechercher…</span>
            <kbd className="shrink-0 rounded border border-line bg-card px-1.5 py-0.5 font-mono text-[10px] font-medium">
              Ctrl K
            </kbd>
          </button>
        </div>
        <nav className="flex-1 space-y-3 overflow-y-auto px-3 py-2">
          <div>
            <div className="flex items-center justify-between px-2.5 pb-1">
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-faint">
                Bibliothèque
              </p>
              <span className="flex items-center gap-0.5">
                <button
                  onClick={() => newAndGo(null)}
                  title="Nouvelle discussion"
                  aria-label="Nouvelle discussion"
                  className="flex h-6 w-6 items-center justify-center rounded-md text-ink-faint hover:bg-raised hover:text-ink"
                >
                  <Icon name="plus" className="h-3.5 w-3.5" />
                </button>
                <button
                  onClick={() => {
                    setCreatingProject(true);
                    setDraft('');
                  }}
                  title="Nouveau dossier"
                  aria-label="Nouveau dossier"
                  className="flex h-6 w-6 items-center justify-center rounded-md text-ink-faint hover:bg-raised hover:text-ink"
                >
                  <Icon name="folder" className="h-4 w-4" />
                </button>
              </span>
            </div>
            {creatingProject && (
              <div className="px-0.5 pb-1">
                <NameEditor
                  initial=""
                  placeholder="Nom du dossier…"
                  onCommit={(v) => {
                    setCreatingProject(false);
                    void createProject(v).then((id) => {
                      if (id) setExpanded((e) => ({ ...e, [id]: true }));
                    });
                  }}
                  onCancel={() => setCreatingProject(false)}
                />
              </div>
            )}
            {!loaded ? (
              <p className="px-2.5 py-1 font-mono text-[11px] text-ink-faint">Chargement…</p>
            ) : (
              chats.length === 0 &&
              projects.length === 0 &&
              !creatingProject && (
                <p className="px-2.5 py-1 text-xs text-ink-faint">
                  Aucune discussion — posez votre première question à Sentinel.
                </p>
              )
            )}
            <div className="space-y-0.5">{unfiled.map(renderChat)}</div>
            {projects.map((p) => {
              const items = chatsOf(p.id);
              const isOpen = expanded[p.id] ?? false;
              return (
                <div key={p.id} className="mt-1">
                  <div className="group flex items-center gap-0.5 rounded-md hover:bg-raised">
                    <button
                      onClick={() => setExpanded((e) => ({ ...e, [p.id]: !isOpen }))}
                      aria-expanded={isOpen}
                      className="flex min-w-0 flex-1 items-center gap-2 px-2 py-[7px] text-left"
                    >
                      <Icon
                        name="chevron-down"
                        className={`h-3.5 w-3.5 shrink-0 text-ink-faint transition-transform duration-150 ${
                          isOpen ? '' : '-rotate-90'
                        }`}
                      />
                      <Icon name="folder" className="h-4 w-4 shrink-0 text-accent" />
                      <span className="flex-1 truncate text-[13px] font-medium text-ink">{p.name}</span>
                      <span className="shrink-0 font-mono text-[10px] text-ink-faint">{items.length}</span>
                    </button>
                    <button
                      onClick={() => {
                        setEditingProject(p.id);
                        setDraft(p.name);
                      }}
                      title="Renommer"
                      aria-label={`Renommer ${p.name}`}
                      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ink-faint opacity-0 transition-opacity hover:bg-raised hover:text-ink focus-visible:opacity-100 group-hover:opacity-100"
                    >
                      <Icon name="edit" className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={() => deleteProject(p.id)}
                      title="Supprimer le dossier (les discussions sont conservées)"
                      aria-label={`Supprimer ${p.name}`}
                      className="mr-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ink-faint opacity-0 transition-opacity hover:bg-raised hover:text-danger focus-visible:opacity-100 group-hover:opacity-100"
                    >
                      <Icon name="trash" className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  {editingProject === p.id && (
                    <div className="px-0.5 py-1">
                      <NameEditor
                        initial={draft}
                        placeholder="Nom du dossier…"
                        onCommit={(v) => {
                          renameProject(p.id, v);
                          setEditingProject(null);
                        }}
                        onCancel={() => setEditingProject(null)}
                      />
                    </div>
                  )}
                  {isOpen && (
                    <div className="ml-3 space-y-0.5 border-l border-line pl-1.5">
                      {items.map(renderChat)}
                      <button
                        onClick={() => newAndGo(p.id)}
                        className="flex w-full items-center gap-2 rounded-md px-2 py-[6px] text-[12px] text-ink-faint hover:bg-raised hover:text-ink"
                      >
                        <Icon name="plus" className="h-3.5 w-3.5" />
                        Discussion
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </nav>
        <div className="border-t border-line p-3">
          <div className="flex items-center gap-2">
            <Avatar name={user?.name ?? '?'} className="h-8 w-8" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-medium">{user?.name}</p>
              <p className="truncate font-mono text-[11px] text-ink-faint">{user?.email}</p>
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
