import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { AppNotification } from '../lib/api';
import { Button, Card, EmptyState, PageHeader, Skeleton, StatusDot } from '../components/ui';
import { ErrorBanner, Pretty } from '../components/crud';
import { fmtDate, fmtNum } from '../lib/wash';

const errMsg = (e: unknown): string => (e instanceof ApiError ? e.message : 'Erreur réseau.');
const shortType = (t: string): string => t.split('\\').pop() ?? t;
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);

export default function NotificationsPage() {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.notifications();
      setItems(res.data);
      setTotal(res.total);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const markRead = async (id: string) => {
    try {
      await api.readNotification(id);
      setItems((prev) => prev.map((n) => (n.id === id ? { ...n, read_at: new Date().toISOString() } : n)));
    } catch (e) {
      setError(errMsg(e));
    }
  };

  const markAll = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.readAllNotifications();
      await load();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const unread = items.filter((n) => !n.read_at).length;

  return (
    <div className="mx-auto w-full max-w-6xl">
      <PageHeader
        title="Notifications"
        description={`${fmtNum(unread)} non lue(s) — ${fmtNum(total)} au total (20 dernières).`}
        actions={
          <Button disabled={busy || unread === 0} onClick={() => void markAll()}>
            Tout marquer comme lu
          </Button>
        }
      />
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {loading && items.length === 0 && (
        <div className="space-y-2">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      )}
      {!loading && items.length === 0 && (
        <Card>
          <EmptyState icon="bell" title="Aucune notification" description="Rien à signaler pour le moment." />
        </Card>
      )}
      <div className="space-y-2">
        {items.map((n) => (
          <Card key={n.id} className="p-3">
            <div className="flex items-start gap-3">
              <span className="mt-1.5">
                <StatusDot tone={n.read_at ? 'idle' : 'live'} pulse={!n.read_at} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold">
                    {str(n.data.title) ?? str(n.data.message) ?? shortType(n.type)}
                  </p>
                  <span className="font-mono text-xs text-ink-faint">{fmtDate(n.created_at)}</span>
                </div>
                <p className="mt-0.5 font-mono text-xs text-ink-faint">{shortType(n.type)}</p>
                <details className="mt-1">
                  <summary className="cursor-pointer text-xs text-ink-soft">Détails bruts</summary>
                  <div className="mt-1">
                    <Pretty data={n.data} />
                  </div>
                </details>
              </div>
              {!n.read_at && (
                <Button size="sm" onClick={() => void markRead(n.id)}>
                  Marquer lue
                </Button>
              )}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
