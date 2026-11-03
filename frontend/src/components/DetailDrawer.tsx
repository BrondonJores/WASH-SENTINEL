import { useEffect, useRef, useState } from 'react';
import type { ReactNode, RefObject } from 'react';
import { api, ApiError } from '../lib/api';
import type { Incident, School } from '../lib/api';
import { localeFor } from '../lib/locale';
import { STATUS_EN, STATUS_FR, URGENCY_EN, URGENCY_FR, urgencyTone } from '../lib/wash';
import { Badge, Button, Skeleton } from './ui';
import { Icon } from './icons';

export type DetailKind = 'incident' | 'school';
export type DetailTarget = { kind: DetailKind; id: number };

// ---------- Helpers ----------

const fmtInt = (v: unknown, lang?: string): string => {
  if (typeof v === 'number' && Number.isFinite(v)) return new Intl.NumberFormat(localeFor(lang)).format(Math.round(v));
  return '—';
};

const fmtDate = (v: unknown, lang?: string): string => {
  if (typeof v !== 'string' || v === '') return '—';
  const d = new Date(v);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleDateString(localeFor(lang), { day: 'numeric', month: 'short', year: 'numeric' });
};

const fmtMoney = (v: number | null, currency: string | null, lang?: string): string =>
  v === null ? '—' : `${fmtInt(v, lang)}${currency ? ` ${currency}` : ''}`;

// DIVERGENCE volontaire conservée : 'Évacuation' (court, badge) vs
// CATEGORY_FR 'Évacuation / drainage' de lib/wash.ts — rendu identique exigé.
const CATEGORY_LABEL: Record<string, string> = {
  water_point: "Point d'eau",
  toilets_latrines: 'Toilettes / latrines',
  handwashing: 'Lavage des mains',
  sewage_drainage: 'Évacuation',
};
// Jumeau EN court ('Drainage'), miroir de la divergence volontaire ci-dessus.
const CATEGORY_LABEL_EN: Record<string, string> = {
  water_point: 'Water point',
  toilets_latrines: 'Toilets / latrines',
  handwashing: 'Handwashing',
  sewage_drainage: 'Drainage',
};

/** Report sérialisé : le backend ajoute photo_url absolue (null si vide/manquante). */
type ReportWithPhotoUrl = Report & { photo_url?: string | null };

/** Borne d'affichage, miroir de WashAgentController::INCIDENT_PHOTOS_LIMIT. */
const INCIDENT_PHOTOS_LIMIT = 4;

function Stat({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <p className="text-[11px] text-stone-500 dark:text-stone-400">{label}</p>
      <p className={`mt-0.5 text-sm font-semibold tabular-nums ${mono ? 'font-mono' : ''}`}>{value}</p>
    </div>
  );
}

function DrawerSkeleton({ lang }: { lang?: string }) {
  return (
    <div className="space-y-3" aria-label={lang === 'en' ? 'Loading details' : 'Chargement du détail'}>
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
  lang,
}: {
  incident: Incident;
  onDetail: (kind: DetailKind, id: number) => void;
  onAsk?: (q: string) => void;
  lang?: string;
}) {
  const en = lang === 'en';
  const urgencyLabel = en ? URGENCY_EN : URGENCY_FR;
  const statusLabel = en ? STATUS_EN : STATUS_FR;
  const categoryLabel = en ? CATEGORY_LABEL_EN : CATEGORY_LABEL;
  const schoolName = incident.school?.name ?? (en ? `School #${incident.school_id}` : `École #${incident.school_id}`);
  const district = incident.school?.district;
  const reportsCount = incident.reports_count ?? incident.reports?.length ?? 0;
  const logs = incident.maintenance_logs ?? [];
  const photos = ((incident.reports ?? []) as ReportWithPhotoUrl[])
    .map((r) => (typeof r.photo_url === 'string' && r.photo_url !== '' ? r.photo_url : null))
    .filter((u): u is string => u !== null)
    .slice(0, INCIDENT_PHOTOS_LIMIT);
  return (
    <div>
      <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-teal-700 dark:text-teal-300">
        Incident · {incident.reference_code}
      </p>
      <h2 className="mt-1 font-display text-xl font-bold leading-snug tracking-tight">{incident.title}</h2>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Badge tone={urgencyTone(incident.urgency)}>
          {en ? `${urgencyLabel[incident.urgency] ?? incident.urgency} urgency` : `Urgence ${urgencyLabel[incident.urgency] ?? incident.urgency}`}
        </Badge>
        <Badge>{statusLabel[incident.status] ?? incident.status}</Badge>
        <Badge tone="info">{categoryLabel[incident.category] ?? incident.category}</Badge>
      </div>

      <button
        type="button"
        onClick={() => onDetail('school', incident.school_id)}
        title={en ? 'View school details' : "Voir le détail de l'école"}
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

      {photos.length > 0 && (
        <div className="mt-3">
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-faint">
            Photos ({photos.length})
          </p>
          <div className="mt-1.5 flex gap-2 overflow-x-auto pb-1">
            {photos.map((url, i) => (
              <a
                key={`${url}-${i}`}
                href={url}
                target="_blank"
                rel="noreferrer"
                title={incident.title}
                aria-label={en ? `Open photo ${i + 1} of ${incident.title} in a new tab` : `Ouvrir la photo ${i + 1} de ${incident.title} dans un nouvel onglet`}
                className="shrink-0 overflow-hidden rounded-lg border border-line transition-[border-color,transform] duration-150 ease-snap hover:border-accent active:scale-[0.97] motion-reduce:transition-none motion-reduce:active:scale-100"
              >
                <img
                  src={url}
                  alt={en ? `Photo ${i + 1} of ${incident.title}` : `Photo ${i + 1} de ${incident.title}`}
                  loading="lazy"
                  className="h-16 w-16 object-cover"
                />
              </a>
            ))}
          </div>
        </div>
      )}

      <div className="mt-4 grid grid-cols-2 gap-3">
        <Stat label={en ? 'Affected pupils' : 'Élèves affectés'} value={fmtInt(incident.affected_students, lang)} />
        <Stat label={en ? 'AI priority' : 'Priorité IA'} value={fmtInt(incident.priority_score, lang)} />
        <Stat label={en ? 'Reports' : 'Signalements'} value={fmtInt(reportsCount, lang)} />
        <Stat label={en ? 'Assigned to' : 'Assigné à'} value={incident.assignee?.name ?? (en ? 'Unassigned' : 'Personne')} mono={false} />
        <Stat label={en ? 'Reported on' : 'Signalé le'} value={fmtDate(incident.created_at, lang)} mono={false} />
        <Stat label={en ? 'Resolved on' : 'Résolu le'} value={incident.resolved_at ? fmtDate(incident.resolved_at, lang) : '—'} mono={false} />
      </div>

      {incident.issue_type !== null && incident.issue_type !== '' && (
        <p className="mt-3 text-sm">
          <span className="text-stone-500 dark:text-stone-400">{en ? 'Breakdown type: ' : 'Type de panne : '}</span>
          <span className="font-medium">{incident.issue_type}</span>
        </p>
      )}
      {incident.health_hazard !== null && incident.health_hazard !== '' && (
        <p className="mt-1 text-sm">
          <span className="text-stone-500 dark:text-stone-400">{en ? 'Health risk: ' : 'Risque sanitaire : '}</span>
          <span className="font-medium">{incident.health_hazard}</span>
        </p>
      )}

      {incident.ai_summary !== null && incident.ai_summary !== '' && (
        <div className="mt-4 rounded-xl border border-line bg-raised/60 p-3">
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-faint">{en ? 'AI summary' : 'Résumé IA'}</p>
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
                  <span className="font-medium">{fmtDate(l.repaired_at ?? l.created_at, lang)}</span>
                  <span className="font-mono text-xs tabular-nums">
{fmtMoney(l.cost_amount, l.currency, lang)}
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
          onClick={() => onAsk(en ? `Explain incident ${incident.reference_code} in simple language` : `Explique l'incident ${incident.reference_code} en langage simple`)}
          className="mt-4"
        >
          <Icon name="chat" className="h-3.5 w-3.5" />
{en ? 'Explain in chat' : 'Expliquer dans le chat'}
        </Button>
      )}
    </div>
  );
}

function SchoolView({
  school,
  onDetail,
  onAsk,
  lang,
}: {
  school: School;
  onDetail: (kind: DetailKind, id: number) => void;
  onAsk?: (q: string) => void;
  lang?: string;
}) {
  const en = lang === 'en';
  const urgencyLabel = en ? URGENCY_EN : URGENCY_FR;
  const open = school.open_incidents ?? [];
  const openCount = school.open_incidents_count ?? open.length;
  return (
    <div>
      <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-teal-700 dark:text-teal-300">
{en ? 'School' : 'École'} · {school.code}
      </p>
      <h2 className="mt-1 font-display text-xl font-bold leading-snug tracking-tight">{school.name}</h2>
      <p className="mt-1 font-mono text-xs text-stone-500 dark:text-stone-400">{school.district}</p>

      <div className="mt-4 grid grid-cols-2 gap-3">
        <Stat label={en ? 'Pupils' : 'Élèves'} value={fmtInt(school.student_count, lang)} />
        <Stat label={en ? 'Open incidents' : 'Incidents ouverts'} value={fmtInt(openCount, lang)} />
        <Stat label={en ? 'Teachers' : 'Enseignants'} value={school.teacher_count === null ? '—' : fmtInt(school.teacher_count, lang)} />
        <Stat label={en ? 'Reports' : 'Signalements'} value={school.reports_count === undefined ? '—' : fmtInt(school.reports_count, lang)} />
      </div>

      {(school.equipment_type !== null || school.installation_year !== null || school.contact_phone !== null) && (
        <dl className="mt-3 space-y-1.5 border-t border-stone-200/70 pt-3 text-sm dark:border-white/[0.06]">
          {school.equipment_type !== null && school.equipment_type !== '' && (
            <div className="flex items-start justify-between gap-3">
              <dt className="shrink-0 text-stone-500 dark:text-stone-400">{en ? 'Equipment' : 'Équipement'}</dt>
              <dd className="text-right font-medium">{school.equipment_type}</dd>
            </div>
          )}
          {school.installation_year !== null && (
            <div className="flex items-start justify-between gap-3">
              <dt className="shrink-0 text-stone-500 dark:text-stone-400">{en ? 'Installed in' : 'Installé en'}</dt>
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
{en ? 'Open incidents' : 'Incidents ouverts'} ({fmtInt(openCount, lang)})
        </p>
        {open.length === 0 ? (
          <p className="mt-2 text-sm text-stone-600 dark:text-stone-400">{en ? 'No open incidents for this school.' : 'Aucun incident ouvert pour cette école.'}</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {open.map((inc) => (
              <li key={inc.id}>
                <button
                  type="button"
                  onClick={() => onDetail('incident', inc.id)}
                  title={en ? 'View incident details' : "Voir le détail de l'incident"}
                  className="flex w-full items-center gap-2.5 rounded-xl border border-line bg-card px-3 py-2.5 text-left transition-[border-color,transform] duration-150 ease-snap hover:border-accent active:scale-[0.99] motion-reduce:transition-none motion-reduce:active:scale-100"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{inc.title}</span>
                    <span className="mt-1 flex flex-wrap items-center gap-1.5">
                      <Badge tone={urgencyTone(inc.urgency)}>
                        {urgencyLabel[inc.urgency] ?? inc.urgency}
                      </Badge>
                      <span className="font-mono text-[11px] text-stone-500 dark:text-stone-400">
{inc.reference_code} · {fmtInt(inc.affected_students, lang)} {en ? 'pupils' : 'élèves'}
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
        <Button size="sm" onClick={() => onAsk(en ? `Analyze ${school.name}?` : `Analyse ${school.name} ?`)} className="mt-4">
          <Icon name="chat" className="h-3.5 w-3.5" />
          {en ? 'Analyze in chat' : 'Analyser dans le chat'}
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
  lang,
}: {
  label: string;
  onClose: () => void;
  closeRef: RefObject<HTMLButtonElement | null>;
  children: ReactNode;
  lang?: string;
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
          aria-label={lang === 'en' ? 'Close' : 'Fermer'}
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
  lang,
}: {
  detail: DetailTarget | null;
  onClose: () => void;
  onDetail: (kind: DetailKind, id: number) => void;
  onAsk?: (q: string) => void;
  lang?: string;
}) {
  const en = lang === 'en';
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
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label={en ? 'Details' : 'Détail'}>
      <button
        type="button"
        aria-label={en ? 'Close panel' : 'Fermer le panneau'}
        onClick={onClose}
        className="absolute inset-0 h-full w-full cursor-default bg-stone-950/45 backdrop-blur-[2px]"
      />
      <SlidePanel
        key={`${detail.kind}-${detail.id}`}
        label={detail.kind === 'incident' ? (en ? 'Incident details' : 'Détail incident') : en ? 'School details' : "Détail école"}
        onClose={onClose}
        closeRef={closeRef}
        lang={lang}
      >
        <DetailContent key={`${detail.kind}-${detail.id}`} detail={detail} onDetail={onDetail} onAsk={onAsk} lang={lang} />
      </SlidePanel>
    </div>
  );
}

type ContentState =
  | { status: 'loading' }
  | { status: 'error'; message: string | null }
  | { status: 'incident'; incident: Incident }
  | { status: 'school'; school: School };

function DetailContent({
  detail,
  onDetail,
  onAsk,
  lang,
}: {
  detail: DetailTarget;
  onDetail: (kind: DetailKind, id: number) => void;
  onAsk?: (q: string) => void;
  lang?: string;
}) {
  const [attempt, setAttempt] = useState(0);
  return (
    <DetailFetch
      key={attempt}
      detail={detail}
      onDetail={onDetail}
      onAsk={onAsk}
      onRetry={() => setAttempt((a) => a + 1)}
      lang={lang}
    />
  );
}

function DetailFetch({
  detail,
  onDetail,
  onAsk,
  onRetry,
  lang,
}: {
  detail: DetailTarget;
  onDetail: (kind: DetailKind, id: number) => void;
  onAsk?: (q: string) => void;
  onRetry: () => void;
  lang?: string;
}) {
  const en = lang === 'en';
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
            message: e instanceof ApiError ? e.message : null,
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [detail]);

  if (state.status === 'loading') return <DrawerSkeleton lang={lang} />;
  if (state.status === 'error') {
    return (
      <div className="rounded-xl border border-danger/30 bg-danger-soft px-4 py-6 text-center">
        <p className="text-sm font-medium text-danger">{state.message ?? (en ? 'Details unavailable.' : 'Détail indisponible.')}</p>
        <Button size="sm" onClick={onRetry} className="mt-3">
{en ? 'Retry' : 'Réessayer'}
        </Button>
      </div>
    );
  }
  if (state.status === 'incident') {
    return <IncidentView incident={state.incident} onDetail={onDetail} onAsk={onAsk} lang={lang} />;
  }
  return <SchoolView school={state.school} onDetail={onDetail} onAsk={onAsk} lang={lang} />;
}
