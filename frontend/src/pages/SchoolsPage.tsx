import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, API_URL, ApiError } from '../lib/api';
import type { School } from '../lib/api';
import { useAuth } from '../auth/AuthContext';
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton } from '../components/ui';
import { ErrorBanner, Field, Pager } from '../components/crud';
import { DetailDrawer } from '../components/DetailDrawer';
import type { DetailTarget } from '../components/DetailDrawer';
import { Icon } from '../components/icons';
import { INPUT_CLS, fmtNum } from '../lib/wash';
import { localeFor } from '../lib/locale';
import { pick, useUILang } from '../lib/i18n';
import { DEFAULT_PER_PAGE } from '../lib/pagination';
import { SEARCH_DEBOUNCE_MS } from '../lib/search';

const errMsg = (e: unknown, lang?: string): string =>
  (e instanceof ApiError ? e.message : pick(lang, 'Erreur réseau.', 'Network error.'));
const toNum = (v: string): number | undefined => (v === '' ? undefined : Number(v));
const errorCls = 'mt-1 text-xs font-medium text-danger';

// Ligne du référentiel prix (GET /v1/wash/equipment-costs, câblé après coup).
type CostRefRow = {
  category: unknown;
  min_xaf: unknown;
  max_xaf: unknown;
  source_name: unknown;
};

type CostRef = { median: number; sources: string };

export default function SchoolsPage() {
  const { user } = useAuth();
  const ui = useUILang();
  const admin = user?.roles.includes('wash_admin') ?? false;

  const [items, setItems] = useState<School[]>([]);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(DEFAULT_PER_PAGE);
  const [lastPage, setLastPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [costRef, setCostRef] = useState<CostRef | null>(null);

  const [searchV, setSearchV] = useState('');
  const [search, setSearch] = useState('');
  const [districtV, setDistrictV] = useState('');
  const [district, setDistrict] = useState('');
  const searchInputRef = useRef<HTMLInputElement>(null);

  const [detail, setDetail] = useState<DetailTarget | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [fName, setFName] = useState('');
  const [fCode, setFCode] = useState('');
  const [fDistrict, setFDistrict] = useState('');
  const [fStudents, setFStudents] = useState('');
  const [fTeachers, setFTeachers] = useState('');
  const [fPhone, setFPhone] = useState('');
  const [fCost, setFCost] = useState('');
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const nameRef = useRef<HTMLInputElement>(null);
  const codeRef = useRef<HTMLInputElement>(null);
  const districtRef = useRef<HTMLInputElement>(null);
  const studentsRef = useRef<HTMLInputElement>(null);
  const teachersRef = useRef<HTMLInputElement>(null);
  const phoneRef = useRef<HTMLInputElement>(null);
  const costRefEl = useRef<HTMLInputElement>(null);

  // Recherche live debounced (remplace le bouton).
  useEffect(() => {
    const id = window.setTimeout(() => {
      setSearch(searchV.trim());
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [searchV]);

  // Filtre district en direct (debounced pour limiter les requêtes).
  useEffect(() => {
    const id = window.setTimeout(() => {
      setDistrict(districtV.trim());
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [districtV]);

  // Référentiel prix national : médiane des points d'eau + sources, en
  // repli d'affichage quand une école n'a pas de coût renseigné. Échec
  // silencieux (route câblée après cette étape) : coût fiche école seul.
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const res = await fetch(`${API_URL}/v1/wash/equipment-costs`, {
          headers: { Accept: 'application/json' },
        });
        if (!res.ok) return;
        const body: unknown = await res.json();
        if (!Array.isArray(body)) return;
        const mids: number[] = [];
        const names: string[] = [];
        for (const r of body as CostRefRow[]) {
          if (typeof r !== 'object' || r === null) continue;
          if (r.category !== 'water_point') continue;
          if (typeof r.min_xaf !== 'number' || typeof r.max_xaf !== 'number') continue;
          if (r.min_xaf <= 0 || r.max_xaf <= 0) continue;
          mids.push((r.min_xaf + r.max_xaf) / 2);
          if (typeof r.source_name === 'string' && r.source_name !== '' && !names.includes(r.source_name)) {
            names.push(r.source_name);
          }
        }
        if (!alive || mids.length === 0) return;
        mids.sort((a, b) => a - b);
        const mid =
          mids.length % 2 === 1
            ? mids[(mids.length - 1) / 2]
            : (mids[mids.length / 2 - 1] + mids[mids.length / 2]) / 2;
        setCostRef({ median: mid, sources: names.join(' · ') });
      } catch {
        // Référentiel indisponible : affichage fiche école uniquement.
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // Raccourci « / » : focus sur la recherche.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/') return;
      const t = e.target;
      if (t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement) return;
      e.preventDefault();
      searchInputRef.current?.focus();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.schools({
        page,
        per_page: perPage,
        search: search || undefined,
        district: district || undefined,
      });
      setItems(res.data);
      setLastPage(res.last_page);
      setTotal(res.total);
    } catch (e) {
      setError(errMsg(e, ui));
    } finally {
      setLoading(false);
    }
  }, [page, perPage, search, district, ui]);

  useEffect(() => {
    void load();
  }, [load]);

  const districts = useMemo(() => {
    const set = new Set<string>();
    for (const s of items) {
      if (s.district.trim() !== '') set.add(s.district);
    }
    return [...set].sort((a, b) => a.localeCompare(b, localeFor(ui)));
  }, [items, ui]);

  const hasFilters = searchV.trim() !== '' || districtV.trim() !== '';
  const resetFilters = () => {
    setSearchV('');
    setSearch('');
    setDistrictV('');
    setDistrict('');
    setPage(1);
  };

  const openDetail = useCallback((id: number) => {
    setDetail({ kind: 'school', id });
  }, []);

  const closeDetail = useCallback(() => {
    setDetail(null);
  }, []);

  const validate = (): Record<string, string> => {
    const errors: Record<string, string> = {};
    if (fName.trim() === '') errors.name = pick(ui, 'Le nom est requis.', 'Name is required.');
    if (fCode.trim() === '') errors.code = pick(ui, 'Le code est requis.', 'Code is required.');
    if (fDistrict.trim() === '') errors.district = pick(ui, 'Le district est requis.', 'District is required.');
    if (fStudents.trim() !== '') {
      const n = Number(fStudents);
      if (!Number.isInteger(n) || n < 0) errors.students = pick(ui, 'Indiquez un nombre entier positif (ou laissez vide).', 'Enter a positive whole number (or leave empty).');
    }
    if (fTeachers.trim() !== '') {
      const n = Number(fTeachers);
      if (!Number.isInteger(n) || n < 0) errors.teachers = pick(ui, 'Indiquez un nombre entier positif (ou laissez vide).', 'Enter a positive whole number (or leave empty).');
    }
    if (fPhone.trim() !== '' && fPhone.trim().length < 6) {
      errors.phone = pick(ui, 'Numéro de téléphone trop court.', 'Phone number too short.');
    }
    if (fCost.trim() !== '') {
      const n = Number(fCost);
      if (!Number.isFinite(n) || n < 0) errors.cost = pick(ui, 'Indiquez un montant positif en XAF (ou laissez vide).', 'Enter a positive amount in XAF (or leave empty).');
    }
    return errors;
  };

  const focusFirstError = (errors: Record<string, string>) => {
    const order: Array<[string, { current: HTMLInputElement | null }]> = [
      ['name', nameRef],
      ['code', codeRef],
      ['district', districtRef],
      ['students', studentsRef],
      ['teachers', teachersRef],
      ['phone', phoneRef],
      ['cost', costRefEl],
    ];
    for (const [key, ref] of order) {
      if (errors[key]) {
        ref.current?.focus();
        return;
      }
    }
  };

  const create = async () => {
    if (busy) return;
    const errors = validate();
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      focusFirstError(errors);
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.createSchool({
        name: fName.trim(),
        code: fCode.trim(),
        district: fDistrict.trim(),
        student_count: toNum(fStudents.trim()),
        teacher_count: toNum(fTeachers.trim()),
        contact_phone: fPhone.trim() || undefined,
        estimated_replacement_cost: toNum(fCost.trim()),
      });
      setMsg(res.message);
      setShowForm(false);
      setFName('');
      setFCode('');
      setFDistrict('');
      setFStudents('');
      setFTeachers('');
      setFPhone('');
      setFCost('');
      setFieldErrors({});
      await load();
      setDetail({ kind: 'school', id: res.school.id });
    } catch (e) {
      setMsg(errMsg(e, ui));
    } finally {
      setBusy(false);
    }
  };

  // Coût de remplacement + sa source : fiche école si renseigné, sinon
  // médiane du référentiel national (jamais de prix codé en dur ici).
  const costLine = (s: School): string => {
    if (typeof s.estimated_replacement_cost === 'number' && s.estimated_replacement_cost > 0) {
      return pick(ui, `Neuf : ${fmtNum(s.estimated_replacement_cost)} XAF · Source : fiche école`, `New: ${fmtNum(s.estimated_replacement_cost)} XAF · Source: school file`);
    }
    if (costRef !== null) {
      const src = costRef.sources.length > 64 ? `${costRef.sources.slice(0, 64)}…` : costRef.sources;
      return pick(ui, `Neuf : ~${fmtNum(costRef.median)} XAF · Source : référentiel (${src})`, `New: ~${fmtNum(costRef.median)} XAF · Source: reference (${src})`);
    }
    return pick(ui, 'Neuf : non renseigné', 'New: not provided');
  };

  const errorList = Object.values(fieldErrors).filter((v) => v !== '');

  return (
    <div className="mx-auto w-full max-w-6xl">
      <PageHeader
        title={pick(ui, 'Écoles', 'Schools')}
        description={pick(ui, `Établissements suivis — ${fmtNum(total)} au total.`, `Tracked schools — ${fmtNum(total)} in total.`)}
        actions={
          admin ? (
            <Button variant="primary" onClick={() => setShowForm((v) => !v)}>
              {showForm ? pick(ui, 'Fermer', 'Close') : pick(ui, '+ Nouvelle école', '+ New school')}
            </Button>
          ) : undefined
        }
      />
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {showForm && (
        <Card className="mb-4 p-4">
          {errorList.length > 0 && (
            <div role="alert" className="mb-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
              <p className="font-semibold">{pick(ui, `Vérifiez ${errorList.length} champ(s) :`, `Check ${errorList.length} field(s):`)}</p>
              <ul className="mt-1 list-disc pl-5">
                {errorList.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label={pick(ui, 'Nom *', 'Name *')}>
              <input
                ref={nameRef}
                value={fName}
                onChange={(e) => {
                  setFName(e.target.value);
                  setFieldErrors((p) => ({ ...p, name: '' }));
                }}
                className={`${INPUT_CLS} ${fieldErrors.name ? 'border-danger' : ''}`}
                aria-invalid={fieldErrors.name ? true : undefined}
              />
              {fieldErrors.name && <p className={errorCls}>{fieldErrors.name}</p>}
            </Field>
            <Field label="Code *">
              <input
                ref={codeRef}
                value={fCode}
                onChange={(e) => {
                  setFCode(e.target.value);
                  setFieldErrors((p) => ({ ...p, code: '' }));
                }}
                className={`${INPUT_CLS} ${fieldErrors.code ? 'border-danger' : ''}`}
                aria-invalid={fieldErrors.code ? true : undefined}
              />
              {fieldErrors.code && <p className={errorCls}>{fieldErrors.code}</p>}
            </Field>
            <Field label="District *">
              <input
                ref={districtRef}
                value={fDistrict}
                onChange={(e) => {
                  setFDistrict(e.target.value);
                  setFieldErrors((p) => ({ ...p, district: '' }));
                }}
                className={`${INPUT_CLS} ${fieldErrors.district ? 'border-danger' : ''}`}
                aria-invalid={fieldErrors.district ? true : undefined}
              />
              {fieldErrors.district && <p className={errorCls}>{fieldErrors.district}</p>}
            </Field>
            <Field label={pick(ui, 'Élèves', 'Students')}>
              <input
                ref={studentsRef}
                type="number"
                min={0}
                step={1}
                value={fStudents}
                onChange={(e) => {
                  setFStudents(e.target.value);
                  setFieldErrors((p) => ({ ...p, students: '' }));
                }}
                className={`${INPUT_CLS} ${fieldErrors.students ? 'border-danger' : ''}`}
                aria-invalid={fieldErrors.students ? true : undefined}
              />
              {fieldErrors.students && <p className={errorCls}>{fieldErrors.students}</p>}
            </Field>
            <Field label={pick(ui, 'Enseignants', 'Teachers')}>
              <input
                ref={teachersRef}
                type="number"
                min={0}
                step={1}
                value={fTeachers}
                onChange={(e) => {
                  setFTeachers(e.target.value);
                  setFieldErrors((p) => ({ ...p, teachers: '' }));
                }}
                className={`${INPUT_CLS} ${fieldErrors.teachers ? 'border-danger' : ''}`}
                aria-invalid={fieldErrors.teachers ? true : undefined}
              />
              {fieldErrors.teachers && <p className={errorCls}>{fieldErrors.teachers}</p>}
            </Field>
            <Field label={pick(ui, 'Téléphone', 'Phone')}>
              <input
                ref={phoneRef}
                value={fPhone}
                onChange={(e) => {
                  setFPhone(e.target.value);
                  setFieldErrors((p) => ({ ...p, phone: '' }));
                }}
                className={`${INPUT_CLS} ${fieldErrors.phone ? 'border-danger' : ''}`}
                aria-invalid={fieldErrors.phone ? true : undefined}
              />
              {fieldErrors.phone && <p className={errorCls}>{fieldErrors.phone}</p>}
            </Field>
            <Field label={pick(ui, 'Coût neuf (XAF)', 'New cost (XAF)')}>
              <input
                ref={costRefEl}
                type="number"
                min={0}
                step={1000}
                value={fCost}
                onChange={(e) => {
                  setFCost(e.target.value);
                  setFieldErrors((p) => ({ ...p, cost: '' }));
                }}
                className={`${INPUT_CLS} ${fieldErrors.cost ? 'border-danger' : ''}`}
                aria-invalid={fieldErrors.cost ? true : undefined}
              />
              {fieldErrors.cost && <p className={errorCls}>{fieldErrors.cost}</p>}
            </Field>
          </div>
          <div className="mt-3 flex gap-2">
            <Button variant="primary" disabled={busy} onClick={() => void create()}>
              {busy ? pick(ui, 'Enregistrement…', 'Saving…') : pick(ui, 'Enregistrer', 'Save')}
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

      <div className="mb-2 flex flex-col gap-2 sm:flex-row">
        <div className="relative sm:max-w-sm sm:flex-1">
          <Icon
            name="search"
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
          />
          <input
            ref={searchInputRef}
            placeholder={pick(ui, 'Rechercher une école…  ( / )', 'Search for a school…  ( / )')}
            title={pick(ui, 'Rechercher — raccourci : /', 'Search — shortcut: /')}
            value={searchV}
            onChange={(e) => setSearchV(e.target.value)}
            aria-label={pick(ui, 'Rechercher une école', 'Search for a school')}
            className={`${INPUT_CLS} pl-9 ${searchV !== '' ? 'pr-9' : ''}`}
          />
          {searchV !== '' && (
            <button
              type="button"
              onClick={() => setSearchV('')}
              aria-label={pick(ui, 'Effacer la recherche', 'Clear search')}
              title={pick(ui, 'Effacer', 'Clear')}
              className="absolute right-2 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full text-ink-faint transition-colors hover:bg-raised hover:text-ink motion-reduce:transition-none"
            >
              <Icon name="x" className="h-4 w-4" />
            </button>
          )}
        </div>
        <div className="sm:max-w-xs sm:flex-1">
          <input
            placeholder={pick(ui, 'Filtrer par district…', 'Filter by district…')}
            value={districtV}
            onChange={(e) => setDistrictV(e.target.value)}
            aria-label={pick(ui, 'Filtrer par district', 'Filter by district')}
            list="school-district-list"
            className={INPUT_CLS}
          />
          <datalist id="school-district-list">
            {districts.map((d) => (
              <option key={d} value={d} />
            ))}
          </datalist>
        </div>
        {hasFilters && (
          <Button variant="ghost" onClick={resetFilters}>
            {pick(ui, 'Réinitialiser', 'Reset')}
          </Button>
        )}
      </div>
      <p aria-live="polite" className="mb-4 text-xs text-ink-soft">
        {loading && items.length === 0 ? pick(ui, 'Recherche en cours…', 'Searching…') : pick(ui, `${fmtNum(total)} résultat(s)`, `${fmtNum(total)} result(s)`)}
        {hasFilters && total > 0 ? ` — page ${page}/${lastPage}` : ''}
      </p>

      <div className="space-y-2">
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
                icon="school"
                title={pick(ui, 'Aucune école trouvée', 'No schools found')}
                description={pick(ui, 'Aucun établissement ne correspond à ces critères.', 'No school matches these criteria.')}
                action={<Button onClick={resetFilters}>{pick(ui, 'Réinitialiser les filtres', 'Reset filters')}</Button>}
              />
            ) : (
              <EmptyState
                icon="school"
                title={pick(ui, 'Aucune école', 'No schools')}
                description={pick(ui, 'Aucun établissement suivi pour le moment.', 'No schools tracked yet.')}
                action={
                  admin ? (
                    <Button variant="primary" onClick={() => setShowForm(true)}>
                      {pick(ui, '+ Nouvelle école', '+ New school')}
                    </Button>
                  ) : undefined
                }
              />
            )}
          </Card>
        )}
        {items.map((s) => {
          const active = detail !== null && detail.kind === 'school' && detail.id === s.id;
          return (
            <button
              key={s.id}
              onClick={() => openDetail(s.id)}
              aria-current={active ? true : undefined}
              className={`w-full rounded-xl border p-3 text-left transition-colors motion-reduce:transition-none ${
                active ? 'border-accent bg-accent/5' : 'border-line bg-card hover:bg-raised'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-ink-faint">{s.code}</span>
                {(s.open_incidents_count ?? 0) > 0 && (
                  <Badge tone="warn">{pick(ui, `${s.open_incidents_count} ouvert(s)`, `${s.open_incidents_count} open`)}</Badge>
                )}
              </div>
              <p className="mt-1 truncate text-sm font-semibold">{s.name}</p>
              <p className="mt-0.5 truncate text-xs text-ink-soft">
                {s.district} · {pick(ui, `${fmtNum(s.student_count)} élèves`, `${fmtNum(s.student_count)} students`)} · {pick(ui, `${s.reports_count ?? 0} signalement(s)`, `${s.reports_count ?? 0} report(s)`)}
              </p>
              <p className="mt-0.5 truncate text-xs text-ink-soft">{costLine(s)}</p>
            </button>
          );
        })}
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

      <DetailDrawer detail={detail} onClose={closeDetail} onDetail={(kind, id) => setDetail({ kind, id })} lang={ui} />
    </div>
  );
}
