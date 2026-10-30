import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { Report, School } from '../lib/api';
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton } from '../components/ui';
import { ErrorBanner, Field, Pager, Pretty } from '../components/crud';
import { CHANNEL_FR, INPUT_CLS, fmtDate } from '../lib/wash';

const errMsg = (e: unknown): string => (e instanceof ApiError ? e.message : 'Erreur réseau.');

export default function ReportsPage() {
  const [items, setItems] = useState<Report[]>([]);
  const [page, setPage] = useState(1);
  const [lastPage, setLastPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<Report | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [schools, setSchools] = useState<School[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [fSchool, setFSchool] = useState('');
  const [fMessage, setFMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.reports({ page });
      setItems(res.data);
      setLastPage(res.last_page);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    api
      .schools({})
      .then((res) => setSchools(res.data))
      .catch(() => setSchools([]));
  }, []);

  const select = useCallback(async (id: number) => {
    setSelectedId(id);
    setDetailLoading(true);
    try {
      setDetail(await api.report(id));
    } catch (e) {
      setDetail(null);
      setMsg(errMsg(e));
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const create = async () => {
    if (busy || !fSchool || !fMessage.trim()) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.createReport({ school_id: Number(fSchool), message: fMessage.trim() });
      setMsg(`${res.message} Incident : ${res.incident.reference_code}.`);
      setFMessage('');
      setShowForm(false);
      setPage(1);
      await load();
      await select(res.report.id);
    } catch (e) {
      setMsg(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-6xl">
      <PageHeader
        title="Signalements"
        description="File de vérification : doublons flaggés, rattachements, corrections."
        actions={
          <Button variant="primary" onClick={() => setShowForm((v) => !v)}>
            {showForm ? 'Fermer' : '+ Nouveau signalement'}
          </Button>
        }
      />
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {showForm && (
        <Card className="mb-4 space-y-3 p-4">
          <Field label="École *">
            <select
              value={fSchool}
              onChange={(e) => setFSchool(e.target.value)}
              className={`${INPUT_CLS} max-w-md`}
            >
              <option value="">Choisir…</option>
              {schools.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.district})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Message *">
            <textarea
              rows={3}
              value={fMessage}
              onChange={(e) => setFMessage(e.target.value)}
              placeholder="Décrivez le problème : pompe cassée, latrines bouchées, eau souillée…"
              className={INPUT_CLS}
            />
          </Field>
          <Button variant="primary" disabled={busy} onClick={() => void create()}>
            Envoyer au tri IA
          </Button>
        </Card>
      )}
      {msg && <p className="mb-4 text-sm text-ink-soft">{msg}</p>}

      <div className="grid items-start gap-4 lg:grid-cols-5">
        <div className="space-y-2 lg:col-span-2">
          {loading && items.length === 0 && (
            <>
              <Skeleton className="h-20" />
              <Skeleton className="h-20" />
              <Skeleton className="h-20" />
            </>
          )}
          {!loading && items.length === 0 && (
            <Card>
              <EmptyState icon="inbox" title="Aucun signalement" description="La file est vide." />
            </Card>
          )}
          {items.map((r) => (
            <button
              key={r.id}
              onClick={() => void select(r.id)}
              className={`w-full rounded-xl border p-3 text-left transition-colors ${
                selectedId === r.id
                  ? 'border-accent bg-accent/5'
                  : 'border-line bg-card hover:bg-raised'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-ink-faint">
                  #{r.id} · {fmtDate(r.created_at)}
                </span>
                {r.is_duplicate && <Badge tone="warn">Doublon</Badge>}
              </div>
              <p className="mt-1 line-clamp-2 text-sm">{r.raw_content}</p>
              <p className="mt-0.5 truncate text-xs text-ink-soft">
                {r.school?.name ?? '—'} · {CHANNEL_FR[r.channel] ?? r.channel}
                {r.incident ? ` · ${r.incident.reference_code}` : ''}
              </p>
            </button>
          ))}
          <Pager page={page} lastPage={lastPage} onPage={setPage} />
        </div>

        <div className="lg:col-span-3">
          {detailLoading && <Skeleton className="h-64" />}
          {!detailLoading && !detail && (
            <Card>
              <EmptyState
                icon="inbox"
                title="Sélectionnez un signalement"
                description="Cliquez sur un signalement pour vérifier son contenu et son rattachement."
              />
            </Card>
          )}
          {!detailLoading && detail && (
            <Card className="space-y-4 p-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">{CHANNEL_FR[detail.channel] ?? detail.channel}</Badge>
                  {detail.is_duplicate && <Badge tone="warn">Doublon</Badge>}
                  <span className="font-mono text-xs text-ink-faint">
                    #{detail.id} · {fmtDate(detail.created_at)}
                  </span>
                </div>
                <p className="mt-2 text-sm">{detail.raw_content}</p>
                <p className="mt-2 text-sm text-ink-soft">
                  École : {detail.school?.name ?? '—'} · Incident :{' '}
                  {detail.incident ? (
                    <span className="font-mono">
                      {detail.incident.reference_code} ({detail.incident.status})
                    </span>
                  ) : (
                    '—'
                  )}
                </p>
                {detail.is_duplicate && (
                  <p className="mt-1 text-sm text-ink-soft">
                    Rattaché à l'incident #{detail.duplicate_of_incident_id} · similarité{' '}
                    {detail.duplicate_similarity_score != null
                      ? `${Math.round(detail.duplicate_similarity_score * 100)} %`
                      : '—'}
                  </p>
                )}
                {(detail.audio_path ?? detail.photo_path) && (
                  <p className="mt-1 font-mono text-xs text-ink-faint">
                    {detail.audio_path ?? detail.photo_path}
                  </p>
                )}
              </div>
              <div>
                <h3 className="mb-1 text-sm font-semibold">Extraction IA</h3>
                <Pretty data={detail.raw_ai_extraction} />
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
