import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { AssignableUser, Incident } from '../lib/api';
import { useAuth } from '../auth/AuthContext';
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton } from '../components/ui';
import { ErrorBanner, Field, Pager } from '../components/crud';
import { DetailDrawer } from '../components/DetailDrawer';
import type { DetailTarget } from '../components/DetailDrawer';
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
const CATEGORIES = ['water_point', 'toilets_latrines', 'handwashing', 'sewage_drainage'];
const SORTS = [
  { value: '-priority_score', label: 'Score IA ↓' },
  { value: '-created_at', label: 'Plus récents' },
  { value: '-affected_students', label: 'Élèves affectés ↓' },
];
const DEFAULT_SORT = '-priority_score';

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
  const [categoryF, setCategoryF] = useState('');
  const [sortV, setSortV] = useState(DEFAULT_SORT);
  const [searchInput, setSearchInput] = useState('');
  const [searchQ, setSearchQ] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);

  // Tiroir d'inspection (lecture seule, remplace le panneau détail inline).
  const [drawer, setDrawer] = useState<DetailTarget | null>(null);

  // Incident sélectionné pour les actions (via « Gérer », sans ouvrir le tiroir).
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

  // Bulk v1 : sélection client + changement de statut séquentiel.
  const [checked, setChecked] = useState<number[]>([]);
  const [bulkStatus, setBulkStatus] = useState('');
  const [bulkConfirm, setBulkConfirm] = useState(false);
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkProg, setBulkProg] = useState({ done: 0, total: 0 });
  const [bulkSummary, setBulkSummary] = useState<{ ok: number; fail: number } | null>(null);

  // Recherche : debounce 300 ms + retour page 1.
  useEffect(() => {
    const t = window.setTimeout(() => {
      setSearchQ(searchInput.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(t);
  }, [searchInput]);

  // Touche « / » : focus recherche (hors champs et tiroir ouvert).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || drawer !== null) return;
      const t = e.target as HTMLElement | null;
      const tag = t?.tagName ?? '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t?.isContentEditable === true)
        return;
      e.preventDefault();
      searchRef.current?.focus();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [drawer]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.incidents({
        page,
        status: statusF || undefined,
        urgency: urgencyF || undefined,
        category: categoryF || undefined,
        search: searchQ || undefined,
        sort: sortV,
      });
      setItems(res.data);
      setLastPage(res.last_page);
      setTotal(res.total);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, [page, statusF, urgencyF, categoryF, searchQ, sortV]);

  useEffect(() => {
    void load();
  }, [load]);

  const selectForActions = useCallback(
    async (id: number) => {
      setSelectedId(id);
      setDetailLoading(true);
      setMsg(null);
      setAssignV('');
      setLogCost('');
      setLogDays('');
      setLogNotes('');
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
      await selectForActions(detail.id);
      await load();
    } catch (e) {
      setMsg(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const filtersActive =
    statusF !== '' || urgencyF !== '' || categoryF !== '' || searchInput !== '' || searchQ !== '';
  const resetFilters = () => {
    setStatusF('');
    setUrgencyF('');
    setCategoryF('');
    setSearchInput('');
    setSearchQ('');
    setPage(1);
  };

  const pageIds = useMemo(() => items.map((i) => i.id), [items]);
  const allPageChecked = pageIds.length > 0 && pageIds.every((id) => checked.includes(id));
  const toggleAllPage = () => {
    setBulkConfirm(false);
    setChecked((prev) =>
      allPageChecked
        ? prev.filter((id) => !pageIds.includes(id))
        : [...new Set([...prev, ...pageIds])],
    );
  };
  const toggleCheck = (id: number) => {
    setBulkConfirm(false);
    setChecked((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const runBulk = async () => {
    if (bulkStatus === '' || checked.length === 0 || bulkRunning) return;
    setBulkRunning(true);
    setBulkConfirm(false);
    setBulkSummary(null);
    const ids = [...checked];
    setBulkProg({ done: 0, total: ids.length });
    let ok = 0;
    let fail = 0;
    for (const id of ids) {
      try {
        await api.updateIncidentStatus(id, bulkStatus);
        ok += 1;
      } catch {
        fail += 1;
      }
      setBulkProg({ done: ok + fail, total: ids.length });
    }
    setBulkSummary({ ok, fail });
    setBulkRunning(false);
    setBulkStatus('');
    setChecked([]);
    await load();
    if (selectedId !== null) await selectForActions(selectedId);
  };

  return (
    <div className="mx-auto w-full max-w-6xl">
      <PageHeader
        title="Interventions"
        description={`Incidents triés par l'IA, vérifiés par l'humain — ${fmtNum(total)} au total.`}
      />
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="mb-3 flex flex-wrap items-center gap-3">
        <div className="relative min-w-0 flex-1 basis-64">
          <input
            ref={searchRef}
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape' && searchInput !== '') {
                e.stopPropagation();
                setSearchInput('');
              }
            }}
            placeholder="Rechercher (titre, référence, école…) — « / » pour focus"
            aria-label="Rechercher un incident"
            className={`${INPUT_CLS} pr-9`}
          />
          {searchInput !== '' && (
            <button
              type="button"
              onClick={() => setSearchInput('')}
              aria-label="Effacer la recherche"
              className="absolute top-1/2 right-2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full text-lg leading-none text-ink-faint transition-colors duration-150 ease-snap hover:bg-raised hover:text-ink motion-reduce:transition-none"
            >
              ×
            </button>
          )}
        </div>
        <p aria-live="polite" className="font-mono text-xs tabular-nums text-ink-soft">
          {fmtNum(total)} résultat{total > 1 ? 's' : ''}
        </p>
      </div>

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="flex items-center gap-2 text-sm">
          <span className="text-ink-soft">Statut</span>
          <select
            value={statusF}
            onChange={(e) => {
              setStatusF(e.target.value);
              setPage(1);
            }}
            className={INPUT_CLS}
            aria-label="Filtrer par statut"
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
            aria-label="Filtrer par urgence"
          >
            <option value="">Toutes</option>
            {URGENCIES.map((u) => (
              <option key={u} value={u}>
                {URGENCY_FR[u]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-ink-soft">Catégorie</span>
          <select
            value={categoryF}
            onChange={(e) => {
              setCategoryF(e.target.value);
              setPage(1);
            }}
            className={INPUT_CLS}
            aria-label="Filtrer par catégorie"
          >
            <option value="">Toutes</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {CATEGORY_FR[c]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-ink-soft">Tri</span>
          <select
            value={sortV}
            onChange={(e) => {
              setSortV(e.target.value);
              setPage(1);
            }}
            className={INPUT_CLS}
            aria-label="Trier les incidents"
          >
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        {filtersActive && (
          <Button size="sm" variant="ghost" onClick={resetFilters}>
            Réinitialiser
          </Button>
        )}
      </div>

      {agent && selectedId !== null && (
        <Card className="msg-in mb-4 p-4">
          {detailLoading && <Skeleton className="h-24" />}
          {!detailLoading && !detail && (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-ink-soft">{msg ?? 'Détail indisponible.'}</p>
              <div className="flex gap-2">
                <Button size="sm" onClick={() => void selectForActions(selectedId)}>
                  Réessayer
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setSelectedId(null);
                    setMsg(null);
                  }}
                >
                  Fermer
                </Button>
              </div>
            </div>
          )}
          {!detailLoading && detail && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={urgencyTone(detail.urgency)}>
                      {URGENCY_FR[detail.urgency] ?? detail.urgency}
                    </Badge>
                    <Badge tone={statusTone(detail.status)}>
                      {STATUS_FR[detail.status] ?? detail.status}
                    </Badge>
                    <span className="font-mono text-xs text-ink-faint">
                      {detail.reference_code}
                    </span>
                  </div>
                  <h2 className="mt-1 font-display text-base font-bold tracking-tight">
                    Actions — {detail.title}
                  </h2>
                  <p className="text-xs text-ink-soft">
                    {detail.school?.name ?? '—'} ({detail.school?.district ?? '—'}) ·{' '}
                    {CATEGORY_FR[detail.category] ?? detail.category} ·{' '}
                    {fmtNum(detail.affected_students)} élèves · signalé le{' '}
                    {fmtDate(detail.created_at)} · Assigné à : {detail.assignee?.name ?? 'personne'}{' '}
                    · Score IA :{' '}
                    <span className="font-mono font-bold text-ink tabular-nums">
                      {detail.priority_score.toFixed(1)}
                    </span>
                  </p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setDrawer({ kind: 'incident', id: detail.id })}
                  >
                    Voir le détail
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label="Fermer le panneau d'actions"
                    onClick={() => {
                      setSelectedId(null);
                      setDetail(null);
                      setMsg(null);
                    }}
                  >
                    ×
                  </Button>
                </div>
              </div>

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
              {msg && <p className="msg-in text-sm text-ink-soft">{msg}</p>}
            </div>
          )}
        </Card>
      )}

      {agent && checked.length > 0 && (
        <Card className="msg-in mb-4 p-3">
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-sm font-semibold tabular-nums">
              {fmtNum(checked.length)} sélectionné{checked.length > 1 ? 's' : ''}
            </p>
            <Button
              size="sm"
              variant="ghost"
              disabled={bulkRunning}
              onClick={() => {
                setChecked([]);
                setBulkConfirm(false);
              }}
            >
              Tout effacer
            </Button>
            <label className="flex items-center gap-2 text-sm">
              <span className="text-ink-soft">Statut</span>
              <select
                value={bulkStatus}
                onChange={(e) => {
                  setBulkStatus(e.target.value);
                  setBulkConfirm(false);
                }}
                className={INPUT_CLS}
                disabled={bulkRunning}
                aria-label="Statut à appliquer en masse"
              >
                <option value="">Choisir…</option>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {STATUS_FR[s]}
                  </option>
                ))}
              </select>
            </label>
            <Button
              size="sm"
              variant="primary"
              disabled={bulkRunning || bulkStatus === ''}
              onClick={() => setBulkConfirm(true)}
            >
              Appliquer
            </Button>
          </div>
          {bulkConfirm && !bulkRunning && (
            <div className="msg-in mt-3 flex flex-wrap items-center gap-3 rounded-md bg-raised px-3 py-2 text-sm">
              <p>
                Appliquer « {STATUS_FR[bulkStatus] ?? bulkStatus} » à {fmtNum(checked.length)}{' '}
                incident{checked.length > 1 ? 's' : ''} ?
              </p>
              <Button size="sm" variant="primary" onClick={() => void runBulk()}>
                Confirmer
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setBulkConfirm(false)}>
                Annuler
              </Button>
            </div>
          )}
          {bulkRunning && (
            <div className="mt-3">
              <p aria-live="polite" className="font-mono text-xs tabular-nums text-ink-soft">
                {fmtNum(bulkProg.done)} / {fmtNum(bulkProg.total)}…
              </p>
              <div className="mt-1 h-2 overflow-hidden rounded-full bg-raised">
                <div
                  className="h-full rounded-full bg-teal-600 transition-[width] duration-150 ease-snap motion-reduce:transition-none"
                  style={{
                    width: `${bulkProg.total > 0 ? Math.round((bulkProg.done / bulkProg.total) * 100) : 0}%`,
                  }}
                />
              </div>
            </div>
          )}
        </Card>
      )}
      {bulkSummary !== null && !bulkRunning && (
        <Card className="msg-in mb-4 flex flex-wrap items-center gap-3 p-3">
          <p className="text-sm">
            {fmtNum(bulkSummary.ok)} réussi{bulkSummary.ok > 1 ? 's' : ''},{' '}
            {fmtNum(bulkSummary.fail)} échoué{bulkSummary.fail > 1 ? 's' : ''}.
          </p>
          <Button size="sm" variant="ghost" onClick={() => setBulkSummary(null)}>
            Fermer
          </Button>
        </Card>
      )}

      {agent && items.length > 0 && (
        <div className="mb-2">
          <label className="flex w-fit cursor-pointer items-center gap-2 text-xs text-ink-soft">
            <input
              type="checkbox"
              checked={allPageChecked}
              onChange={toggleAllPage}
              className="h-4 w-4 accent-teal-700"
            />
            Tout sélectionner (page)
          </label>
        </div>
      )}

      {loading && items.length === 0 && (
        <div className="space-y-2">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      )}
      {!loading && items.length === 0 && (
        <Card>
          <EmptyState
            icon="alert"
            title="Aucun incident"
            description={
              filtersActive
                ? 'Aucun incident ne correspond à la recherche ou aux filtres.'
                : 'Aucun incident pour le moment.'
            }
            action={
              filtersActive ? (
                <Button size="sm" onClick={resetFilters}>
                  Réinitialiser
                </Button>
              ) : undefined
            }
          />
        </Card>
      )}
      <ul className="cards-in space-y-2">
        {items.map((i) => (
          <li
            key={i.id}
            className={`flex items-center gap-2 rounded-xl border p-2 pl-3 transition-colors duration-150 ease-snap motion-reduce:transition-none ${
              selectedId === i.id
                ? 'border-accent bg-accent/5'
                : 'border-line bg-card hover:bg-raised'
            }`}
          >
            {agent && (
              <input
                type="checkbox"
                checked={checked.includes(i.id)}
                onChange={() => toggleCheck(i.id)}
                aria-label={`Sélectionner ${i.reference_code}`}
                className="h-4 w-4 shrink-0 accent-teal-700"
              />
            )}
            <button
              type="button"
              onClick={() => setDrawer({ kind: 'incident', id: i.id })}
              aria-label={`Voir le détail ${i.reference_code}`}
              className="min-w-0 flex-1 rounded-lg p-1 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-ink-faint">{i.reference_code}</span>
                <span className="font-mono text-xs font-bold tabular-nums">
                  {i.priority_score.toFixed(1)}
                </span>
              </div>
              <p className="mt-0.5 truncate font-display text-sm font-bold tracking-tight">
                {i.title}
              </p>
              <p className="mt-0.5 truncate text-xs text-ink-soft">
                {i.school?.name ?? '—'} · {fmtNum(i.affected_students)} élèves ·{' '}
                {i.reports_count ?? 0} signalement{(i.reports_count ?? 0) > 1 ? 's' : ''}
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                <Badge tone={urgencyTone(i.urgency)}>{URGENCY_FR[i.urgency] ?? i.urgency}</Badge>
                <Badge tone={statusTone(i.status)}>{STATUS_FR[i.status] ?? i.status}</Badge>
                <Badge>{CATEGORY_FR[i.category] ?? i.category}</Badge>
              </div>
            </button>
            {agent && (
              <Button
                type="button"
                size="sm"
                variant={selectedId === i.id ? 'primary' : 'secondary'}
                onClick={() => void selectForActions(i.id)}
                aria-label={`Gérer ${i.reference_code}`}
                className="shrink-0"
              >
                Gérer
              </Button>
            )}
          </li>
        ))}
      </ul>
      <Pager page={page} lastPage={lastPage} onPage={setPage} />

      <DetailDrawer
        detail={drawer}
        onClose={() => setDrawer(null)}
        onDetail={(kind, id) => setDrawer({ kind, id })}
      />
    </div>
  );
}
