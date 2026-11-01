import { memo, useState } from 'react';
import type { ReactNode } from 'react';
import { Badge, Button, Card } from './ui';
import { Icon } from './icons';
import { VoicePlayer } from './VoiceControls';
import type { AgentCard, ProposalNextAction } from '../lib/api';
import { api, ApiError } from '../lib/api';
import { ThresholdGauge } from './ThresholdGauge';
import { TrendChart, TrendDonut, TrendHBars } from './TrendChart';
import type { DonutEntry, HBarEntry, TrendSeries } from './TrendChart';
import { BudgetCompare, CalendarHeatmap, IncidentTimeline } from './VizExtra';
import type { BudgetCategory, BudgetSchool, HeatmapDay, TimelineStep } from './VizExtra';
import { TerritoryLegend, TerritoryMap } from './TerritoryMap';
import { SlideDeck } from './SlideDeck';
import type { DeckSlide } from './SlideDeck';
import type { TerritoryPoint } from './TerritoryMap';
import type { DetailKind } from './DetailDrawer';

// ---------- Helpers défensifs (les observations tools varient) ----------

const fmtInt = (v: unknown): string => {
  if (typeof v === 'number' && Number.isFinite(v)) return new Intl.NumberFormat('fr-FR').format(Math.round(v));
  return '—';
};

const fmtNum1 = (v: unknown): string => {
  if (typeof v === 'number' && Number.isFinite(v))
    return v.toLocaleString('fr-FR', { maximumFractionDigits: 1 });
  return '—';
};

const fmtText = (v: unknown): string => (typeof v === 'string' && v !== '' ? v : '—');

const fmtOpt = (v: unknown): string | undefined => (typeof v === 'string' && v !== '' ? v : undefined);

const fmtDate = (v: unknown): string => {
  if (typeof v !== 'string' || v === '') return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  const d =
    m !== null ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(v);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
};

/** Remplace les dates ISO (AAAA-MM-JJ) d'un texte par des dates lisibles. */
const humanizeDates = (text: string): string =>
  text.replace(/\d{4}-\d{2}-\d{2}/g, (m) => fmtDate(m));

/** Assemble un texte parlé en français simple à partir de morceaux. */
const speak = (...parts: (string | undefined)[]): string =>
  parts.filter((p): p is string => typeof p === 'string' && p.trim() !== '').join(' ');

/** Convertit un montant en libellé « 12 500 XAF » ; undefined si absent. */
const fmtCostXAF = (v: unknown): string | undefined =>
  typeof v === 'number' && Number.isFinite(v) ? `${fmtInt(v)} XAF` : undefined;

const asArray = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);
const asRecord = (v: unknown): Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : {};

const URGENCY_TONE: Record<string, 'danger' | 'warn' | 'info' | 'neutral'> = {
  critical: 'danger',
  high: 'warn',
  medium: 'info',
  low: 'neutral',
};
const URGENCY_LABEL: Record<string, string> = {
  critical: 'Critique',
  high: 'Haute',
  medium: 'Moyenne',
  low: 'Basse',
};
const URGENCY_DOT: Record<string, string> = {
  critical: 'bg-red-500',
  high: 'bg-amber-500',
  medium: 'bg-sky-500',
  low: 'bg-teal-500',
};
const URGENCY_BAR: Record<string, string> = {
  critical: 'bg-red-500',
  high: 'bg-amber-500',
  medium: 'bg-sky-500',
  low: 'bg-teal-600 dark:bg-teal-500',
};
const CATEGORY_LABEL: Record<string, string> = {
  water_point: "Point d'eau",
  toilets_latrines: 'Toilettes / latrines',
  handwashing: 'Lavage des mains',
  sewage_drainage: 'Évacuation',
};
const STATUS_LABEL: Record<string, string> = {
  reported: 'Signalé',
  triaged: 'Trié',
  assigned: 'Assigné',
  in_progress: 'En cours',
  resolved: 'Résolu',
  closed: 'Clôturé',
};
const RECOMMENDATION: Record<string, { label: string; tone: 'danger' | 'warn' | 'success' }> = {
  REPLACE_EQUIPMENT: { label: "Remplacer l'équipement", tone: 'danger' },
  MONITOR_CLOSELY: { label: 'Surveillance renforcée', tone: 'warn' },
  CONTINUE_REPAIR: { label: 'Continuer les réparations', tone: 'success' },
};
const VERDICT_STYLE: Record<string, string> = {
  danger: 'bg-red-50 text-red-800 dark:bg-red-950/60 dark:text-red-200',
  warn: 'bg-amber-50 text-amber-900 dark:bg-amber-950/60 dark:text-amber-200',
  success: 'bg-teal-50 text-teal-900 dark:bg-teal-950/60 dark:text-teal-200',
};

// ---------- Briques ----------

/** Même pattern que ConsolePage : synthèse vocale au clic, jamais d'autoplay. */
async function synthesizeToUrl(text: string): Promise<string | null> {
  try {
    const res = await api.synthesizeVoice(text);
    const bin = atob(res.audio_base64);
    const bytes = new Uint8Array(bin.length);
    for (let k = 0; k < bin.length; k++) bytes[k] = bin.charCodeAt(k);
    return URL.createObjectURL(new Blob([bytes], { type: res.mime_type }));
  } catch {
    return null;
  }
}

function ListenButton({ text }: { text: string }) {
  if (text === '') return null;
  return <VoicePlayer onRequestAudio={() => synthesizeToUrl(text)} />;
}

function CardShell({
  title,
  meta,
  actions,
  listenText,
  children,
}: {
  title: string;
  meta?: string;
  actions?: ReactNode;
  listenText?: string;
  children: ReactNode;
}) {
  return (
    <Card className="p-4 sm:p-5">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-x-3 gap-y-2 border-b border-stone-200/80 pb-3 dark:border-white/[0.07]">
        <h3 className="font-display text-[17px] font-bold leading-snug tracking-tight">{title}</h3>
        {(meta !== undefined || actions !== undefined || listenText !== undefined) && (
          <div className="flex flex-wrap items-center gap-2">
            {listenText !== undefined && listenText !== '' && <ListenButton text={listenText} />}
            {meta !== undefined && (
              <span className="font-mono text-[11px] text-stone-500 dark:text-stone-400">{meta}</span>
            )}
            {actions}
          </div>
        )}
      </div>
      {children}
    </Card>
  );
}

function Stat({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <p className="text-[11px] text-stone-500 dark:text-stone-400">{label}</p>
      <p className={`mt-0.5 text-sm font-semibold tabular-nums ${mono ? 'font-mono' : ''}`}>{value}</p>
    </div>
  );
}

function HeroStat({
  label,
  value,
  delta,
  invert = false,
}: {
  label: string;
  value: string;
  delta?: number | null;
  invert?: boolean;
}) {
  return (
    <div className="flex items-end justify-between gap-3">
      <div>
        <p className="text-xs text-stone-500 dark:text-stone-400">{label}</p>
        <p className="mt-1 font-display text-[34px] font-extrabold leading-none tabular-nums">{value}</p>
      </div>
      {delta !== undefined && delta !== null && <DeltaChip pct={delta} invert={invert} />}
    </div>
  );
}

function DeltaChip({ pct, invert = false }: { pct: number; invert?: boolean }) {
  if (!Number.isFinite(pct)) return null;
  const up = pct >= 0;
  const good = invert ? !up : up;
  const flat = Math.abs(pct) < 0.5;
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-1 font-mono text-xs font-semibold tabular-nums ${
        flat
          ? 'bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-300'
          : good
            ? 'bg-teal-50 text-teal-800 dark:bg-teal-950/60 dark:text-teal-300'
            : 'bg-red-50 text-red-700 dark:bg-red-950/60 dark:text-red-300'
      }`}
    >
      {!flat && (
        <span aria-hidden="true">{up ? '▲' : '▼'}</span>
      )}
      {flat ? 'stable' : `${up ? '+' : ''}${pct.toLocaleString('fr-FR', { maximumFractionDigits: 0 })} %`}
    </span>
  );
}

function Sparkline({ data, width = 120, height = 36 }: { data: number[]; width?: number; height?: number }) {
  if (data.length < 2) return null;
  const min = Math.min(...data);
  const span = Math.max(...data) - min || 1;
  const y = (v: number) => height - 3 - ((v - min) / span) * (height - 6);
  const pts = data
    .map((v, i) => `${((i / (data.length - 1)) * width).toFixed(1)},${y(v).toFixed(1)}`)
    .join(' ');
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
      className="shrink-0 overflow-visible text-teal-700 dark:text-teal-400"
    >
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={width} cy={y(data[data.length - 1])} r="3" fill="currentColor" />
    </svg>
  );
}

function InsightLine({ text }: { text: string }) {
  if (text === '') return null;
  return (
    <p className="mb-3 flex gap-2 border-b border-stone-200/70 pb-3 text-sm leading-relaxed text-stone-700 dark:border-white/[0.06] dark:text-stone-300">
      <span aria-hidden="true" className="font-mono font-bold text-teal-700 dark:text-teal-400">
        ›
      </span>
      <span>{text}</span>
    </p>
  );
}

export function FollowUps({ items, onAsk }: { items: string[]; onAsk?: (q: string) => void }) {
  if (onAsk === undefined || items.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-1.5 border-t border-stone-200/70 pt-3 dark:border-white/[0.06]">
      {items.map((q) => (
        <button
          key={q}
          type="button"
          onClick={() => onAsk(q)}
          className="max-w-full truncate rounded-full border border-line bg-card px-3 py-1.5 text-[13px] text-ink-soft transition-[border-color,color,transform] duration-150 ease-snap hover:border-accent hover:text-ink active:scale-[0.97] motion-reduce:transition-none motion-reduce:active:scale-100"
        >
          {q}
        </button>
      ))}
    </div>
  );
}

function UrgencyDot({ level }: { level: string }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block h-2 w-2 shrink-0 rounded-full ${URGENCY_DOT[level] ?? 'bg-stone-400'}`}
    />
  );
}

function NeedBar({ value, max, bar = 'bg-teal-600 dark:bg-teal-500' }: { value: number; max: number; bar?: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800">
      <div className={`h-full rounded-full ${bar}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function CopyButton({ value, label = 'Copier' }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  if (value === '') return null;
  return (
    <Button
      size="sm"
      onClick={() => {
        try {
          void navigator.clipboard.writeText(value).then(() => setCopied(true));
        } catch {
          /* presse-papiers indisponible */
        }
        window.setTimeout(() => setCopied(false), 1500);
      }}
    >
      <Icon name={copied ? 'check' : 'file'} className="h-3.5 w-3.5" />
      {copied ? 'Copié' : label}
    </Button>
  );
}

// ---------- Cartes ----------

function IncidentPickerCard({
  title,
  data,
  onAsk,
}: {
  title: string;
  data: Record<string, unknown>;
  onAsk?: (q: string) => void;
}) {
  const [picked, setPicked] = useState<string | null>(null);
  const candidates = asArray<Record<string, unknown>>(data.candidates);
  const hint = fmtOpt(data.hint);
  if (candidates.length === 0) return null;
  const pick = (ref: string) => {
    if (picked !== null) return;
    setPicked(ref);
    onAsk?.(ref);
  };
  const countLabel = candidates.length <= 1 ? '1 incident' : `${candidates.length} incidents`;
  return (
    <CardShell
      title={title}
      meta={hint === undefined ? countLabel : `« ${hint} » · ${countLabel}`}
      listenText={speak(
        'Plusieurs incidents sont possibles.',
        hint !== undefined ? `Tu as dit : ${hint}.` : undefined,
        'Choisis le bon dans la liste.',
      )}
    >
      <p className="mb-3 text-sm text-stone-500 dark:text-stone-400">
        Plusieurs incidents correspondent. Cliquez sur le bon — école, urgence et élèves aident à trancher.
      </p>
      <ul className="space-y-2">
        {candidates.map((c, i) => {
          const ref = typeof c.reference_code === 'string' && c.reference_code !== ''
            ? c.reference_code
            : `incident ${String(c.id ?? i + 1)}`;
          const urgency = typeof c.urgency === 'string' ? c.urgency : 'medium';
          const isPicked = picked === ref;
          const dimmed = picked !== null && !isPicked;
          return (
            <li key={`${ref}-${i}`}>
              <button
                type="button"
                disabled={picked !== null}
                onClick={() => pick(ref)}
                className={`flex w-full items-start gap-3 rounded-xl border border-line bg-card p-3 text-left transition-[border-color,opacity,transform] duration-150 ease-snap motion-reduce:transition-none ${dimmed ? 'opacity-45' : ''} ${isPicked ? 'border-accent' : 'hover:border-accent active:scale-[0.99] motion-reduce:active:scale-100'} disabled:cursor-default`}
              >
                <span className="pt-1.5"><UrgencyDot level={urgency} /></span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-display text-[15px] font-bold leading-snug tracking-tight">
                    {fmtText(c.title)}
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-stone-500 dark:text-stone-400">
                    {fmtText(c.school_name)}{typeof c.district === 'string' && c.district !== '' ? ` · ${c.district}` : ''}
                  </span>
                  <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    <Badge tone={URGENCY_TONE[urgency] ?? 'neutral'}>{URGENCY_LABEL[urgency] ?? urgency}</Badge>
                    <Badge>{STATUS_LABEL[String(c.status)] ?? fmtText(c.status)}</Badge>
                    <span className="font-mono text-[11px] text-stone-500 dark:text-stone-400">{ref}</span>
                  </span>
                </span>
                <span className="shrink-0 text-right">
                  <span className="block font-display text-lg font-extrabold tabular-nums">{fmtInt(c.affected_students)}</span>
                  <span className="block text-[11px] text-stone-500 dark:text-stone-400">élèves</span>
                  {isPicked && <Icon name="check" className="ml-auto mt-1 h-4 w-4" />}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </CardShell>
  );
}

function IncidentCard({
  title,
  data,
  onAsk,
  onDetail,
}: {
  title: string;
  data: Record<string, unknown>;
  onAsk?: (q: string) => void;
  onDetail?: (kind: DetailKind, id: number) => void;
}) {
  const urgency = typeof data.urgency === 'string' ? data.urgency : 'medium';
  const priority = typeof data.priority_score === 'number' ? data.priority_score : null;
  const school = fmtOpt(data.school_name);
  const incidentId = typeof data.id === 'number' ? data.id : null;
  const affected = typeof data.affected_students === 'number' ? data.affected_students : null;
  const summary = typeof data.summary === 'string' ? data.summary : fmtOpt(data.insight);
  return (
    <CardShell
      title={title}
      meta={fmtOpt(data.reference_code)}
      listenText={speak(
        "Détail de l'intervention.",
        summary,
        school !== undefined ? `École : ${school}.` : undefined,
        affected === null
          ? undefined
          : affected === 0
            ? 'Aucun élève touché.'
            : affected === 1
              ? '1 élève touché.'
              : `${affected} élèves touchés.`,
      )}
      actions={
        <>
          {onDetail !== undefined && incidentId !== null && (
            <Button size="sm" onClick={() => onDetail('incident', incidentId)}>
              Détails
            </Button>
          )}
          <CopyButton value={fmtOpt(data.reference_code) ?? ''} label="Référence" />
        </>
      }
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs text-stone-500 dark:text-stone-400">Priorité IA</p>
          <p className="mt-1 font-display text-[34px] font-extrabold leading-none tabular-nums">
            {priority === null ? '—' : fmtNum1(priority)}
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Badge tone={URGENCY_TONE[urgency] ?? 'neutral'}>Urgence {URGENCY_LABEL[urgency] ?? urgency}</Badge>
          <Badge>{STATUS_LABEL[String(data.status)] ?? fmtText(data.status)}</Badge>
          {typeof data.category === 'string' && (
            <Badge tone="info">{CATEGORY_LABEL[data.category] ?? data.category}</Badge>
          )}
        </div>
      </div>
      <InsightLine text={fmtOpt(data.insight) ?? ''} />
      {typeof data.summary === 'string' && data.summary !== '' && (
        <p className="mt-3 text-sm leading-relaxed">{data.summary}</p>
      )}
      <p className="mt-1 font-mono text-xs text-stone-500 dark:text-stone-400">
        {fmtText(data.school_name)} · {fmtText(data.district)}
      </p>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Stat label="Élèves affectés" value={fmtInt(data.affected_students)} />
        <Stat label="Signalé le" value={fmtDate(data.reported_at)} mono={false} />
        <Stat
          label="Catégorie"
          value={
            typeof data.category === 'string' && data.category !== ''
              ? (CATEGORY_LABEL[data.category] ?? data.category)
              : 'Non précisée'
          }
          mono={false}
        />
      </div>
      <FollowUps
        onAsk={onAsk}
        items={
          school !== undefined
            ? [`Analyser ${school} ?`, `Voir les tendances de ${school}`]
            : ['Résume la situation du district']
        }
      />
    </CardShell>
  );
}

function RankingCard({
  title,
  data,
  onAsk,
  onDetail,
}: {
  title: string;
  data: Record<string, unknown>;
  onAsk?: (q: string) => void;
  onDetail?: (kind: DetailKind, id: number) => void;
}) {
  const ranking = asArray<Record<string, unknown>>(data.ranking);
  const max = Math.max(0, ...ranking.map((r) => (typeof r.need_score === 'number' ? r.need_score : 0)));
  const top = fmtOpt(ranking[0]?.school_name);
  const totalSchools = typeof data.total === 'number' ? data.total : ranking.length;
  const schoolsMeta =
    totalSchools === 0 ? 'Aucune école' : `${fmtInt(totalSchools)} école${totalSchools > 1 ? 's' : ''}`;
  const rankingInsight = fmtOpt(data.insight) ?? '';
  return (
    <CardShell
      title={title}
      meta={schoolsMeta}
      listenText={speak(
        'Classement des écoles par besoin.',
        rankingInsight !== '' ? rankingInsight : undefined,
        top !== undefined ? `En premier : ${top}.` : 'Aucune école à classer.',
      )}
    >
      <InsightLine text={rankingInsight} />
      {ranking.length === 0 ? (
        <p className="text-sm text-stone-600 dark:text-stone-400">Aucune école à classer.</p>
      ) : (
        <div className="divide-y divide-stone-200 dark:divide-stone-800">
          {ranking.map((r, i) => {
            const urg = typeof r.top_urgency === 'string' ? r.top_urgency : 'low';
            const score = typeof r.need_score === 'number' ? r.need_score : 0;
            const n = typeof r.open_incidents === 'number' ? r.open_incidents : 0;
            const pupils = typeof r.affected_students === 'number' ? r.affected_students : 0;
            const oldest = typeof r.oldest_days === 'number' ? r.oldest_days : 0;
            const incidentsLabel = n === 0 ? 'Aucun incident' : `${fmtInt(n)} incident${n > 1 ? 's' : ''}`;
            const pupilsLabel =
              pupils === 0 ? 'aucun élève' : `${fmtInt(pupils)} élève${pupils > 1 ? 's' : ''}`;
            const oldestLabel = oldest <= 0 ? "aujourd'hui" : `${fmtInt(oldest)} j`;
            const schoolId = typeof r.school_id === 'number' ? r.school_id : null;
            const clickable = onDetail !== undefined && schoolId !== null;
            const rowClass = `flex items-center gap-3 py-2.5 first:pt-0 last:pb-0 ${
              i === 0 ? '-mx-2 rounded-lg bg-teal-50/70 px-2 dark:bg-teal-950/30' : ''
            }`;
            const content = (
              <>
                <span className="w-7 shrink-0 font-display text-sm font-bold tabular-nums text-stone-400 dark:text-stone-500">
                  {String(i + 1).padStart(2, '0')}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{fmtText(r.school_name)}</span>
                  <span className="block font-mono text-[11px] text-stone-500 dark:text-stone-400">
                    {fmtText(r.district)} · {incidentsLabel} · {pupilsLabel} · {oldestLabel}
                  </span>
                  <span className="mt-1.5 block">
                    <NeedBar value={score} max={max} />
                  </span>
                </span>
                <span className="flex shrink-0 flex-col items-end gap-1">
                  <span className="font-display text-lg font-extrabold tabular-nums">{fmtNum1(score)}</span>
                  <span className="inline-flex items-center gap-1.5 text-xs text-stone-600 dark:text-stone-400">
                    <UrgencyDot level={urg} />
                    {URGENCY_LABEL[urg] ?? urg}
                  </span>
                </span>
              </>
            );
            return clickable ? (
              <button
                key={String(schoolId ?? i)}
                type="button"
                onClick={() => {
                  if (schoolId !== null) onDetail?.('school', schoolId);
                }}
                title="Voir le détail de l'école"
                className={`${rowClass} w-full rounded-lg text-left transition-[background-color,transform] duration-150 ease-snap hover:bg-raised active:scale-[0.99] motion-reduce:transition-none motion-reduce:active:scale-100`}
              >
                {content}
              </button>
            ) : (
              <div key={String(r.school_id ?? i)} className={rowClass}>
                {content}
              </div>
            );
          })}
        </div>
      )}
      <FollowUps
        onAsk={onAsk}
        items={top !== undefined ? [`Analyser ${top} ?`, 'Voir la carte du territoire'] : ['Voir la carte du territoire']}
      />
    </CardShell>
  );
}

function AnalysisCard({
  title,
  data,
  onAsk,
}: {
  title: string;
  data: Record<string, unknown>;
  onAsk?: (q: string) => void;
}) {
  const reco =
    typeof data.recommendation === 'string' ? RECOMMENDATION[data.recommendation] : undefined;
  const ratio = typeof data.repair_ratio_percent === 'number' ? data.repair_ratio_percent : null;
  const open = asArray<Record<string, unknown>>(data.open_incidents);
  const school = fmtOpt(data.school_name);
  const justification = typeof data.justification === 'string' ? data.justification : undefined;
  return (
    <CardShell
      title={title}
      meta={fmtOpt(data.district)}
      listenText={speak(
        school !== undefined ? `Analyse de ${school}.` : "Analyse de l'école.",
        reco?.label,
        justification,
      )}
    >
      {reco && (
        <div
          className={`mb-3 flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold ${VERDICT_STYLE[reco.tone]}`}
        >
          <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full bg-current" />
          {reco.label}
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div>
          <p className="text-[11px] text-stone-500 dark:text-stone-400">Ratio réparations / neuf</p>
          <div className="mt-1">
            {ratio === null ? (
              <p className="font-mono text-sm font-semibold tabular-nums">—</p>
            ) : (
              <ThresholdGauge
                value={ratio}
                display={`${fmtNum1(ratio)} %`}
                thresholds={[
                  { value: 30, label: '30 %', tone: 'warn' },
                  { value: 55, label: '55 %', tone: 'danger' },
                ]}
              />
            )}
          </div>
        </div>
        <Stat label="Pannes / an" value={fmtNum1(data.annualized_failure_rate)} />
        <Stat label="Économies potentielles" value={fmtInt(data.financial_saving_potential)} />
      </div>
      {typeof data.justification === 'string' && data.justification !== '' && (
        <p className="mt-3 text-sm leading-relaxed">{data.justification}</p>
      )}
      {typeof data.suggested_modernization === 'string' && data.suggested_modernization !== '' && (
        <p className="mt-2 text-sm">
          <span className="font-semibold">Modernisation suggérée : </span>
          {data.suggested_modernization}
        </p>
      )}
      {open.length > 0 && (
        <div className="mt-3 divide-y divide-stone-200 dark:divide-stone-800">
          {open.map((inc, i) => {
            const urg = typeof inc.urgency === 'string' ? inc.urgency : 'low';
            return (
              <div key={String(inc.id ?? i)} className="flex items-center gap-2 py-1.5 text-sm first:pt-0 last:pb-0">
                <UrgencyDot level={urg} />
                <span className="w-16 shrink-0 text-xs text-stone-600 dark:text-stone-400">
                  {URGENCY_LABEL[urg] ?? urg}
                </span>
                <span className="min-w-0 flex-1 truncate">{fmtText(inc.title)}</span>
                <span className="shrink-0 font-mono text-xs text-stone-500 dark:text-stone-400">
                  {fmtInt(inc.affected_students)} élèves
                </span>
              </div>
            );
          })}
        </div>
      )}
      <FollowUps
        onAsk={onAsk}
        items={
          school !== undefined
            ? [`Voir les tendances de ${school}`, 'Préparer un briefing']
            : ['Préparer un briefing']
        }
      />
    </CardShell>
  );
}

function DistrictCard({
  title,
  data,
  onAsk,
}: {
  title: string;
  data: Record<string, unknown>;
  onAsk?: (q: string) => void;
}) {
  const byUrgency = asRecord(data.by_urgency);
  const byCategory = asRecord(data.by_category);
  const schools = asArray<string>(data.schools_involved);
  const total = typeof data.open_incidents === 'number' ? data.open_incidents : 0;
  const totalPupils = typeof data.total_affected_students === 'number' ? data.total_affected_students : 0;
  const districtInsight = fmtOpt(data.insight);
  const urgEntries = Object.entries(byUrgency).filter(([, v]) => typeof v === 'number') as [string, number][];
  return (
    <CardShell
      title={title}
      listenText={speak(
        'Synthèse du district.',
        districtInsight,
        total === 0
          ? 'Aucun incident ouvert.'
          : total === 1
            ? '1 incident ouvert.'
            : `${total} incidents ouverts.`,
        totalPupils === 0 ? 'Aucun élève touché.' : `${totalPupils} élèves touchés.`,
      )}
    >
      <div className="grid grid-cols-2 gap-3">
        <HeroStat label="Incidents ouverts" value={fmtInt(data.open_incidents)} />
        <HeroStat label="Élèves affectés" value={fmtInt(data.total_affected_students)} />
      </div>
      <div className="mt-3">
        <InsightLine text={districtInsight ?? ''} />
      </div>
      {urgEntries.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {urgEntries.map(([k, v]) => (
            <div key={k} className="flex items-center gap-2">
              <span className="flex w-24 shrink-0 items-center gap-1.5 text-xs text-stone-600 dark:text-stone-400">
                <UrgencyDot level={k} />
                {URGENCY_LABEL[k] ?? k}
              </span>
              <div className="flex-1">
                <NeedBar value={v} max={Math.max(total, 1)} bar={URGENCY_BAR[k] ?? 'bg-teal-600 dark:bg-teal-500'} />
              </div>
              <span className="w-8 shrink-0 text-right font-mono text-xs tabular-nums">{fmtInt(v)}</span>
            </div>
          ))}
        </div>
      )}
      {Object.keys(byCategory).length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {Object.entries(byCategory).map(([k, v]) => (
            <Badge key={k} tone="info">
              {CATEGORY_LABEL[k] ?? k} · {fmtInt(v)}
            </Badge>
          ))}
        </div>
      )}
      {schools.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {schools.map((s) => (
            <Badge key={s}>{s}</Badge>
          ))}
        </div>
      )}
      <FollowUps
        onAsk={onAsk}
        items={["Quelles écoles ont le plus besoin d'aide ?", 'Voir la carte du territoire']}
      />
    </CardShell>
  );
}

// ---------- Tendances : vues riches (helpers privés) ----------

type TrendViewId = 'courbe' | 'couts' | 'pannes' | 'ecoles' | 'urgences';

const TREND_PERIODS = [3, 6, 12];

const URGENCY_SLICE: Record<string, string> = {
  critical: '#ef4444',
  high: '#f59e0b',
  medium: '#0284c7',
  low: '#0d9488',
};

/** Nombre sûr (0 si absent) pour les calculs de vues. */
const trendNum = (v: unknown): number =>
  typeof v === 'number' && Number.isFinite(v) ? v : 0;

/** Entrées anneau urgences depuis by_urgency (optionnel, défensif). */
function trendUrgencyEntries(data: Record<string, unknown>): DonutEntry[] {
  return Object.entries(asRecord(data.by_urgency))
    .filter(([, v]) => typeof v === 'number' && Number.isFinite(v) && (v as number) > 0)
    .map(([k, v]) => ({
      name: URGENCY_LABEL[k] ?? k,
      value: v as number,
      color: URGENCY_SLICE[k] ?? '#a8a29e',
    }))
    .sort((a, b) => b.value - a.value);
}

/** Top écoles depuis per_school (optionnel, défensif : liste ou objet). */
function trendSchoolEntries(data: Record<string, unknown>): HBarEntry[] {
  const raw = data.per_school;
  const out: HBarEntry[] = [];
  for (const r of asArray<unknown>(raw)) {
    const rec = asRecord(r);
    const name = fmtOpt(rec.school_name) ?? fmtOpt(rec.name) ?? fmtOpt(rec.label);
    if (name === undefined) continue;
    const v = rec.incidents ?? rec.total_incidents ?? rec.pannes ?? rec.count ?? rec.value ?? rec.total;
    out.push({ name, value: trendNum(v) });
  }
  for (const [k, v] of Object.entries(asRecord(raw))) {
    if (typeof v === 'number' && Number.isFinite(v)) out.push({ name: k, value: v });
  }
  return out
    .filter((e) => e.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 5);
}

/** Onglets simples en français pour changer de graphique. */
function TrendTabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: TrendViewId; label: string }[];
  active: TrendViewId;
  onChange: (v: TrendViewId) => void;
}) {
  return (
    <div role="tablist" aria-label="Choisir le graphique" className="flex flex-wrap gap-1.5">
      {tabs.map((t, i) => {
        const selected = t.id === active;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(t.id)}
            style={{ animationDelay: `${i * 40}ms` }}
            className={`trend-in rounded-full px-3 py-1.5 text-[13px] font-medium transition-[transform,opacity] duration-150 ease-snap active:scale-[0.97] motion-reduce:transition-none motion-reduce:active:scale-100 ${
              selected
                ? 'bg-teal-700 text-white dark:bg-teal-500 dark:text-stone-950'
                : 'border border-line bg-card text-ink-soft hover:text-ink'
            }`}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

/** Sélecteur de période : repose une question tendances sur 3, 6 ou 12 mois. */
function TrendPeriods({
  current,
  school,
  onAsk,
}: {
  current: number | null;
  school?: string;
  onAsk: (q: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs text-stone-500 dark:text-stone-400">Période :</span>
      {TREND_PERIODS.map((n) => {
        const selected = current === n;
        return (
          <button
            key={n}
            type="button"
            disabled={selected}
            aria-current={selected ? 'true' : undefined}
            onClick={() =>
              onAsk(
                school !== undefined
                  ? `Voir les tendances de ${school} sur ${n} mois`
                  : `Voir les tendances sur ${n} mois`,
              )
            }
            className={`rounded-full px-2.5 py-1 text-xs font-medium transition-[transform,opacity] duration-150 ease-snap active:scale-[0.97] motion-reduce:transition-none motion-reduce:active:scale-100 disabled:cursor-default ${
              selected
                ? 'bg-teal-700 text-white dark:bg-teal-500 dark:text-stone-950'
                : 'border border-line bg-card text-ink-soft hover:text-ink'
            }`}
          >
            {n} mois
          </button>
        );
      })}
    </div>
  );
}

function TrendCard({
  title,
  data,
  onAsk,
}: {
  title: string;
  data: Record<string, unknown>;
  onAsk?: (q: string) => void;
}) {
  const labels = asArray<unknown>(data.labels).map((l, i) =>
    typeof l === 'string' && l !== '' ? l : `M${i + 1}`,
  );
  const datasets = asArray<{ label?: unknown; data?: unknown; kind?: unknown }>(data.datasets);
  const figures = asRecord(data.figures);
  const palette = ['#0d9488', '#d97706', '#e11d48', '#0284c7'];
  const series: TrendSeries[] = datasets.map((d, i) => ({
    key: `s${i}`,
    label: typeof d.label === 'string' && d.label !== '' ? d.label : `Série ${i + 1}`,
    kind: d.kind === 'line' ? 'line' : 'bar',
    data: asArray<number>(d.data).map((v) => (typeof v === 'number' && Number.isFinite(v) ? v : 0)),
    color: palette[i % palette.length],
  }));
  const costs = series[0]?.kind === 'bar' ? (series[0]?.data ?? []) : [];
  const last = costs[costs.length - 1];
  const prev = costs.slice(0, -1);
  const avg = prev.length > 0 ? prev.reduce((s, v) => s + v, 0) / prev.length : 0;
  const delta = last !== undefined && avg > 0 ? ((last - avg) / avg) * 100 : null;
  const currency = typeof figures.currency === 'string' ? ` (${figures.currency})` : '';
  const currencyCode = typeof figures.currency === 'string' ? figures.currency : 'XAF';
  const school = fmtOpt(data.school_name);
  const months = typeof data.months === 'number' && Number.isFinite(data.months) ? data.months : null;
  const trendInsight = fmtOpt(data.insight);
  // Séries repérées par mots-clés (défensif : repli sur l'ordre backend coûts/pannes/jours).
  const lines = series.filter((s) => s.kind === 'line');
  const byWords = (words: string[]): number[] =>
    series.find((s) => words.some((w) => s.label.toLowerCase().includes(w)))?.data ?? [];
  const costData = byWords(['coût', 'cout', 'xaf', 'fcfa', 'franc', 'réparation']);
  const incidentData = byWords(['panne', 'incident']);
  const daysData = byWords(['jour']);
  const costBars = costData.length > 0 ? costData : costs;
  const incidentBars = incidentData.length > 0 ? incidentData : (lines[0]?.data ?? []);
  const daysBars = daysData.length > 0 ? daysData : (lines[1]?.data ?? []);
  // Enrichissements optionnels (rendu dégradé propre si absents).
  const urgencyEntries = trendUrgencyEntries(data);
  const schoolEntries = trendSchoolEntries(data);
  const tabs: { id: TrendViewId; label: string }[] = [
    { id: 'courbe', label: 'Courbe' },
    { id: 'couts', label: 'Coûts' },
    { id: 'pannes', label: 'Pannes' },
    ...(schoolEntries.length > 0 ? [{ id: 'ecoles' as TrendViewId, label: 'Écoles' }] : []),
    ...(urgencyEntries.length > 0 ? [{ id: 'urgences' as TrendViewId, label: 'Urgences' }] : []),
  ];
  const [view, setView] = useState<TrendViewId>('courbe');
  const activeView = tabs.some((t) => t.id === view) ? view : 'courbe';
  const hasChart = labels.length > 0 && series.length > 0;
  const askMonth = (index: number): void => {
    if (onAsk === undefined) return;
    const label = labels[index] ?? `M${index + 1}`;
    onAsk(school !== undefined ? `Détail de ${school} en ${label} ?` : `Détail en ${label} ?`);
  };
  const askSchool = (index: number): void => {
    const entry = schoolEntries[index];
    if (onAsk === undefined || entry === undefined) return;
    onAsk(`Voir les tendances de ${entry.name} ?`);
  };
  const askUrgency = (index: number): void => {
    const entry = urgencyEntries[index];
    if (onAsk === undefined || entry === undefined) return;
    const level = entry.name.toLowerCase();
    onAsk(school !== undefined ? `Détail des incidents ${level} à ${school} ?` : `Détail des incidents ${level} ?`);
  };
  // Résumé parlé : « 3 pannes, 50 000 francs, en hausse. »
  const trendDir = typeof figures.trend_direction === 'string' ? figures.trend_direction : 'stable';
  const spokenTrend = trendDir === 'up' ? 'en hausse' : trendDir === 'down' ? 'en baisse' : 'stable';
  const spokenMoney = currencyCode === 'XAF' ? 'francs' : currencyCode;
  const spokenSummary =
    typeof figures.total_incidents === 'number' && typeof figures.total_cost === 'number'
      ? `${fmtInt(figures.total_incidents)} pannes, ${fmtInt(figures.total_cost)} ${spokenMoney}, ${spokenTrend}.`
      : undefined;
  const costOnly: TrendSeries[] = [
    { key: 'couts', label: `Coût réparations (${currencyCode})`, kind: 'bar', data: costBars, color: '#0d9488' },
  ];
  const panneSeries: TrendSeries[] = [
    { key: 'pannes', label: 'Pannes signalées', kind: 'bar', data: incidentBars, color: '#d97706' },
    { key: 'jours', label: 'Jours sans service', kind: 'bar', data: daysBars, color: '#0284c7' },
  ];
  return (
    <CardShell
      title={title}
      meta={months === null ? undefined : months <= 1 ? '1 mois' : `${fmtInt(months)} mois`}
      listenText={speak(
        months === null
          ? 'Tendances.'
          : months <= 1
            ? 'Tendance du mois.'
            : `Tendances sur ${months} mois.`,
        trendInsight,
        school !== undefined ? `École : ${school}.` : undefined,
        spokenSummary,
      )}
    >
      <style>{`@keyframes trend-in{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}.trend-in{animation:trend-in 180ms cubic-bezier(0.23,1,0.32,1) both}@media (prefers-reduced-motion:reduce){.trend-in{animation:none}}`}</style>
      <div className="flex items-end justify-between gap-3">
        <HeroStat label={`Coût total${currency}`} value={fmtInt(figures.total_cost)} delta={delta} invert />
        <Sparkline data={costs} />
      </div>
      <div className="mt-3">
        <InsightLine text={trendInsight ?? ''} />
      </div>
      <div className="mt-3 grid grid-cols-3 gap-3">
        <Stat label="Pannes" value={fmtInt(figures.total_incidents)} />
        <Stat label="Jours sans service" value={fmtInt(figures.total_days_lost)} />
        <Stat label="Coût / mois" value={fmtInt(figures.avg_cost_per_month)} />
      </div>
      {hasChart ? (
        <div className="mt-3 space-y-3">
          <TrendTabs tabs={tabs} active={activeView} onChange={setView} />
          <div key={activeView} className="trend-in">
            {activeView === 'courbe' && (
              <TrendChart labels={labels} series={series} onSelect={onAsk === undefined ? undefined : askMonth} />
            )}
            {activeView === 'couts' && (
              <TrendChart labels={labels} series={costOnly} onSelect={onAsk === undefined ? undefined : askMonth} />
            )}
            {activeView === 'pannes' && (
              <TrendChart labels={labels} series={panneSeries} onSelect={onAsk === undefined ? undefined : askMonth} />
            )}
            {activeView === 'ecoles' && (
              <TrendHBars entries={schoolEntries} unit="pannes" onSelect={onAsk === undefined ? undefined : askSchool} />
            )}
            {activeView === 'urgences' && (
              <TrendDonut entries={urgencyEntries} onSelect={onAsk === undefined ? undefined : askUrgency} />
            )}
          </div>
          {onAsk !== undefined && (
            <p className="text-xs text-stone-500 dark:text-stone-400">
              Touchez le graphique pour poser une question sur un mois.
            </p>
          )}
          {onAsk !== undefined && <TrendPeriods current={months} school={school} onAsk={onAsk} />}
        </div>
      ) : (
        <p className="mt-3 text-sm text-stone-600 dark:text-stone-400">
          Pas assez de données pour tracer la tendance.
        </p>
      )}
      <FollowUps
        onAsk={onAsk}
        items={
          school !== undefined
            ? [`Faut-il remplacer à ${school} ?`, 'Comparer avec une autre école']
            : ['Voir la carte du territoire']
        }
      />
    </CardShell>
  );
}

function ConfirmationCard({ title, data }: { title: string; data: Record<string, unknown> }) {
  const matched = asRecord(data.matched_school);
  const description = typeof data.description === 'string' ? data.description : undefined;
  const matchedName = fmtOpt(matched.school_name);
  return (
    <CardShell
      title={title}
      meta="Brouillon"
      actions={data.needs_confirmation === true ? <Badge tone="warn">Confirmation requise</Badge> : undefined}
      listenText={speak(
        'Vérifie ce brouillon.',
        description,
        matchedName !== undefined ? `École : ${matchedName}.` : undefined,
      )}
    >
      {description !== undefined && (
        <p className="text-sm leading-relaxed">{description}</p>
      )}
      {Object.keys(matched).length > 0 && (
        <p className="mt-2 text-sm">
          <span className="text-stone-500 dark:text-stone-400">École détectée : </span>
          <span className="font-medium">{fmtText(matched.school_name)}</span>{' '}
          <span className="font-mono text-xs text-stone-500 dark:text-stone-400">
            #{fmtText(matched.school_id)}
          </span>
        </p>
      )}
      <p className="mt-2 font-mono text-[11px] text-stone-500 dark:text-stone-400">
        Brouillon uniquement — le dépôt effectif arrive avec la page Signalements, aucun ticket créé.
      </p>
    </CardShell>
  );
}

function ActionConfirmationCard({
  title,
  data,
  onAsk,
  onAppend,
}: {
  title: string;
  data: Record<string, unknown>;
  onAsk?: (q: string) => void;
  onAppend?: (content: string, cards?: AgentCard[]) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [guidance, setGuidance] = useState<ProposalNextAction | null>(null);
  const proposalId = typeof data.proposal_id === 'number' ? data.proposal_id : null;
  const rows = Array.isArray(data.recap_rows) ? data.recap_rows : [];
  const loginRequired = data.login_required === true;
  const notPermitted = data.not_permitted === true;
  const invalid = data.invalid === true;
  const terminal = outcome !== null || loginRequired || notPermitted || invalid;

  const run = async (kind: 'confirm' | 'cancel') => {
    if (proposalId === null || busy || outcome !== null) return;
    setBusy(true);
    setError(null);
    setGuidance(null);
    try {
      const res = kind === 'confirm' ? await api.confirmProposal(proposalId) : await api.cancelProposal(proposalId);
      setOutcome(res.result.status);
      onAppend?.(res.result.summary, [
        {
          type: 'action_result',
          title: kind === 'confirm' ? 'Résultat de la validation' : 'Proposition annulée',
          data: { ...res.result },
        },
      ]);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(e.message);
        // Guidage structuré (expiré, déjà validé, conflit, refusé) : terminal,
        // on ne réessaie pas — on propose l'action suivante.
        if (e.guidanceStatus !== undefined) {
          setGuidance(e.nextAction ?? null);
          setOutcome(e.guidanceStatus);
        }
      } else {
        setError('Erreur réseau.');
      }
    } finally {
      setBusy(false);
    }
  };

  const expiry = (() => {
    if (typeof data.expires_at !== 'string' || data.expires_at === '') return null;
    const d = new Date(data.expires_at);
    return Number.isNaN(d.getTime()) ? null : d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  })();

  const recapText =
    typeof data.recap === 'string' && data.recap !== ''
      ? data.recap
      : rows
          .slice(0, 4)
          .map((r) => {
            const row = asRecord(r);
            const label = fmtOpt(row.label);
            const value = fmtOpt(row.value);
            if (label !== undefined && value !== undefined) return `${label} : ${value}`;
            return value ?? label ?? '';
          })
          .filter((s) => s !== '')
          .join('. ');
  const retryPrompt =
    typeof guidance?.prompt === 'string' && guidance.prompt !== '' ? guidance.prompt : null;
  const retryLabel =
    typeof guidance?.label === 'string' && guidance.label !== '' ? guidance.label : 'Refaire la demande';
  const ask = onAsk;
  return (
    <CardShell
      title={title}
      meta="À valider"
      actions={
        outcome === 'confirmed' ? (
          <Badge tone="success">Confirmé</Badge>
        ) : outcome === 'cancelled' ? (
          <Badge tone="neutral">Annulé</Badge>
        ) : outcome === 'already_confirmed' ? (
          <Badge tone="success">Déjà enregistré</Badge>
        ) : outcome === 'expired' ? (
          <Badge tone="neutral">Expiré</Badge>
        ) : outcome === 'conflict' ? (
          <Badge tone="neutral">Déjà traité</Badge>
        ) : outcome === 'forbidden' ? (
          <Badge tone="danger">Refusé</Badge>
        ) : outcome !== null ? (
          <Badge tone="neutral">Terminé</Badge>
        ) : (
          <Badge tone="warn">Confirmation requise</Badge>
        )
      }
      listenText={speak('Confirme ton choix.', recapText !== '' ? recapText : undefined)}
    >
      <dl className="space-y-1.5">
        {rows.map((r, i) => {
          const row = asRecord(r);
          return (
            <div key={i} className="flex items-start justify-between gap-3 text-sm">
              <dt className="shrink-0 text-stone-500 dark:text-stone-400">{fmtText(row.label)}</dt>
              <dd className="min-w-0 break-words text-right font-medium">{fmtText(row.value)}</dd>
            </div>
          );
        })}
      </dl>
      {rows.length === 0 && typeof data.recap === 'string' && data.recap !== '' && (
        <p className="whitespace-pre-line text-sm leading-relaxed">{data.recap}</p>
      )}
      {expiry && outcome === null && (
        <p className="mt-2 font-mono text-[11px] text-stone-500 dark:text-stone-400">
          Expire à {expiry} — sans validation, rien ne sera créé.
        </p>
      )}
      {loginRequired && (
        <p className="mt-2 text-sm text-amber-700 dark:text-amber-400">
          Connectez-vous pour valider cette proposition.
        </p>
      )}
      {notPermitted && (
        <p className="mt-2 text-sm text-amber-700 dark:text-amber-400">
          {fmtText(data.permission_error) !== '—' ? fmtText(data.permission_error) : "Votre rôle ne permet pas cette action."}
        </p>
      )}
      {invalid && (
        <p className="mt-2 text-sm text-red-700 dark:text-red-400">
          Proposition incomplète — précisez les éléments manquants dans le chat.
        </p>
      )}
      {error && <p className="mt-2 text-sm text-red-700 dark:text-red-400">{error}</p>}
      {retryPrompt !== null && ask !== undefined && (
        <div className="mt-2">
          <Button variant="primary" size="sm" onClick={() => ask(retryPrompt)}>
            {retryLabel}
          </Button>
        </div>
      )}
      {!terminal && proposalId !== null && (
        <div className="mt-3 flex gap-2">
          <Button variant="primary" size="sm" disabled={busy} onClick={() => void run('confirm')}>
            {busy ? 'En cours…' : 'Confirmer'}
          </Button>
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => void run('cancel')}>
            Annuler
          </Button>
        </div>
      )}
    </CardShell>
  );
}

function ActionResultCard({ title, data }: { title: string; data: Record<string, unknown> }) {
  const status = typeof data.status === 'string' ? data.status : 'confirmed';
  const resultSummary = typeof data.summary === 'string' ? data.summary : undefined;
  return (
    <CardShell
      title={title}
      meta="Résultat"
      listenText={speak(title, resultSummary)}
      actions={
        status === 'confirmed' ? (
          <Badge tone="success">Exécuté</Badge>
        ) : status === 'cancelled' ? (
          <Badge tone="neutral">Annulé</Badge>
        ) : (
          <Badge tone="danger">Erreur</Badge>
        )
      }
    >
      <p className="text-sm leading-relaxed">{resultSummary ?? 'Terminé.'}</p>
      {typeof data.reference_code === 'string' && data.reference_code !== '' && (
        <p className="mt-1 font-mono text-xs text-stone-500 dark:text-stone-400">{data.reference_code}</p>
      )}
    </CardShell>
  );
}

function GenericCard({ card }: { card: AgentCard }) {
  const data = asRecord(card.data);
  const insight =
    fmtOpt(data.insight) ?? fmtOpt(data.summary) ?? fmtOpt(data.description) ?? fmtOpt(data.message);
  const text =
    insight !== undefined
      ? humanizeDates(insight)
      : "Le résultat est prêt. Appuie sur Écouter pour l'entendre, ou demande un résumé.";
  return (
    <CardShell title={card.title} listenText={speak(card.title, text)}>
      <p className="text-sm leading-relaxed">{text}</p>
    </CardShell>
  );
}

// ---------- Entrées ----------

function TerritoryMapCard({
  title,
  data,
  onAsk,
}: {
  title: string;
  data: Record<string, unknown>;
  onAsk?: (q: string) => void;
}) {
  const schools = asArray<unknown>(data.schools);
  const missing = asArray<unknown>(data.missing_gps)
    .map((m) => fmtOpt(m))
    .filter((m): m is string => m !== undefined);
  const points: TerritoryPoint[] = [];
  schools.forEach((s, i) => {
    const rec = asRecord(s);
    const lat = rec.lat;
    const lng = rec.lng;
    if (typeof lat !== 'number' || typeof lng !== 'number' || !Number.isFinite(lat) || !Number.isFinite(lng)) return;
    points.push({
      key: `s${i}`,
      name: typeof rec.school_name === 'string' ? rec.school_name : `École ${i + 1}`,
      district: typeof rec.district === 'string' ? rec.district : '',
      lat,
      lng,
      openIncidents: typeof rec.open_incidents === 'number' ? rec.open_incidents : 0,
      affectedStudents: typeof rec.affected_students === 'number' ? rec.affected_students : 0,
      topUrgency: typeof rec.top_urgency === 'string' ? rec.top_urgency : null,
    });
  });
  const district = fmtOpt(data.district);
  const territoryInsight = fmtOpt(data.insight) ?? '';
  return (
    <CardShell
      title={title}
      meta={points.length === 0 ? undefined : points.length === 1 ? '1 école' : `${points.length} écoles`}
      listenText={speak(
        'Carte du territoire.',
        territoryInsight !== '' ? territoryInsight : undefined,
        district !== undefined ? `District : ${district}.` : undefined,
        points.length === 0
          ? 'Aucune école sur la carte.'
          : points.length === 1
            ? '1 école sur la carte.'
            : `${points.length} écoles sur la carte.`,
      )}
    >
      <InsightLine text={territoryInsight} />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Écoles géolocalisées" value={fmtInt(data.total)} />
        <Stat label="Incidents ouverts" value={fmtInt(data.open_incidents)} />
      </div>
      <div className="mt-3">
        <TerritoryLegend />
      </div>
      <div className="mt-3">
        {points.length > 0 ? (
          <TerritoryMap points={points} />
        ) : (
          <p className="text-sm text-stone-600 dark:text-stone-400">
            Aucune école géolocalisée pour ce territoire.
          </p>
        )}
      </div>
      {missing.length > 0 && (
        <p className="mt-2 font-mono text-[11px] text-stone-500 dark:text-stone-400">
          Sans GPS : {missing.join(', ')}
        </p>
      )}
      <FollowUps
        onAsk={onAsk}
        items={[
          district !== undefined ? `Préparer un briefing ${district}` : 'Préparer un briefing',
          "Quelles écoles ont le plus besoin d'aide ?",
        ]}
      />
    </CardShell>
  );
}

function BriefingDeckCard({ title, data }: { title: string; data: Record<string, unknown> }) {
  const slides: DeckSlide[] = [];
  asArray<unknown>(data.slides).forEach((s) => {
    const rec = asRecord(s);
    const kind = rec.kind === 'cover' || rec.kind === 'stats' ? rec.kind : 'bullets';
    const lines = asArray<unknown>(rec.lines)
      .map((l) => fmtOpt(l))
      .filter((l): l is string => l !== undefined);
    const stats = asArray<unknown>(rec.stats)
      .map((st) => {
        const r = asRecord(st);
        return { label: fmtOpt(r.label) ?? '', value: fmtOpt(r.value) ?? '' };
      })
      .filter((st) => st.label !== '' || st.value !== '');
    slides.push({
      kind,
      title: fmtOpt(rec.title) ?? 'Sans titre',
      subtitle: fmtOpt(rec.subtitle),
      lines,
      stats,
      note: fmtOpt(rec.note),
    });
  });
  if (slides.length === 0) return null;
  return (
    <CardShell
      title={title}
      meta={slides.length <= 1 ? '1 page' : `${slides.length} pages`}
      listenText={speak(
        'Briefing prêt.',
        slides.length <= 1 ? '1 page.' : `${slides.length} pages.`,
        `Première page : ${slides[0].title}.`,
      )}
    >
      <SlideDeck slides={slides} />
    </CardShell>
  );
}

function MaintenanceLogsCard({
  title,
  data,
  onAsk,
}: {
  title: string;
  data: Record<string, unknown>;
  onAsk?: (q: string) => void;
}) {
  const items = asArray<Record<string, unknown>>(data.items);
  const total =
    typeof data.total === 'number' && Number.isFinite(data.total) ? Math.max(0, Math.round(data.total)) : items.length;
  const empty = data.is_empty === true || items.length === 0;
  const dayLabel = fmtDate(data.date);
  const displayTitle = dayLabel === '—' ? title : `Interventions du ${dayLabel}`;
  const insight = humanizeDates(fmtOpt(data.insight) ?? '');
  const filters = asRecord(data.applied_filters);
  const unknownSchool =
    filters.school_matched === false &&
    typeof filters.school_raw === 'string' &&
    filters.school_raw.trim() !== ''
      ? filters.school_raw.trim()
      : undefined;
  const schoolWarning =
    unknownSchool !== undefined ? `École « ${unknownSchool} » non reconnue — filtre ignoré.` : undefined;

  if (empty) {
    const phrase = 'Aucune intervention ce jour-là.';
    return (
      <CardShell
        title={displayTitle}
        listenText={speak(
          phrase,
          dayLabel === '—' ? undefined : `Jour demandé : ${dayLabel}.`,
          schoolWarning,
          'Essaie hier ou cette semaine.',
        )}
      >
        <div className="flex flex-col items-center py-4 text-center">
          <span
            aria-hidden="true"
            className="flex h-14 w-14 items-center justify-center rounded-full bg-teal-700/10 text-teal-800 dark:bg-teal-300/15 dark:text-teal-200"
          >
            <Icon name="inbox" className="h-7 w-7" />
          </span>
          <p className="mt-3 text-[15px] font-semibold leading-relaxed">{phrase}</p>
          {dayLabel !== '—' && (
            <p className="mt-1 text-sm text-stone-500 dark:text-stone-400">{dayLabel}</p>
          )}
          {schoolWarning !== undefined && (
            <p className="mt-2 text-sm text-amber-700 dark:text-amber-400">{schoolWarning}</p>
          )}
          {onAsk !== undefined && (
            <div className="mt-3 flex flex-wrap justify-center gap-2">
              <Button
                variant="primary"
                size="sm"
                onClick={() => onAsk('Interventions réalisées hier ?')}
              >
                Voir hier ?
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => onAsk('Interventions réalisées cette semaine ?')}
              >
                Voir la semaine ?
              </Button>
            </div>
          )}
        </div>
      </CardShell>
    );
  }

  const rest = Math.max(0, total - items.length);
  return (
    <CardShell
      title={displayTitle}
      listenText={speak(
        total <= 1 ? '1 intervention ce jour-là.' : `${total} interventions ce jour-là.`,
        insight !== '' ? insight : undefined,
        schoolWarning,
      )}
    >
      <HeroStat
        label={total <= 1 ? 'Intervention ce jour-là' : 'Interventions ce jour-là'}
        value={fmtInt(total)}
      />
      {insight !== '' && (
        <div className="mt-3">
          <InsightLine text={insight} />
        </div>
      )}
      {schoolWarning !== undefined && (
        <p className="mb-3 text-sm text-amber-700 dark:text-amber-400">{schoolWarning}</p>
      )}
      <ul className="divide-y divide-stone-200 dark:divide-stone-800">
        {items.map((it, i) => {
          const logSchool = fmtOpt(it.school_name) ?? 'École non précisée';
          const ref = fmtOpt(it.incident_ref);
          const logTitle = fmtOpt(it.incident_title);
          const cost = fmtCostXAF(it.cost_amount);
          const notes = fmtOpt(it.notes);
          const when = fmtDate(it.created_at);
          return (
            <li key={String(it.id ?? it.incident_id ?? i)} className="flex gap-3 py-3 first:pt-0 last:pb-0">
              <span
                aria-hidden="true"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-teal-700/10 text-teal-800 dark:bg-teal-300/15 dark:text-teal-200"
              >
                <Icon name="school" className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold leading-snug">{logSchool}</p>
                {logTitle !== undefined && (
                  <p className="mt-0.5 text-sm leading-snug text-stone-600 dark:text-stone-400">{logTitle}</p>
                )}
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  {ref !== undefined && <Badge>{ref}</Badge>}
                  {cost !== undefined && <Badge tone="info">{cost}</Badge>}
                  {when !== '—' && (
                    <span className="font-mono text-[11px] text-stone-500 dark:text-stone-400">{when}</span>
                  )}
                </div>
                {notes !== undefined && (
                  <p className="mt-1.5 text-sm leading-relaxed">{notes}</p>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {rest > 0 && (
        <p className="mt-2 font-mono text-[11px] text-stone-500 dark:text-stone-400">
          {rest === 1 ? '+ 1 autre intervention' : `+ ${rest} autres interventions`}
        </p>
      )}
      <FollowUps onAsk={onAsk} items={['Interventions réalisées hier ?', 'Interventions réalisées cette semaine ?']} />
    </CardShell>
  );
}

// ---------- Nouveaux rendus : calendrier, suivi, budgets ----------

/** Nombre sûr (0 si absent) pour les cumuls de rendus. */
const vizNum = (v: unknown): number =>
  typeof v === 'number' && Number.isFinite(v) ? v : 0;

function HeatmapCard({
  title,
  data,
  onAsk,
}: {
  title: string;
  data: Record<string, unknown>;
  onAsk?: (q: string) => void;
}) {
  const days: HeatmapDay[] = [];
  for (const d of asArray<unknown>(data.days)) {
    const rec = asRecord(d);
    if (typeof rec.date !== 'string' || rec.date === '') continue;
    const schools = asArray<unknown>(rec.ecoles_touchees ?? rec.schools).filter(
      (s): s is string => typeof s === 'string' && s !== '',
    );
    days.push({ date: rec.date, count: Math.max(0, Math.round(vizNum(rec.pannes ?? rec.incidents))), schools });
  }
  if (days.length === 0) return null;
  const total =
    typeof data.total_pannes === 'number' || typeof data.total_incidents === 'number'
      ? vizNum(data.total_pannes ?? data.total_incidents)
      : days.reduce((s, d) => s + d.count, 0);
  const start = fmtOpt(data.start);
  const end = fmtOpt(data.end);
  const peak = days.reduce((a, b) => (b.count > a.count ? b : a), days[0]);
  return (
    <CardShell
      title={title}
      meta={start !== undefined && end !== undefined ? `Du ${fmtDate(start)} au ${fmtDate(end)}` : undefined}
      listenText={speak(
        'Calendrier des pannes.',
        total === 0
          ? 'Aucune panne sur la période.'
          : total === 1
            ? '1 panne sur la période.'
            : `${fmtInt(total)} pannes sur la période.`,
        total > 0 && peak.count > 0 ? `Jour le plus chargé : le ${fmtDate(peak.date)}, ${fmtInt(peak.count)} panne${peak.count > 1 ? 's' : ''}.` : undefined,
      )}
    >
      <CalendarHeatmap
        days={days}
        total={total}
        onSelect={onAsk === undefined ? undefined : (date) => onAsk(`Que s'est-il passé le ${fmtDate(date)} ?`)}
      />
      {onAsk !== undefined && (
        <p className="mt-2 text-xs text-stone-500 dark:text-stone-400">
          Touchez un jour pour poser une question dessus.
        </p>
      )}
      <FollowUps onAsk={onAsk} items={['Voir les tendances sur 6 mois', 'Voir la carte du territoire']} />
    </CardShell>
  );
}

function TimelineCard({ title, data }: { title: string; data: Record<string, unknown> }) {
  const steps: TimelineStep[] = [];
  for (const s of asArray<unknown>(data.timeline)) {
    const rec = asRecord(s);
    if (typeof rec.label !== 'string' || rec.label === '') continue;
    steps.push({
      label: rec.label,
      date: typeof rec.date === 'string' ? rec.date : null,
      done: rec.fait === true || rec.done === true,
    });
  }
  if (steps.length === 0) return null;
  const doneCount = steps.filter((s) => s.done).length;
  const current = steps.find((s) => !s.done)?.label;
  return (
    <CardShell
      title={title}
      meta={fmtOpt(data.reference_code)}
      listenText={speak(
        "Suivi de l'incident.",
        current !== undefined ? `Étape actuelle : ${current}.` : 'Toutes les étapes sont faites.',
        `${doneCount} étape${doneCount > 1 ? 's' : ''} sur ${steps.length} faite${doneCount > 1 ? 's' : ''}.`,
      )}
    >
      <IncidentTimeline steps={steps} />
    </CardShell>
  );
}

const BUDGET_CATEGORY_LABEL: Record<string, string> = {
  ...CATEGORY_LABEL,
  unknown: 'Autre',
};

function BudgetCard({
  title,
  data,
  onAsk,
}: {
  title: string;
  data: Record<string, unknown>;
  onAsk?: (q: string) => void;
}) {
  const schools: BudgetSchool[] = [];
  for (const e of asArray<unknown>(data.ecoles)) {
    const rec = asRecord(e);
    const name = fmtOpt(rec.nom) ?? fmtOpt(rec.school_name);
    if (name === undefined) continue;
    schools.push({
      name,
      cost: Math.max(0, vizNum(rec.cumul_reparations_XAF ?? rec.total_cost_XAF)),
      incidents: Math.max(0, Math.round(vizNum(rec.nb_pannes ?? rec.incidents))),
    });
  }
  const catCosts = asRecord(data.par_categorie_XAF ?? data.by_category_XAF);
  const shares = asRecord(data.parts_pct ?? data.shares_pct);
  const categories: BudgetCategory[] = [];
  for (const [code, v] of Object.entries(catCosts)) {
    if (typeof v !== 'number' || !Number.isFinite(v)) continue;
    categories.push({
      code,
      label: BUDGET_CATEGORY_LABEL[code] ?? code,
      cost: Math.max(0, v),
      share: Math.max(0, vizNum(shares[code])),
    });
  }
  categories.sort((a, b) => b.cost - a.cost);
  const total =
    typeof data.total_XAF === 'number' || typeof data.total_cost_XAF === 'number'
      ? Math.max(0, vizNum(data.total_XAF ?? data.total_cost_XAF))
      : categories.reduce((s, c) => s + c.cost, 0);
  const currency = fmtOpt(data.currency) ?? 'XAF';
  if (schools.length === 0 && categories.length === 0) return null;
  const top = [...schools].sort((a, b) => b.cost - a.cost)[0];
  const spokenMoney = currency === 'XAF' ? 'francs' : currency;
  return (
    <CardShell
      title={title}
      meta={fmtOpt(data.district)}
      listenText={speak(
        'Comparaison des budgets réparations.',
        `Total : ${fmtInt(total)} ${spokenMoney}.`,
        top !== undefined ? `L'école la plus chère : ${top.name}, ${fmtInt(top.cost)} ${spokenMoney}.` : undefined,
      )}
    >
      <BudgetCompare
        schools={schools}
        categories={categories}
        total={total}
        currency={currency}
        onSelectSchool={
          onAsk === undefined
            ? undefined
            : (i) => {
                const s = schools[i];
                if (s !== undefined) onAsk(`Analyser ${s.name} ?`);
              }
        }
      />
      <FollowUps
        onAsk={onAsk}
        items={top !== undefined ? [`Analyser ${top.name} ?`, 'Voir les tendances sur 6 mois'] : ['Voir les tendances sur 6 mois']}
      />
    </CardShell>
  );
}

function CapabilitiesCard({ title, data, onAsk }: { title: string; data: Record<string, unknown>; onAsk?: (q: string) => void }) {
  const items = asArray<Record<string, unknown>>(data.items);
  if (items.length === 0) return null;
  const insight = fmtOpt(data.insight) ?? '';
  return (
    <CardShell title={title} listenText={speak(insight, 'Voici des exemples de questions à me poser.')}>
      <InsightLine text={insight} />
      <ol className="space-y-2">
        {items.map((it, i) => {
          const capability = fmtOpt(it.capability) ?? `Capacité ${i + 1}`;
          const exemple = fmtOpt(it.exemple);
          return (
            <li key={`${capability}-${i}`} className="flex items-start gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-teal-700/10 font-mono text-[11px] font-bold text-teal-800 dark:bg-teal-300/15 dark:text-teal-200">
                {i + 1}
              </span>
              <div className="min-w-0">
                <p className="text-sm font-semibold leading-snug">{capability}</p>
                {exemple !== undefined && onAsk !== undefined ? (
                  <button
                    type="button"
                    onClick={() => onAsk(exemple)}
                    className="mt-0.5 block max-w-full truncate text-left text-[13px] text-teal-800 underline decoration-teal-700/30 underline-offset-2 hover:decoration-teal-700 dark:text-teal-300"
                  >
                    « {exemple} »
                  </button>
                ) : (
                  exemple !== undefined && <p className="mt-0.5 text-[13px] text-stone-500 dark:text-stone-400">« {exemple} »</p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </CardShell>
  );
}

function DistrictAlertsCard({ title, data, onAsk }: { title: string; data: Record<string, unknown>; onAsk?: (q: string) => void }) {
  const alerts = asArray<Record<string, unknown>>(data.alerts);
  const insight = fmtOpt(data.insight) ?? '';
  if (alerts.length === 0) {
    return (
      <CardShell title={title} listenText={speak(insight === '' ? 'Aucune alerte sur ce district. Tout est calme.' : insight)}>
        <InsightLine text={insight} />
        <p className="text-sm text-stone-500 dark:text-stone-400">Aucune alerte — tout est calme sur ce district.</p>
        <FollowUps onAsk={onAsk} items={['Voir un autre district ?', 'Quelles écoles ont le plus besoin d’aide ?']} />
      </CardShell>
    );
  }
  return (
    <CardShell
      title={title}
      meta={`${alerts.length} alerte${alerts.length > 1 ? 's' : ''}`}
      listenText={speak(insight, `${alerts.length} alertes à traiter.`)}
    >
      <InsightLine text={insight} />
      <ul className="space-y-2">
        {alerts.map((a, i) => (
          <li key={i} className="flex items-start gap-2.5 border-b border-stone-200/60 pb-2 last:border-0 last:pb-0 dark:border-white/[0.06]">
            <UrgencyDot level={fmtOpt(a.urgency) ?? fmtOpt(a.severity) ?? fmtOpt(a.level) ?? 'medium'} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold leading-snug">
                {fmtOpt(a.title) ?? fmtOpt(a.label) ?? fmtOpt(a.message) ?? `Alerte ${i + 1}`}
              </p>
              {(fmtOpt(a.school_name) ?? fmtOpt(a.school) ?? fmtOpt(a.district) ?? fmtOpt(a.reference_code)) !== undefined && (
                <p className="mt-0.5 font-mono text-[11px] text-stone-500 dark:text-stone-400">
                  {[fmtOpt(a.school_name) ?? fmtOpt(a.school) ?? fmtOpt(a.district), fmtOpt(a.reference_code)].filter((s) => s !== undefined).join(' · ')}
                </p>
              )}
              {(fmtOpt(a.action) ?? fmtOpt(a.detail) ?? fmtOpt(a.description) ?? fmtOpt(a.text)) !== undefined && (
                <p className="mt-0.5 text-[13px] leading-relaxed text-stone-600 dark:text-stone-400">
                  {fmtOpt(a.action) ?? fmtOpt(a.detail) ?? fmtOpt(a.description) ?? fmtOpt(a.text)}
                </p>
              )}
            </div>
          </li>
        ))}
      </ul>
      <FollowUps onAsk={onAsk} items={['Qui envoyer sur place ?', 'Voir les détails du premier incident']} />
    </CardShell>
  );
}

function EpidemicAlertsCard({ title, data, onAsk }: { title: string; data: Record<string, unknown>; onAsk?: (q: string) => void }) {
  const clusters = asArray<Record<string, unknown>>(data.clusters);
  const insight = fmtOpt(data.insight) ?? '';
  if (clusters.length === 0) {
    return (
      <CardShell title={title} listenText={speak(insight === '' ? 'Aucun foyer sanitaire détecté. La veille continue.' : insight)}>
        <InsightLine text={insight} />
        <p className="text-sm text-stone-500 dark:text-stone-400">Aucun foyer détecté — la veille sanitaire continue.</p>
        <FollowUps onAsk={onAsk} items={['Voir les alertes du district ?', 'Voir les incidents ouverts']} />
      </CardShell>
    );
  }
  return (
    <CardShell
      title={title}
      meta={`${clusters.length} foyer${clusters.length > 1 ? 's' : ''}`}
      listenText={speak(insight, 'Attention, des foyers sanitaires sont suspectés.')}
    >
      <InsightLine text={insight} />
      <ul className="space-y-3">
        {clusters.map((c, i) => {
          const schools = asArray<unknown>(c.schools).map((s) => (typeof s === 'string' ? s : fmtOpt((s as Record<string, unknown>).name) ?? '')).filter((s) => s !== '');
          const signals = asArray<unknown>(c.signals ?? c.keywords).map((s) => (typeof s === 'string' ? s : '')).filter((s) => s !== '');
          return (
            <li key={i} className="rounded-lg bg-red-50/60 p-3 dark:bg-red-950/20">
              <div className="flex items-center gap-2">
                <UrgencyDot level="critical" />
                <p className="text-sm font-bold">{fmtOpt(c.district) ?? fmtOpt(c.title) ?? `Foyer ${i + 1}`}</p>
                {fmtOpt(c.risk_level) !== undefined && (
                  <span className="ml-auto rounded-full bg-red-700 px-2 py-0.5 text-[11px] font-bold text-white dark:bg-red-400 dark:text-red-950">
                    risque {fmtOpt(c.risk_level)}
                  </span>
                )}
              </div>
              {(typeof c.school_count === 'number' || typeof c.incident_count === 'number') && (
                <p className="mt-1 font-mono text-[11px] text-stone-500 dark:text-stone-400">
                  {[typeof c.school_count === 'number' ? `${c.school_count} école${c.school_count > 1 ? 's' : ''}` : undefined, typeof c.incident_count === 'number' ? `${c.incident_count} incident${c.incident_count > 1 ? 's' : ''}` : undefined].filter((s) => s !== undefined).join(' · ')}
                </p>
              )}
              {schools.length > 0 && <p className="mt-1 text-[13px] text-stone-600 dark:text-stone-400">{schools.join(' · ')}</p>}
              {signals.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {signals.map((s) => (
                    <span key={s} className="rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-semibold text-red-800 dark:bg-red-900/50 dark:text-red-200">{s}</span>
                  ))}
                </div>
              )}
              {(fmtOpt(c.recommendation) ?? fmtOpt(c.advice)) !== undefined && (
                <p className="mt-1.5 text-[13px] font-medium leading-relaxed">› {fmtOpt(c.recommendation) ?? fmtOpt(c.advice)}</p>
              )}
            </li>
          );
        })}
      </ul>
      <FollowUps onAsk={onAsk} items={['Qui envoyer sur place ?', 'Voir les incidents ouverts']} />
    </CardShell>
  );
}

function tourFallback(t: Record<string, unknown>): string {
  const parts = [
    typeof t.open_incidents === 'number' ? `${t.open_incidents} incident${t.open_incidents > 1 ? 's' : ''}` : undefined,
    typeof t.affected_students === 'number' ? `${fmtInt(t.affected_students)} élèves` : undefined,
    fmtOpt(t.max_urgency) !== undefined ? `urgence ${fmtOpt(t.max_urgency)}` : undefined,
  ].filter((s): s is string => s !== undefined);
  if (parts.length > 0) return parts.join(' · ');
  return fmtOpt(t.district) ?? '';
}

function MaintenanceTeamCard({ title, data, onAsk }: { title: string; data: Record<string, unknown>; onAsk?: (q: string) => void }) {
  const workload = asArray<Record<string, unknown>>(data.workload);
  const tour = asArray<Record<string, unknown>>(data.suggested_tour ?? data.tour);
  const insight = fmtOpt(data.insight) ?? '';
  if (workload.length === 0 && tour.length === 0) return null;
  return (
    <CardShell title={title} listenText={speak(insight)}>
      <InsightLine text={insight} />
      {workload.length > 0 && (
        <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {workload.map((w, i) => (
            <div key={i} className="rounded-lg bg-stone-100/70 p-2.5 dark:bg-white/[0.04]">
              <p className="truncate text-[11px] font-semibold text-stone-500 dark:text-stone-400">{fmtOpt(w.district) ?? fmtOpt(w.label) ?? `Zone ${i + 1}`}</p>
              <p className="mt-0.5 font-display text-xl font-extrabold tabular-nums">
                {typeof w.open_incidents === 'number' ? w.open_incidents : typeof w.open === 'number' ? w.open : typeof w.incidents === 'number' ? w.incidents : '—'}
              </p>
              <p className="text-[11px] text-stone-500 dark:text-stone-400">incident(s) ouvert(s)</p>
            </div>
          ))}
        </div>
      )}
      {tour.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-bold uppercase tracking-wide text-stone-500 dark:text-stone-400">Tournée suggérée</p>
          <ol className="space-y-1.5">
            {tour.map((t, i) => (
              <li key={i} className="flex items-start gap-2.5">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-teal-700 font-mono text-[10px] font-bold text-white dark:bg-teal-400 dark:text-teal-950">
                  {typeof t.order === 'number' ? t.order : typeof t.step === 'number' ? t.step : i + 1}
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-semibold leading-snug">{fmtOpt(t.school_name) ?? fmtOpt(t.school) ?? fmtOpt(t.name) ?? `Étape ${i + 1}`}</p>
                  <p className="text-[13px] text-stone-500 dark:text-stone-400">
                    {fmtOpt(t.reason) ?? fmtOpt(t.why) ?? tourFallback(t)}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
      <FollowUps onAsk={onAsk} items={['Voir les missions passées ?', 'Quelles écoles ont le plus besoin d’aide ?']} />
    </CardShell>
  );
}

function CompareSchoolsCard({ title, data, onAsk }: { title: string; data: Record<string, unknown>; onAsk?: (q: string) => void }) {
  const columns = asArray<Record<string, unknown>>(data.columns);
  const verdict = fmtOpt(data.verdict) ?? '';
  const unresolved = asArray<unknown>(data.unresolved).map((s) => (typeof s === 'string' ? s : '')).filter((s) => s !== '');
  const insight = fmtOpt(data.insight) ?? '';
  if (columns.length === 0) return null;
  const cell = (c: Record<string, unknown>, keys: string[]): string => {
    for (const k of keys) {
      const v = c[k];
      if (typeof v === 'number' && Number.isFinite(v)) return fmtInt(v);
    }
    return '—';
  };
  return (
    <CardShell title={title} listenText={speak(insight, verdict)}>
      <InsightLine text={insight} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-stone-200 dark:border-white/10">
              <th className="py-1.5 pr-2 text-left text-[11px] font-semibold text-stone-500 dark:text-stone-400">École</th>
              <th className="px-2 py-1.5 text-right font-mono text-[11px] text-stone-500 dark:text-stone-400">Ouverts</th>
              <th className="px-2 py-1.5 text-right font-mono text-[11px] text-stone-500 dark:text-stone-400">Élèves</th>
              <th className="px-2 py-1.5 text-right font-mono text-[11px] text-stone-500 dark:text-stone-400">Interv.</th>
              <th className="px-2 py-1.5 text-right font-mono text-[11px] text-stone-500 dark:text-stone-400">Coût XAF</th>
            </tr>
          </thead>
          <tbody>
            {columns.map((c, i) => (
              <tr key={i} className="border-b border-stone-100 last:border-0 dark:border-white/[0.05]">
                <td className="py-1.5 pr-2 font-semibold leading-snug">{fmtOpt(c.school_name) ?? fmtOpt(c.school) ?? fmtOpt(c.name) ?? `École ${i + 1}`}</td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums">{cell(c, ['open', 'incidents', 'open_incidents'])}</td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums">{cell(c, ['affected', 'students', 'affected_students'])}</td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums">{cell(c, ['logs', 'interventions', 'logs_count'])}</td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums">{cell(c, ['total_cost_XAF', 'cost', 'cost_amount', 'total_cost'])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {verdict !== '' && (
        <p className="mt-3 rounded-lg bg-teal-700/[0.07] p-2.5 text-sm font-medium leading-relaxed dark:bg-teal-300/10">› {verdict}</p>
      )}
      {unresolved.length > 0 && (
        <p className="mt-2 text-[13px] text-amber-700 dark:text-amber-400">Non reconnue(s) : {unresolved.join(', ')}.</p>
      )}
      <FollowUps onAsk={onAsk} items={verdict !== '' ? ['Pourquoi ce verdict ?', 'Voir les tendances sur 6 mois'] : ['Voir les tendances sur 6 mois']} />
    </CardShell>
  );
}

const FIGURE_LABELS: Record<string, string> = {
  incident_count: 'Incidents analysés',
  open_incidents: 'Incidents ouverts',
  total_repair_cost: 'Coût réparations (XAF)',
  total_days_without_service: 'Jours sans service',
  estimated_replacement_cost: 'Coût remplacement (XAF)',
  repair_ratio_percent: 'Ratio réparations (%)',
  schools: 'Écoles',
};

function CopilotAnswerCard({ title, data, onAsk }: { title: string; data: Record<string, unknown>; onAsk?: (q: string) => void }) {
  const recommendation = fmtOpt(data.recommendation_label) ?? fmtOpt(data.recommendation) ?? '';
  const insight = fmtOpt(data.insight) ?? '';
  const rawFigures = data.figures ?? data.chiffres;
  const figures: Array<{ label: string; value: string }> = Array.isArray(rawFigures)
    ? asArray<Record<string, unknown>>(rawFigures).map((f, i) => ({
        label: fmtOpt(f.label) ?? `Chiffre ${i + 1}`,
        value: typeof f.value === 'number' ? fmtInt(f.value) : fmtOpt(f.value) ?? '—',
      }))
    : Object.entries(asRecord(rawFigures)).map(([k, v]) => ({
        label: FIGURE_LABELS[k] ?? k.replace(/_/g, ' '),
        value: typeof v === 'number' ? fmtInt(v) : fmtOpt(v) ?? '—',
      }));
  if (insight === '' && recommendation === '') return null;
  return (
    <CardShell title={title} listenText={speak(insight, recommendation)}>
      <InsightLine text={insight} />
      {figures.length > 0 && (
        <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {figures.map((f, i) => (
            <Stat key={`${f.label}-${i}`} label={f.label} value={f.value} />
          ))}
        </div>
      )}
      {recommendation !== '' && (
        <p className="rounded-lg bg-teal-700/[0.07] p-2.5 text-sm font-medium leading-relaxed dark:bg-teal-300/10">› {recommendation}</p>
      )}
      <FollowUps onAsk={onAsk} items={['Explique-moi pourquoi ?', 'Que faire en premier ?']} />
    </CardShell>
  );
}

function MissionTimelineCard({ title, data, onAsk }: { title: string; data: Record<string, unknown>; onAsk?: (q: string) => void }) {
  const items = asArray<Record<string, unknown>>(data.items);
  const totals = asRecord(data.totals);
  const insight = fmtOpt(data.insight) ?? '';
  if (items.length === 0) {
    return (
      <CardShell title={title} listenText={speak(insight === '' ? 'Aucune mission sur cette période.' : insight)}>
        <InsightLine text={insight} />
        <p className="text-sm text-stone-500 dark:text-stone-400">Aucune mission sur cette période.</p>
        <FollowUps onAsk={onAsk} items={['Voir une période plus longue ?', 'Qui envoyer sur place ?']} />
      </CardShell>
    );
  }
  const totalLabel = ((): string | undefined => {
    const parts: string[] = [];
    const missions = totals.missions ?? totals.count;
    const schools = totals.schools ?? totals.schools_visited;
    const cost = totals.cost ?? totals.cost_total;
    if (typeof missions === 'number') parts.push(`${fmtInt(missions)} mission${missions > 1 ? 's' : ''}`);
    if (typeof schools === 'number') parts.push(`${fmtInt(schools)} école${schools > 1 ? 's' : ''}`);
    if (typeof cost === 'number') parts.push(`${fmtInt(cost)} XAF`);
    return parts.length > 0 ? parts.join(' · ') : undefined;
  })();
  return (
    <CardShell title={title} meta={totalLabel} listenText={speak(insight, totalLabel)}>
      <InsightLine text={insight} />
      <ol className="relative space-y-3 border-l-2 border-teal-700/20 pl-4 dark:border-teal-300/20">
        {items.map((it, i) => (
          <li key={i} className="relative">
            <span aria-hidden="true" className="absolute -left-[23px] top-1 h-2.5 w-2.5 rounded-full bg-teal-700 dark:bg-teal-300" />
            <p className="font-mono text-[11px] text-stone-500 dark:text-stone-400">{fmtDate(fmtOpt(it.date) ?? fmtOpt(it.day))}</p>
            <p className="text-sm font-semibold leading-snug">{fmtOpt(it.school) ?? fmtOpt(it.name) ?? `Mission ${i + 1}`}</p>
            {(fmtOpt(it.action) ?? fmtOpt(it.label) ?? fmtOpt(it.notes)) !== undefined && (
              <p className="text-[13px] leading-relaxed text-stone-600 dark:text-stone-400">{fmtOpt(it.action) ?? fmtOpt(it.label) ?? fmtOpt(it.notes)}</p>
            )}
            {(typeof it.cost === 'number' || typeof it.cost_amount === 'number') && (
              <p className="mt-0.5 font-mono text-[11px] text-stone-500 dark:text-stone-400">
                {fmtInt((typeof it.cost === 'number' ? it.cost : it.cost_amount) as number)} XAF
              </p>
            )}
          </li>
        ))}
      </ol>
      <FollowUps onAsk={onAsk} items={['Voir une période plus longue ?', 'Comparer les budgets ?']} />
    </CardShell>
  );
}

function DocumentBriefingCard({ title, data }: { title: string; data: Record<string, unknown> }) {
  const sections = asArray<Record<string, unknown>>(data.sections);
  const rawSlides = asArray<Record<string, unknown>>(data.slides);
  const insight = fmtOpt(data.insight) ?? '';
  const slides: DeckSlide[] = rawSlides.length > 0
    ? rawSlides.map((s, i) => ({
        kind: s.kind === 'cover' || s.kind === 'stats' || s.kind === 'bullets' ? s.kind : ('bullets' as const),
        title: fmtOpt(s.title) ?? `Point ${i + 1}`,
        subtitle: fmtOpt(s.subtitle),
        lines: asArray<unknown>(s.bullets ?? s.lines).map((b) => (typeof b === 'string' ? b : '')).filter((b) => b !== ''),
        stats: asArray<Record<string, unknown>>(s.stats)
          .map((st) => ({ label: fmtOpt(st.label) ?? '', value: fmtOpt(st.value) ?? (typeof st.value === 'number' ? fmtInt(st.value) : '') }))
          .filter((st) => st.label !== ''),
        note: fmtOpt(s.note),
      }))
    : sections.map((s, i) => ({
        kind: 'bullets' as const,
        title: fmtOpt(s.heading) ?? fmtOpt(s.title) ?? `Section ${i + 1}`,
        lines: (() => {
          const bullets = asArray<unknown>(s.bullets).map((b) => (typeof b === 'string' ? b : '')).filter((b) => b !== '');
          const body = fmtOpt(s.body) ?? fmtOpt(s.text);
          return bullets.length > 0 ? bullets : body !== undefined ? [body] : [];
        })(),
        stats: [],
      }));
  if (slides.length === 0 && sections.length === 0) return null;
  return (
    <CardShell title={title} listenText={speak(insight)}>
      <InsightLine text={insight} />
      {slides.length > 0 ? (
        <SlideDeck slides={slides} />
      ) : (
        <div className="space-y-3">
          {sections.map((s, i) => (
            <div key={i}>
              <p className="text-sm font-bold">{fmtOpt(s.heading) ?? fmtOpt(s.title) ?? `Section ${i + 1}`}</p>
              {(fmtOpt(s.body) ?? fmtOpt(s.text)) !== undefined && (
                <p className="mt-0.5 text-sm leading-relaxed text-stone-600 dark:text-stone-400">{fmtOpt(s.body) ?? fmtOpt(s.text)}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </CardShell>
  );
}

const CHANTIER_LABELS: Record<string, string> = {
  incident: 'Incident',
  progress_percent: 'Avancement',
  step: 'Étape',
  cost_amount: 'Coût (XAF)',
  notes: 'Notes',
};

function ChantierDossierCard({ title, data, onAsk }: { title: string; data: Record<string, unknown>; onAsk?: (q: string) => void }) {
  const fields = asRecord(data.fields);
  const missingLabels = asArray<unknown>(data.missing_labels).map((s) => (typeof s === 'string' ? s : '')).filter((s) => s !== '');
  const questions = asArray<unknown>(data.questions).map((s) => (typeof s === 'string' ? s : '')).filter((s) => s !== '');
  const ready = data.ready === true || data.complete === true;
  const insight = fmtOpt(data.insight) ?? '';
  const recap = fmtOpt(data.recap);
  const entries = Object.entries(CHANTIER_LABELS)
    .map(([k, label]) => ({ label, value: fields[k] }))
    .filter((e) => e.value !== undefined && e.value !== null && e.value !== '');
  if (entries.length === 0 && questions.length === 0) return null;
  const progress = typeof fields.progress_percent === 'number' ? Math.max(0, Math.min(100, fields.progress_percent)) : undefined;
  return (
    <CardShell
      title={title}
      meta={ready ? 'Dossier prêt' : 'En cours'}
      listenText={speak(insight, recap, ready ? 'Le dossier est prêt à valider.' : undefined)}
    >
      <InsightLine text={insight} />
      {progress !== undefined && (
        <div className="mb-3">
          <div className="h-2 overflow-hidden rounded-full bg-stone-200 dark:bg-white/10">
            <div className="h-full rounded-full bg-teal-700 transition-[width] dark:bg-teal-400" style={{ width: `${progress}%` }} />
          </div>
          <p className="mt-1 font-mono text-[11px] text-stone-500 dark:text-stone-400">{progress} % d'avancement</p>
        </div>
      )}
      <dl className="space-y-1.5">
        {entries.filter((e) => e.label !== 'Avancement').map((e) => (
          <div key={e.label} className="flex items-baseline justify-between gap-3 text-sm">
            <dt className="shrink-0 text-[11px] font-semibold text-stone-500 dark:text-stone-400">{e.label}</dt>
            <dd className="text-right font-medium leading-snug">
              {typeof e.value === 'number' ? fmtInt(e.value) : String(e.value)}
            </dd>
          </div>
        ))}
      </dl>
      {missingLabels.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1">
          {missingLabels.map((m) => (
            <span key={m} className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800 dark:bg-amber-900/50 dark:text-amber-200">manque : {m}</span>
          ))}
        </div>
      )}
      {questions.length > 0 && onAsk !== undefined && (
        <div className="mt-3 space-y-1.5">
          {questions.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => onAsk(q)}
              className="block w-full rounded-lg border border-line bg-card px-3 py-2 text-left text-sm transition-[border-color] hover:border-accent"
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </CardShell>
  );
}

function SaisieAssisteeCard({ title, data, onAsk }: { title: string; data: Record<string, unknown>; onAsk?: (q: string) => void }) {
  const question = fmtOpt(data.question) ?? '';
  const options = asArray<unknown>(data.options).map((s) => (typeof s === 'string' ? s : '')).filter((s) => s !== '');
  const progress = typeof data.progress_percent === 'number' ? Math.max(0, Math.min(100, Math.round(data.progress_percent))) : 0;
  const recap = asRecord(data.recap);
  const recapEntries = Object.entries(recap).filter(([, v]) => v !== undefined && v !== null && v !== '');
  const insight = fmtOpt(data.insight) ?? '';
  if (question === '' && options.length === 0) return null;
  return (
    <CardShell title={title} meta={`${progress} %`} listenText={speak(question, options.length > 0 ? `Choix possibles : ${options.join(', ')}.` : undefined)}>
      <div className="mb-3 h-2 overflow-hidden rounded-full bg-stone-200 dark:bg-white/10">
        <div className="h-full rounded-full bg-teal-700 transition-[width] dark:bg-teal-400" style={{ width: `${progress}%` }} />
      </div>
      <InsightLine text={insight} />
      <p className="text-[15px] font-bold leading-snug">{question}</p>
      {options.length > 0 && (
        <div className="mt-2.5 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
          {options.map((opt) => (
            <button
              key={opt}
              type="button"
              disabled={onAsk === undefined}
              onClick={() => onAsk?.(opt)}
              className="rounded-lg border border-line bg-card px-3 py-2 text-left text-sm font-medium transition-[border-color,transform] duration-150 ease-snap hover:border-accent active:scale-[0.98] disabled:cursor-default disabled:hover:border-line motion-reduce:transition-none motion-reduce:active:scale-100"
            >
              {opt}
            </button>
          ))}
        </div>
      )}
      {recapEntries.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1 border-t border-stone-200/70 pt-2.5 dark:border-white/[0.06]">
          {recapEntries.map(([k, v]) => (
            <span key={k} className="rounded-full bg-stone-100 px-2 py-0.5 text-[11px] text-stone-600 dark:bg-white/[0.06] dark:text-stone-300">
              {k} : {String(v)}
            </span>
          ))}
        </div>
      )}
    </CardShell>
  );
}

function OfflineQueueCard({ title, data, onAsk }: { title: string; data: Record<string, unknown>; onAsk?: (q: string) => void }) {
  const pending = asArray<Record<string, unknown>>(data.pending);
  const count = typeof data.count === 'number' ? data.count : pending.length;
  const online = data.online === true;
  const lastSync = fmtOpt(data.last_sync);
  const insight = fmtOpt(data.insight) ?? '';
  return (
    <CardShell
      title={title}
      meta={online ? 'En ligne' : 'Hors ligne'}
      listenText={speak(insight, count === 0 ? 'Aucun signalement en attente.' : `${count} signalement${count > 1 ? 's' : ''} en attente de synchronisation.`)}
    >
      <InsightLine text={insight} />
      <div className="mb-3 flex items-center gap-2">
        <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold ${online ? 'bg-teal-700/10 text-teal-800 dark:bg-teal-300/15 dark:text-teal-200' : 'bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200'}`}>
          <span aria-hidden="true" className={`h-2 w-2 rounded-full ${online ? 'bg-teal-600 dark:bg-teal-300' : 'bg-amber-500'}`} />
          {online ? 'Connecté' : 'Hors ligne'}
        </span>
        <span className="font-mono text-[11px] text-stone-500 dark:text-stone-400">
          {count} en attente{lastSync !== undefined ? ` · synchro : ${lastSync}` : ''}
        </span>
      </div>
      {pending.length === 0 ? (
        <p className="text-sm text-stone-500 dark:text-stone-400">File vide — rien à synchroniser.</p>
      ) : (
        <ul className="space-y-2">
          {pending.map((p, i) => (
            <li key={i} className="flex items-start gap-2.5 border-b border-stone-200/60 pb-2 last:border-0 last:pb-0 dark:border-white/[0.06]">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold leading-snug">{fmtOpt(p.school) ?? fmtOpt(p.school_name) ?? `Signalement ${i + 1}`}</p>
                {(fmtOpt(p.summary) ?? fmtOpt(p.title)) !== undefined && (
                  <p className="mt-0.5 text-[13px] leading-relaxed text-stone-600 dark:text-stone-400">{fmtOpt(p.summary) ?? fmtOpt(p.title)}</p>
                )}
                <p className="mt-0.5 font-mono text-[11px] text-stone-500 dark:text-stone-400">
                  {[fmtOpt(p.created_at), fmtOpt(p.status)].filter((s) => s !== undefined).join(' · ')}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
      <FollowUps onAsk={onAsk} items={['Voir les incidents ouverts ?', 'Aide-moi à remplir un signalement']} />
    </CardShell>
  );
}

function RelancesCard({ title, data, onAsk }: { title: string; data: Record<string, unknown>; onAsk?: (q: string) => void }) {
  const items = asArray<Record<string, unknown>>(data.items);
  const insight = fmtOpt(data.insight) ?? '';
  if (items.length === 0) {
    return (
      <CardShell title={title} listenText={speak(insight === '' ? 'Aucun incident dormant. Tout est suivi.' : insight)}>
        <InsightLine text={insight} />
        <p className="text-sm text-stone-500 dark:text-stone-400">Aucun incident dormant — tout est suivi.</p>
        <FollowUps onAsk={onAsk} items={['Voir les incidents ouverts ?', 'Voir les alertes du district ?']} />
      </CardShell>
    );
  }
  return (
    <CardShell
      title={title}
      meta={`${items.length} à relancer`}
      listenText={speak(insight, `${items.length} incidents sans nouvelles à relancer.`)}
    >
      <InsightLine text={insight} />
      <ul className="space-y-3">
        {items.map((it, i) => (
          <li key={i} className="rounded-lg bg-stone-100/70 p-3 dark:bg-white/[0.04]">
            <div className="flex items-center gap-2">
              <p className="text-sm font-bold">{fmtOpt(it.school_name) ?? fmtOpt(it.school) ?? `École ${i + 1}`}</p>
              {typeof it.days_idle === 'number' && (
                <span className="ml-auto shrink-0 rounded-full bg-amber-100 px-2 py-0.5 font-mono text-[11px] font-bold text-amber-800 dark:bg-amber-900/50 dark:text-amber-200">
                  {it.days_idle} j sans nouvelles
                </span>
              )}
            </div>
            <p className="mt-0.5 text-[13px] text-stone-600 dark:text-stone-400">
              {[fmtOpt(it.incident_title) ?? fmtOpt(it.title), fmtOpt(it.reference_code)].filter((s) => s !== undefined).join(' · ')}
            </p>
            {fmtOpt(it.draft_message) !== undefined && (
              <p className="mt-1.5 border-l-2 border-teal-700/40 pl-2 text-[13px] italic leading-relaxed dark:border-teal-300/40">« {fmtOpt(it.draft_message)} »</p>
            )}
          </li>
        ))}
      </ul>
      <FollowUps onAsk={onAsk} items={['Qui envoyer sur place ?', 'Voir les missions passées ?']} />
    </CardShell>
  );
}

function ObservatoireCard({ title, data, onAsk }: { title: string; data: Record<string, unknown>; onAsk?: (q: string) => void }) {
  const totals = asRecord(data.totals);
  const byDistrict = asArray<Record<string, unknown>>(data.by_district);
  const byUrgency = asArray<Record<string, unknown>>(data.by_urgency);
  const trend = asArray<Record<string, unknown>>(data.trend);
  const insight = fmtOpt(data.insight) ?? '';
  const openCount = typeof totals.incidents_open === 'number' ? totals.incidents_open : undefined;
  if (openCount === undefined && byDistrict.length === 0) return null;
  const maxOpen = Math.max(1, ...byDistrict.map((d) => (typeof d.open === 'number' ? d.open : 0)));
  const trendCounts = trend.map((t) => (typeof t.count === 'number' ? t.count : 0));
  return (
    <CardShell title={title} listenText={speak(insight)}>
      <InsightLine text={insight} />
      <div className="mb-3 flex items-end justify-between gap-3">
        <HeroStat label="Incidents ouverts" value={openCount !== undefined ? fmtInt(openCount) : '—'} />
        {trendCounts.length >= 2 && <Sparkline data={trendCounts} />}
      </div>
      <div className="mb-3 grid grid-cols-3 gap-2">
        <Stat label="Écoles suivies" value={typeof totals.schools === 'number' ? fmtInt(totals.schools) : '—'} />
        <Stat label="Élèves affectés" value={typeof totals.affected_students === 'number' ? fmtInt(totals.affected_students) : '—'} />
        <Stat label="Critiques" value={typeof totals.critical === 'number' ? fmtInt(totals.critical) : '—'} />
      </div>
      {byDistrict.length > 0 && (
        <div className="mb-2 space-y-1.5">
          {byDistrict.map((d, i) => {
            const open = typeof d.open === 'number' ? d.open : 0;
            return (
              <div key={i}>
                <div className="flex items-baseline justify-between gap-2 text-[13px]">
                  <span className="truncate font-medium">{fmtOpt(d.district) ?? `Zone ${i + 1}`}</span>
                  <span className="shrink-0 font-mono tabular-nums">{open}</span>
                </div>
                <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-stone-200 dark:bg-white/10">
                  <div className="h-full rounded-full bg-teal-700 dark:bg-teal-400" style={{ width: `${Math.round((open / maxOpen) * 100)}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      )}
      {byUrgency.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {byUrgency.map((u, i) => (
            <span key={i} className="inline-flex items-center gap-1.5 rounded-full bg-stone-100 px-2 py-0.5 text-[11px] font-semibold dark:bg-white/[0.06]">
              <UrgencyDot level={fmtOpt(u.urgency) ?? 'medium'} />
              {fmtOpt(u.urgency) ?? '?'} · {typeof u.count === 'number' ? u.count : '—'}
            </span>
          ))}
        </div>
      )}
      <FollowUps onAsk={onAsk} items={['Quelles écoles ont le plus besoin d’aide ?', 'Voir les alertes du district ?']} />
    </CardShell>
  );
}

function GuidanceCard({ title, data, onAsk }: { title: string; data: Record<string, unknown>; onAsk?: (q: string) => void }) {
  const insight = fmtOpt(data.insight) ?? '';
  const explication = fmtOpt(data.explication);
  const causes = asArray<unknown>(data.causes_possibles).map((c) => (typeof c === 'string' ? c : '')).filter((c) => c !== '');
  const actions = asArray<Record<string, unknown>>(data.actions);
  return (
    <CardShell title={title} listenText={speak(insight, explication)}>
      <InsightLine text={insight} />
      {explication !== undefined && (
        <p className="text-sm leading-relaxed text-stone-600 dark:text-stone-400">{explication}</p>
      )}
      {causes.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-[13px] text-stone-500 marker:text-stone-400 dark:text-stone-400">
          {causes.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
      {actions.length > 0 && (
        <div className="mt-2.5 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
          {actions.map((a, i) => {
            const label = fmtOpt(a.label) ?? fmtOpt(a.question) ?? `Action ${i + 1}`;
            const question = fmtOpt(a.question);
            return (
              <button
                key={`${label}-${i}`}
                type="button"
                disabled={onAsk === undefined || question === undefined}
                onClick={() => question !== undefined && onAsk?.(question)}
                className="rounded-lg border border-line bg-card px-3 py-2 text-left text-sm font-medium transition-[border-color,transform] duration-150 ease-snap hover:border-accent active:scale-[0.98] disabled:cursor-default disabled:hover:border-line motion-reduce:transition-none motion-reduce:active:scale-100"
              >
                {label}
              </button>
            );
          })}
        </div>
      )}
    </CardShell>
  );
}

function PlaceSuggestionsCard({ title, data, onAsk }: { title: string; data: Record<string, unknown>; onAsk?: (q: string) => void }) {
  const suggestions = asArray<Record<string, unknown>>(data.suggestions);
  const ecoles = asArray<unknown>(data.ecoles_sample).map((s) => (typeof s === 'string' ? s : '')).filter((s) => s !== '');
  const districts = asArray<unknown>(data.districts_sample).map((s) => (typeof s === 'string' ? s : '')).filter((s) => s !== '');
  const insight = fmtOpt(data.insight) ?? '';
  if (suggestions.length === 0 && ecoles.length === 0 && districts.length === 0) return null;
  return (
    <CardShell title={title} listenText={speak(insight)}>
      <InsightLine text={insight} />
      {suggestions.length > 0 && (
        <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
          {suggestions.map((s, i) => {
            const label = fmtOpt(s.label) ?? `Lieu ${i + 1}`;
            const question = fmtOpt(s.question);
            return (
              <button
                key={`${label}-${i}`}
                type="button"
                disabled={onAsk === undefined || question === undefined}
                onClick={() => question !== undefined && onAsk?.(question)}
                className="rounded-lg border border-line bg-card px-3 py-2 text-left text-sm font-semibold transition-[border-color,transform] duration-150 ease-snap hover:border-accent active:scale-[0.98] disabled:cursor-default disabled:hover:border-line motion-reduce:transition-none motion-reduce:active:scale-100"
              >
                {label}
                {fmtOpt(s.kind) !== undefined && (
                  <span className="ml-1.5 font-mono text-[11px] font-normal text-stone-500 dark:text-stone-400">
                    {s.kind === 'district' ? 'district' : 'école'}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}
      {(ecoles.length > 0 || districts.length > 0) && (
        <p className="mt-2.5 text-[13px] leading-relaxed text-stone-500 dark:text-stone-400">
          {districts.length > 0 && <>Districts suivis : {districts.join(', ')}. </>}
          {ecoles.length > 0 && <>Écoles : {ecoles.join(' · ')}.</>}
        </p>
      )}
    </CardShell>
  );
}

function AgentCardViewInner({ card, onAsk, onAppend, onDetail }: { card: AgentCard; onAsk?: (q: string) => void; onAppend?: (content: string, cards?: AgentCard[]) => void; onDetail?: (kind: DetailKind, id: number) => void }) {
  const data = asRecord(card.data);
  switch (card.type) {
    case 'incident_detail':
      return <IncidentCard title={card.title} data={data} onAsk={onAsk} onDetail={onDetail} />;
    case 'school_ranking':
      return <RankingCard title={card.title} data={data} onAsk={onAsk} onDetail={onDetail} />;
    case 'school_analysis':
      return <AnalysisCard title={card.title} data={data} onAsk={onAsk} />;
    case 'district_summary':
      return <DistrictCard title={card.title} data={data} onAsk={onAsk} />;
    case 'trend_chart':
      return <TrendCard title={card.title} data={data} onAsk={onAsk} />;
    case 'report_confirmation':
      return <ConfirmationCard title={card.title} data={data} />;
    case 'action_confirmation':
      return <ActionConfirmationCard title={card.title} data={data} onAsk={onAsk} onAppend={onAppend} />;
    case 'action_result':
      return <ActionResultCard title={card.title} data={data} />;
    case 'incident_picker':
      return <IncidentPickerCard title={card.title} data={data} onAsk={onAsk} />;
    case 'territory_map':
      return <TerritoryMapCard title={card.title} data={data} onAsk={onAsk} />;
    case 'briefing_deck':
      return <BriefingDeckCard title={card.title} data={data} />;
    case 'maintenance_logs':
      return <MaintenanceLogsCard title={card.title} data={data} onAsk={onAsk} />;
    case 'calendar_heatmap':
      return <HeatmapCard title={card.title} data={data} onAsk={onAsk} />;
    case 'incident_timeline':
      return <TimelineCard title={card.title} data={data} />;
    case 'budget_compare':
      return <BudgetCard title={card.title} data={data} onAsk={onAsk} />;
    case 'capabilities_list':
      return <CapabilitiesCard title={card.title} data={data} onAsk={onAsk} />;
    case 'district_alerts':
      return <DistrictAlertsCard title={card.title} data={data} onAsk={onAsk} />;
    case 'epidemic_alerts':
      return <EpidemicAlertsCard title={card.title} data={data} onAsk={onAsk} />;
    case 'maintenance_team':
      return <MaintenanceTeamCard title={card.title} data={data} onAsk={onAsk} />;
    case 'compare_schools':
      return <CompareSchoolsCard title={card.title} data={data} onAsk={onAsk} />;
    case 'copilot_answer':
      return <CopilotAnswerCard title={card.title} data={data} onAsk={onAsk} />;
    case 'mission_timeline':
      return <MissionTimelineCard title={card.title} data={data} onAsk={onAsk} />;
    case 'document_briefing':
      return <DocumentBriefingCard title={card.title} data={data} />;
    case 'chantier_dossier':
      return <ChantierDossierCard title={card.title} data={data} onAsk={onAsk} />;
    case 'saisie_assistee':
      return <SaisieAssisteeCard title={card.title} data={data} onAsk={onAsk} />;
    case 'offline_queue':
      return <OfflineQueueCard title={card.title} data={data} onAsk={onAsk} />;
    case 'relances':
      return <RelancesCard title={card.title} data={data} onAsk={onAsk} />;
    case 'observatoire':
      return <ObservatoireCard title={card.title} data={data} onAsk={onAsk} />;
    case 'guidance':
      return <GuidanceCard title={card.title} data={data} onAsk={onAsk} />;
    case 'place_suggestions':
      return <PlaceSuggestionsCard title={card.title} data={data} onAsk={onAsk} />;
    default:
      return <GenericCard card={card} />;
  }
}

export const AgentCardView = memo(AgentCardViewInner);

export function AgentCardList({ cards, onAsk, onAppend, onDetail }: { cards: AgentCard[]; onAsk?: (q: string) => void; onAppend?: (content: string, cards?: AgentCard[]) => void; onDetail?: (kind: DetailKind, id: number) => void }) {
  if (cards.length === 0) return null;
  return (
    <div className="space-y-3 pt-1">
      {cards.map((c, i) => (
        <AgentCardView key={`${c.type}-${i}`} card={c} onAsk={onAsk} onAppend={onAppend} onDetail={onDetail} />
      ))}
    </div>
  );
}
