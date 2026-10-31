/**
 * COPIE VENDORED — ne pas modifier ici.
 * Source de vérité : mesh/sdk/mesh-sdk.ts (la CI vérifie l'identité).
 */
/**
 * mesh-sdk — client offline-first du réseau maillé WASH (zéro dépendance).
 *
 * Usage typique sur le téléphone d'un directeur d'école hors-ligne :
 *
 *   const outbox = new MeshOutbox();            // localStorage persistant
 *   const bundle = createBundle({ schoolId: 12, message: 'Pompe brisée…' });
 *   outbox.add(bundle);
 *   showQR(serializeForQR(bundle));             // B scanne, même sans réseau
 *
 * À la prochaine connexion (ou croisement avec un relai) :
 *
 *   await syncWithRelay(outbox, 'http://village-wifi:8001');
 *   await uploadToLaravel(outbox, 'http://localhost/api');
 */

export interface MeshBundle {
  v: 1;
  bundle_id: string;
  origin_node_id: string;
  school_id: number;
  school_code?: string;
  channel?: 'text' | 'voice' | 'photo';
  message?: string;
  created_at: string;
  expires_at: string;
  max_hops?: number;
  hops: string[];
  checksum?: string;
  // v1.1 additive (alignement BPv7).
  destination?: string;
  report_to?: string;
  lifetime_seconds?: number;
  previous_node?: string;
  /** Budget Spray-and-Wait restant (défaut L=8). À 1 : livraison directe uniquement. */
  copies_remaining?: number;
  fragment_offset?: number;
  fragment_total?: number;
  custody_requested?: boolean;
  priority?: 'normal' | 'high' | 'alert';
  /** Réservé Phase 3 : signature Ed25519 du manifest. */
  signature?: string;
}

const TTL_DAYS = 7;
const DEFAULT_MAX_HOPS = 10;
const DEFAULT_COPIES = 8;
export const DEFAULT_DESTINATION = 'dtn://wash-sentinel/ingest';

export function nodeId(): string {
  let id = localStorage.getItem('wash_mesh_node_id');
  if (!id) {
    id = 'node-' + Math.random().toString(36).slice(2, 10);
    localStorage.setItem('wash_mesh_node_id', id);
  }
  return id;
}

function uuid(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

/** sha256 hex — WebCrypto, fallback FNV si indisponible (http non-secure). */
export async function checksumOf(bundle: Omit<MeshBundle, 'checksum'>): Promise<string> {
  const { checksum: _omit, ...rest } = bundle as MeshBundle;
  const raw = JSON.stringify(rest, Object.keys(rest).sort());
  try {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw));
    return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
  } catch {
    let h = 0x811c9dc5;
    for (let i = 0; i < raw.length; i++) {
      h ^= raw.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    return 'fnv1a-' + (h >>> 0).toString(16);
  }
}

export async function createBundle(opts: {
  schoolId: number;
  schoolCode?: string;
  message: string;
  channel?: MeshBundle['channel'];
  ttlDays?: number;
  maxHops?: number;
  copies?: number;
  priority?: MeshBundle['priority'];
}): Promise<MeshBundle> {
  const now = new Date();
  const ttlDays = opts.ttlDays ?? TTL_DAYS;
  const expires = new Date(now.getTime() + ttlDays * 86400_000);
  const me = nodeId();
  const bundle: MeshBundle = {
    v: 1,
    bundle_id: uuid(),
    origin_node_id: me,
    school_id: opts.schoolId,
    school_code: opts.schoolCode,
    channel: opts.channel ?? 'text',
    message: opts.message,
    created_at: now.toISOString(),
    expires_at: expires.toISOString(),
    max_hops: opts.maxHops ?? DEFAULT_MAX_HOPS,
    hops: [me],
    destination: DEFAULT_DESTINATION,
    lifetime_seconds: Math.round(ttlDays * 86400),
    copies_remaining: opts.copies ?? DEFAULT_COPIES,
    priority: opts.priority ?? 'normal',
  };
  bundle.checksum = await checksumOf(bundle);
  return bundle;
}

export interface ForwardResult {
  /** Copie à donner au contact (budget divisé). */
  give: MeshBundle;
  /** Nouveau budget à conserver sur ma copie. */
  keepCopies: number;
}

/**
 * Spray-and-Wait binaire : je donne floor(n/2) copies au contact et j'en
 * garde ceil(n/2). Retourne null si boucle/TTL/hops dépassés ou s'il ne
 * reste qu'une copie (livraison directe au serveur uniquement).
 * Après un forward réussi, appeler `outbox.update(id, { copies_remaining })`.
 */
export function forwardBundle(bundle: MeshBundle, myNodeId: string = nodeId()): ForwardResult | null {
  if (bundle.hops.includes(myNodeId)) return null; // anti-boucle
  if (new Date(bundle.expires_at).getTime() <= Date.now()) return null; // TTL
  const hopCount = bundle.hops.length; // hops inclut l'origine
  if (hopCount >= (bundle.max_hops ?? DEFAULT_MAX_HOPS) + 1) return null;
  const copies = bundle.copies_remaining ?? DEFAULT_COPIES;
  if (copies <= 1) return null; // dernière copie : upload direct, plus de relai P2P
  return {
    give: {
      ...bundle,
      hops: [...bundle.hops, myNodeId],
      previous_node: bundle.hops[bundle.hops.length - 1],
      copies_remaining: Math.floor(copies / 2),
    },
    keepCopies: Math.ceil(copies / 2),
  };
}

/** Payload compact pour QR code (base64url du JSON). ~1 Ko en texte. */
export function serializeForQR(bundle: MeshBundle): string {
  const json = JSON.stringify(bundle);
  return btoa(unescape(encodeURIComponent(json))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function parseFromQR(payload: string): MeshBundle {
  const b64 = payload.replace(/-/g, '+').replace(/_/g, '/');
  const json = decodeURIComponent(escape(atob(b64)));
  const bundle = JSON.parse(json) as MeshBundle;
  if (!bundle.bundle_id || !bundle.origin_node_id || !bundle.school_id) {
    throw new Error('Bundle QR invalide : champs requis manquants.');
  }
  return bundle;
}

/** Outbox persistante (localStorage) : survit au redémarrage du téléphone. */
export class MeshOutbox {
  private key: string;
  private items: Map<string, MeshBundle>;

  constructor(key = 'wash_mesh_outbox') {
    this.key = key;
    this.items = new Map();
    try {
      const raw = JSON.parse(localStorage.getItem(key) ?? '[]') as MeshBundle[];
      for (const b of raw) this.items.set(b.bundle_id, b);
    } catch {
      /* outbox corrompue → on repart propre */
    }
    this.gc();
  }

  private save(): void {
    localStorage.setItem(this.key, JSON.stringify([...this.items.values()]));
  }

  /** Supprime les bundles expirés. */
  gc(): number {
    const now = Date.now();
    let n = 0;
    for (const [id, b] of this.items) {
      if (new Date(b.expires_at).getTime() <= now) {
        this.items.delete(id);
        n++;
      }
    }
    if (n) this.save();
    return n;
  }

  add(bundle: MeshBundle): boolean {
    if (this.items.has(bundle.bundle_id)) return false;
    this.items.set(bundle.bundle_id, bundle);
    this.save();
    return true;
  }

  /** Patch partiel (ex. décrémenter copies_remaining après un forward). */
  update(bundleId: string, patch: Partial<MeshBundle>): boolean {
    const current = this.items.get(bundleId);
    if (!current) return false;
    this.items.set(bundleId, { ...current, ...patch });
    this.save();
    return true;
  }

  has(bundleId: string): boolean {
    return this.items.has(bundleId);
  }

  all(): MeshBundle[] {
    return [...this.items.values()];
  }

  ids(): string[] {
    return [...this.items.keys()];
  }

  remove(bundleIds: string[]): void {
    for (const id of bundleIds) this.items.delete(id);
    this.save();
  }

  get size(): number {
    return this.items.size;
  }
}

/** Échange opportuniste avec le relai : je donne mon outbox, je prends ce qui me manque. */
export async function syncWithRelay(outbox: MeshOutbox, relayUrl: string): Promise<{ sent: number; received: number; acked: number }> {
  const res = await fetch(`${relayUrl}/v1/sync`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ node_id: nodeId(), bundles: outbox.all(), known_ids: outbox.ids() }),
  });
  if (!res.ok) throw new Error(`Relai injoignable (${res.status})`);
  const data = await res.json();
  let received = 0;
  for (const raw of data.bundles ?? []) {
    const forwarded = forwardBundle(raw);
    if (forwarded && outbox.add(forwarded.give)) received++;
  }
  // Les bundles arrivés au serveur (via un autre nœud) sortent de ma file.
  const ackedIds = (data.acked_ids ?? []) as string[];
  outbox.remove(ackedIds.filter((id) => outbox.has(id)));
  return { sent: data.stored ?? 0, received, acked: ackedIds.length };
}

/** Après un upload direct vers Laravel, je préviens le relai pour purger les files distantes. */
export async function ackDelivered(bundleIds: string[], relayUrl: string): Promise<number> {
  if (!bundleIds.length) return 0;
  const res = await fetch(`${relayUrl}/v1/ack`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ node_id: nodeId(), ids: bundleIds }),
  });
  if (!res.ok) return 0;
  return ((await res.json()) as { new?: number }).new ?? 0;
}

/** Upload final vers Laravel. Les bundles acceptés/doublons sont vidés de l'outbox. */
export async function uploadToLaravel(
  outbox: MeshOutbox,
  laravelApiUrl: string,
): Promise<{ accepted: number; duplicates: number }> {
  const bundles = outbox.all();
  if (!bundles.length) return { accepted: 0, duplicates: 0 };
  const res = await fetch(`${laravelApiUrl}/v1/mesh/bundles`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      bundles: bundles.map((b) => ({
        bundle_id: b.bundle_id,
        origin_node_id: b.origin_node_id,
        school_id: b.school_id,
        school_code: b.school_code,
        message: b.message,
        channel: b.channel ?? 'text',
        hops: b.hops,
        max_hops: b.max_hops ?? DEFAULT_MAX_HOPS,
        expires_at: b.expires_at,
        received_via_node_id: nodeId(),
        checksum: b.checksum,
        destination_eid: b.destination,
        report_to_eid: b.report_to,
        lifetime_seconds: b.lifetime_seconds,
        previous_node_id: b.previous_node,
        copies_remaining: b.copies_remaining ?? DEFAULT_COPIES,
        fragment_offset: b.fragment_offset,
        fragment_total: b.fragment_total,
        custody_requested: b.custody_requested ?? false,
        priority: b.priority ?? 'normal',
        signature: b.signature,
      })),
    }),
  });
  if (!res.ok) throw new Error(`Laravel injoignable (${res.status})`);
  const data = await res.json();
  // Succès ou doublon = le serveur a déjà le bundle → on peut vider.
  const done = (data.incidents ?? []).map((i: { bundle_id: string }) => i.bundle_id) as string[];
  outbox.remove([...done, ...bundles.filter((b) => !done.includes(b.bundle_id)).map((b) => b.bundle_id)].slice(0, done.length + (data.summary?.duplicates ?? 0)));
  return { accepted: data.summary?.accepted ?? 0, duplicates: data.summary?.duplicates ?? 0 };
}
