import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { AiAnalysis } from '../lib/api';
import { Badge, Button, Card, ConfidenceMeter, EmptyState, PageHeader, Skeleton } from '../components/ui';
import { ErrorBanner, Pager, Pretty } from '../components/crud';
import { INPUT_CLS, fmtDate } from '../lib/wash';

const errMsg = (e: unknown): string => (e instanceof ApiError ? e.message : 'Erreur réseau.');
const confPct = (v: number | null): number => {
  if (v == null) return 0;
  return v > 1 ? v : v * 100;
};

export default function JournalPage() {
  const [items, setItems] = useState<AiAnalysis[]>([]);
  const [page, setPage] = useState(1);
  const [lastPage, setLastPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [typeF, setTypeF] = useState('');
  const [typeV, setTypeV] = useState('');

  const [selected, setSelected] = useState<AiAnalysis | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.aiAnalyses({ page, analysis_type: typeF || undefined });
      setItems(res.data);
      setLastPage(res.last_page);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, [page, typeF]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mx-auto w-full max-w-6xl">
      <PageHeader
        title="Journal IA"
        description="Toutes les décisions de l'IA : confiance, modèle, traçabilité."
      />
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <form
        className="mb-4 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setTypeF(typeV.trim());
        }}
      >
        <input
          placeholder="Filtrer par type : triage, repair, extraction…"
          value={typeV}
          onChange={(e) => setTypeV(e.target.value)}
          className={`${INPUT_CLS} max-w-sm`}
        />
        <Button type="submit">Filtrer</Button>
      </form>

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
              <EmptyState icon="file" title="Aucune analyse" description="Le journal est vide." />
            </Card>
          )}
          {items.map((a) => (
            <button
              key={a.id}
              onClick={() => setSelected(a)}
              className={`w-full rounded-xl border p-3 text-left transition-colors ${
                selected?.id === a.id
                  ? 'border-accent bg-accent/5'
                  : 'border-line bg-card hover:bg-raised'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <Badge tone="neutral">{a.analysis_type}</Badge>
                <span className="font-mono text-xs text-ink-faint">#{a.id}</span>
              </div>
              <p className="mt-1 truncate font-mono text-xs">
                {a.incident?.reference_code ?? '—'} · {a.model_used ?? 'modèle ?'}
              </p>
              <div className="mt-1.5 flex items-center justify-between gap-2">
                <ConfidenceMeter value={confPct(a.confidence)} />
                <span className="font-mono text-xs text-ink-faint">
                  {a.processing_ms != null ? `${a.processing_ms} ms · ` : ''}
                  {fmtDate(a.created_at)}
                </span>
              </div>
            </button>
          ))}
          <Pager page={page} lastPage={lastPage} onPage={setPage} />
        </div>

        <div className="lg:col-span-3">
          {!selected && (
            <Card>
              <EmptyState
                icon="file"
                title="Sélectionnez une analyse"
                description="Vérifiez les entrées et sorties de chaque décision IA."
              />
            </Card>
          )}
          {selected && (
            <Card className="space-y-4 p-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">{selected.analysis_type}</Badge>
                  <ConfidenceMeter value={confPct(selected.confidence)} label="Confiance" />
                </div>
                <p className="mt-2 font-mono text-xs">
                  {selected.incident?.reference_code ?? '—'} · {selected.model_used ?? 'modèle ?'} ·{' '}
                  {fmtDate(selected.created_at)}
                </p>
                {selected.incident?.school && (
                  <p className="mt-1 text-sm text-ink-soft">
                    {selected.incident.school.name} ({selected.incident.school.district})
                  </p>
                )}
              </div>
              <div>
                <h3 className="mb-1 text-sm font-semibold">Entrée</h3>
                <Pretty data={selected.input_payload} />
              </div>
              <div>
                <h3 className="mb-1 text-sm font-semibold">Sortie</h3>
                <Pretty data={selected.output_payload} />
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
