import { createContext, useContext } from 'react';
import type { ChatItem, DialogueMessage, ProjectItem } from '../lib/dialogues';

export interface DialogueApi {
  chats: ChatItem[];
  projects: ProjectItem[];
  activeChatId: number | null;
  activeChat: ChatItem | null;
  loaded: boolean;
  openChat: (id: number) => void;
  newChat: (projectId?: number | null) => void;
  syncMessages: (messages: DialogueMessage[]) => void;
  deleteChat: (id: number) => void;
  createProject: (name: string) => Promise<number | null>;
  renameProject: (id: number, name: string) => void;
  deleteProject: (id: number) => void;
  registerLoader: (fn: (chat: ChatItem | null) => void) => void;
}

export const DialogueContext = createContext<DialogueApi | null>(null);

export function useDialogues(): DialogueApi {
  const ctx = useContext(DialogueContext);
  if (!ctx) throw new Error('useDialogues utilisé hors DialogueProvider');
  return ctx;
}
