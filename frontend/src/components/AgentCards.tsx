import { useState } from 'react';
import type { ReactNode } from 'react';
import { Badge, Button, Card, ConfidenceMeter } from './ui';
import { Icon } from './icons';
import type { AgentCard } from '../lib/api';
import { ThresholdGauge } from './ThresholdGauge';
import { TrendChart } from './TrendChart';
import type { TrendSeries } from './TrendChart';

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

// ---------- Briques ----------

function CardShell({
  title,
  kicker,
  actions,
  children,
}: {
  title: string;
  kicker: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card className="p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-stone-500 dark:text-stone-400">
            {kicker}
          </p>
          <h3 className="mt-0.5 text-[15px] font-semibold tracking-tight">{title}</h3>
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
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

function NeedBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800">
      <div className="h-full rounded-full bg-teal-600 dark:bg-teal-500" style={{ width: `${pct}%` }} />
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

function IncidentCard({ title, data }: { title: string; data: Record<string, unknown> }) {
  const urgency = typeof data.urgency === 'string' ? data.urgency : 'medium';
  const priority = typeof data.priority_score === 'number' ? data.priority_score : null;
  return (
    <CardShell
      title={title}
      kicker="Incident"
      actions={<CopyButton value={typeof data.reference_code === 'string' ? data.reference_code : ''} label="Référence" />}
    >
      <div className="flex flex-wrap gap-1.5">
        <Badge tone={URGENCY_TONE[urgency] ?? 'neutral'}>Urgence {URGENCY_LABEL[urgency] ?? urgency}</Badge>
        <Badge>{STATUS_LABEL[String(data.status)] ?? fmtText(data.status)}</Badge>
        {typeof data.category === 'string' && (
          <Badge tone="info">{CATEGORY_LABEL[data.category] ?? data.category}</Badge>
        )}
      </div>
      {typeof data.summary === 'string' && data.summary !== '' && (
        <p className="mt-2 text-sm leading-relaxed">{data.summary}</p>
      )}
      <p className="mt-1 font-mono text-xs text-stone-500 dark:text-stone-400">
        {fmtText(data.school_name)} · {fmtText(data.district)}
      </p>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Référence" value={fmtText(data.reference_code)} />
        <Stat label="Élèves affectés" value={fmtInt(data.affected_students)} />
        <Stat label="Signalé le" value={fmtDate(data.reported_at)} mono={false} />
        <div>
          <p className="text-[11px] text-stone-500 dark:text-stone-400">Priorité</p>
          <div className="mt-1">
            {priority === null ? (
              <p className="font-mono text-sm font-semibold tabular-nums">—</p>
            ) : (
              <ConfidenceMeter value={priority} />
            )}
          </div>
        </div>
      </div>
    </CardShell>
  );
}

function RankingCard({ title, data }: { title: string; data: Record<string, unknown> }) {
  const ranking = asArray<Record<string, unknown>>(data.ranking);
  const max = Math.max(0, ...ranking.map((r) => (typeof r.need_score === 'number' ? r.need_score : 0)));
  return (
    <CardShell title={title} kicker={`Classement — ${fmtInt(data.total)} écoles`}>
      {ranking.length === 0 ? (
        <p className="text-sm text-stone-600 dark:text-stone-400">Aucune école à classer.</p>
      ) : (
        <div className="divide-y divide-stone-200 dark:divide-stone-800">
          {ranking.map((r, i) => {
            const urg = typeof r.top_urgency === 'string' ? r.top_urgency : 'low';
            const score = typeof r.need_score === 'number' ? r.need_score : 0;
            return (
              <div key={String(r.school_id ?? i)} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
                <span className="w-6 shrink-0 font-mono text-xs tabular-nums text-stone-400 dark:text-stone-500">
                  {String(i + 1).padStart(2, '0')}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{fmtText(r.school_name)}</p>
                  <p className="font-mono text-[11px] text-stone-500 dark:text-stone-400">
                    {fmtText(r.district)} · {fmtInt(r.open_incidents)} incident(s) · {fmtInt(r.affected_students)} élèves
                    · {fmtInt(r.oldest_days)} j
                  </p>
                  <div className="mt-1.5">
                    <NeedBar value={score} max={max} />
                  </div>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <span className="font-mono text-sm font-bold tabular-nums">{fmtNum1(score)}</span>
                  <Badge tone={URGENCY_TONE[urg] ?? 'neutral'}>{URGENCY_LABEL[urg] ?? urg}</Badge>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </CardShell>
  );
}

function AnalysisCard({ title, data }: { title: string; data: Record<string, unknown> }) {
  const reco =
    typeof data.recommendation === 'string' ? RECOMMENDATION[data.recommendation] : undefined;
  const ratio = typeof data.repair_ratio_percent === 'number' ? data.repair_ratio_percent : null;
  const open = asArray<Record<string, unknown>>(data.open_incidents);
  return (
    <CardShell
      title={title}
      kicker={`Analyse — ${fmtText(data.district)}`}
      actions={reco ? <Badge tone={reco.tone}>{reco.label}</Badge> : undefined}
    >
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
                <Badge tone={URGENCY_TONE[urg] ?? 'neutral'}>{URGENCY_LABEL[urg] ?? urg}</Badge>
                <span className="min-w-0 flex-1 truncate">{fmtText(inc.title)}</span>
                <span className="shrink-0 font-mono text-xs text-stone-500 dark:text-stone-400">
                  {fmtInt(inc.affected_students)} élèves
                </span>
              </div>
            );
          })}
        </div>
      )}
    </CardShell>
  );
}

function DistrictCard({ title, data }: { title: string; data: Record<string, unknown> }) {
  const byUrgency = asRecord(data.by_urgency);
  const byCategory = asRecord(data.by_category);
  const schools = asArray<string>(data.schools_involved);
  const total = typeof data.open_incidents === 'number' ? data.open_incidents : 0;
  const urgEntries = Object.entries(byUrgency).filter(([, v]) => typeof v === 'number') as [string, number][];
  return (
    <CardShell title={title} kicker="District">
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Incidents ouverts" value={fmtInt(data.open_incidents)} />
        <Stat label="Élèves affectés" value={fmtInt(data.total_affected_students)} />
        <Stat label="Écoles impliquées" value={fmtInt(schools.length)} />
      </div>
      {urgEntries.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {urgEntries.map(([k, v]) => (
            <div key={k} className="flex items-center gap-2">
              <span className="w-20 shrink-0 text-xs text-stone-600 dark:text-stone-400">
                {URGENCY_LABEL[k] ?? k}
              </span>
              <div className="flex-1">
                <NeedBar value={v} max={Math.max(total, 1)} />
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
    </CardShell>
  );
}

function TrendCard({ title, data }: { title: string; data: Record<string, unknown> }) {
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
  return (
    <CardShell
      title={title}
      kicker="Tendances"
      actions={
        figures.trend_direction !== undefined && figures.trend_direction !== '' ? (
          <Badge tone="info">Tendance : {fmtText(figures.trend_direction)}</Badge>
        ) : undefined
      }
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat
          label={`Coût total${typeof figures.currency === 'string' ? ` (${figures.currency})` : ''}`}
          value={fmtInt(figures.total_cost)}
        />
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
    </CardShell>
  );
}

function ConfirmationCard({ title, data }: { title: string; data: Record<string, unknown> }) {
  const matched = asRecord(data.matched_school);
  return (
    <CardShell
      title={title}
      kicker="Brouillon"
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
    <CardShell title={card.title} kicker={card.type}>
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

export function AgentCardView({ card }: { card: AgentCard }) {
  const data = asRecord(card.data);
  switch (card.type) {
    case 'incident_detail':
      return <IncidentCard title={card.title} data={data} />;
    case 'school_ranking':
      return <RankingCard title={card.title} data={data} />;
    case 'school_analysis':
      return <AnalysisCard title={card.title} data={data} />;
    case 'district_summary':
      return <DistrictCard title={card.title} data={data} />;
    case 'trend_chart':
      return <TrendCard title={card.title} data={data} />;
    case 'report_confirmation':
      return <ConfirmationCard title={card.title} data={data} />;
    default:
      return <GenericCard card={card} />;
  }
}

export function AgentCardList({ cards }: { cards: AgentCard[] }) {
  if (cards.length === 0) return null;
  return (
    <div className="space-y-3 pt-1">
      {cards.map((c, i) => (
        <AgentCardView key={`${c.type}-${i}`} card={c} />
      ))}
    </div>
  );
}
