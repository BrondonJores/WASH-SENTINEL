export interface GaugeThreshold {
  value: number;
  label: string;
  tone: 'warn' | 'danger' | 'info';
}

const TICK: Record<GaugeThreshold['tone'], string> = {
  warn: 'bg-amber-500',
  danger: 'bg-red-500',
  info: 'bg-sky-500',
};

/** Jauge horizontale avec seuils de décision (zéro dépendance). */
export function ThresholdGauge({
  value,
  max = 100,
  display,
  thresholds,
}: {
  value: number;
  max?: number;
  display: string;
  thresholds: GaugeThreshold[];
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div>
      <p className="font-mono text-sm font-bold tabular-nums">{display}</p>
      <div className="relative mt-1.5 h-2 rounded-full bg-stone-200 dark:bg-stone-800">
        <div className="h-full rounded-full bg-teal-600 dark:bg-teal-500" style={{ width: `${pct}%` }} />
        {thresholds.map((t) => (
          <span
            key={t.value}
            title={t.label}
            className={`absolute top-[-3px] h-[14px] w-[2px] rounded-full ${TICK[t.tone]}`}
            style={{ left: `calc(${(t.value / max) * 100}% - 1px)` }}
          />
        ))}
      </div>
      <div className="relative mt-1 h-3 font-mono text-[10px] tabular-nums text-stone-500 dark:text-stone-400">
        {thresholds.map((t) => (
          <span
            key={t.value}
            className="absolute -translate-x-1/2"
            style={{ left: `${(t.value / max) * 100}%` }}
          >
            {t.label}
          </span>
        ))}
      </div>
    </div>
  );
}
