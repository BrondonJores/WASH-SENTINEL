import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { AppNotification } from '../lib/api';
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton, StatusDot } from '../components/ui';
import { ErrorBanner, Pager, Pretty } from '../components/crud';
import { Toggle } from '../components/controls';
import { DetailDrawer } from '../components/DetailDrawer';
import type { DetailTarget } from '../components/DetailDrawer';
import { URGENCY_EN, URGENCY_FR, fmtNum, urgencyTone } from '../lib/wash';
import { localeFor } from '../lib/locale';
import { pick, useUILang } from '../lib/i18n';
import { DEFAULT_PER_PAGE } from '../lib/pagination';

// Forme réelle de `data` (lecture seule backend) — seule classe existante :
// CriticalIncidentNotification::toArray() = { incident_id, reference_code, school,
// district, title, urgency, priority_score, affected_students, ai_summary }.

const errMsg = (e: unknown, lang?: string): string =>
  (e instanceof ApiError ? e.message : pick(lang, 'Erreur réseau.', 'Network error.'));
const shortType = (t: string): string => t.split('\\').pop() ?? t;
const str = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null);
const num = (v: unknown): number | null =>
  typeof v === 'number' && Number.isFinite(v) ? v : null;

/** Temps relatif, ex. « il y a 2 h » / « 2 h ago ». */
const timeAgo = (iso: string, lang: string | undefined): string => {
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return pick(lang, 'à l\u2019instant', 'just now');
  const min = Math.floor(ms / 60000);
  if (min < 1) return pick(lang, 'à l\u2019instant', 'just now');
  if (min < 60) return pick(lang, `il y a ${min} min`, `${min} min ago`);
  const h = Math.floor(min / 60);
  if (h < 24) return pick(lang, `il y a ${h} h`, `${h} h ago`);
  const d = Math.floor(h / 24);
  if (d < 30) return pick(lang, `il y a ${d} j`, `${d} d ago`);
  const mo = Math.floor(d / 30);
  if (mo < 12) return pick(lang, `il y a ${mo} mois`, `${mo} mo ago`);
  return pick(lang, `il y a ${Math.floor(mo / 12)} an${mo >= 24 ? 's' : ''}`, `${Math.floor(mo / 12)} yr ago`);
};

const fullDate = (iso: string, lang: string | undefined): string => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(localeFor(lang), { dateStyle: 'full', timeStyle: 'short' });
};

const byNewest = (a: AppNotification, b: AppNotification): number =>
  new Date(b.created_at).getTime() - new Date(a.created_at).getTime();

export default function NotificationsPage() {
  const ui = useUILang();
  const [items, setItems] = useState<AppNotification[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(DEFAULT_PER_PAGE);
  const [lastPage, setLastPage] = useState(1);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DetailTarget | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.notifications({
        unread: unreadOnly ? 1 : undefined,
        page,
        per_page: perPage,
      });
      // Écarts backend (WashNotificationController::index, non modifié) :
      // - aucun tri garanti → tri client par date décroissante sur la page chargée ;
      // - ?unread ignoré → repli client sur read_at quand le toggle est actif.
      const sorted = [...res.data].sort(byNewest);
      setItems(unreadOnly ? sorted.filter((n) => !n.read_at) : sorted);
      setTotal(res.total);
      setLastPage(res.last_page);
    } catch (e) {
      setError(errMsg(e, ui));
    } finally {
      setLoading(false);
    }
  }, [page, perPage, unreadOnly, ui]);

  useEffect(() => {
    void load();
  }, [load]);

  const markRead = async (id: string) => {
    if (busyId) return;
    setBusyId(id);
    try {
      await api.readNotification(id);
      if (unreadOnly) {
        setItems((prev) => prev.filter((n) => n.id !== id));
        setTotal((t) => Math.max(0, t - 1));
      } else {
        setItems((prev) =>
          prev.map((n) => (n.id === id ? { ...n, read_at: new Date().toISOString() } : n)),
        );
      }
    } catch (e) {
      setError(errMsg(e, ui));
    } finally {
      setBusyId(null);
    }
  };

  const markAll = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.readAllNotifications();
      if (page !== 1) {
        setPage(1);
      } else {
        await load();
      }
    } catch (e) {
      setError(errMsg(e, ui));
    } finally {
      setBusy(false);
    }
  };

  const unreadOnPage = items.filter((n) => !n.read_at).length;

  return (
    <div className="mx-auto w-full max-w-6xl">
      <PageHeader
        title="Notifications"
        description={
          unreadOnly
            ? pick(ui, `${fmtNum(items.length)} non lue(s) affichée(s) — ${fmtNum(total)} au total.`, `${fmtNum(items.length)} unread shown — ${fmtNum(total)} in total.`)
            : pick(ui, `${fmtNum(unreadOnPage)} non lue(s) sur cette page — ${fmtNum(total)} au total.`, `${fmtNum(unreadOnPage)} unread on this page — ${fmtNum(total)} in total.`)
        }
        actions={
          <Button disabled={busy || (unreadOnly ? items.length === 0 : unreadOnPage === 0)} onClick={() => void markAll()}>
            {pick(ui, 'Tout marquer comme lu', 'Mark all as read')}
          </Button>
        }
      />
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Toggle
          checked={unreadOnly}
          label={pick(ui, 'Non lues uniquement', 'Unread only')}
          onChange={(v) => {
            setPage(1);
            setUnreadOnly(v);
          }}
        />
      </div>

      {loading && items.length === 0 && (
        <div className="space-y-2">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      )}
      {!loading && items.length === 0 && (
        <Card>
          <EmptyState
            icon={unreadOnly ? 'check' : 'bell'}
            title={unreadOnly ? pick(ui, 'Aucune notification non lue', 'No unread notifications') : pick(ui, 'Aucune notification', 'No notifications')}
            description={
              unreadOnly
                ? pick(ui, 'Tout est lu. Décochez le filtre pour revoir l\u2019historique.', 'All caught up. Uncheck the filter to see history again.')
                : pick(ui, 'Rien à signaler pour le moment.', 'Nothing to report right now.')
            }
            action={
              unreadOnly ? (
                <Button size="sm" onClick={() => setUnreadOnly(false)}>
                  {pick(ui, "Voir tout l'historique", 'See full history')}
                </Button>
              ) : undefined
            }
          />
        </Card>
      )}
      <div className="space-y-2">
        {items.map((n) => {
          const data = n.data ?? {};
          const incidentId = num(data.incident_id);
          const reference = str(data.reference_code);
          const school = str(data.school);
          const district = str(data.district);
          const title = str(data.title) ?? str(data.message);
          const urgency = str(data.urgency);
          const summary = str(data.ai_summary);
          const affected = num(data.affected_students);
          const score = num(data.priority_score);
          const hasData = Object.keys(data).length > 0;
          const rowBusy = busyId === n.id;

          return (
            <Card key={n.id} className="p-3">
              <div className="flex items-start gap-3">
                <span className="mt-1.5">
                  <StatusDot tone={n.read_at ? 'idle' : 'live'} pulse={!n.read_at} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-semibold">
                      {title ?? (hasData ? pick(ui, 'Incident critique', 'Critical incident') : shortType(n.type))}
                    </p>
                    <span className="font-mono text-xs text-ink-faint" title={fullDate(n.created_at, ui)}>
                      {timeAgo(n.created_at, ui)}
                    </span>
                  </div>
                  <p className="mt-0.5 font-mono text-xs text-ink-faint">
                    {[reference, school, district].filter(Boolean).join(' · ') || shortType(n.type)}
                  </p>
                  {summary && (
                    <p className="mt-1 line-clamp-2 text-sm text-ink-soft">{summary}</p>
                  )}
                  {!hasData && (
                    <p className="mt-1 text-sm text-ink-faint">
                      {pick(ui, 'Détails indisponibles pour cette notification.', 'Details unavailable for this notification.')}
                    </p>
                  )}
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    {urgency && <Badge tone={urgencyTone(urgency)}>{(ui === 'en' ? URGENCY_EN : URGENCY_FR)[urgency] ?? urgency}</Badge>}
                    {affected !== null && (
                      <span className="font-mono text-xs text-ink-faint">
                        {pick(ui, `${fmtNum(affected)} élèves`, `${fmtNum(affected)} students`)}
                      </span>
                    )}
                    {score !== null && (
                      <span className="font-mono text-xs text-ink-faint">
                        {pick(ui, `Priorité ${fmtNum(Math.round(score))}/100`, `Priority ${fmtNum(Math.round(score))}/100`)}
                      </span>
                    )}
                  </div>
                  {hasData && (
                    <details className="mt-1">
                      <summary className="cursor-pointer text-xs text-ink-soft">{pick(ui, 'Détails bruts', 'Raw details')}</summary>
                      <div className="mt-1">
                        <Pretty data={n.data} />
                      </div>
                    </details>
                  )}
                </div>
                <div className="flex shrink-0 flex-col gap-2">
                  {incidentId !== null && (
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => setDetail({ kind: 'incident', id: incidentId })}
                    >
                      {pick(ui, "Voir l'incident", 'See incident')}
                    </Button>
                  )}
                  {!n.read_at && (
                    <Button size="sm" variant="ghost" disabled={rowBusy} onClick={() => void markRead(n.id)}>
                      {rowBusy ? '…' : pick(ui, 'Marquer lu', 'Mark read')}
                    </Button>
                  )}
                </div>
              </div>
            </Card>
          );
        })}
      </div>
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

      <DetailDrawer
        detail={detail}
        onClose={() => setDetail(null)}
        onDetail={(kind, id) => setDetail({ kind, id })}
        lang={ui}
      />
    </div>
  );
}
