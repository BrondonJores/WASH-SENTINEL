import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { Report, School } from '../lib/api';
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton } from '../components/ui';
import { ErrorBanner, Field, Pager, Pretty } from '../components/crud';
import { Radio, Select } from '../components/controls';
import { DetailDrawer } from '../components/DetailDrawer';
import type { DetailTarget } from '../components/DetailDrawer';
import { Icon } from '../components/icons';
import { CHANNEL_FR, INPUT_CLS } from '../lib/wash';
import { localeFor } from '../lib/locale';
import { pick, useUILang } from '../lib/i18n';
import { DEFAULT_PER_PAGE } from '../lib/pagination';
import { SEARCH_DEBOUNCE_MS } from '../lib/search';

const errMsg = (e: unknown, lang?: string): string =>
  (e instanceof ApiError ? e.message : pick(lang, 'Erreur réseau.', 'Network error.'));

// Libellés EN des canaux (miroir local de CHANNEL_FR : lib/wash.ts hors périmètre).
const CHANNEL_EN: Record<string, string> = {
  voice: 'Voice',
  text: 'Text',
  photo: 'Photo',
  webrtc_call: 'Call',
};

/** Même format que wash.fmtDate, avec la locale de la langue UI. */
const fmtDateL = (iso: string | null, lang: string | undefined): string =>
  iso
    ? new Date(iso).toLocaleString(localeFor(lang), {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '—';
const errorCls = 'mt-1 text-xs font-medium text-danger';
const CHANNEL_KEYS = ['voice', 'text', 'photo', 'webrtc_call'] as const;

type DupFilter = 'all' | 'unique' | 'dup';

// Recherche d'école distante debounced avec anti-requêtes-obsolètes
// (même pattern que le widget public : debounce partagé + compteur de run).
function useSchoolOptions() {
  const ui = useUILang();
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [options, setOptions] = useState<School[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const reqRef = useRef(0);

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(search.trim()), SEARCH_DEBOUNCE_MS);
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
        setError(pick(ui, "La liste des écoles n'a pas pu être chargée.", 'The school list could not be loaded.'));
      })
      .finally(() => {
        if (reqRef.current === run) setLoading(false);
      });
  }, [debounced, ui]);

  return { search, setSearch, options, loading, error };
}

export default function ReportsPage() {
  const ui = useUILang();
  const channelMap = ui === 'en' ? CHANNEL_EN : CHANNEL_FR;
  const [items, setItems] = useState<Report[]>([]);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(DEFAULT_PER_PAGE);
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
      setError(errMsg(e, ui));
    } finally {
      setLoading(false);
    }
  }, [page, perPage, schoolId, channel, dupFilter, ui]);

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
      setMsg(errMsg(e, ui));
    } finally {
      setDetailLoading(false);
    }
  }, [ui]);

  const pickCreateSchool = (s: School) => {
    setFSchoolId(s.id);
    createSchools.setSearch(s.name);
    setFOpen(false);
    setFErrors((p) => ({ ...p, school: '' }));
  };

  const create = async () => {
    if (busy) return;
    const errors: Record<string, string> = {};
    if (!fSchoolId) errors.school = pick(ui, 'Choisissez une école dans la liste.', 'Choose a school from the list.');
    if (fMessage.trim() === '') errors.message = pick(ui, 'Le message est requis.', 'Message is required.');
    setFErrors(errors);
    if (Object.keys(errors).length > 0) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.createReport({ school_id: fSchoolId as number, message: fMessage.trim() });
      setMsg(`${res.message} ${pick(ui, `Incident : ${res.incident.reference_code}.`, `Incident: ${res.incident.reference_code}.`)}`);
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
      setMsg(errMsg(e, ui));
    } finally {
      setBusy(false);
    }
  };

  const dupOptions: Array<{ key: DupFilter; label: string }> = [
    { key: 'all', label: pick(ui, 'Tous', 'All') },
    { key: 'unique', label: pick(ui, 'Uniques', 'Unique') },
    { key: 'dup', label: pick(ui, 'Doublons', 'Duplicates') },
  ];

  return (
    <div className="mx-auto w-full max-w-6xl">
      <PageHeader
        title={pick(ui, 'Signalements', 'Reports')}
        description={pick(ui, 'File de vérification : doublons flaggés, rattachements, corrections.', 'Review queue: flagged duplicates, attachments, corrections.')}
        actions={
          <Button variant="primary" onClick={() => setShowForm((v) => !v)}>
            {showForm ? pick(ui, 'Fermer', 'Close') : pick(ui, '+ Nouveau signalement', '+ New report')}
          </Button>
        }
      />
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {showForm && (
        <Card className="mb-4 space-y-3 p-4">
          <Field label={pick(ui, 'École *', 'School *')}>
            <div className="relative max-w-md">
              <input
                type="text"
                autoComplete="off"
                placeholder={pick(ui, 'Tapez le nom de l’école…', 'Type the school name…')}
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
                    <p className="p-3 text-sm text-ink-soft">{pick(ui, 'Aucune école trouvée. Essayez un autre nom.', 'No schools found. Try another name.')}</p>
                  ) : (
                    <ul id="create-school-listbox" role="listbox" aria-label={pick(ui, 'Écoles', 'Schools')}>
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
          <Field label={pick(ui, 'Message *', 'Message *')}>
            <textarea
              rows={3}
              value={fMessage}
              onChange={(e) => {
                setFMessage(e.target.value);
                setFErrors((p) => ({ ...p, message: '' }));
              }}
              placeholder={pick(ui, 'Décrivez le problème : pompe cassée, latrines bouchées, eau souillée…', 'Describe the problem: broken pump, clogged latrines, dirty water…')}
              className={INPUT_CLS}
              aria-invalid={fErrors.message ? true : undefined}
            />
            {fErrors.message && <p className={errorCls}>{fErrors.message}</p>}
          </Field>
          <div className="flex gap-2">
            <Button variant="primary" disabled={busy} onClick={() => void create()}>
              {busy ? pick(ui, 'Envoi en cours…', 'Sending…') : pick(ui, 'Envoyer au tri IA', 'Send to AI triage')}
            </Button>
            <Button variant="ghost" onClick={() => setShowForm(false)}>
              {pick(ui, 'Annuler', 'Cancel')}
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
            placeholder={pick(ui, 'Filtrer par école…', 'Filter by school…')}
            aria-label={pick(ui, 'Filtrer par école', 'Filter by school')}
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
              aria-label={pick(ui, 'Effacer le filtre école', 'Clear the school filter')}
              title={pick(ui, 'Effacer', 'Clear')}
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
                <p className="p-3 text-sm text-ink-soft">{pick(ui, 'Aucune école trouvée. Essayez un autre nom.', 'No schools found. Try another name.')}</p>
              ) : (
                <ul id="filter-school-listbox" role="listbox" aria-label={pick(ui, 'Écoles', 'Schools')}>
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
          ariaLabel={pick(ui, 'Filtrer par canal', 'Filter by channel')}
          options={[{ value: '', label: pick(ui, 'Tous les canaux', 'All channels') },
            ...CHANNEL_KEYS.map((k) => ({ value: k, label: channelMap[k] ?? k }))]}
        />
        <div className="flex items-center gap-2">
          <div role="radiogroup" aria-label={pick(ui, 'Filtrer les doublons', 'Filter duplicates')} className="flex flex-1 flex-wrap gap-3">
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
        {loading && items.length === 0 ? pick(ui, 'Chargement…', 'Loading…') : pick(ui, `${total} signalement(s)`, `${total} report(s)`)}
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
                  title={pick(ui, 'Aucun signalement', 'No reports')}
                  description={pick(ui, 'Aucun signalement ne correspond à ces filtres.', 'No reports match these filters.')}
                  action={<Button onClick={resetFilters}>{pick(ui, 'Réinitialiser les filtres', 'Reset filters')}</Button>}
                />
              ) : (
                <EmptyState
                  icon="inbox"
                  title={pick(ui, 'Aucun signalement', 'No reports')}
                  description={pick(ui, 'La file est vide.', 'The queue is empty.')}
                  action={
                    <Button variant="primary" onClick={() => setShowForm(true)}>
                      {pick(ui, '+ Nouveau signalement', '+ New report')}
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
                  #{r.id} · {fmtDateL(r.created_at, ui)}
                </span>
                {r.is_duplicate ? (
                  <Badge tone="warn">{pick(ui, 'Doublon', 'Duplicate')}</Badge>
                ) : (
                  <Badge tone="neutral">{channelMap[r.channel] ?? r.channel}</Badge>
                )}
              </div>
              <p className="mt-1 line-clamp-2 text-sm">{r.raw_content}</p>
              <p className="mt-0.5 truncate text-xs text-ink-soft">
                {r.school?.name ?? '—'} · {channelMap[r.channel] ?? r.channel}
                {r.incident ? ` · ${r.incident.reference_code}` : pick(ui, ' · sans incident', ' · no incident')}
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
                title={pick(ui, 'Sélectionnez un signalement', 'Select a report')}
                description={pick(ui, "Les signalements rattachés à un incident s'ouvrent dans le panneau latéral. Les autres s'affichent ici.", 'Reports linked to an incident open in the side panel. Others show here.')}
              />
            </Card>
          )}
          {!detailLoading && inlineDetail && (
            <Card className="space-y-4 p-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">{channelMap[inlineDetail.channel] ?? inlineDetail.channel}</Badge>
                  {inlineDetail.is_duplicate && <Badge tone="warn">{pick(ui, 'Doublon', 'Duplicate')}</Badge>}
                  <span className="font-mono text-xs text-ink-faint">
                    #{inlineDetail.id} · {fmtDateL(inlineDetail.created_at, ui)}
                  </span>
                </div>
                <p className="mt-2 text-sm">{inlineDetail.raw_content}</p>
                <p className="mt-2 text-sm text-ink-soft">
                  {pick(ui, 'École :', 'School:')} {inlineDetail.school?.name ?? '—'} · {pick(ui, 'Incident :', 'Incident:')}{' '}
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
                    {pick(ui, `Rattaché à l'incident #${inlineDetail.duplicate_of_incident_id} · similarité`, `Attached to incident #${inlineDetail.duplicate_of_incident_id} · similarity`)}{' '}
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
                  {pick(ui, 'Extraction IA', 'AI extraction')}
                </button>
                {showExtraction && <Pretty data={inlineDetail.raw_ai_extraction} />}
              </div>
            </Card>
          )}
        </div>
      </div>

      <DetailDrawer detail={drawer} onClose={() => setDrawer(null)} onDetail={(kind, id) => setDrawer({ kind, id })} lang={ui} />
    </div>
  );
}
