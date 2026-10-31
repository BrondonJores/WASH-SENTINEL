import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { AiAnalysis } from '../lib/api';
import { Badge, Button, Card, ConfidenceMeter, EmptyState, PageHeader, Skeleton } from '../components/ui';
import { ErrorBanner, Pager, Pretty } from '../components/crud';
import { Select } from '../components/controls';
import { DetailDrawer } from '../components/DetailDrawer';
import type { DetailTarget } from '../components/DetailDrawer';
import { CATEGORY_FR, CHANNEL_FR, INPUT_CLS, URGENCY_FR, fmtDate, fmtNum, urgencyTone } from '../lib/wash';

// Valeurs réelles de `analysis_type` observées dans backend/app (lecture seule) :
// triage (IncidentTriageService), repair (WashIncidentController),
// copilot / equity / epidemic / agent (WashAgentController), agent_action (AgentProposalService).
const ANALYSIS_TYPES = [
  { value: 'triage', label: 'Triage', tone: 'info' },
  { value: 'repair', label: 'Réparation', tone: 'warn' },
  { value: 'copilot', label: 'Copilote', tone: 'accent' },
  { value: 'equity', label: 'Équité', tone: 'success' },
  { value: 'epidemic', label: 'Épidémie', tone: 'danger' },
  { value: 'agent', label: 'Agent', tone: 'neutral' },
  { value: 'agent_action', label: 'Action agent', tone: 'success' },
] as const;

type Tone = 'neutral' | 'accent' | 'success' | 'warn' | 'danger' | 'info';

const typeMeta = (t: string): { label: string; tone: Tone } =>
  (ANALYSIS_TYPES.find((e) => e.value === t) as { label: string; tone: Tone } | undefined) ?? {
    label: t,
    tone: 'neutral',
  };

const errMsg = (e: unknown): string => (e instanceof ApiError ? e.message : 'Erreur réseau.');
const confPct = (v: number | null): number => {
  if (v == null) return 0;
  return v > 1 ? v : v * 100;
};

const str = (v: unknown): string | null =>
  typeof v === 'string' && v !== '' ? v : typeof v === 'number' && Number.isFinite(v) ? String(v) : null;
const num = (v: unknown): number | null =>
  typeof v === 'number' && Number.isFinite(v) ? v : null;
const obj = (v: unknown): Record<string, unknown> | null =>
  typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
const fmtScalar = (v: unknown): string | null => {
  if (typeof v === 'string' && v !== '') return v;
  if (typeof v === 'number' && Number.isFinite(v)) return fmtNum(Math.round(v * 100) / 100);
  if (typeof v === 'boolean') return v ? 'Oui' : 'Non';
  return null;
};

interface SummaryRow {
  label: string;
  value: string;
}
interface Summary {
  headline: string | null;
  rows: SummaryRow[];
}

const HEADLINE_KEYS = ['short_summary', 'answer', 'summary', 'response', 'text', 'content', 'message'];

/** Cherche un texte de synthèse dans un payload de sortie au format inconnu (moteur IA opaque). */
const findHeadline = (out: Record<string, unknown> | null): string | null => {
  if (!out) return null;
  for (const k of HEADLINE_KEYS) {
    const s = str(out[k]);
    if (s) return s;
  }
  return null;
};

const pushRow = (rows: SummaryRow[], label: string, value: string | null): void => {
  if (value !== null && value !== '') rows.push({ label, value });
};

/** Résumé lisible construit selon le type d'analyse et la forme réelle des payloads backend. */
const buildSummary = (a: AiAnalysis): Summary => {
  const rows: SummaryRow[] = [];
  const input = obj(a.input_payload);
  const output = obj(a.output_payload);

  if (a.analysis_type === 'triage') {
    const ext = obj(output?.extraction);
    const dup = obj(output?.duplicate);
    const headline = str(ext?.short_summary);
    pushRow(rows, 'Canal', CHANNEL_FR[str(input?.channel) ?? ''] ?? str(input?.channel));
    pushRow(rows, 'Infrastructure', CATEGORY_FR[str(ext?.infrastructure_type) ?? ''] ?? str(ext?.infrastructure_type));
    pushRow(rows, 'Type de panne', str(ext?.issue_type));
    const urg = str(ext?.urgency_level);
    pushRow(rows, 'Urgence', urg ? (URGENCY_FR[urg] ?? urg) : null);
    const affected = num(ext?.estimated_affected_students);
    pushRow(rows, 'Élèves concernés', affected !== null ? fmtNum(affected) : null);
    const score = num(ext?.recommended_priority_score);
    pushRow(rows, 'Score de priorité', score !== null ? `${fmtNum(Math.round(score))} / 100` : null);
    pushRow(rows, 'Risque sanitaire', str(ext?.health_hazard_risk));
    if (dup) {
      const isDup = dup.is_duplicate === true;
      const matched = num(dup.matched_incident_id);
      const sim = num(dup.similarity_score);
      pushRow(
        rows,
        'Doublon',
        isDup
          ? `Oui${matched !== null ? ` — incident #${matched}` : ''}${sim !== null ? ` (${Math.round(sim * 100)} %)` : ''}`
          : 'Non — nouvel incident',
      );
    }
    if (ext && typeof ext.human_overrides !== 'undefined' && ext.human_overrides !== null) {
      pushRow(rows, 'Ajusté par un humain', 'Oui');
    }
    return { headline, rows };
  }

  if (a.analysis_type === 'agent') {
    const rawTools = output?.tools_executed;
    const tools = Array.isArray(rawTools)
      ? rawTools.filter((t): t is string => typeof t === 'string')
      : [];
    const rawCards = output?.cards;
    const cards = Array.isArray(rawCards) ? rawCards : [];
    pushRow(rows, 'Question', str(input?.message));
    pushRow(rows, 'Outils exécutés', tools.length > 0 ? tools.join(', ') : 'Aucun');
    pushRow(rows, 'Cartes', cards.length > 0 ? fmtNum(cards.length) : null);
    return { headline: findHeadline(output), rows };
  }

  if (a.analysis_type === 'agent_action') {
    pushRow(rows, 'Action', str(input?.action));
    const pid = num(input?.proposal_id);
    pushRow(rows, 'Proposition', pid !== null ? `#${pid}` : null);
    pushRow(rows, 'Statut', str(output?.status));
    return { headline: str(output?.summary) ?? findHeadline(output), rows };
  }

  if (a.analysis_type === 'copilot') {
    pushRow(rows, 'Question', str(input?.query));
    pushRow(rows, 'District', str(input?.district));
    return { headline: findHeadline(output), rows };
  }

  if (a.analysis_type === 'equity') {
    pushRow(rows, 'District', str(input?.district));
    const n = num(input?.schools);
    pushRow(rows, 'Écoles analysées', n !== null ? fmtNum(n) : null);
    return { headline: findHeadline(output), rows };
  }

  if (a.analysis_type === 'epidemic') {
    pushRow(rows, 'District', str(input?.district));
    const n = num(input?.incidents);
    pushRow(rows, 'Incidents récents analysés', n !== null ? fmtNum(n) : null);
    return { headline: findHeadline(output), rows };
  }

  if (a.analysis_type === 'repair') {
    const steps = Array.isArray(output?.steps)
      ? (output?.steps as unknown[])
      : Array.isArray(output?.tasks)
        ? (output?.tasks as unknown[])
        : null;
    if (steps) pushRow(rows, 'Étapes', fmtNum(steps.length));
    const cost = num(output?.total_cost) ?? num(output?.estimated_cost);
    pushRow(rows, 'Coût estimé', cost !== null ? `${fmtNum(Math.round(cost))}${str(output?.currency) ? ` ${str(output?.currency)}` : ''}` : null);
    pushRow(rows, 'Durée estimée', str(output?.duration) ?? str(output?.estimated_duration));
    return { headline: findHeadline(output), rows };
  }

  // Type inconnu : repli générique sur les scalaires du payload d'entrée.
  if (input) {
    for (const [k, v] of Object.entries(input).slice(0, 6)) {
      const s = fmtScalar(v);
      if (s) rows.push({ label: k, value: s });
    }
  }
  return { headline: findHeadline(output), rows };
};

export default function JournalPage() {
  const [items, setItems] = useState<AiAnalysis[]>([]);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(20);
  const [lastPage, setLastPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [typeV, setTypeV] = useState('');
  const [incidentV, setIncidentV] = useState('');
  const [typeF, setTypeF] = useState('');
  const [incidentF, setIncidentF] = useState<number | undefined>(undefined);

  const [selected, setSelected] = useState<AiAnalysis | null>(null);
  const [detail, setDetail] = useState<DetailTarget | null>(null);

  const hasFilter = typeF !== '' || incidentF !== undefined;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.aiAnalyses({
        page,
        per_page: perPage,
        analysis_type: typeF || undefined,
        incident_id: incidentF,
      });
      setItems(res.data);
      setLastPage(res.last_page);
      setTotal(res.total);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, [page, perPage, typeF, incidentF]);

  useEffect(() => {
    void load();
  }, [load]);

  const applyFilters = () => {
    setPage(1);
    setSelected(null);
    setTypeF(typeV);
    const n = incidentV.trim() === '' ? undefined : Number(incidentV);
    setIncidentF(n !== undefined && Number.isInteger(n) && n > 0 ? n : undefined);
  };

  const resetFilters = () => {
    setTypeV('');
    setIncidentV('');
    setTypeF('');
    setIncidentF(undefined);
    setPage(1);
    setSelected(null);
  };

  const summary = selected ? buildSummary(selected) : null;
  const selectedIncidentId = selected?.incident_id ?? selected?.incident?.id ?? null;

  return (
    <div className="mx-auto w-full max-w-6xl">
      <PageHeader
        title="Journal IA"
        description={`Toutes les décisions de l'IA : confiance, modèle, traçabilité — ${fmtNum(total)} analyse(s).`}
      />
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <form
        className="mb-4 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          applyFilters();
        }}
      >
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-ink-soft">Type d'analyse</span>
          <Select
            value={typeV}
            onChange={(e) => setTypeV(e.target.value)}
            className="w-48"
            options={[{ value: '', label: 'Tous les types' },
              ...ANALYSIS_TYPES.map((t) => ({ value: t.value, label: t.label }))]}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-ink-soft">Incident (n°)</span>
          <input
            type="number"
            min={1}
            step={1}
            inputMode="numeric"
            placeholder="ex. 12"
            value={incidentV}
            onChange={(e) => setIncidentV(e.target.value)}
            className={`${INPUT_CLS} w-32`}
          />
        </label>
        <Button type="submit" variant="primary">
          Filtrer
        </Button>
        {hasFilter && (
          <Button type="button" variant="ghost" onClick={resetFilters}>
            Réinitialiser
          </Button>
        )}
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
              <EmptyState
                icon="file"
                title="Aucune analyse"
                description={
                  hasFilter
                    ? "Aucune analyse ne correspond à ces filtres."
                    : 'Le journal est vide.'
                }
                action={
                  hasFilter ? (
                    <Button size="sm" onClick={resetFilters}>
                      Réinitialiser les filtres
                    </Button>
                  ) : undefined
                }
              />
            </Card>
          )}
          {items.map((a) => {
            const meta = typeMeta(a.analysis_type);
            const active = selected?.id === a.id;
            return (
              <button
                key={a.id}
                onClick={() => setSelected(a)}
                aria-current={active}
                className={`w-full rounded-xl border p-3 text-left transition-colors ${
                  active
                    ? 'border-accent bg-accent/5'
                    : 'border-line bg-card hover:bg-raised'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <Badge tone={meta.tone}>
                    <span title={a.analysis_type}>{meta.label}</span>
                  </Badge>
                  <span className="font-mono text-xs text-ink-faint">#{a.id}</span>
                </div>
                <p className="mt-1 truncate font-mono text-xs">
                  {a.incident?.reference_code ?? (a.incident_id ? `Incident #${a.incident_id}` : 'Sans incident')} ·{' '}
                  {a.model_used ?? 'modèle ?'}
                </p>
                <div className="mt-1.5 flex items-center justify-between gap-2">
                  <ConfidenceMeter value={confPct(a.confidence)} />
                  <span className="font-mono text-xs text-ink-faint">
                    {a.processing_ms != null ? `${fmtNum(a.processing_ms)} ms · ` : ''}
                    {fmtDate(a.created_at)}
                  </span>
                </div>
              </button>
            );
          })}
          <Pager
            page={page}
            lastPage={lastPage}
            onPage={setPage}
            total={total}
            perPage={perPage}
            onPerPage={(n) => {
              setPerPage(n);
              setPage(1);
            }}
          />
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
          {selected && summary && (
            <Card className="space-y-4 p-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={typeMeta(selected.analysis_type).tone}>
                    {typeMeta(selected.analysis_type).label}
                  </Badge>
                  <ConfidenceMeter value={confPct(selected.confidence)} label="Confiance" />
                </div>
                <p className="mt-2 font-mono text-xs">
                  {selected.incident?.reference_code ?? (selected.incident_id ? `Incident #${selected.incident_id}` : 'Sans incident')} ·{' '}
                  {selected.model_used ?? 'modèle ?'} · {fmtDate(selected.created_at)}
                  {selected.processing_ms != null ? ` · ${fmtNum(selected.processing_ms)} ms` : ''}
                </p>
                {selected.incident?.school && (
                  <p className="mt-1 text-sm text-ink-soft">
                    {selected.incident.school.name} ({selected.incident.school.district})
                  </p>
                )}
                {selectedIncidentId !== null && (
                  <div className="mt-2">
                    <Button
                      size="sm"
                      onClick={() => setDetail({ kind: 'incident', id: selectedIncidentId })}
                    >
                      Voir l'incident
                    </Button>
                  </div>
                )}
              </div>

              <div>
                <h3 className="mb-1 text-sm font-semibold">Résumé</h3>
                {summary.headline !== null && (
                  <p className="text-sm leading-relaxed">{summary.headline}</p>
                )}
                {summary.rows.length > 0 && (
                  <dl className="mt-2 space-y-1.5 border-t border-line pt-2 text-sm">
                    {summary.rows.map((r) => (
                      <div key={r.label} className="flex items-start justify-between gap-3">
                        <dt className="shrink-0 text-ink-soft">{r.label}</dt>
                        <dd className="text-right font-medium">
                          {r.label === 'Urgence' && selected.analysis_type === 'triage' ? (
                            <Badge tone={urgencyTone(r.value === 'Critique' ? 'critical' : r.value === 'Haute' ? 'high' : r.value === 'Moyenne' ? 'medium' : 'low')}>
                              {r.value}
                            </Badge>
                          ) : (
                            r.value
                          )}
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
                {summary.headline === null && summary.rows.length === 0 && (
                  <p className="text-sm text-ink-faint">
                    Aucun résumé disponible — consultez les payloads ci-dessous.
                  </p>
                )}
              </div>

              <details>
                <summary className="cursor-pointer text-sm font-semibold text-ink-soft">
                  Entrée (données envoyées à l'IA)
                </summary>
                <div className="mt-2">
                  <Pretty data={selected.input_payload} />
                </div>
              </details>
              <details>
                <summary className="cursor-pointer text-sm font-semibold text-ink-soft">
                  Sortie (réponse brute de l'IA)
                </summary>
                <div className="mt-2">
                  <Pretty data={selected.output_payload} />
                </div>
              </details>
            </Card>
          )}
        </div>
      </div>

      <DetailDrawer
        detail={detail}
        onClose={() => setDetail(null)}
        onDetail={(kind, id) => setDetail({ kind, id })}
      />
    </div>
  );
}
