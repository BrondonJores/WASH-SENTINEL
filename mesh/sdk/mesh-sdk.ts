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
  /** V2 signatures : Ed25519 base64 (88 car.) sur les octets canoniques, clé `node_pubkey`. */
  signature?: string;
  /** V2 signatures : clé publique Ed25519 du nœud origine (base64, 44 car.). Auto-annoncée (TOFU), incluse dans les octets signés. */
  node_pubkey?: string;
  /** V2 E2E : enveloppe scellée (base64) ; `message` reste vide quand présent. */
  sealed?: string;
  sealed_alg?: 'nacl-sealed-box';
  /** V2b médias : groupe du manifeste, morceau base64, métadonnées. */
  bundle_group?: string;
  chunk?: string;
  media_mime?: string;
  media_size?: number;
  media_sha256?: string;
  media_sealed_alg?: string;
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

/**
 * Forme canonique signée (zéro dépendance) : JSON compact, clés triées,
 * UTF-8 brut — exactement le `raw` de `checksumOf`, moins le champ
 * `signature` (auto-exclusion : une signature ne peut pas couvrir sa
 * propre valeur). `node_pubkey` est INCLUSE : la signature lie le contenu
 * à la clé annoncée. Même forme en Python (`mesh_verify.canonical_bytes`)
 * et PHP (`MeshSignature::canonicalBytes`).
 */
export function canonicalString(bundle: Omit<MeshBundle, 'checksum' | 'signature'>): string {
  // Immuables + node_pubkey seuls : hops/previous_node/copies_remaining
  // vivent à chaque saut, checksum/signature sont des témoins.
  const { checksum: _omit, hops: _h, previous_node: _p, copies_remaining: _c, signature: _s, ...rest } = bundle as MeshBundle;
  return JSON.stringify(rest, Object.keys(rest).sort());
}

/** Octets UTF-8 de `canonicalString` — l'entrée exacte d'Ed25519. */
export function canonicalBytes(bundle: Omit<MeshBundle, 'checksum' | 'signature'>): Uint8Array {
  return new TextEncoder().encode(canonicalString(bundle));
}

/**
 * sha256 hex — WebCrypto, fallback FNV si indisponible (http non-secure).
 * Couvre aussi `signature`/`node_pubkey` quand présents (même ensemble que
 * le relai) — donc toujours (re)calculer APRÈS `signBundle` (qui le fait).
 */
export async function checksumOf(bundle: Omit<MeshBundle, 'checksum'>): Promise<string> {
  // Tout sauf hops/previous_node/copies_remaining (mutés à chaque saut) : couvre aussi signature/node_pubkey.
  const { checksum: _omit, hops: _h, previous_node: _p, copies_remaining: _c, ...rest } = bundle as MeshBundle;
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
  message?: string;
  sealed?: string;
  sealedAlg?: MeshBundle['sealed_alg'];
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
    sealed: opts.sealed,
    sealed_alg: opts.sealedAlg,
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
 * Après un forward réussi, appeler `outbox.update(id, { copies_remaining: result.keepCopies })`.
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

/** Payload compact pour QR code (base64url du JSON). ~0,5 Ko en texte (~700 car. QR, ~900 signé V2 — mesuré). */
export function serializeForQR(bundle: MeshBundle): string {
  const json = JSON.stringify(bundle);
  return btoa(unescape(encodeURIComponent(json))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export const MEDIA_CHUNK_SIZE = 32768;
export const MEDIA_MAX_BYTES = 2097152;

export function chunkBytes(b64: string, size: number = MEDIA_CHUNK_SIZE): string[] {
  const out: string[] = [];
  for (let i = 0; i < b64.length; i += size) out.push(b64.slice(i, i + size));
  return out;
}

export function assembleBytes(chunks: string[]): string {
  return chunks.join('');
}

/** sha256 hex d'une chaîne base64 — même forme que PHP hash('sha256', $b64). */
export async function sha256Text(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

export interface MediaSplit {
  manifest: MeshBundle;
  fragments: MeshBundle[];
}

/**
 * V2b : découpe un média (base64 en clair) en manifeste + fragments.
 * Chiffre-puis-découpe : si `seal` est fourni, le payload est scellé avant
 * découpage, et le sha256 couvre toujours le clair (vérifié après ouverture).
 * Le manifeste porte le texte (triagé immédiatement) ; les fragments suivent
 * et le serveur réassemble + attache quand le groupe est complet.
 */
export async function splitMedia(opts: {
  schoolId: number;
  schoolCode?: string;
  message?: string;
  sealed?: string;
  sealedAlg?: MeshBundle['sealed_alg'];
  channel: 'photo' | 'voice';
  mime: string;
  dataB64: string;
  seal?: (plainB64: string) => Promise<{ sealed: string; alg: string }>;
  chunkSize?: number;
  ttlDays?: number;
  copies?: number;
  priority?: MeshBundle['priority'];
}): Promise<MediaSplit> {
  const sealedMedia = opts.seal ? await opts.seal(opts.dataB64) : null;
  const payload = sealedMedia?.sealed ?? opts.dataB64;
  const chunks = chunkBytes(payload, opts.chunkSize ?? MEDIA_CHUNK_SIZE);
  const manifest = await createBundle({
    schoolId: opts.schoolId,
    schoolCode: opts.schoolCode,
    message: opts.message,
    sealed: opts.sealed,
    sealedAlg: opts.sealedAlg,
    channel: opts.channel,
    ttlDays: opts.ttlDays,
    copies: opts.copies,
    priority: opts.priority,
  });
  manifest.media_mime = opts.mime;
  manifest.media_size = Math.floor((opts.dataB64.length * 3) / 4);
  manifest.media_sha256 = await sha256Text(opts.dataB64);
  manifest.media_sealed_alg = sealedMedia?.alg;
  manifest.fragment_total = chunks.length;
  manifest.checksum = await checksumOf(manifest);
  const fragments: MeshBundle[] = [];
  for (let i = 0; i < chunks.length; i++) {
    const f = await createBundle({
      schoolId: opts.schoolId,
      schoolCode: opts.schoolCode,
      channel: opts.channel,
      ttlDays: opts.ttlDays,
      copies: opts.copies,
    });
    f.bundle_group = manifest.bundle_id;
    f.fragment_offset = i;
    f.fragment_total = chunks.length;
    f.chunk = chunks[i];
    f.checksum = await checksumOf(f);
    fragments.push(f);
  }
  return { manifest, fragments };
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
        v: b.v,
        bundle_id: b.bundle_id,
        origin_node_id: b.origin_node_id,
        school_id: b.school_id,
        school_code: b.school_code,
        created_at: b.created_at,
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
        custody_requested: b.custody_requested,
        priority: b.priority ?? 'normal',
        signature: b.signature,
        node_pubkey: b.node_pubkey,
        sealed: b.sealed,
        sealed_alg: b.sealed_alg,
        bundle_group: b.bundle_group,
        chunk: b.chunk,
        media_mime: b.media_mime,
        media_size: b.media_size,
        media_sha256: b.media_sha256,
        media_sealed_alg: b.media_sealed_alg,
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
