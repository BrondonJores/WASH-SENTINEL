import { useEffect, useRef, useState } from 'react';
import type { ReactNode, RefObject } from 'react';
import { api, ApiError } from '../lib/api';
import type { Incident, School } from '../lib/api';
import { LOCALE } from '../lib/locale';
import { STATUS_FR, URGENCY_FR, urgencyTone } from '../lib/wash';
import { Badge, Button, Skeleton } from './ui';
import { Icon } from './icons';

export type DetailKind = 'incident' | 'school';
export type DetailTarget = { kind: DetailKind; id: number };

// ---------- Helpers ----------

const fmtInt = (v: unknown): string => {
  if (typeof v === 'number' && Number.isFinite(v)) return new Intl.NumberFormat(LOCALE).format(Math.round(v));
  return '—';
};

const fmtDate = (v: unknown): string => {
  if (typeof v !== 'string' || v === '') return '—';
  const d = new Date(v);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleDateString(LOCALE, { day: 'numeric', month: 'short', year: 'numeric' });
};

const fmtMoney = (v: number | null, currency: string | null): string =>
  v === null ? '—' : `${fmtInt(v)}${currency ? ` ${currency}` : ''}`;

// DIVERGENCE volontaire conservée : 'Évacuation' (court, badge) vs
// CATEGORY_FR 'Évacuation / drainage' de lib/wash.ts — rendu identique exigé.
const CATEGORY_LABEL: Record<string, string> = {
  water_point: "Point d'eau",
  toilets_latrines: 'Toilettes / latrines',
  handwashing: 'Lavage des mains',
  sewage_drainage: 'Évacuation',
};

function Stat({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <p className="text-[11px] text-stone-500 dark:text-stone-400">{label}</p>
      <p className={`mt-0.5 text-sm font-semibold tabular-nums ${mono ? 'font-mono' : ''}`}>{value}</p>
    </div>
  );
}

function DrawerSkeleton() {
  return (
    <div className="space-y-3" aria-label="Chargement du détail">
      <Skeleton className="h-7 w-3/4" />
      <Skeleton className="h-4 w-1/3" />
      <div className="flex gap-2">
        <Skeleton className="h-6 w-20 rounded-full" />
        <Skeleton className="h-6 w-20 rounded-full" />
        <Skeleton className="h-6 w-24 rounded-full" />
      </div>
      <Skeleton className="h-20 w-full" />
      <div className="grid grid-cols-2 gap-3">
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-12 w-full" />
      </div>
    </div>
  );
}

// ---------- Vues ----------

function IncidentView({
  incident,
  onDetail,
  onAsk,
}: {
  incident: Incident;
  onDetail: (kind: DetailKind, id: number) => void;
  onAsk?: (q: string) => void;
}) {
  const schoolName = incident.school?.name ?? `École #${incident.school_id}`;
  const district = incident.school?.district;
  const reportsCount = incident.reports_count ?? incident.reports?.length ?? 0;
  const logs = incident.maintenance_logs ?? [];
  return (
    <div>
      <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-teal-700 dark:text-teal-300">
        Incident · {incident.reference_code}
      </p>
      <h2 className="mt-1 font-display text-xl font-bold leading-snug tracking-tight">{incident.title}</h2>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Badge tone={urgencyTone(incident.urgency)}>
          Urgence {URGENCY_FR[incident.urgency] ?? incident.urgency}
        </Badge>
        <Badge>{STATUS_FR[incident.status] ?? incident.status}</Badge>
        <Badge tone="info">{CATEGORY_LABEL[incident.category] ?? incident.category}</Badge>
      </div>

      <button
        type="button"
        onClick={() => onDetail('school', incident.school_id)}
        title="Voir le détail de l'école"
        className="mt-3 flex w-full items-center gap-2.5 rounded-xl border border-line bg-card px-3 py-2.5 text-left transition-[border-color,transform] duration-150 ease-snap hover:border-accent active:scale-[0.99] motion-reduce:transition-none motion-reduce:active:scale-100"
      >
        <Icon name="school" className="h-5 w-5 shrink-0 text-teal-700 dark:text-teal-300" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold">{schoolName}</span>
          {district !== undefined && district !== '' && (
            <span className="block truncate text-xs text-stone-500 dark:text-stone-400">{district}</span>
          )}
        </span>
        <Icon name="arrow-right" className="h-4 w-4 shrink-0 text-stone-400" />
      </button>

      <div className="mt-4 grid grid-cols-2 gap-3">
        <Stat label="Élèves affectés" value={fmtInt(incident.affected_students)} />
        <Stat label="Priorité IA" value={fmtInt(incident.priority_score)} />
        <Stat label="Signalements" value={fmtInt(reportsCount)} />
        <Stat label="Assigné à" value={incident.assignee?.name ?? 'Personne'} mono={false} />
        <Stat label="Signalé le" value={fmtDate(incident.created_at)} mono={false} />
        <Stat label="Résolu le" value={incident.resolved_at ? fmtDate(incident.resolved_at) : '—'} mono={false} />
      </div>

      {incident.issue_type !== null && incident.issue_type !== '' && (
        <p className="mt-3 text-sm">
          <span className="text-stone-500 dark:text-stone-400">Type de panne : </span>
          <span className="font-medium">{incident.issue_type}</span>
        </p>
      )}
      {incident.health_hazard !== null && incident.health_hazard !== '' && (
        <p className="mt-1 text-sm">
          <span className="text-stone-500 dark:text-stone-400">Risque sanitaire : </span>
          <span className="font-medium">{incident.health_hazard}</span>
        </p>
      )}

      {incident.ai_summary !== null && incident.ai_summary !== '' && (
        <div className="mt-4 rounded-xl border border-line bg-raised/60 p-3">
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-faint">Résumé IA</p>
          <p className="mt-1 text-sm leading-relaxed">{incident.ai_summary}</p>
        </div>
      )}
      {incident.ai_tags !== null && incident.ai_tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {incident.ai_tags.map((t) => (
            <Badge key={t}>{t}</Badge>
          ))}
        </div>
      )}

      {logs.length > 0 && (
        <div className="mt-4">
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-faint">
            Interventions ({logs.length})
          </p>
          <ul className="mt-2 space-y-2">
            {logs.slice(0, 5).map((l) => (
              <li key={l.id} className="rounded-lg border border-line px-3 py-2 text-sm">
                <span className="flex items-center justify-between gap-2">
                  <span className="font-medium">{fmtDate(l.repaired_at ?? l.created_at)}</span>
                  <span className="font-mono text-xs tabular-nums">
                    {fmtMoney(l.cost_amount, l.currency)}
                  </span>
                </span>
                {l.notes !== null && l.notes !== '' && (
                  <span className="mt-0.5 block text-[13px] text-stone-600 dark:text-stone-400">{l.notes}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {onAsk !== undefined && (
        <Button
          size="sm"
          onClick={() => onAsk(`Explique l'incident ${incident.reference_code} en langage simple`)}
          className="mt-4"
        >
          <Icon name="chat" className="h-3.5 w-3.5" />
          Expliquer dans le chat
        </Button>
      )}
    </div>
  );
}

function SchoolView({
  school,
  onDetail,
  onAsk,
}: {
  school: School;
  onDetail: (kind: DetailKind, id: number) => void;
  onAsk?: (q: string) => void;
}) {
  const open = school.open_incidents ?? [];
  const openCount = school.open_incidents_count ?? open.length;
  return (
    <div>
      <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-teal-700 dark:text-teal-300">
        École · {school.code}
      </p>
      <h2 className="mt-1 font-display text-xl font-bold leading-snug tracking-tight">{school.name}</h2>
      <p className="mt-1 font-mono text-xs text-stone-500 dark:text-stone-400">{school.district}</p>

      <div className="mt-4 grid grid-cols-2 gap-3">
        <Stat label="Élèves" value={fmtInt(school.student_count)} />
        <Stat label="Incidents ouverts" value={fmtInt(openCount)} />
        <Stat label="Enseignants" value={school.teacher_count === null ? '—' : fmtInt(school.teacher_count)} />
        <Stat label="Signalements" value={school.reports_count === undefined ? '—' : fmtInt(school.reports_count)} />
      </div>

      {(school.equipment_type !== null || school.installation_year !== null || school.contact_phone !== null) && (
        <dl className="mt-3 space-y-1.5 border-t border-stone-200/70 pt-3 text-sm dark:border-white/[0.06]">
          {school.equipment_type !== null && school.equipment_type !== '' && (
            <div className="flex items-start justify-between gap-3">
              <dt className="shrink-0 text-stone-500 dark:text-stone-400">Équipement</dt>
              <dd className="text-right font-medium">{school.equipment_type}</dd>
            </div>
          )}
          {school.installation_year !== null && (
            <div className="flex items-start justify-between gap-3">
              <dt className="shrink-0 text-stone-500 dark:text-stone-400">Installé en</dt>
              <dd className="text-right font-medium tabular-nums">{school.installation_year}</dd>
            </div>
          )}
          {school.contact_phone !== null && school.contact_phone !== '' && (
            <div className="flex items-start justify-between gap-3">
              <dt className="shrink-0 text-stone-500 dark:text-stone-400">Contact</dt>
              <dd className="text-right font-medium font-mono">{school.contact_phone}</dd>
            </div>
          )}
        </dl>
      )}

      <div className="mt-4">
        <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-faint">
          Incidents ouverts ({fmtInt(openCount)})
        </p>
        {open.length === 0 ? (
          <p className="mt-2 text-sm text-stone-600 dark:text-stone-400">Aucun incident ouvert pour cette école.</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {open.map((inc) => (
              <li key={inc.id}>
                <button
                  type="button"
                  onClick={() => onDetail('incident', inc.id)}
                  title="Voir le détail de l'incident"
                  className="flex w-full items-center gap-2.5 rounded-xl border border-line bg-card px-3 py-2.5 text-left transition-[border-color,transform] duration-150 ease-snap hover:border-accent active:scale-[0.99] motion-reduce:transition-none motion-reduce:active:scale-100"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{inc.title}</span>
                    <span className="mt-1 flex flex-wrap items-center gap-1.5">
                      <Badge tone={urgencyTone(inc.urgency)}>
                        {URGENCY_FR[inc.urgency] ?? inc.urgency}
                      </Badge>
                      <span className="font-mono text-[11px] text-stone-500 dark:text-stone-400">
                        {inc.reference_code} · {fmtInt(inc.affected_students)} élèves
                      </span>
                    </span>
                  </span>
                  <Icon name="arrow-right" className="h-4 w-4 shrink-0 text-stone-400" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {onAsk !== undefined && (
        <Button size="sm" onClick={() => onAsk(`Analyse ${school.name} ?`)} className="mt-4">
          <Icon name="chat" className="h-3.5 w-3.5" />
          Analyser dans le chat
        </Button>
      )}
    </div>
  );
}

// ---------- Tiroir ----------

function SlidePanel({
  label,
  onClose,
  closeRef,
  children,
}: {
  label: string;
  onClose: () => void;
  closeRef: RefObject<HTMLButtonElement | null>;
  children: ReactNode;
}) {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const frame = window.requestAnimationFrame(() => setShown(true));
    return () => window.cancelAnimationFrame(frame);
  }, []);
  return (
    <aside
      className={`absolute right-0 top-0 flex h-full w-full flex-col bg-canvas shadow-2xl transition-transform duration-300 ease-drawer motion-reduce:transition-none sm:max-w-md ${
        shown ? 'translate-x-0' : 'translate-x-full'
      }`}
    >
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
        <p className="font-display text-sm font-bold tracking-tight text-ink-soft">{label}</p>
        <button
          ref={closeRef}
          type="button"
          onClick={onClose}
          aria-label="Fermer"
          className="flex h-9 w-9 items-center justify-center rounded-full text-ink-soft transition-[transform,color] duration-150 ease-snap hover:bg-raised hover:text-ink active:scale-95 motion-reduce:transition-none motion-reduce:active:scale-100"
        >
          <Icon name="x" className="h-5 w-5" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-5">{children}</div>
    </aside>
  );
}

export function DetailDrawer({
  detail,
  onClose,
  onDetail,
  onAsk,
}: {
  detail: DetailTarget | null;
  onClose: () => void;
  onDetail: (kind: DetailKind, id: number) => void;
  onAsk?: (q: string) => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (detail === null) return;
    closeRef.current?.focus();
  }, [detail]);

  useEffect(() => {
    if (detail === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = prev;
    };
  }, [detail, onClose]);

  if (detail === null) return null;

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Détail">
      <button
        type="button"
        aria-label="Fermer le panneau"
        onClick={onClose}
        className="absolute inset-0 h-full w-full cursor-default bg-stone-950/45 backdrop-blur-[2px]"
      />
      <SlidePanel
        key={`${detail.kind}-${detail.id}`}
        label={detail.kind === 'incident' ? 'Détail incident' : "Détail école"}
        onClose={onClose}
        closeRef={closeRef}
      >
        <DetailContent key={`${detail.kind}-${detail.id}`} detail={detail} onDetail={onDetail} onAsk={onAsk} />
      </SlidePanel>
    </div>
  );
}

type ContentState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'incident'; incident: Incident }
  | { status: 'school'; school: School };

function DetailContent({
  detail,
  onDetail,
  onAsk,
}: {
  detail: DetailTarget;
  onDetail: (kind: DetailKind, id: number) => void;
  onAsk?: (q: string) => void;
}) {
  const [attempt, setAttempt] = useState(0);
  return (
    <DetailFetch
      key={attempt}
      detail={detail}
      onDetail={onDetail}
      onAsk={onAsk}
      onRetry={() => setAttempt((a) => a + 1)}
    />
  );
}

function DetailFetch({
  detail,
  onDetail,
  onAsk,
  onRetry,
}: {
  detail: DetailTarget;
  onDetail: (kind: DetailKind, id: number) => void;
  onAsk?: (q: string) => void;
  onRetry: () => void;
}) {
  const [state, setState] = useState<ContentState>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        if (detail.kind === 'incident') {
          const res = await api.incident(detail.id);
          if (!cancelled) setState({ status: 'incident', incident: res.incident });
        } else {
          const school = await api.school(detail.id);
          if (!cancelled) setState({ status: 'school', school });
        }
      } catch (e) {
        if (!cancelled) {
          setState({
            status: 'error',
            message: e instanceof ApiError ? e.message : 'Détail indisponible.',
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [detail]);

  if (state.status === 'loading') return <DrawerSkeleton />;
  if (state.status === 'error') {
    return (
      <div className="rounded-xl border border-danger/30 bg-danger-soft px-4 py-6 text-center">
        <p className="text-sm font-medium text-danger">{state.message}</p>
        <Button size="sm" onClick={onRetry} className="mt-3">
          Réessayer
        </Button>
      </div>
    );
  }
  if (state.status === 'incident') {
    return <IncidentView incident={state.incident} onDetail={onDetail} onAsk={onAsk} />;
  }
  return <SchoolView school={state.school} onDetail={onDetail} onAsk={onAsk} />;
}
