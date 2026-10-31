// États visibles de l'outbox mesh : en attente / envoi / échec (+ envoyés récents).
//
// `MeshOutbox` (mesh-sdk, vendored) ne stocke aucun statut : l'upload réussi
// RETIRE les bundles de la file. Ce module dérive donc l'affichage en combinant
// le contenu courant de l'outbox + une méta locale (échecs, envoyés récents).

import type { MeshBundle } from './mesh-sdk';

export type OutboxItemStatus = 'pending' | 'sending' | 'failed';

export interface FailedInfo {
  at: number;
  error: string;
}

export interface SentEntry {
  id: string;
  label: string;
  at: number;
}

export interface OutboxMeta {
  failed: Record<string, FailedInfo>;
  sent: SentEntry[];
}

export interface OutboxCounts {
  pending: number;
  sending: number;
  failed: number;
  sent: number;
}

export interface OutboxViewItem {
  id: string;
  shortId: string;
  status: OutboxItemStatus;
  label: string;
  detail: string;
  error?: string;
}

export const OUTBOX_META_KEY = 'wash_mesh_outbox_meta';
export const MAX_SENT_HISTORY = 20;

export function emptyOutboxMeta(): OutboxMeta {
  return { failed: {}, sent: [] };
}

/** Libellé court FR d'un bundle (jamais vide). */
export function bundleLabel(bundle: MeshBundle): string {
  if (bundle.sealed) return '(chiffré)';
  const text = bundle.message?.trim();
  if (text) return text.slice(0, 60);
  if (bundle.chunk) return `(fragment ${String((bundle.fragment_offset ?? 0) + 1)}/${String(bundle.fragment_total ?? '?')})`;
  if (bundle.fragment_total) return `(média, ${String(bundle.fragment_total)} fragments)`;
  return '(sans texte)';
}

export function bundleDetail(bundle: MeshBundle): string {
  const parts: string[] = [];
  if (bundle.fragment_total && !bundle.chunk) {
    parts.push(`média (${String(bundle.fragment_total)} frag.)`);
  }
  if (bundle.school_code) parts.push(bundle.school_code);
  return parts.join(' · ');
}

export interface DeriveOutboxViewInput {
  /** Bundles encore dans l'outbox (manifestes + fragments). */
  bundles: MeshBundle[];
  /** Un flush est en cours : tout le pending passe en « envoi ». */
  sending: boolean;
  /** Échecs persistés (clés = bundle_id). */
  failed: Record<string, FailedInfo>;
  /** Envoyés récents (méta, hors outbox). */
  sent: SentEntry[];
}

export interface OutboxView {
  /** Manifestes affichables (les fragments restent internes). */
  items: OutboxViewItem[];
  fragmentCount: number;
  counts: OutboxCounts;
}

/** Pure : construit la vue file d'envoi. Les fragments ne sont pas listés. */
export function deriveOutboxView(input: DeriveOutboxViewInput): OutboxView {
  const manifests = input.bundles.filter((b) => !b.chunk);
  const fragmentCount = input.bundles.length - manifests.length;
  const items: OutboxViewItem[] = manifests.map((b) => {
    const failure = input.failed[b.bundle_id];
    const status: OutboxItemStatus = input.sending
      ? 'sending'
      : failure
        ? 'failed'
        : 'pending';
    return {
      id: b.bundle_id,
      shortId: b.bundle_id.slice(0, 8),
      status,
      label: bundleLabel(b),
      detail: bundleDetail(b),
      error: status === 'failed' ? failure?.error : undefined,
    };
  });
  const failed = items.filter((i) => i.status === 'failed').length;
  const sending = items.filter((i) => i.status === 'sending').length;
  return {
    items,
    fragmentCount,
    counts: {
      pending: items.length - failed - sending,
      sending,
      failed,
      sent: input.sent.length,
    },
  };
}

/** Phrase FR de compteurs pour lecteur d'écran + affichage. */
export function outboxSummary(counts: OutboxCounts, fragmentCount: number): string {
  const parts = [`${String(counts.pending + counts.sending)} en attente`];
  if (fragmentCount > 0) parts.push(`${String(fragmentCount)} fragments`);
  if (counts.failed > 0) parts.push(`${String(counts.failed)} en échec`);
  if (counts.sent > 0) parts.push(`${String(counts.sent)} envoyé(s)`);
  return parts.join(' · ');
}

export function loadOutboxMeta(): OutboxMeta {
  try {
    const raw = localStorage.getItem(OUTBOX_META_KEY);
    if (!raw) return emptyOutboxMeta();
    const parsed = JSON.parse(raw) as Partial<OutboxMeta>;
    return {
      failed:
        parsed.failed && typeof parsed.failed === 'object' ? parsed.failed : {},
      sent: Array.isArray(parsed.sent) ? parsed.sent.slice(0, MAX_SENT_HISTORY) : [],
    };
  } catch {
    return emptyOutboxMeta();
  }
}

export function saveOutboxMeta(meta: OutboxMeta): void {
  try {
    localStorage.setItem(
      OUTBOX_META_KEY,
      JSON.stringify({ failed: meta.failed, sent: meta.sent.slice(0, MAX_SENT_HISTORY) }),
    );
  } catch {
    /* stockage indisponible : la vue reste correcte pour la session */
  }
}
