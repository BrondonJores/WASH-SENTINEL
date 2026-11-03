import type { AgentCard, MessagePayload } from './api';
import { localeFor } from './locale';
import { getUILang, pick } from './i18n';

/** Longueur max du titre auto d'une discussion (tronqué avec …). */
export const CHAT_TITLE_MAX_CHARS = 42;

export interface DialogueMessage {
  role: 'user' | 'assistant';
  content: string;
  /** Photo jointe (URL objet locale, jamais persistée : toMessagePayload l'ignore). */
  imageUrl?: string | null;
  tools: string[];
  cards: AgentCard[];
  model: string;
  at: number;
  follow_ups: string[];
  lang?: string;
}

export interface ChatItem {
  id: number;
  projectId: number | null;
  title: string;
  messages: DialogueMessage[];
  updatedAt: number;
}

export interface ProjectItem {
  id: number;
  name: string;
  createdAt: number;
}

export function chatTitle(messages: DialogueMessage[]): string {
  const first = messages.find((m) => m.role === 'user');
  const text = (first?.content ?? pick(getUILang(), 'Discussion', 'Conversation')).trim().replace(/\s+/g, ' ');
  return text.length > CHAT_TITLE_MAX_CHARS ? `${text.slice(0, CHAT_TITLE_MAX_CHARS)}…` : text;
}

export function fmtWhen(at: number, lang?: string): string {
  const locale = localeFor(lang ?? getUILang());
  const d = new Date(at);
  if (d.toDateString() === new Date().toDateString()) {
    return d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString(locale, { day: 'numeric', month: 'short' });
}

export function toMessagePayload(messages: DialogueMessage[]): MessagePayload[] {
  return messages.map((m) => ({
    role: m.role,
    content: m.content,
    tools: m.tools,
    cards: m.cards,
    model: m.model,
    said_at: m.at,
    follow_ups: m.follow_ups,
  }));
}
