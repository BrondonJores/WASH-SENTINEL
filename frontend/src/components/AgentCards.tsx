import { memo, useState } from 'react';
import type { ReactNode } from 'react';
import { Badge, Button, Card } from './ui';
import { Icon } from './icons';
import type { AgentCard } from '../lib/api';
import { ThresholdGauge } from './ThresholdGauge';
import { TrendChart } from './TrendChart';
import type { TrendSeries } from './TrendChart';
import { TerritoryLegend, TerritoryMap } from './TerritoryMap';
import { SlideDeck } from './SlideDeck';
import type { DeckSlide } from './SlideDeck';
import type { TerritoryPoint } from './TerritoryMap';

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
  const d = new Date(v);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
};

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

function CardShell({
  title,
  meta,
  actions,
  children,
}: {
  title: string;
  meta?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card className="p-4 sm:p-5">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-x-3 gap-y-2 border-b border-stone-200/80 pb-3 dark:border-white/[0.07]">
        <h3 className="font-display text-[17px] font-bold leading-snug tracking-tight">{title}</h3>
        {(meta !== undefined || actions) && (
          <div className="flex flex-wrap items-center gap-2">
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

function FollowUps({ items, onAsk }: { items: string[]; onAsk?: (q: string) => void }) {
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

function IncidentCard({
  title,
  data,
  onAsk,
}: {
  title: string;
  data: Record<string, unknown>;
  onAsk?: (q: string) => void;
}) {
  const urgency = typeof data.urgency === 'string' ? data.urgency : 'medium';
  const priority = typeof data.priority_score === 'number' ? data.priority_score : null;
  const school = fmtOpt(data.school_name);
  return (
    <CardShell
      title={title}
      meta={fmtOpt(data.reference_code)}
      actions={<CopyButton value={fmtOpt(data.reference_code) ?? ''} label="Référence" />}
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
        <Stat label="Catégorie" value={fmtText(data.category)} mono={false} />
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
}: {
  title: string;
  data: Record<string, unknown>;
  onAsk?: (q: string) => void;
}) {
  const ranking = asArray<Record<string, unknown>>(data.ranking);
  const max = Math.max(0, ...ranking.map((r) => (typeof r.need_score === 'number' ? r.need_score : 0)));
  const top = fmtOpt(ranking[0]?.school_name);
  return (
    <CardShell title={title} meta={`${fmtInt(data.total)} écoles`}>
      <InsightLine text={fmtOpt(data.insight) ?? ''} />
      {ranking.length === 0 ? (
        <p className="text-sm text-stone-600 dark:text-stone-400">Aucune école à classer.</p>
      ) : (
        <div className="divide-y divide-stone-200 dark:divide-stone-800">
          {ranking.map((r, i) => {
            const urg = typeof r.top_urgency === 'string' ? r.top_urgency : 'low';
            const score = typeof r.need_score === 'number' ? r.need_score : 0;
            const n = typeof r.open_incidents === 'number' ? r.open_incidents : 0;
            return (
              <div
                key={String(r.school_id ?? i)}
                className={`flex items-center gap-3 py-2.5 first:pt-0 last:pb-0 ${
                  i === 0 ? '-mx-2 rounded-lg bg-teal-50/70 px-2 dark:bg-teal-950/30' : ''
                }`}
              >
                <span className="w-7 shrink-0 font-display text-sm font-bold tabular-nums text-stone-400 dark:text-stone-500">
                  {String(i + 1).padStart(2, '0')}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{fmtText(r.school_name)}</p>
                  <p className="font-mono text-[11px] text-stone-500 dark:text-stone-400">
                    {fmtText(r.district)} · {fmtInt(n)} incident{n === 1 ? '' : 's'} ·{' '}
                    {fmtInt(r.affected_students)} élèves · {fmtInt(r.oldest_days)} j
                  </p>
                  <div className="mt-1.5">
                    <NeedBar value={score} max={max} />
                  </div>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <span className="font-display text-lg font-extrabold tabular-nums">{fmtNum1(score)}</span>
                  <span className="inline-flex items-center gap-1.5 text-xs text-stone-600 dark:text-stone-400">
                    <UrgencyDot level={urg} />
                    {URGENCY_LABEL[urg] ?? urg}
                  </span>
                </div>
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
  return (
    <CardShell title={title} meta={fmtOpt(data.district)}>
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
  const urgEntries = Object.entries(byUrgency).filter(([, v]) => typeof v === 'number') as [string, number][];
  return (
    <CardShell title={title}>
      <div className="grid grid-cols-2 gap-3">
        <HeroStat label="Incidents ouverts" value={fmtInt(data.open_incidents)} />
        <HeroStat label="Élèves affectés" value={fmtInt(data.total_affected_students)} />
      </div>
      <div className="mt-3">
        <InsightLine text={fmtOpt(data.insight) ?? ''} />
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
  const school = fmtOpt(data.school_name);
  return (
    <CardShell title={title} meta={typeof data.months === 'number' ? `${fmtInt(data.months)} mois` : undefined}>
      <div className="flex items-end justify-between gap-3">
        <HeroStat label={`Coût total${currency}`} value={fmtInt(figures.total_cost)} delta={delta} invert />
        <Sparkline data={costs} />
      </div>
      <div className="mt-3">
        <InsightLine text={fmtOpt(data.insight) ?? ''} />
      </div>
      <div className="mt-3 grid grid-cols-3 gap-3">
        <Stat label="Pannes" value={fmtInt(figures.total_incidents)} />
        <Stat label="Jours sans service" value={fmtInt(figures.total_days_lost)} />
        <Stat label="Coût / mois" value={fmtInt(figures.avg_cost_per_month)} />
      </div>
      {labels.length > 0 && series.length > 0 ? (
        <div className="mt-3">
          <TrendChart labels={labels} series={series} />
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
  return (
    <CardShell
      title={title}
      meta="Brouillon"
      actions={data.needs_confirmation === true ? <Badge tone="warn">Confirmation requise</Badge> : undefined}
    >
      {typeof data.description === 'string' && data.description !== '' && (
        <p className="text-sm leading-relaxed">{data.description}</p>
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

function GenericCard({ card }: { card: AgentCard }) {
  const entries = Object.entries(card.data);
  return (
    <CardShell title={card.title} meta={card.type}>
      {entries.length === 0 ? (
        <p className="text-sm text-stone-600 dark:text-stone-400">Aucune donnée.</p>
      ) : (
        <dl className="space-y-1.5">
          {entries.map(([k, v]) => (
            <div key={k} className="flex items-start justify-between gap-3 text-sm">
              <dt className="shrink-0 font-mono text-xs text-stone-500 dark:text-stone-400">{k}</dt>
              <dd className="min-w-0 break-words text-right font-mono text-xs tabular-nums">
                {typeof v === 'object' ? JSON.stringify(v)?.slice(0, 200) : fmtText(v)}
              </dd>
            </div>
          ))}
        </dl>
      )}
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
  return (
    <CardShell title={title} meta={points.length > 0 ? `${points.length} écoles` : undefined}>
      <InsightLine text={fmtOpt(data.insight) ?? ''} />
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
    <CardShell title={title} meta={`${slides.length} slides`}>
      <SlideDeck slides={slides} />
    </CardShell>
  );
}

function AgentCardViewInner({ card, onAsk }: { card: AgentCard; onAsk?: (q: string) => void }) {
  const data = asRecord(card.data);
  switch (card.type) {
    case 'incident_detail':
      return <IncidentCard title={card.title} data={data} onAsk={onAsk} />;
    case 'school_ranking':
      return <RankingCard title={card.title} data={data} onAsk={onAsk} />;
    case 'school_analysis':
      return <AnalysisCard title={card.title} data={data} onAsk={onAsk} />;
    case 'district_summary':
      return <DistrictCard title={card.title} data={data} onAsk={onAsk} />;
    case 'trend_chart':
      return <TrendCard title={card.title} data={data} onAsk={onAsk} />;
    case 'report_confirmation':
      return <ConfirmationCard title={card.title} data={data} />;
    case 'territory_map':
      return <TerritoryMapCard title={card.title} data={data} onAsk={onAsk} />;
    case 'briefing_deck':
      return <BriefingDeckCard title={card.title} data={data} />;
    default:
      return <GenericCard card={card} />;
  }
}

export const AgentCardView = memo(AgentCardViewInner);

export function AgentCardList({ cards, onAsk }: { cards: AgentCard[]; onAsk?: (q: string) => void }) {
  if (cards.length === 0) return null;
  return (
    <div className="space-y-3 pt-1">
      {cards.map((c, i) => (
        <AgentCardView key={`${c.type}-${i}`} card={c} onAsk={onAsk} />
      ))}
    </div>
  );
}
