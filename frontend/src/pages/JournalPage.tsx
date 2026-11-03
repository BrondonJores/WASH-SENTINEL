import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { AiAnalysis } from '../lib/api';
import { Badge, Button, Card, ConfidenceMeter, EmptyState, PageHeader, Skeleton } from '../components/ui';
import { ErrorBanner, Pager, Pretty } from '../components/crud';
import { Select } from '../components/controls';
import { DetailDrawer } from '../components/DetailDrawer';
import type { DetailTarget } from '../components/DetailDrawer';
import { CATEGORY_FR, CHANNEL_FR, INPUT_CLS, URGENCY_EN, URGENCY_FR, fmtNum, urgencyTone } from '../lib/wash';
import { localeFor } from '../lib/locale';
import { pick, useUILang } from '../lib/i18n';
import { DEFAULT_PER_PAGE } from '../lib/pagination';

// Libellés EN (miroirs locaux : lib/wash.ts hors périmètre).
const CATEGORY_EN: Record<string, string> = {
  water_point: 'Water point',
  toilets_latrines: 'Toilets / latrines',
  handwashing: 'Handwashing',
  sewage_drainage: 'Sewage / drainage',
};
const CHANNEL_EN: Record<string, string> = {
  voice: 'Voice',
  text: 'Text',
  photo: 'Photo',
  webrtc_call: 'Call',
};

/** Même format que wash.fmtDate, avec la locale de la langue UI. */
const fmtDateL = (iso: string | null, lang: string | undefined): string =>
  iso
    ? new Date(iso).toLocaleString(localeFor(lang), {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '—';

/** Retrouve le code urgence depuis son libellé FR ou EN (badge du résumé triage). */
const urgencyCodeFromLabel = (label: string): string => {
  for (const [code, fr] of Object.entries(URGENCY_FR)) if (fr === label) return code;
  for (const [code, en] of Object.entries(URGENCY_EN)) if (en === label) return code;
  return 'low';
};

// Valeurs réelles de `analysis_type` observées dans backend/app (lecture seule) :
// triage (IncidentTriageService), repair (WashIncidentController),
// copilot / equity / epidemic / agent (WashAgentController), agent_action (AgentProposalService).
const ANALYSIS_TYPES = [
  { value: 'triage', label: 'Triage', labelEn: 'Triage', tone: 'info' },
  { value: 'repair', label: 'Réparation', labelEn: 'Repair', tone: 'warn' },
  { value: 'copilot', label: 'Copilote', labelEn: 'Copilot', tone: 'accent' },
  { value: 'equity', label: 'Équité', labelEn: 'Equity', tone: 'success' },
  { value: 'epidemic', label: 'Épidémie', labelEn: 'Epidemic', tone: 'danger' },
  { value: 'agent', label: 'Agent', labelEn: 'Agent', tone: 'neutral' },
  { value: 'agent_action', label: 'Action agent', labelEn: 'Agent action', tone: 'success' },
] as const;

type Tone = 'neutral' | 'accent' | 'success' | 'warn' | 'danger' | 'info';

const typeMeta = (t: string, lang?: string): { label: string; tone: Tone } => {
  const found = ANALYSIS_TYPES.find((e) => e.value === t) as
    | { label: string; labelEn: string; tone: Tone }
    | undefined;
  if (!found) return { label: t, tone: 'neutral' };
  return { label: pick(lang, found.label, found.labelEn), tone: found.tone };
};

const errMsg = (e: unknown, lang?: string): string =>
  (e instanceof ApiError ? e.message : pick(lang, 'Erreur réseau.', 'Network error.'));
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
const fmtScalar = (v: unknown, lang?: string): string | null => {
  if (typeof v === 'string' && v !== '') return v;
  if (typeof v === 'number' && Number.isFinite(v)) return fmtNum(Math.round(v * 100) / 100);
  if (typeof v === 'boolean') return v ? pick(lang, 'Oui', 'Yes') : pick(lang, 'Non', 'No');
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
const buildSummary = (a: AiAnalysis, lang: string | undefined): Summary => {
  const catMap = lang === 'en' ? CATEGORY_EN : CATEGORY_FR;
  const chanMap = lang === 'en' ? CHANNEL_EN : CHANNEL_FR;
  const urgMap = lang === 'en' ? URGENCY_EN : URGENCY_FR;
  const rows: SummaryRow[] = [];
  const input = obj(a.input_payload);
  const output = obj(a.output_payload);

  if (a.analysis_type === 'triage') {
    const ext = obj(output?.extraction);
    const dup = obj(output?.duplicate);
    const headline = str(ext?.short_summary);
    pushRow(rows, pick(lang, 'Canal', 'Channel'), chanMap[str(input?.channel) ?? ''] ?? str(input?.channel));
    pushRow(rows, 'Infrastructure', catMap[str(ext?.infrastructure_type) ?? ''] ?? str(ext?.infrastructure_type));
    pushRow(rows, pick(lang, 'Type de panne', 'Failure type'), str(ext?.issue_type));
    const urg = str(ext?.urgency_level);
    pushRow(rows, pick(lang, 'Urgence', 'Urgency'), urg ? (urgMap[urg] ?? urg) : null);
    const affected = num(ext?.estimated_affected_students);
    pushRow(rows, pick(lang, 'Élèves concernés', 'Students affected'), affected !== null ? fmtNum(affected) : null);
    const score = num(ext?.recommended_priority_score);
    pushRow(rows, pick(lang, 'Score de priorité', 'Priority score'), score !== null ? `${fmtNum(Math.round(score))} / 100` : null);
    pushRow(rows, pick(lang, 'Risque sanitaire', 'Health risk'), str(ext?.health_hazard_risk));
    if (dup) {
      const isDup = dup.is_duplicate === true;
      const matched = num(dup.matched_incident_id);
      const sim = num(dup.similarity_score);
      pushRow(
        rows,
        pick(lang, 'Doublon', 'Duplicate'),
        isDup
          ? pick(lang, `Oui${matched !== null ? ` — incident #${matched}` : ''}${sim !== null ? ` (${Math.round(sim * 100)} %)` : ''}`, `Yes${matched !== null ? ` — incident #${matched}` : ''}${sim !== null ? ` (${Math.round(sim * 100)}%)` : ''}`)
          : pick(lang, 'Non — nouvel incident', 'No — new incident'),
      );
    }
    if (ext && typeof ext.human_overrides !== 'undefined' && ext.human_overrides !== null) {
      pushRow(rows, pick(lang, 'Ajusté par un humain', 'Adjusted by a human'), pick(lang, 'Oui', 'Yes'));
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
    pushRow(rows, pick(lang, 'Outils exécutés', 'Tools run'), tools.length > 0 ? tools.join(', ') : pick(lang, 'Aucun', 'None'));
    pushRow(rows, pick(lang, 'Cartes', 'Cards'), cards.length > 0 ? fmtNum(cards.length) : null);
    return { headline: findHeadline(output), rows };
  }

  if (a.analysis_type === 'agent_action') {
    pushRow(rows, 'Action', str(input?.action));
    const pid = num(input?.proposal_id);
    pushRow(rows, pick(lang, 'Proposition', 'Proposal'), pid !== null ? `#${pid}` : null);
    pushRow(rows, pick(lang, 'Statut', 'Status'), str(output?.status));
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
    pushRow(rows, pick(lang, 'Écoles analysées', 'Schools analyzed'), n !== null ? fmtNum(n) : null);
    return { headline: findHeadline(output), rows };
  }

  if (a.analysis_type === 'epidemic') {
    pushRow(rows, 'District', str(input?.district));
    const n = num(input?.incidents);
    pushRow(rows, pick(lang, 'Incidents récents analysés', 'Recent incidents analyzed'), n !== null ? fmtNum(n) : null);
    return { headline: findHeadline(output), rows };
  }

  if (a.analysis_type === 'repair') {
    const steps = Array.isArray(output?.steps)
      ? (output?.steps as unknown[])
      : Array.isArray(output?.tasks)
        ? (output?.tasks as unknown[])
        : null;
    if (steps) pushRow(rows, pick(lang, 'Étapes', 'Steps'), fmtNum(steps.length));
    const cost = num(output?.total_cost) ?? num(output?.estimated_cost);
    pushRow(rows, pick(lang, 'Coût estimé', 'Estimated cost'), cost !== null ? `${fmtNum(Math.round(cost))}${str(output?.currency) ? ` ${str(output?.currency)}` : ''}` : null);
    pushRow(rows, pick(lang, 'Durée estimée', 'Estimated duration'), str(output?.duration) ?? str(output?.estimated_duration));
    return { headline: findHeadline(output), rows };
  }

  // Type inconnu : repli générique sur les scalaires du payload d'entrée.
  if (input) {
    for (const [k, v] of Object.entries(input).slice(0, 6)) {
      const s = fmtScalar(v, lang);
      if (s) rows.push({ label: k, value: s });
    }
  }
  return { headline: findHeadline(output), rows };
};

export default function JournalPage() {
  const ui = useUILang();
  const [items, setItems] = useState<AiAnalysis[]>([]);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(DEFAULT_PER_PAGE);
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
      setError(errMsg(e, ui));
    } finally {
      setLoading(false);
    }
  }, [page, perPage, typeF, incidentF, ui]);

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

  const summary = selected ? buildSummary(selected, ui) : null;
  const selectedIncidentId = selected?.incident_id ?? selected?.incident?.id ?? null;

  return (
    <div className="mx-auto w-full max-w-6xl">
      <PageHeader
        title={pick(ui, 'Journal IA', 'AI journal')}
        description={pick(ui, `Toutes les décisions de l'IA : confiance, modèle, traçabilité — ${fmtNum(total)} analyse(s).`, `Every AI decision: confidence, model, traceability — ${fmtNum(total)} analyse(s).`)}
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
          <span className="mb-1 block text-xs font-medium text-ink-soft">{pick(ui, "Type d'analyse", 'Analysis type')}</span>
          <Select
            value={typeV}
            onChange={(e) => setTypeV(e.target.value)}
            className="w-48"
            options={[{ value: '', label: pick(ui, 'Tous les types', 'All types') },
              ...ANALYSIS_TYPES.map((t) => ({ value: t.value, label: pick(ui, t.label, t.labelEn) }))]}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-ink-soft">{pick(ui, 'Incident (n°)', 'Incident (#)')}</span>
          <input
            type="number"
            min={1}
            step={1}
            inputMode="numeric"
            placeholder={pick(ui, 'ex. 12', 'e.g. 12')}
            value={incidentV}
            onChange={(e) => setIncidentV(e.target.value)}
            className={`${INPUT_CLS} w-32`}
          />
        </label>
        <Button type="submit" variant="primary">
          {pick(ui, 'Filtrer', 'Filter')}
        </Button>
        {hasFilter && (
          <Button type="button" variant="ghost" onClick={resetFilters}>
            {pick(ui, 'Réinitialiser', 'Reset')}
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
                title={pick(ui, 'Aucune analyse', 'No analyses')}
                description={
                  hasFilter
                    ? pick(ui, "Aucune analyse ne correspond à ces filtres.", 'No analyses match these filters.')
                    : pick(ui, 'Le journal est vide.', 'The journal is empty.')
                }
                action={
                  hasFilter ? (
                    <Button size="sm" onClick={resetFilters}>
                      {pick(ui, 'Réinitialiser les filtres', 'Reset filters')}
                    </Button>
                  ) : undefined
                }
              />
            </Card>
          )}
          {items.map((a) => {
            const meta = typeMeta(a.analysis_type, ui);
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
                  {a.incident?.reference_code ?? (a.incident_id ? `Incident #${a.incident_id}` : pick(ui, 'Sans incident', 'No incident'))} ·{' '}
                  {a.model_used ?? pick(ui, 'modèle ?', 'model?')}
                </p>
                <div className="mt-1.5 flex items-center justify-between gap-2">
                  <ConfidenceMeter value={confPct(a.confidence)} />
                  <span className="font-mono text-xs text-ink-faint">
                    {a.processing_ms != null ? `${fmtNum(a.processing_ms)} ms · ` : ''}
                    {fmtDateL(a.created_at, ui)}
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
                title={pick(ui, 'Sélectionnez une analyse', 'Select an analysis')}
                description={pick(ui, 'Vérifiez les entrées et sorties de chaque décision IA.', 'Check the inputs and outputs of each AI decision.')}
              />
            </Card>
          )}
          {selected && summary && (
            <Card className="space-y-4 p-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={typeMeta(selected.analysis_type, ui).tone}>
                    {typeMeta(selected.analysis_type, ui).label}
                  </Badge>
                  <ConfidenceMeter value={confPct(selected.confidence)} label={pick(ui, 'Confiance', 'Confidence')} />
                </div>
                <p className="mt-2 font-mono text-xs">
                  {selected.incident?.reference_code ?? (selected.incident_id ? `Incident #${selected.incident_id}` : pick(ui, 'Sans incident', 'No incident'))} ·{' '}
                  {selected.model_used ?? pick(ui, 'modèle ?', 'model?')} · {fmtDateL(selected.created_at, ui)}
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
                      {pick(ui, "Voir l'incident", 'See incident')}
                    </Button>
                  </div>
                )}
              </div>

              <div>
                <h3 className="mb-1 text-sm font-semibold">{pick(ui, 'Résumé', 'Summary')}</h3>
                {summary.headline !== null && (
                  <p className="text-sm leading-relaxed">{summary.headline}</p>
                )}
                {summary.rows.length > 0 && (
                  <dl className="mt-2 space-y-1.5 border-t border-line pt-2 text-sm">
                    {summary.rows.map((r) => (
                      <div key={r.label} className="flex items-start justify-between gap-3">
                        <dt className="shrink-0 text-ink-soft">{r.label}</dt>
                        <dd className="text-right font-medium">
                          {(r.label === 'Urgence' || r.label === 'Urgency') && selected.analysis_type === 'triage' ? (
                            <Badge tone={urgencyTone(urgencyCodeFromLabel(r.value))}>
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
                    {pick(ui, 'Aucun résumé disponible — consultez les payloads ci-dessous.', 'No summary available — see the payloads below.')}
                  </p>
                )}
              </div>

              <details>
                <summary className="cursor-pointer text-sm font-semibold text-ink-soft">
                  {pick(ui, "Entrée (données envoyées à l'IA)", 'Input (data sent to the AI)')}
                </summary>
                <div className="mt-2">
                  <Pretty data={selected.input_payload} />
                </div>
              </details>
              <details>
                <summary className="cursor-pointer text-sm font-semibold text-ink-soft">
                  {pick(ui, "Sortie (réponse brute de l'IA)", 'Output (raw AI response)')}
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
        lang={ui}
      />
    </div>
  );
}
