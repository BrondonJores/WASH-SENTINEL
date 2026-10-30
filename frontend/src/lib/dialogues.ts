import type { AgentCard, MessagePayload } from './api';

export interface DialogueMessage {
  role: 'user' | 'assistant';
  content: string;
  tools: string[];
  cards: AgentCard[];
  model: string;
  at: number;
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
  const text = (first?.content ?? 'Discussion').trim().replace(/\s+/g, ' ');
  return text.length > 42 ? `${text.slice(0, 42)}…` : text;
}

export function fmtWhen(at: number): string {
  const d = new Date(at);
  if (d.toDateString() === new Date().toDateString()) {
    return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
}

export function toMessagePayload(messages: DialogueMessage[]): MessagePayload[] {
  return messages.map((m) => ({
    role: m.role,
    content: m.content,
    tools: m.tools,
    cards: m.cards,
    model: m.model,
  }));
}
