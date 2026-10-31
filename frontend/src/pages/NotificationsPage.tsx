import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { AppNotification } from '../lib/api';
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton, StatusDot } from '../components/ui';
import { ErrorBanner, Pager, Pretty } from '../components/crud';
import { DetailDrawer } from '../components/DetailDrawer';
import type { DetailTarget } from '../components/DetailDrawer';
import { URGENCY_FR, fmtNum, urgencyTone } from '../lib/wash';

// Forme réelle de `data` (lecture seule backend) — seule classe existante :
// CriticalIncidentNotification::toArray() = { incident_id, reference_code, school,
// district, title, urgency, priority_score, affected_students, ai_summary }.

const errMsg = (e: unknown): string => (e instanceof ApiError ? e.message : 'Erreur réseau.');
const shortType = (t: string): string => t.split('\\').pop() ?? t;
const str = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null);
const num = (v: unknown): number | null =>
  typeof v === 'number' && Number.isFinite(v) ? v : null;

/** Temps relatif en français, ex. « il y a 2 h ». */
const timeAgo = (iso: string): string => {
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return 'à l\u2019instant';
  const min = Math.floor(ms / 60000);
  if (min < 1) return 'à l\u2019instant';
  if (min < 60) return `il y a ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `il y a ${h} h`;
  const d = Math.floor(h / 24);
  if (d < 30) return `il y a ${d} j`;
  const mo = Math.floor(d / 30);
  if (mo < 12) return `il y a ${mo} mois`;
  return `il y a ${Math.floor(mo / 12)} an${mo >= 24 ? 's' : ''}`;
};

const fullDate = (iso: string): string => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString('fr-FR', { dateStyle: 'full', timeStyle: 'short' });
};

const byNewest = (a: AppNotification, b: AppNotification): number =>
  new Date(b.created_at).getTime() - new Date(a.created_at).getTime();

export default function NotificationsPage() {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
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
      const res = await api.notifications({ unread: unreadOnly ? 1 : undefined, page });
      // Écarts backend (WashNotificationController::index, non modifié) :
      // - aucun tri garanti → tri client par date décroissante sur la page chargée ;
      // - ?unread ignoré → repli client sur read_at quand le toggle est actif.
      const sorted = [...res.data].sort(byNewest);
      setItems(unreadOnly ? sorted.filter((n) => !n.read_at) : sorted);
      setTotal(res.total);
      setLastPage(res.last_page);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, [page, unreadOnly]);

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
      setError(errMsg(e));
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
      setError(errMsg(e));
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
            ? `${fmtNum(items.length)} non lue(s) affichée(s) — ${fmtNum(total)} au total.`
            : `${fmtNum(unreadOnPage)} non lue(s) sur cette page — ${fmtNum(total)} au total.`
        }
        actions={
          <Button disabled={busy || (unreadOnly ? items.length === 0 : unreadOnPage === 0)} onClick={() => void markAll()}>
            Tout marquer comme lu
          </Button>
        }
      />
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label className="inline-flex cursor-pointer items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={unreadOnly}
            onChange={(e) => {
              setPage(1);
              setUnreadOnly(e.target.checked);
            }}
            className="h-4 w-4 accent-teal-700"
          />
          Non lues uniquement
        </label>
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
            title={unreadOnly ? 'Aucune notification non lue' : 'Aucune notification'}
            description={
              unreadOnly
                ? 'Tout est lu. Décochez le filtre pour revoir l\u2019historique.'
                : 'Rien à signaler pour le moment.'
            }
            action={
              unreadOnly ? (
                <Button size="sm" onClick={() => setUnreadOnly(false)}>
                  Voir tout l'historique
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
                      {title ?? (hasData ? 'Incident critique' : shortType(n.type))}
                    </p>
                    <span className="font-mono text-xs text-ink-faint" title={fullDate(n.created_at)}>
                      {timeAgo(n.created_at)}
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
                      Détails indisponibles pour cette notification.
                    </p>
                  )}
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    {urgency && <Badge tone={urgencyTone(urgency)}>{URGENCY_FR[urgency] ?? urgency}</Badge>}
                    {affected !== null && (
                      <span className="font-mono text-xs text-ink-faint">
                        {fmtNum(affected)} élèves
                      </span>
                    )}
                    {score !== null && (
                      <span className="font-mono text-xs text-ink-faint">
                        Priorité {fmtNum(Math.round(score))}/100
                      </span>
                    )}
                  </div>
                  {hasData && (
                    <details className="mt-1">
                      <summary className="cursor-pointer text-xs text-ink-soft">Détails bruts</summary>
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
                      Voir l'incident
                    </Button>
                  )}
                  {!n.read_at && (
                    <Button size="sm" variant="ghost" disabled={rowBusy} onClick={() => void markRead(n.id)}>
                      {rowBusy ? '…' : 'Marquer lu'}
                    </Button>
                  )}
                </div>
              </div>
            </Card>
          );
        })}
      </div>
      <Pager page={page} lastPage={lastPage} onPage={setPage} />

      <DetailDrawer
        detail={detail}
        onClose={() => setDetail(null)}
        onDetail={(kind, id) => setDetail({ kind, id })}
      />
    </div>
  );
}
