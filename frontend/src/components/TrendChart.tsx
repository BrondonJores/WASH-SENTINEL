import { useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useTheme } from '../theme';
import { localeFor } from '../lib/locale';

export interface TrendSeries {
  key: string;
  label: string;
  kind: 'bar' | 'line';
  data: number[];
  color: string;
}

export interface DonutEntry {
  name: string;
  value: number;
  color: string;
}

export interface HBarEntry {
  name: string;
  value: number;
  color?: string;
}

interface TooltipEntry {
  name?: string;
  value?: number | string;
  color?: string;
}

const fmtFR = (v: number, lang?: string): string => new Intl.NumberFormat(localeFor(lang)).format(v);
const fmtCompact = (v: number, lang?: string): string =>
  new Intl.NumberFormat(localeFor(lang), { notation: 'compact' }).format(v);

/** Respecte prefers-reduced-motion pour les animations recharts. */
function useReducedMotion(): boolean {
  const [reduced] = useState(
    () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false,
  );
  return reduced;
}

/** Couleurs d'axes selon le thème maison (stone). */
function useAxisColors(): { grid: string; tick: string } {
  const { theme } = useTheme();
  const dark = theme === 'dark';
  return { grid: dark ? '#292524' : '#e7e5e4', tick: dark ? '#a8a29e' : '#78716c' };
}

/** Unité lisible selon le libellé de la série (« 12 500 XAF », « 3 pannes », « 5 jours »). */
function suffixFor(label: unknown, value: number, lang?: string): string {
  if (typeof label !== 'string') return '';
  const en = lang === 'en';
  const l = label.toLowerCase();
  if (/coût|cout|cost|xaf|fcfa|franc|réparation|reparation|repair/.test(l)) return ' XAF';
  if (/panne|incident|breakdown|failure/.test(l)) return en ? (value > 1 ? ' breakdowns' : ' breakdown') : value > 1 ? ' pannes' : ' panne';
  if (/jour|day/.test(l)) return en ? (value > 1 ? ' days' : ' day') : value > 1 ? ' jours' : ' jour';
  if (/école|ecole|school/.test(l)) return en ? (value > 1 ? ' schools' : ' school') : value > 1 ? ' écoles' : ' école';
  return '';
}

function ChartTooltip({
  active,
  payload,
  label,
  lang,
}: {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: string | number;
  lang?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-md border border-stone-200 bg-white px-3 py-2 shadow-lg dark:border-stone-700 dark:bg-stone-900">
      <p className="mb-1 text-[11px] font-semibold">{label}</p>
      {payload.map((p, i) => (
        <p key={i} className="flex items-center gap-2 font-mono text-xs tabular-nums">
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: p.color ?? '#888' }} />
          <span className="text-stone-500 dark:text-stone-400">{p.name}</span>
          <span className="ml-auto pl-3 font-semibold">
            {typeof p.value === 'number'
              ? `${fmtFR(p.value, lang)}${suffixFor(p.name, p.value, lang)}`
              : (p.value ?? '—')}
          </span>
        </p>
      ))}
    </div>
  );
}

/** Graphe composé isolé : barres + lignes + moyenne. Interchangeable. */
export function TrendChart({
  labels,
  series,
  height = 224,
  onSelect,
  lang,
}: {
  labels: string[];
  series: TrendSeries[];
  height?: number;
  /** Clic sur un point ou une barre : index du mois. */
  onSelect?: (index: number) => void;
  lang?: string;
}) {
  const en = lang === 'en';
  const reduced = useReducedMotion();
  const { grid, tick } = useAxisColors();

  const rows: Record<string, string | number>[] = labels.map((name, i) => {
    const row: Record<string, string | number> = { name };
    for (const s of series) row[s.key] = s.data[i] ?? 0;
    return row;
  });
  const primary = series.find((s) => s.kind === 'bar') ?? series[0];
  const avg =
    primary && primary.data.length > 0 ? primary.data.reduce((a, b) => a + b, 0) / primary.data.length : 0;
  const hasBars = series.some((s) => s.kind === 'bar');
  const hasLines = series.some((s) => s.kind === 'line');
  const clickable = onSelect !== undefined;
  const handleClick = (_entry: unknown, index: number): void => {
    if (Number.isInteger(index) && index >= 0 && index < labels.length) onSelect?.(index);
  };
  /** Clic sur un point de courbe : recharts donne les props du point, on retrouve le mois. */
  const handleDotClick = (entry: unknown): void => {
    const rec = typeof entry === 'object' && entry !== null ? (entry as Record<string, unknown>) : {};
    const nested =
      typeof rec.payload === 'object' && rec.payload !== null
        ? (rec.payload as Record<string, unknown>)
        : {};
    const name = rec.name ?? nested.name;
    const idx = typeof name === 'string' ? labels.indexOf(name) : -1;
    if (idx >= 0) onSelect?.(idx);
  };

  return (
    <div style={{ height }} className={`w-full ${clickable ? 'cursor-pointer' : ''}`}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap="28%">
          <CartesianGrid stroke={grid} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="name"
            tick={{ fill: tick, fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: grid }}
            minTickGap={12}
          />
          {hasBars && (
            <YAxis
              yAxisId="left"
              tick={{ fill: tick, fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              width={52}
              tickFormatter={(v: number) => fmtCompact(v, lang)}
            />
          )}
          {hasLines && (
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={{ fill: tick, fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              width={36}
              allowDecimals={false}
            />
          )}
          <Tooltip content={<ChartTooltip lang={lang} />} cursor={{ stroke: grid }} />
          <Legend
            wrapperStyle={{ fontSize: 12 }}
            formatter={(v: string) => <span className="text-stone-600 dark:text-stone-400">{v}</span>}
          />
          {hasBars && primary && (
            <ReferenceLine
              y={avg}
              yAxisId="left"
              stroke={tick}
              strokeDasharray="4 4"
              label={{ value: en ? 'average' : 'moyenne', position: 'insideTopRight', fontSize: 10, fill: tick }}
            />
          )}
          {series
            .filter((s) => s.kind === 'bar')
            .map((s) => (
              <Bar
                key={s.key}
                yAxisId="left"
                dataKey={s.key}
                name={s.label}
                fill={s.color}
                radius={[4, 4, 0, 0]}
                maxBarSize={44}
                isAnimationActive={!reduced}
                onClick={clickable ? handleClick : undefined}
              />
            ))}
          {series
            .filter((s) => s.kind === 'line')
            .map((s) => (
              <Line
                key={s.key}
                yAxisId="right"
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={s.color}
                strokeWidth={2}
                dot={{ r: clickable ? 4 : 3, fill: s.color }}
                activeDot={{ r: 5 }}
                isAnimationActive={!reduced}
                onClick={clickable ? handleDotClick : undefined}
              />
            ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function DonutTooltip({
  active,
  payload,
  total,
  lang,
}: {
  active?: boolean;
  payload?: TooltipEntry[];
  total: number;
  lang?: string;
}) {
  const first = payload?.[0];
  if (!active || first === undefined) return null;
  const value = typeof first.value === 'number' ? first.value : 0;
  const pct = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div className="rounded-md border border-stone-200 bg-white px-3 py-2 shadow-lg dark:border-stone-700 dark:bg-stone-900">
      <p className="flex items-center gap-2 font-mono text-xs tabular-nums">
        <span
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: first.color ?? '#888' }}
        />
        <span className="text-stone-500 dark:text-stone-400">{first.name}</span>
        <span className="ml-auto pl-3 font-semibold">
{fmtFR(value, lang)} ({pct} %)
        </span>
      </p>
    </div>
  );
}

/** Anneau de répartition (ex : urgences) + légende lisible avec chiffres. */
export function TrendDonut({
  entries,
  height = 200,
  onSelect,
  lang,
}: {
  entries: DonutEntry[];
  height?: number;
  /** Clic sur une part ou une ligne de légende : index de l'entrée. */
  onSelect?: (index: number) => void;
  lang?: string;
}) {
  const en = lang === 'en';
  const reduced = useReducedMotion();
  const total = entries.reduce((s, e) => s + e.value, 0);
  const clickable = onSelect !== undefined;
  if (entries.length === 0) return null;
  return (
    <div>
      <div style={{ height }} className={`relative w-full ${clickable ? 'cursor-pointer' : ''}`}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Tooltip content={<DonutTooltip total={total} lang={lang} />} />
            <Pie
              data={entries}
              dataKey="value"
              nameKey="name"
              innerRadius="58%"
              outerRadius="85%"
              paddingAngle={2}
              strokeWidth={0}
              isAnimationActive={!reduced}
              onClick={clickable ? (_entry: unknown, index: number) => onSelect?.(index) : undefined}
            >
              {entries.map((e) => (
                <Cell key={e.name} fill={e.color} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-mono text-2xl font-bold tabular-nums">{fmtFR(total, lang)}</span>
          <span className="text-[11px] text-stone-500 dark:text-stone-400">{en ? 'in total' : 'au total'}</span>
        </div>
      </div>
      <ul className="mt-1 space-y-1">
        {entries.map((e, i) => {
          const pct = total > 0 ? Math.round((e.value / total) * 100) : 0;
          const row = (
            <>
              <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: e.color }} />
              <span className="text-[13px] text-stone-600 dark:text-stone-400">{e.name}</span>
              <span className="ml-auto font-mono text-xs font-semibold tabular-nums">
{fmtFR(e.value, lang)} · {pct} %
              </span>
            </>
          );
          return (
            <li key={e.name}>
              {clickable ? (
                <button
                  type="button"
                  onClick={() => onSelect?.(i)}
                  className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 transition-[transform,opacity] duration-150 ease-snap hover:bg-stone-100 active:scale-[0.98] dark:hover:bg-stone-800 motion-reduce:transition-none motion-reduce:active:scale-100"
                >
                  {row}
                </button>
              ) : (
                <div className="flex w-full items-center gap-2 px-1.5 py-1">{row}</div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function HBarTooltip({
  active,
  payload,
  unit,
  lang,
}: {
  active?: boolean;
  payload?: (TooltipEntry & { payload?: { name?: string } })[];
  unit?: string;
  lang?: string;
}) {
  const first = payload?.[0];
  if (!active || first === undefined) return null;
  const value = typeof first.value === 'number' ? first.value : 0;
  return (
    <div className="rounded-md border border-stone-200 bg-white px-3 py-2 shadow-lg dark:border-stone-700 dark:bg-stone-900">
      <p className="mb-0.5 text-[11px] font-semibold">{first.payload?.name ?? first.name}</p>
      <p className="font-mono text-xs tabular-nums">
        <span className="font-semibold">
{fmtFR(value, lang)}
          {unit !== undefined && unit !== '' ? ` ${unit}` : ''}
        </span>
      </p>
    </div>
  );
}

/** Barres horizontales (ex : top écoles). Hauteur adaptée au nombre de lignes. */
export function TrendHBars({
  entries,
  unit,
  onSelect,
  lang,
}: {
  entries: HBarEntry[];
  unit?: string;
  /** Clic sur une barre : index de l'entrée. */
  onSelect?: (index: number) => void;
  lang?: string;
}) {
  const en = lang === 'en';
  const reduced = useReducedMotion();
  const { grid, tick } = useAxisColors();
  if (entries.length === 0) return null;
  const height = Math.max(120, entries.length * 34 + 44);
  const clickable = onSelect !== undefined;
  return (
    <div style={{ height }} className={`w-full ${clickable ? 'cursor-pointer' : ''}`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={entries} layout="vertical" margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={grid} strokeDasharray="3 3" horizontal={false} />
          <XAxis
            type="number"
            tick={{ fill: tick, fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: grid }}
            tickFormatter={(v: number) => fmtCompact(v, lang)}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={112}
            tick={{ fill: tick, fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: string) => (v.length > 16 ? `${v.slice(0, 15)}…` : v)}
          />
          <Tooltip content={<HBarTooltip unit={unit} lang={lang} />} cursor={{ fill: grid, opacity: 0.35 }} />
          <Bar
            dataKey="value"
            name={unit ?? (en ? 'Value' : 'Valeur')}
            radius={[0, 4, 4, 0]}
            maxBarSize={20}
            isAnimationActive={!reduced}
            onClick={clickable ? (_entry: unknown, index: number) => onSelect?.(index) : undefined}
          >
            {entries.map((e) => (
              <Cell key={e.name} fill={e.color ?? '#0d9488'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
