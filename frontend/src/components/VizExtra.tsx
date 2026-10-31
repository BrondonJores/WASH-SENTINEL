// Rendus graphiques supplémentaires : calendrier des pannes, suivi d'incident, budgets.
// Thème maison (teal/stone/amber), français simple, chiffres fr-FR, motion réduite respectée.
import { Icon } from './icons';

const fmtIntFR = (v: number): string => new Intl.NumberFormat('fr-FR').format(Math.round(v));

/** Date lisible fr-FR depuis AAAA-MM-JJ ou ISO complet ; '—' si absent. */
function fmtDateFR(v: unknown): string {
  if (typeof v !== 'string' || v === '') return '—';
  const day = v.length >= 10 ? v.slice(0, 10) : v;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  const d = m !== null ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(v);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
}

const MONTH_SHORT = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];

/** Libellé « 12 500 XAF » ; '—' si absent. */
function fmtMoney(cost: number, currency: string): string {
  return `${fmtIntFR(cost)} ${currency}`;
}

// ---------- Calendrier des pannes (style GitHub) ----------

export interface HeatmapDay {
  /** Jour AAAA-MM-JJ. */
  date: string;
  count: number;
  schools: string[];
}

/** Jour de semaine lundi = 0 … dimanche = 6. */
function weekdayMon0(iso: string): number {
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
  if (Number.isNaN(d.getTime())) return 0;
  return (d.getDay() + 6) % 7;
}

const HEAT_LEVELS = [
  'bg-stone-200 dark:bg-stone-800',
  'bg-teal-100 dark:bg-teal-950',
  'bg-teal-300 dark:bg-teal-800',
  'bg-teal-500 dark:bg-teal-600',
  'bg-teal-700 dark:bg-teal-400',
];

function heatLevel(count: number, max: number): number {
  if (count <= 0 || max <= 0) return 0;
  const t = count / max;
  if (t <= 0.25) return 1;
  if (t <= 0.5) return 2;
  if (t <= 0.75) return 3;
  return 4;
}

export function CalendarHeatmap({
  days,
  total,
  onSelect,
}: {
  days: HeatmapDay[];
  total?: number;
  /** Clic sur un jour : date AAAA-MM-JJ. */
  onSelect?: (date: string) => void;
}) {
  if (days.length === 0) return null;
  const sorted = [...days].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  const max = Math.max(0, ...sorted.map((d) => d.count));
  const sum = typeof total === 'number' && Number.isFinite(total) ? total : sorted.reduce((s, d) => s + d.count, 0);

  // Colonnes = semaines, lignes = jours (lundi en haut).
  const cells: (HeatmapDay | null)[] = [];
  for (let k = 0; k < weekdayMon0(sorted[0].date); k++) cells.push(null);
  for (const d of sorted) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);
  const weekCount = cells.length / 7;
  const weeks: (HeatmapDay | null)[][] = [];
  for (let w = 0; w < weekCount; w++) weeks.push(cells.slice(w * 7, w * 7 + 7));

  // Étiquette de mois par colonne quand le mois change.
  let prevMonth = -1;
  const monthLabels: string[] = weeks.map((week) => {
    const first = week.find((c) => c !== null);
    if (first === undefined) return '';
    const month = Number(first.date.slice(5, 7)) - 1;
    if (month === prevMonth || month < 0 || month > 11) return '';
    prevMonth = month;
    return MONTH_SHORT[month];
  });

  const cellBox = 'h-3.5 w-3.5 sm:h-4 sm:w-4';
  const clickable = onSelect !== undefined;
  const dayLabel = (d: HeatmapDay): string =>
    d.count === 0
      ? `Aucune panne le ${fmtDateFR(d.date)}`
      : d.count === 1
        ? `1 panne le ${fmtDateFR(d.date)}`
        : `${fmtIntFR(d.count)} pannes le ${fmtDateFR(d.date)}`;

  return (
    <div>
      <div className="overflow-x-auto pb-1">
        <div className="inline-flex gap-1.5">
          {/* Libellés des jours */}
          <div className="flex shrink-0 flex-col" aria-hidden="true">
            <span className="mb-1 h-4 text-[10px] leading-4">&nbsp;</span>
            <div className="flex flex-col gap-[3px]">
              {['Lun', '', 'Mer', '', 'Ven', '', ''].map((w, i) => (
                <span key={i} className={`${cellBox} flex items-center text-[10px] text-stone-500 dark:text-stone-400`}>
                  {w}
                </span>
              ))}
            </div>
          </div>
          <div className="shrink-0">
            {/* Libellés des mois */}
            <div className="mb-1 flex h-4 gap-[3px]" aria-hidden="true">
              {monthLabels.map((m, w) => (
                <span key={w} className={`${cellBox} overflow-visible whitespace-nowrap text-[10px] leading-4 text-stone-500 dark:text-stone-400`}>
                  {m}
                </span>
              ))}
            </div>
            <div
              role={clickable ? 'group' : 'img'}
              aria-label={clickable ? 'Calendrier des pannes, touchez un jour pour le détail' : 'Calendrier des pannes'}
              className="grid grid-flow-col gap-[3px]"
              style={{ gridTemplateRows: 'repeat(7, minmax(0, 1fr))' }}
            >
              {cells.map((d, i) =>
                d === null ? (
                  <span key={i} className={cellBox} aria-hidden="true" />
                ) : clickable ? (
                  <button
                    key={`${d.date}-${i}`}
                    type="button"
                    title={dayLabel(d)}
                    aria-label={dayLabel(d)}
                    onClick={() => onSelect(d.date)}
                    className={`${cellBox} rounded-[3px] ${HEAT_LEVELS[heatLevel(d.count, max)]} transition-[transform] duration-150 ease-out hover:ring-2 hover:ring-teal-700/50 active:scale-90 motion-reduce:transition-none motion-reduce:active:scale-100 dark:hover:ring-teal-400/50`}
                  />
                ) : (
                  <span
                    key={`${d.date}-${i}`}
                    title={dayLabel(d)}
                    className={`${cellBox} rounded-[3px] ${HEAT_LEVELS[heatLevel(d.count, max)]}`}
                  />
                ),
              )}
            </div>
          </div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-stone-500 dark:text-stone-400">
          {sum === 0 ? 'Aucune panne sur la période.' : `${fmtIntFR(sum)} panne${sum > 1 ? 's' : ''} sur la période.`}
        </p>
        <div className="flex items-center gap-1" aria-hidden="true">
          <span className="mr-0.5 text-[11px] text-stone-500 dark:text-stone-400">Moins</span>
          {HEAT_LEVELS.map((c, i) => (
            <span key={i} className={`h-3 w-3 rounded-[3px] ${c}`} />
          ))}
          <span className="ml-0.5 text-[11px] text-stone-500 dark:text-stone-400">Plus</span>
        </div>
      </div>
    </div>
  );
}

// ---------- Suivi d'incident (timeline verticale) ----------

export interface TimelineStep {
  label: string;
  /** Date ISO ou AAAA-MM-JJ, null si non fournie. */
  date: string | null;
  done: boolean;
}

export function IncidentTimeline({ steps }: { steps: TimelineStep[] }) {
  if (steps.length === 0) return null;
  const currentIdx = steps.findIndex((s) => !s.done);
  return (
    <ol>
      {steps.map((s, i) => {
        const last = i === steps.length - 1;
        const isCurrent = i === currentIdx;
        return (
          <li key={`${s.label}-${i}`} className={`relative flex gap-3 ${last ? '' : 'pb-5'}`}>
            {!last && (
              <span
                aria-hidden="true"
                className={`absolute bottom-0 left-[11px] top-6 w-0.5 rounded-full ${s.done ? 'bg-teal-600/70 dark:bg-teal-500/70' : 'bg-stone-200 dark:bg-stone-700'}`}
              />
            )}
            <span
              aria-hidden="true"
              className={`relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
                s.done
                  ? 'bg-teal-600 text-white dark:bg-teal-500 dark:text-stone-950'
                  : 'border-2 border-stone-300 bg-white dark:border-stone-600 dark:bg-stone-900'
              }`}
            >
              {s.done && <Icon name="check" className="h-3.5 w-3.5" />}
            </span>
            <div className="min-w-0 pt-0.5">
              <p className={`text-sm leading-snug ${s.done || isCurrent ? 'font-semibold' : ''}`}>
                {s.label}
                {isCurrent && (
                  <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
                    Étape actuelle
                  </span>
                )}
              </p>
              {s.date !== null && s.date !== '' && (
                <p className="mt-0.5 font-mono text-xs text-stone-500 dark:text-stone-400">{fmtDateFR(s.date)}</p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

// ---------- Comparatif budget ----------

export interface BudgetSchool {
  name: string;
  cost: number;
  incidents: number;
}

export interface BudgetCategory {
  /** Code backend (water_point, …, unknown). */
  code: string;
  label: string;
  cost: number;
  /** Part en %, 0 si inconnue. */
  share: number;
}

const CATEGORY_DOT: Record<string, string> = {
  water_point: 'bg-teal-600 dark:bg-teal-500',
  toilets_latrines: 'bg-amber-500',
  handwashing: 'bg-sky-600 dark:bg-sky-500',
  sewage_drainage: 'bg-stone-500 dark:bg-stone-400',
  unknown: 'bg-stone-300 dark:bg-stone-600',
};

export function BudgetCompare({
  schools,
  categories,
  total,
  currency,
  onSelectSchool,
}: {
  schools: BudgetSchool[];
  categories: BudgetCategory[];
  total: number;
  currency: string;
  /** Clic sur une école : index dans la liste. */
  onSelectSchool?: (index: number) => void;
}) {
  if (schools.length === 0 && categories.length === 0) return null;
  const max = Math.max(0, ...schools.map((s) => s.cost));
  const shown = [...schools].sort((a, b) => b.cost - a.cost);
  const catTotal = categories.reduce((s, c) => s + c.cost, 0);
  const shareOf = (c: BudgetCategory): number =>
    c.share > 0 ? c.share : catTotal > 0 ? Math.round((c.cost / catTotal) * 1000) / 10 : 0;
  const clickable = onSelectSchool !== undefined;
  return (
    <div className="space-y-4">
      {shown.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-stone-500 dark:text-stone-400">
            Dépenses par école
          </p>
          <ul className="space-y-2.5">
            {shown.map((s, i) => {
              const pct = max > 0 ? Math.round((s.cost / max) * 100) : 0;
              const row = (
                <>
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="min-w-0 truncate text-sm font-medium">{s.name}</span>
                    <span className="shrink-0 font-mono text-xs font-semibold tabular-nums">
                      {fmtMoney(s.cost, currency)}
                    </span>
                  </span>
                  <span className="mt-1 block h-2.5 w-full overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800">
                    <span className="block h-full rounded-full bg-teal-600 dark:bg-teal-500" style={{ width: `${pct}%` }} />
                  </span>
                  <span className="mt-0.5 block font-mono text-[11px] text-stone-500 dark:text-stone-400">
                    {s.incidents === 0 ? 'Aucune panne' : s.incidents === 1 ? '1 panne' : `${fmtIntFR(s.incidents)} pannes`}
                  </span>
                </>
              );
              const origIdx = schools.indexOf(s);
              return (
                <li key={`${s.name}-${i}`}>
                  {clickable ? (
                    <button
                      type="button"
                      onClick={() => onSelectSchool(origIdx)}
                      title={`Analyser ${s.name}`}
                      className="block w-full rounded-lg text-left transition-[transform] duration-150 ease-out active:scale-[0.99] motion-reduce:transition-none motion-reduce:active:scale-100"
                    >
                      {row}
                    </button>
                  ) : (
                    <div>{row}</div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {categories.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-stone-500 dark:text-stone-400">
            Parts par catégorie
          </p>
          <div
            className="flex h-3 w-full overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800"
            role="img"
            aria-label={`Répartition : ${categories.map((c) => `${c.label} ${shareOf(c).toLocaleString('fr-FR', { maximumFractionDigits: 1 })} %`).join(', ')}`}
          >
            {categories.map((c) => (
              <span
                key={c.code}
                className={CATEGORY_DOT[c.code] ?? CATEGORY_DOT.unknown}
                style={{ width: `${shareOf(c)}%` }}
              />
            ))}
          </div>
          <ul className="mt-2 space-y-1">
            {categories.map((c) => (
              <li key={c.code} className="flex items-center gap-2 text-[13px]">
                <span aria-hidden="true" className={`h-2.5 w-2.5 shrink-0 rounded-full ${CATEGORY_DOT[c.code] ?? CATEGORY_DOT.unknown}`} />
                <span className="min-w-0 flex-1 truncate text-stone-600 dark:text-stone-400">{c.label}</span>
                <span className="shrink-0 font-mono text-xs tabular-nums">
                  {fmtMoney(c.cost, currency)} · {shareOf(c).toLocaleString('fr-FR', { maximumFractionDigits: 1 })} %
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="border-t border-stone-200/70 pt-2 text-sm dark:border-white/[0.06]">
        <span className="text-stone-500 dark:text-stone-400">Total : </span>
        <span className="font-mono font-bold tabular-nums">{fmtMoney(total, currency)}</span>
      </p>
    </div>
  );
}
