import { useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { School } from '../lib/api';
import { Badge, Button, Card, PageHeader } from '../components/ui';
import { ErrorBanner } from '../components/crud';

interface HopNode {
  id: string;
  label: string;
  place: string;
  online: boolean;
  hasBundle: boolean;
}

const errMsg = (e: unknown): string => (e instanceof ApiError ? e.message : 'Erreur réseau.');

function uuid(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export default function MeshPage() {
  const [schools, setSchools] = useState<School[]>([]);
  const [schoolId, setSchoolId] = useState('');
  const [message, setMessage] = useState('Pompe du forage brisée depuis ce matin, 400 élèves sans eau potable.');
  const [bundleId, setBundleId] = useState<string | null>(null);
  const [nodes, setNodes] = useState<HopNode[]>([
    { id: 'node-A-yokadouma', label: 'A — Directeur', place: 'Yokadouma (offline)', online: false, hasBundle: false },
    { id: 'node-B-taximoto', label: 'B — Taxi-moto', place: 'Route (relai)', online: false, hasBundle: false },
    { id: 'node-C-bertoua', label: 'C — Relai connecté', place: 'Bertoua (4G)', online: true, hasBundle: false },
  ]);
  const [hops, setHops] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<{ total: number; avg_hops: number; relayed_share: number } | null>(null);

  useEffect(() => {
    api.schools({}).then((res) => setSchools(res.data)).catch(() => setSchools([]));
    fetchStats();
  }, []);

  const fetchStats = async () => {
    try {
      const res = await fetch(`${(import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost/api'}/v1/mesh/stats`);
      if (res.ok) setStats(await res.json());
    } catch {
      /* API pas encore migrée */
    }
  };

  const create = () => {
    if (!schoolId) {
      setError('Choisis une école d\u2019origine.');
      return;
    }
    setError(null);
    setResult(null);
    setBundleId(uuid());
    setHops([nodes[0].id]);
    setNodes((ns) => ns.map((n, i) => ({ ...n, hasBundle: i === 0 })));
  };

  const relay = (from: number, to: number) => {
    if (!nodes[from].hasBundle || nodes[to].hasBundle) return;
    if (hops.includes(nodes[to].id)) {
      setError('Boucle évitée : ce nœud a déjà le bundle.');
      return;
    }
    setHops((h) => [...h, nodes[to].id]);
    setNodes((ns) => ns.map((n, i) => (i === to ? { ...n, hasBundle: true } : n)));
  };

  const upload = async () => {
    if (!bundleId || !nodes[2].hasBundle) return;
    setBusy(true);
    setError(null);
    try {
      const base = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost/api';
      const res = await fetch(`${base}/v1/mesh/bundles`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bundles: [
            {
              bundle_id: bundleId,
              origin_node_id: nodes[0].id,
              school_id: Number(schoolId),
              message,
              hops,
              max_hops: 10,
              expires_at: new Date(Date.now() + 7 * 86400_000).toISOString(),
              received_via_node_id: nodes[2].id,
            },
          ],
        }),
      });
      if (!res.ok) throw new ApiError(res.status, 'Upload mesh refusé.');
      const data = await res.json();
      const ref = data.incidents?.[0]?.reference_code ?? data.incidents?.[0]?.incident_id;
      setResult(`Incident ${ref} créé après ${hops.length - 1} saut(s) — ${data.message}`);
      setNodes((ns) => ns.map((n) => ({ ...n, hasBundle: false })));
      setBundleId(null);
      fetchStats();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setBundleId(null);
    setHops([]);
    setResult(null);
    setError(null);
    setNodes((ns) => ns.map((n) => ({ ...n, hasBundle: false })));
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Réseau maillé"
        description="Signalements pair-à-pair : A hors-ligne → B relai → C connecté → serveur."
        actions={stats ? <Badge tone="info">{stats.total} bundle(s) · {stats.avg_hops} sauts moy.</Badge> : undefined}
      />
      {error && <ErrorBanner message={error} />}
      {result && <p className="rounded-md bg-green-100 px-3 py-2 text-sm text-green-900 dark:bg-green-950 dark:text-green-200">{result}</p>}

      <Card className="space-y-3 p-4">
        <h2 className="text-sm font-semibold">1 — Signalement hors-ligne (nœud A)</h2>
        <div className="grid gap-3 sm:grid-cols-[1fr_2fr]">
          <select value={schoolId} onChange={(e) => setSchoolId(e.target.value)} className="rounded-md border border-line bg-card px-2 py-1.5 text-sm">
            <option value="">École d&apos;origine…</option>
            {schools.map((s) => (
              <option key={s.id} value={s.id}>{s.name} — {s.district}</option>
            ))}
          </select>
          <input value={message} onChange={(e) => setMessage(e.target.value)} className="rounded-md border border-line bg-card px-2 py-1.5 text-sm" />
        </div>
        <div className="flex gap-2">
          <Button variant="primary" size="sm" onClick={create}>Créer le bundle offline</Button>
          <Button size="sm" variant="ghost" onClick={reset}>Réinitialiser</Button>
        </div>
        {bundleId && <p className="font-mono text-xs text-ink-soft">bundle {bundleId.slice(0, 8)}… · hops: {hops.join(' → ')}</p>}
      </Card>

      <div className="grid gap-3 md:grid-cols-3">
        {nodes.map((n, i) => (
          <Card key={n.id} className="space-y-2 p-4">
            <div className="flex items-center justify-between">
              <p className="text-sm font-semibold">{n.label}</p>
              <Badge tone={n.online ? 'success' : 'neutral'}>{n.online ? 'en ligne' : 'offline'}</Badge>
            </div>
            <p className="text-xs text-ink-soft">{n.place}</p>
            <p className="font-mono text-[11px] text-ink-soft">{n.id}</p>
            <Badge tone={n.hasBundle ? 'accent' : 'neutral'}>{n.hasBundle ? 'a le bundle' : 'pas de bundle'}</Badge>
            {i < 2 && (
              <Button size="sm" disabled={!n.hasBundle || nodes[i + 1].hasBundle} onClick={() => relay(i, i + 1)}>
                Transmettre à {nodes[i + 1].label.split(' — ')[0]} (QR / BT)
              </Button>
            )}
            {i === 2 && (
              <Button variant="primary" size="sm" disabled={!n.hasBundle || busy} onClick={upload}>
                {busy ? 'Upload…' : 'Uploader vers Sentinel'}
              </Button>
            )}
          </Card>
        ))}
      </div>

      <Card className="p-4 text-xs text-ink-soft">
        <p>Démo du protocole store-and-forward : déduplication par <span className="font-mono">bundle_id</span>, anti-boucle via <span className="font-mono">hops</span>, TTL 7 jours, <span className="font-mono">max_hops</span> 10. Le relai mesh (<span className="font-mono">:8001</span>) et le SDK <span className="font-mono">mesh/sdk/mesh-sdk.ts</span> implémentent le même protocole pour les vrais téléphones.</p>
      </Card>
    </div>
  );
}
