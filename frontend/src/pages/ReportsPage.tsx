import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { Report, School } from '../lib/api';
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton } from '../components/ui';
import { ErrorBanner, Field, Pager, Pretty } from '../components/crud';
import { Radio, Select } from '../components/controls';
import { DetailDrawer } from '../components/DetailDrawer';
import type { DetailTarget } from '../components/DetailDrawer';
import { Icon } from '../components/icons';
import { CHANNEL_FR, INPUT_CLS, fmtDate } from '../lib/wash';

const errMsg = (e: unknown): string => (e instanceof ApiError ? e.message : 'Erreur réseau.');
const errorCls = 'mt-1 text-xs font-medium text-danger';
const CHANNEL_KEYS = ['voice', 'text', 'photo', 'webrtc_call'] as const;

type DupFilter = 'all' | 'unique' | 'dup';

// Recherche d'école distante debounced avec anti-requêtes-obsolètes
// (même pattern que le widget public : debounce 300 ms + compteur de run).
function useSchoolOptions() {
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [options, setOptions] = useState<School[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const reqRef = useRef(0);

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(search.trim()), 300);
    return () => window.clearTimeout(id);
  }, [search]);

  useEffect(() => {
    const run = reqRef.current + 1;
    reqRef.current = run;
    // États mis à jour uniquement dans les callbacks async (pas de setState synchrone).
    api
      .schools(debounced ? { search: debounced } : {})
      .then((page) => {
        if (reqRef.current !== run) return;
        setOptions(page.data);
        setError(null);
      })
      .catch(() => {
        if (reqRef.current !== run) return;
        setOptions([]);
        setError("La liste des écoles n'a pas pu être chargée.");
      })
      .finally(() => {
        if (reqRef.current === run) setLoading(false);
      });
  }, [debounced]);

  return { search, setSearch, options, loading, error };
}

export default function ReportsPage() {
  const [items, setItems] = useState<Report[]>([]);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(20);
  const [lastPage, setLastPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [inlineDetail, setInlineDetail] = useState<Report | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [showExtraction, setShowExtraction] = useState(false);
  const [drawer, setDrawer] = useState<DetailTarget | null>(null);

  // --- Filtres ---
  const [schoolId, setSchoolId] = useState<number | null>(null);
  const [filterOpen, setFilterOpen] = useState(false);
  const filterSchools = useSchoolOptions();
  const [channel, setChannel] = useState<string>('');
  const [dupFilter, setDupFilter] = useState<DupFilter>('all');

  // --- Formulaire de création (contrat inchangé : school_id + message) ---
  const [showForm, setShowForm] = useState(false);
  const [fSchoolId, setFSchoolId] = useState<number | null>(null);
  const [fOpen, setFOpen] = useState(false);
  const createSchools = useSchoolOptions();
  const [fMessage, setFMessage] = useState('');
  const [fErrors, setFErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.reports({
        page,
        per_page: perPage,
        school_id: schoolId ?? undefined,
        channel: channel || undefined,
        is_duplicate: dupFilter === 'all' ? undefined : dupFilter === 'dup' ? 1 : 0,
      });
      setItems(res.data);
      setLastPage(res.last_page);
      setTotal(res.total);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, [page, perPage, schoolId, channel, dupFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const clearInline = () => {
    setSelectedId(null);
    setInlineDetail(null);
    setShowExtraction(false);
  };

  const hasFilters = schoolId !== null || channel !== '' || dupFilter !== 'all';
  const resetFilters = () => {
    setSchoolId(null);
    filterSchools.setSearch('');
    setFilterOpen(false);
    setChannel('');
    setDupFilter('all');
    setPage(1);
    clearInline();
  };

  const pickFilterSchool = (s: School) => {
    setSchoolId(s.id);
    filterSchools.setSearch(s.name);
    setFilterOpen(false);
    setPage(1);
    clearInline();
  };

  const clearFilterSchool = () => {
    setSchoolId(null);
    filterSchools.setSearch('');
    setPage(1);
    clearInline();
  };

  const select = useCallback(async (r: Report) => {
    setSelectedId(r.id);
    if (r.incident_id !== null) {
      setDrawer({ kind: 'incident', id: r.incident_id });
      return;
    }
    setDetailLoading(true);
    setShowExtraction(false);
    try {
      setInlineDetail(await api.report(r.id));
    } catch (e) {
      setInlineDetail(null);
      setMsg(errMsg(e));
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const pickCreateSchool = (s: School) => {
    setFSchoolId(s.id);
    createSchools.setSearch(s.name);
    setFOpen(false);
    setFErrors((p) => ({ ...p, school: '' }));
  };

  const create = async () => {
    if (busy) return;
    const errors: Record<string, string> = {};
    if (!fSchoolId) errors.school = 'Choisissez une école dans la liste.';
    if (fMessage.trim() === '') errors.message = 'Le message est requis.';
    setFErrors(errors);
    if (Object.keys(errors).length > 0) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.createReport({ school_id: fSchoolId as number, message: fMessage.trim() });
      setMsg(`${res.message} Incident : ${res.incident.reference_code}.`);
      setFMessage('');
      setFErrors({});
      setShowForm(false);
      if (page !== 1) {
        setPage(1);
      } else {
        await load();
      }
      setSelectedId(res.report.id);
      setDrawer({ kind: 'incident', id: res.incident.id });
    } catch (e) {
      setMsg(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const dupOptions: Array<{ key: DupFilter; label: string }> = [
    { key: 'all', label: 'Tous' },
    { key: 'unique', label: 'Uniques' },
    { key: 'dup', label: 'Doublons' },
  ];

  return (
    <div className="mx-auto w-full max-w-6xl">
      <PageHeader
        title="Signalements"
        description="File de vérification : doublons flaggés, rattachements, corrections."
        actions={
          <Button variant="primary" onClick={() => setShowForm((v) => !v)}>
            {showForm ? 'Fermer' : '+ Nouveau signalement'}
          </Button>
        }
      />
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {showForm && (
        <Card className="mb-4 space-y-3 p-4">
          <Field label="École *">
            <div className="relative max-w-md">
              <input
                type="text"
                autoComplete="off"
                placeholder="Tapez le nom de l’école…"
                value={createSchools.search}
                onChange={(e) => {
                  createSchools.setSearch(e.target.value);
                  setFOpen(true);
                  if (fSchoolId) setFSchoolId(null);
                }}
                onFocus={() => setFOpen(true)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') setFOpen(false);
                }}
                className={INPUT_CLS}
                aria-expanded={fOpen}
                aria-controls="create-school-listbox"
                role="combobox"
                aria-autocomplete="list"
              />
              {fOpen && (
                <div className="absolute inset-x-0 top-full z-20 mt-1 max-h-56 overflow-auto rounded-md border border-line bg-card shadow-lg">
                  {createSchools.loading ? (
                    <div className="space-y-2 p-3" aria-live="polite">
                      <Skeleton className="h-8 w-full" />
                      <Skeleton className="h-8 w-full" />
                    </div>
                  ) : createSchools.error ? (
                    <p className="p-3 text-sm text-danger">{createSchools.error}</p>
                  ) : createSchools.options.length === 0 ? (
                    <p className="p-3 text-sm text-ink-soft">Aucune école trouvée. Essayez un autre nom.</p>
                  ) : (
                    <ul id="create-school-listbox" role="listbox" aria-label="Écoles">
                      {createSchools.options.map((s) => (
                        <li key={s.id}>
                          <button
                            type="button"
                            role="option"
                            aria-selected={s.id === fSchoolId}
                            onClick={() => pickCreateSchool(s)}
                            className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-raised"
                          >
                            <span className="font-medium">{s.name}</span>
                            <span className="shrink-0 text-xs text-ink-faint">{s.district}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
            {fErrors.school && <p className={errorCls}>{fErrors.school}</p>}
          </Field>
          <Field label="Message *">
            <textarea
              rows={3}
              value={fMessage}
              onChange={(e) => {
                setFMessage(e.target.value);
                setFErrors((p) => ({ ...p, message: '' }));
              }}
              placeholder="Décrivez le problème : pompe cassée, latrines bouchées, eau souillée…"
              className={INPUT_CLS}
              aria-invalid={fErrors.message ? true : undefined}
            />
            {fErrors.message && <p className={errorCls}>{fErrors.message}</p>}
          </Field>
          <div className="flex gap-2">
            <Button variant="primary" disabled={busy} onClick={() => void create()}>
              {busy ? 'Envoi en cours…' : 'Envoyer au tri IA'}
            </Button>
            <Button variant="ghost" onClick={() => setShowForm(false)}>
              Annuler
            </Button>
          </div>
        </Card>
      )}
      {msg && (
        <p role="status" className="mb-4 text-sm text-ink-soft">
          {msg}
        </p>
      )}

      <div className="mb-2 grid gap-2 md:grid-cols-3">
        <div className="relative">
          <input
            type="text"
            autoComplete="off"
            placeholder="Filtrer par école…"
            aria-label="Filtrer par école"
            value={filterSchools.search}
            onChange={(e) => {
              filterSchools.setSearch(e.target.value);
              setFilterOpen(true);
              if (schoolId) {
                setSchoolId(null);
                setPage(1);
                clearInline();
              }
            }}
            onFocus={() => setFilterOpen(true)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setFilterOpen(false);
            }}
            role="combobox"
            aria-expanded={filterOpen}
            aria-controls="filter-school-listbox"
            aria-autocomplete="list"
            className={`${INPUT_CLS} ${filterSchools.search !== '' ? 'pr-9' : ''}`}
          />
          {filterSchools.search !== '' && (
            <button
              type="button"
              onClick={clearFilterSchool}
              aria-label="Effacer le filtre école"
              title="Effacer"
              className="absolute right-2 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full text-ink-faint transition-colors hover:bg-raised hover:text-ink motion-reduce:transition-none"
            >
              <Icon name="x" className="h-4 w-4" />
            </button>
          )}
          {filterOpen && (
            <div className="absolute inset-x-0 top-full z-20 mt-1 max-h-56 overflow-auto rounded-md border border-line bg-card shadow-lg">
              {filterSchools.loading ? (
                <div className="space-y-2 p-3" aria-live="polite">
                  <Skeleton className="h-8 w-full" />
                  <Skeleton className="h-8 w-full" />
                </div>
              ) : filterSchools.error ? (
                <p className="p-3 text-sm text-danger">{filterSchools.error}</p>
              ) : filterSchools.options.length === 0 ? (
                <p className="p-3 text-sm text-ink-soft">Aucune école trouvée. Essayez un autre nom.</p>
              ) : (
                <ul id="filter-school-listbox" role="listbox" aria-label="Écoles">
                  {filterSchools.options.map((s) => (
                    <li key={s.id}>
                      <button
                        type="button"
                        role="option"
                        aria-selected={s.id === schoolId}
                        onClick={() => pickFilterSchool(s)}
                        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-raised"
                      >
                        <span className="font-medium">{s.name}</span>
                        <span className="shrink-0 text-xs text-ink-faint">{s.district}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
        <Select
          value={channel}
          onChange={(e) => {
            setChannel(e.target.value);
            setPage(1);
            clearInline();
          }}
          ariaLabel="Filtrer par canal"
          options={[{ value: '', label: 'Tous les canaux' },
            ...CHANNEL_KEYS.map((k) => ({ value: k, label: CHANNEL_FR[k] ?? k }))]}
        />
        <div className="flex items-center gap-2">
          <div role="radiogroup" aria-label="Filtrer les doublons" className="flex flex-1 flex-wrap gap-3">
            {dupOptions.map((o) => (
              <Radio
                key={o.key}
                name="dup-filter"
                value={o.key}
                checked={dupFilter === o.key}
                onChange={() => {
                  setDupFilter(o.key);
                  setPage(1);
                  clearInline();
                }}
                label={o.label}
              />
            ))}
          </div>
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={resetFilters}>
              Reset
            </Button>
          )}
        </div>
      </div>
      <p aria-live="polite" className="mb-4 text-xs text-ink-soft">
        {loading && items.length === 0 ? 'Chargement…' : `${total} signalement(s)`}
      </p>

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
              {hasFilters ? (
                <EmptyState
                  icon="inbox"
                  title="Aucun signalement"
                  description="Aucun signalement ne correspond à ces filtres."
                  action={<Button onClick={resetFilters}>Réinitialiser les filtres</Button>}
                />
              ) : (
                <EmptyState
                  icon="inbox"
                  title="Aucun signalement"
                  description="La file est vide."
                  action={
                    <Button variant="primary" onClick={() => setShowForm(true)}>
                      + Nouveau signalement
                    </Button>
                  }
                />
              )}
            </Card>
          )}
          {items.map((r) => (
            <button
              key={r.id}
              onClick={() => void select(r)}
              aria-current={selectedId === r.id ? true : undefined}
              className={`w-full rounded-xl border p-3 text-left transition-colors motion-reduce:transition-none ${
                selectedId === r.id
                  ? 'border-accent bg-accent/5'
                  : 'border-line bg-card hover:bg-raised'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-ink-faint">
                  #{r.id} · {fmtDate(r.created_at)}
                </span>
                {r.is_duplicate ? (
                  <Badge tone="warn">Doublon</Badge>
                ) : (
                  <Badge tone="neutral">{CHANNEL_FR[r.channel] ?? r.channel}</Badge>
                )}
              </div>
              <p className="mt-1 line-clamp-2 text-sm">{r.raw_content}</p>
              <p className="mt-0.5 truncate text-xs text-ink-soft">
                {r.school?.name ?? '—'} · {CHANNEL_FR[r.channel] ?? r.channel}
                {r.incident ? ` · ${r.incident.reference_code}` : ' · sans incident'}
              </p>
            </button>
          ))}
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
        </div>

        <div className="lg:col-span-3">
          {detailLoading && <Skeleton className="h-64" />}
          {!detailLoading && !inlineDetail && (
            <Card>
              <EmptyState
                icon="inbox"
                title="Sélectionnez un signalement"
                description="Les signalements rattachés à un incident s'ouvrent dans le panneau latéral. Les autres s'affichent ici."
              />
            </Card>
          )}
          {!detailLoading && inlineDetail && (
            <Card className="space-y-4 p-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">{CHANNEL_FR[inlineDetail.channel] ?? inlineDetail.channel}</Badge>
                  {inlineDetail.is_duplicate && <Badge tone="warn">Doublon</Badge>}
                  <span className="font-mono text-xs text-ink-faint">
                    #{inlineDetail.id} · {fmtDate(inlineDetail.created_at)}
                  </span>
                </div>
                <p className="mt-2 text-sm">{inlineDetail.raw_content}</p>
                <p className="mt-2 text-sm text-ink-soft">
                  École : {inlineDetail.school?.name ?? '—'} · Incident :{' '}
                  {inlineDetail.incident ? (
                    <span className="font-mono">
                      {inlineDetail.incident.reference_code} ({inlineDetail.incident.status})
                    </span>
                  ) : (
                    '—'
                  )}
                </p>
                {inlineDetail.is_duplicate && (
                  <p className="mt-1 text-sm text-ink-soft">
                    Rattaché à l'incident #{inlineDetail.duplicate_of_incident_id} · similarité{' '}
                    {inlineDetail.duplicate_similarity_score != null
                      ? `${Math.round(inlineDetail.duplicate_similarity_score * 100)} %`
                      : '—'}
                  </p>
                )}
                {(inlineDetail.audio_path ?? inlineDetail.photo_path) && (
                  <p className="mt-1 font-mono text-xs text-ink-faint">
                    {inlineDetail.audio_path ?? inlineDetail.photo_path}
                  </p>
                )}
              </div>
              <div>
                <button
                  type="button"
                  onClick={() => setShowExtraction((v) => !v)}
                  aria-expanded={showExtraction}
                  className="mb-1 inline-flex items-center gap-1 text-sm font-semibold text-ink-soft transition-colors hover:text-ink motion-reduce:transition-none"
                >
                  <Icon
                    name="chevron-down"
                    className={`h-4 w-4 transition-transform motion-reduce:transition-none ${showExtraction ? 'rotate-180' : ''}`}
                  />
                  Extraction IA
                </button>
                {showExtraction && <Pretty data={inlineDetail.raw_ai_extraction} />}
              </div>
            </Card>
          )}
        </div>
      </div>

      <DetailDrawer detail={drawer} onClose={() => setDrawer(null)} onDetail={(kind, id) => setDrawer({ kind, id })} />
    </div>
  );
}
