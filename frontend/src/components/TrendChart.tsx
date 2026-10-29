import { useState } from 'react';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useTheme } from '../theme';

export interface TrendSeries {
  key: string;
  label: string;
  kind: 'bar' | 'line';
  data: number[];
  color: string;
}

interface TooltipEntry {
  name?: string;
  value?: number | string;
  color?: string;
}

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: string | number;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-md border border-stone-200 bg-white px-3 py-2 shadow-lg dark:border-stone-700 dark:bg-stone-900">
      <p className="mb-1 font-mono text-[11px] font-semibold">{label}</p>
      {payload.map((p, i) => (
        <p key={i} className="flex items-center gap-2 font-mono text-xs tabular-nums">
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: p.color ?? '#888' }} />
          <span className="text-stone-500 dark:text-stone-400">{p.name}</span>
          <span className="ml-auto pl-3 font-semibold">
            {typeof p.value === 'number' ? new Intl.NumberFormat('fr-FR').format(p.value) : p.value}
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
}: {
  labels: string[];
  series: TrendSeries[];
  height?: number;
}) {
  const { theme } = useTheme();
  const [reduced] = useState(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false);
  const dark = theme === 'dark';
  const grid = dark ? '#292524' : '#e7e5e4';
  const tick = dark ? '#a8a29e' : '#78716c';

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

  return (
    <div style={{ height }} className="w-full">
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
              tickFormatter={(v: number) => new Intl.NumberFormat('fr-FR', { notation: 'compact' }).format(v)}
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
          <Tooltip content={<ChartTooltip />} cursor={{ stroke: grid }} />
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
              label={{ value: 'moyenne', position: 'insideTopRight', fontSize: 10, fill: tick }}
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
                dot={{ r: 3, fill: s.color }}
                isAnimationActive={!reduced}
              />
            ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
