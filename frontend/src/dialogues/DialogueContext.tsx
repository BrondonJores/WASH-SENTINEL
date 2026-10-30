import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from '../lib/api';
import type { LibraryConversation } from '../lib/api';
import { DialogueContext } from './context';
import { chatTitle, toMessagePayload } from '../lib/dialogues';
import type { ChatItem, DialogueMessage, ProjectItem } from '../lib/dialogues';

const ACTIVE_KEY = 'wash_active_chat';

function readActive(): number | null {
  try {
    const v = Number(localStorage.getItem(ACTIVE_KEY));
    return Number.isInteger(v) && v > 0 ? v : null;
  } catch {
    return null;
  }
}

function writeActive(id: number | null): void {
  try {
    if (id) localStorage.setItem(ACTIVE_KEY, String(id));
    else localStorage.removeItem(ACTIVE_KEY);
  } catch {
    /* navigation privée : on reste en mémoire */
  }
}

function toClient(c: LibraryConversation): ChatItem {
  return {
    id: c.id,
    projectId: c.project_id,
    title: c.title,
    updatedAt: Date.parse(c.updated_at) || 0,
    messages: c.messages.map((m) => ({
      role: m.role,
      content: m.content,
      tools: m.tools ?? [],
      cards: m.cards ?? [],
      model: m.model ?? '',
      at: Date.parse(m.created_at) || 0,
    })),
  };
}

export function DialogueProvider({ children }: { children: ReactNode }) {
  const [chats, setChats] = useState<ChatItem[]>([]);
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [activeChatId, setActiveChatId] = useState<number | null>(null);
  const [loaded, setLoaded] = useState(false);
  const loaderRef = useRef<(chat: ChatItem | null) => void>(() => {});
  const pendingRef = useRef<number | null>(null);
  const activeRef = useRef<number | null>(null);
  const chatsRef = useRef<ChatItem[]>([]);

  useEffect(() => {
    chatsRef.current = chats;
  });
  const queueRef = useRef<Promise<unknown>>(Promise.resolve());

  useEffect(() => {
    let cancelled = false;
    api
      .library()
      .then((lib) => {
        if (cancelled) return;
        setProjects(
          lib.projects.map((p) => ({ id: p.id, name: p.name, createdAt: Date.parse(p.created_at) || 0 })),
        );
        const items = lib.conversations.map(toClient);
        setChats(items);
        const saved = readActive();
        const restored = saved ? (items.find((c) => c.id === saved) ?? null) : null;
        activeRef.current = restored?.id ?? null;
        setActiveChatId(restored?.id ?? null);
        loaderRef.current(restored);
        setLoaded(true);
      })
      .catch(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const enqueue = useCallback(<T,>(fn: () => Promise<T>): Promise<T> => {
    const run = queueRef.current.then(fn, fn);
    queueRef.current = run.catch(() => {});
    return run;
  }, []);

  const setActive = useCallback((id: number | null) => {
    activeRef.current = id;
    setActiveChatId(id);
    writeActive(id);
  }, []);

  const registerLoader = useCallback((fn: (chat: ChatItem | null) => void) => {
    loaderRef.current = fn;
  }, []);

  const refresh = useCallback(() => {
    api
      .library()
      .then((lib) => {
        setProjects(
          lib.projects.map((p) => ({ id: p.id, name: p.name, createdAt: Date.parse(p.created_at) || 0 })),
        );
        setChats(lib.conversations.map(toClient));
      })
      .catch(() => {});
  }, []);

  const openChat = useCallback(
    (id: number) => {
      pendingRef.current = null;
      setActive(id);
      loaderRef.current(chatsRef.current.find((c) => c.id === id) ?? null);
    },
    [setActive],
  );

  const newChat = useCallback(
    (projectId: number | null = null) => {
      pendingRef.current = projectId;
      setActive(null);
      loaderRef.current(null);
    },
    [setActive],
  );

  const syncMessages = useCallback(
    (messages: DialogueMessage[]) => {
      if (messages.length === 0) return;
      void enqueue(async () => {
        const current = chatsRef.current.find((c) => c.id === activeRef.current);
        if (current && current.messages === messages) return;
        if (!activeRef.current) {
          const created = await api.createConversation({
            title: chatTitle(messages),
            project_id: pendingRef.current,
            messages: toMessagePayload(messages),
          });
          const item = toClient(created);
          setChats((prev) => [item, ...prev.filter((c) => c.id !== item.id)]);
          setActive(item.id);
          return;
        }
        const id = activeRef.current;
        await api.replaceMessages(id, toMessagePayload(messages));
        setChats((prev) =>
          prev.map((c) => (c.id === id ? { ...c, messages, updatedAt: Date.now() } : c)),
        );
      }).catch(() => {
        /* la prochaine sauvegarde embarque tout l'historique */
      });
    },
    [enqueue, setActive],
  );

  const deleteChat = useCallback(
    (id: number) => {
      const wasActive = activeRef.current === id;
      setChats((prev) => prev.filter((c) => c.id !== id));
      if (wasActive) {
        setActive(null);
        loaderRef.current(null);
      }
      api.deleteConversation(id).catch(() => refresh());
    },
    [refresh, setActive],
  );

  const createProject = useCallback(
    (name: string): Promise<number | null> => {
      const clean = name.trim().slice(0, 60);
      if (!clean) return Promise.resolve(null);
      return api
        .createProject(clean)
        .then((p) => {
          setProjects((prev) =>
            [...prev, { id: p.id, name: p.name, createdAt: Date.parse(p.created_at) || 0 }].sort(
              (a, b) => a.name.localeCompare(b.name, 'fr'),
            ),
          );
          return p.id;
        })
        .catch(() => {
          refresh();
          return null;
        });
    },
    [refresh],
  );

  const renameProject = useCallback(
    (id: number, name: string) => {
      const clean = name.trim().slice(0, 60);
      if (!clean) return;
      setProjects((prev) => prev.map((p) => (p.id === id ? { ...p, name: clean } : p)));
      api.renameProject(id, clean).catch(() => refresh());
    },
    [refresh],
  );

  const deleteProject = useCallback(
    (id: number) => {
      setProjects((prev) => prev.filter((p) => p.id !== id));
      setChats((prev) => prev.map((c) => (c.projectId === id ? { ...c, projectId: null } : c)));
      api.deleteProject(id).catch(() => refresh());
    },
    [refresh],
  );

  const activeChat = useMemo(
    () => chats.find((c) => c.id === activeChatId) ?? null,
    [chats, activeChatId],
  );

  const value = useMemo(
    () => ({
      chats,
      projects,
      activeChatId,
      activeChat,
      loaded,
      openChat,
      newChat,
      syncMessages,
      deleteChat,
      createProject,
      renameProject,
      deleteProject,
      registerLoader,
    }),
    [
      chats,
      projects,
      activeChatId,
      activeChat,
      loaded,
      openChat,
      newChat,
      syncMessages,
      deleteChat,
      createProject,
      renameProject,
      deleteProject,
      registerLoader,
    ],
  );

  return <DialogueContext.Provider value={value}>{children}</DialogueContext.Provider>;
}
