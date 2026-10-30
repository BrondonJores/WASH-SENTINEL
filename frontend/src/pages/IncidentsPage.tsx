import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { AssignableUser, Incident } from '../lib/api';
import { useAuth } from '../auth/AuthContext';
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton } from '../components/ui';
import { ErrorBanner, Field, Pager } from '../components/crud';
import {
  CATEGORY_FR,
  INPUT_CLS,
  STATUS_FR,
  URGENCY_FR,
  fmtDate,
  fmtNum,
  statusTone,
  urgencyTone,
} from '../lib/wash';

const errMsg = (e: unknown): string => (e instanceof ApiError ? e.message : 'Erreur réseau.');

const STATUSES = ['reported', 'triaged', 'assigned', 'in_progress', 'resolved', 'closed'];
const URGENCIES = ['low', 'medium', 'high', 'critical'];

export default function IncidentsPage() {
  const { user } = useAuth();
  const admin = user?.roles.includes('wash_admin') ?? false;
  const agent = admin || (user?.roles.includes('maintenance_agent') ?? false);

  const [items, setItems] = useState<Incident[]>([]);
  const [page, setPage] = useState(1);
  const [lastPage, setLastPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusF, setStatusF] = useState('');
  const [urgencyF, setUrgencyF] = useState('');

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<Incident | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [users, setUsers] = useState<AssignableUser[]>([]);

  const [statusV, setStatusV] = useState('');
  const [assignV, setAssignV] = useState('');
  const [scoreV, setScoreV] = useState('');
  const [scoreUrgencyV, setScoreUrgencyV] = useState('');
  const [logCost, setLogCost] = useState('');
  const [logDays, setLogDays] = useState('');
  const [logNotes, setLogNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.incidents({
        page,
        status: statusF || undefined,
        urgency: urgencyF || undefined,
      });
      setItems(res.data);
      setLastPage(res.last_page);
      setTotal(res.total);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, [page, statusF, urgencyF]);

  useEffect(() => {
    void load();
  }, [load]);

  const select = useCallback(
    async (id: number) => {
      setSelectedId(id);
      setDetailLoading(true);
      setMsg(null);
      try {
        const res = await api.incident(id);
        setDetail(res.incident);
        setStatusV(res.incident.status);
        setScoreV(String(res.incident.priority_score));
        setScoreUrgencyV(res.incident.urgency);
        if (admin) {
          try {
            setUsers(await api.assignableUsers());
          } catch {
            setUsers([]);
          }
        }
      } catch (e) {
        setDetail(null);
        setMsg(errMsg(e));
      } finally {
        setDetailLoading(false);
      }
    },
    [admin],
  );

  const runAction = async (fn: () => Promise<{ message: string }>) => {
    if (!detail || busy) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await fn();
      setMsg(res.message);
      await select(detail.id);
      await load();
    } catch (e) {
      setMsg(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-6xl">
      <PageHeader
        title="Interventions"
        description={`Incidents triés par l'IA, vérifiés par l'humain — ${fmtNum(total)} au total.`}
      />
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="mb-4 flex flex-wrap gap-3">
        <label className="flex items-center gap-2 text-sm">
          <span className="text-ink-soft">Statut</span>
          <select
            value={statusF}
            onChange={(e) => {
              setStatusF(e.target.value);
              setPage(1);
            }}
            className={INPUT_CLS}
          >
            <option value="">Tous</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_FR[s]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-ink-soft">Urgence</span>
          <select
            value={urgencyF}
            onChange={(e) => {
              setUrgencyF(e.target.value);
              setPage(1);
            }}
            className={INPUT_CLS}
          >
            <option value="">Toutes</option>
            {URGENCIES.map((u) => (
              <option key={u} value={u}>
                {URGENCY_FR[u]}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-5">
        <div className="space-y-2 lg:col-span-2">
          {loading && items.length === 0 && (
            <>
              <Skeleton className="h-20" />
              <Skeleton className="h-20" />
              <Skeleton className="h-20" />
            </>
          )}
          {!loading && items.length === 0 && (
            <Card>
              <EmptyState icon="alert" title="Aucun incident" description="Aucun incident ne correspond aux filtres." />
            </Card>
          )}
          {items.map((i) => (
            <button
              key={i.id}
              onClick={() => void select(i.id)}
              className={`w-full rounded-xl border p-3 text-left transition-colors ${
                selectedId === i.id
                  ? 'border-accent bg-accent/5'
                  : 'border-line bg-card hover:bg-raised'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-ink-faint">{i.reference_code}</span>
                <span className="font-mono text-xs font-bold tabular-nums">
                  {i.priority_score.toFixed(1)}
                </span>
              </div>
              <p className="mt-1 truncate text-sm font-semibold">{i.title}</p>
              <p className="mt-0.5 truncate text-xs text-ink-soft">
                {i.school?.name ?? '—'} · {fmtNum(i.affected_students)} élèves ·{' '}
                {i.reports_count ?? 0} signalement(s)
              </p>
              <div className="mt-2 flex gap-1.5">
                <Badge tone={urgencyTone(i.urgency)}>{URGENCY_FR[i.urgency] ?? i.urgency}</Badge>
                <Badge tone={statusTone(i.status)}>{STATUS_FR[i.status] ?? i.status}</Badge>
              </div>
            </button>
          ))}
          <Pager page={page} lastPage={lastPage} onPage={setPage} />
        </div>

        <div className="lg:col-span-3">
          {detailLoading && <Skeleton className="h-64" />}
          {!detailLoading && !detail && (
            <Card>
              <EmptyState
                icon="alert"
                title="Sélectionnez un incident"
                description="Cliquez sur un incident pour voir le détail et agir."
              />
            </Card>
          )}
          {!detailLoading && detail && (
            <Card className="space-y-4 p-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={urgencyTone(detail.urgency)}>
                    {URGENCY_FR[detail.urgency] ?? detail.urgency}
                  </Badge>
                  <Badge tone={statusTone(detail.status)}>
                    {STATUS_FR[detail.status] ?? detail.status}
                  </Badge>
                  <span className="font-mono text-xs text-ink-faint">{detail.reference_code}</span>
                </div>
                <h2 className="mt-2 font-display text-lg font-bold">{detail.title}</h2>
                <p className="text-sm text-ink-soft">
                  {detail.school?.name ?? '—'} ({detail.school?.district ?? '—'}) ·{' '}
                  {CATEGORY_FR[detail.category] ?? detail.category} · {fmtNum(detail.affected_students)}{' '}
                  élèves · signalé le {fmtDate(detail.created_at)}
                </p>
                {detail.ai_summary && <p className="mt-2 text-sm">{detail.ai_summary}</p>}
                {Array.isArray(detail.ai_tags) && detail.ai_tags.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {detail.ai_tags.map((t) => (
                      <Badge key={t} tone="neutral">
                        {t}
                      </Badge>
                    ))}
                  </div>
                )}
                <p className="mt-2 text-sm text-ink-soft">
                  Assigné à : {detail.assignee?.name ?? 'personne'} · Score IA :{' '}
                  <span className="font-mono font-bold text-ink">
                    {detail.priority_score.toFixed(1)}
                  </span>
                </p>
              </div>

              <div>
                <h3 className="mb-1 text-sm font-semibold">
                  Signalements ({detail.reports?.length ?? 0})
                </h3>
                {(detail.reports?.length ?? 0) === 0 && (
                  <p className="text-sm text-ink-faint">Aucun signalement rattaché.</p>
                )}
                <ul className="space-y-1">
                  {(detail.reports ?? []).map((r) => (
                    <li key={r.id} className="truncate rounded-md bg-raised px-2 py-1 text-xs">
                      #{r.id} · {r.channel} · {r.is_duplicate ? 'doublon · ' : ''}
                      {r.raw_content.slice(0, 100)}
                    </li>
                  ))}
                </ul>
              </div>

              <div>
                <h3 className="mb-1 text-sm font-semibold">
                  Journal de maintenance ({detail.maintenance_logs?.length ?? 0})
                </h3>
                {(detail.maintenance_logs?.length ?? 0) === 0 && (
                  <p className="text-sm text-ink-faint">Aucune intervention journalisée.</p>
                )}
                <ul className="space-y-1">
                  {(detail.maintenance_logs ?? []).map((l) => (
                    <li key={l.id} className="rounded-md bg-raised px-2 py-1 text-xs">
                      {fmtNum(l.cost_amount)} {l.currency ?? 'XAF'} · {fmtDate(l.created_at)}
                      {l.notes ? ` · ${l.notes}` : ''}
                    </li>
                  ))}
                </ul>
              </div>

              {agent && (
                <div className="grid gap-3 border-t border-line pt-3 sm:grid-cols-2">
                  <Field label="Changer le statut">
                    <div className="flex gap-2">
                      <select
                        value={statusV}
                        onChange={(e) => setStatusV(e.target.value)}
                        className={INPUT_CLS}
                        disabled={busy}
                      >
                        {STATUSES.map((s) => (
                          <option key={s} value={s}>
                            {STATUS_FR[s]}
                          </option>
                        ))}
                      </select>
                      <Button
                        size="sm"
                        variant="primary"
                        disabled={busy}
                        onClick={() => void runAction(() => api.updateIncidentStatus(detail.id, statusV))}
                      >
                        OK
                      </Button>
                    </div>
                  </Field>
                  {admin && (
                    <Field label="Assigner à">
                      <div className="flex gap-2">
                        <select
                          value={assignV}
                          onChange={(e) => setAssignV(e.target.value)}
                          className={INPUT_CLS}
                          disabled={busy}
                        >
                          <option value="">Choisir…</option>
                          {users.map((u) => (
                            <option key={u.id} value={u.id}>
                              {u.name}
                            </option>
                          ))}
                        </select>
                        <Button
                          size="sm"
                          variant="primary"
                          disabled={busy || !assignV}
                          onClick={() =>
                            void runAction(() => api.assignIncident(detail.id, Number(assignV)))
                          }
                        >
                          OK
                        </Button>
                      </div>
                    </Field>
                  )}
                  {admin && (
                    <Field label="Forcer la priorité (score + urgence)">
                      <div className="flex gap-2">
                        <input
                          type="number"
                          min={0}
                          max={100}
                          value={scoreV}
                          onChange={(e) => setScoreV(e.target.value)}
                          className={INPUT_CLS}
                          disabled={busy}
                        />
                        <select
                          value={scoreUrgencyV}
                          onChange={(e) => setScoreUrgencyV(e.target.value)}
                          className={INPUT_CLS}
                          disabled={busy}
                        >
                          {URGENCIES.map((u) => (
                            <option key={u} value={u}>
                              {URGENCY_FR[u]}
                            </option>
                          ))}
                        </select>
                        <Button
                          size="sm"
                          variant="primary"
                          disabled={busy}
                          onClick={() =>
                            void runAction(() =>
                              api.overridePriority(detail.id, {
                                priority_score: Number(scoreV),
                                urgency: scoreUrgencyV,
                              }),
                            )
                          }
                        >
                          OK
                        </Button>
                      </div>
                    </Field>
                  )}
                  <Field label="Journaliser une intervention (coût XAF, jours, notes)">
                    <div className="flex gap-2">
                      <input
                        type="number"
                        min={0}
                        placeholder="Coût"
                        value={logCost}
                        onChange={(e) => setLogCost(e.target.value)}
                        className={INPUT_CLS}
                        disabled={busy}
                      />
                      <input
                        type="number"
                        min={0}
                        placeholder="Jours"
                        value={logDays}
                        onChange={(e) => setLogDays(e.target.value)}
                        className={INPUT_CLS}
                        disabled={busy}
                      />
                      <input
                        placeholder="Notes"
                        value={logNotes}
                        onChange={(e) => setLogNotes(e.target.value)}
                        className={INPUT_CLS}
                        disabled={busy}
                      />
                      <Button
                        size="sm"
                        variant="primary"
                        disabled={busy || !logCost}
                        onClick={() =>
                          void runAction(() =>
                            api.storeMaintenanceLog(detail.id, {
                              cost_amount: Number(logCost),
                              days_without_service: logDays ? Number(logDays) : undefined,
                              notes: logNotes || undefined,
                            }),
                          )
                        }
                      >
                        OK
                      </Button>
                    </div>
                  </Field>
                </div>
              )}
              {msg && <p className="text-sm text-ink-soft">{msg}</p>}
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
