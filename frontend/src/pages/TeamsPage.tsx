import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { Team } from '../lib/api';
import { useAuth } from '../auth/AuthContext';
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton } from '../components/ui';
import { ErrorBanner, Field, Pager } from '../components/crud';
import { INPUT_CLS, fmtNum } from '../lib/wash';
import { pick, useUILang } from '../lib/i18n';
import { DEFAULT_PER_PAGE } from '../lib/pagination';
import { SEARCH_DEBOUNCE_MS } from '../lib/search';

const errMsg = (e: unknown, lang?: string): string =>
  (e instanceof ApiError ? e.message : pick(lang, 'Erreur réseau.', 'Network error.'));
const errorCls = 'mt-1 text-xs font-medium text-danger';

// Spécialités saisies comme texte libre séparé par des virgules.
const splitSpecialties = (v: string): string[] =>
  v
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s !== '');

export default function TeamsPage() {
  const { user } = useAuth();
  const ui = useUILang();
  const admin = user?.roles.includes('wash_admin') ?? false;

  const [items, setItems] = useState<Team[]>([]);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(DEFAULT_PER_PAGE);
  const [lastPage, setLastPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [searchV, setSearchV] = useState('');
  const [search, setSearch] = useState('');
  const [districtV, setDistrictV] = useState('');
  const [district, setDistrict] = useState('');
  const [activeOnly, setActiveOnly] = useState(false);

  // Formulaire création / édition.
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Team | null>(null);
  const [fName, setFName] = useState('');
  const [fDistrict, setFDistrict] = useState('');
  const [fPhone, setFPhone] = useState('');
  const [fSpecialties, setFSpecialties] = useState('');
  const [fActive, setFActive] = useState(true);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);

  // Filtres debounced (convention SchoolsPage).
  useEffect(() => {
    const id = window.setTimeout(() => {
      setSearch(searchV.trim());
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [searchV]);

  useEffect(() => {
    const id = window.setTimeout(() => {
      setDistrict(districtV.trim());
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [districtV]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.teams({
        page,
        per_page: perPage,
        search: search || undefined,
        district: district || undefined,
        active_only: activeOnly || undefined,
      });
      setItems(res.data);
      setLastPage(res.last_page);
      setTotal(res.total);
    } catch (e) {
      setError(errMsg(e, ui));
    } finally {
      setLoading(false);
    }
  }, [page, perPage, search, district, activeOnly, ui]);

  useEffect(() => {
    void load();
  }, [load]);

  const hasFilters = searchV.trim() !== '' || districtV.trim() !== '' || activeOnly;
  const resetFilters = () => {
    setSearchV('');
    setSearch('');
    setDistrictV('');
    setDistrict('');
    setActiveOnly(false);
    setPage(1);
  };

  const openCreate = () => {
    setEditing(null);
    setFName('');
    setFDistrict('');
    setFPhone('');
    setFSpecialties('');
    setFActive(true);
    setFieldErrors({});
    setShowForm(true);
  };

  const openEdit = (t: Team) => {
    setEditing(t);
    setFName(t.name);
    setFDistrict(t.district);
    setFPhone(t.phone ?? '');
    setFSpecialties((t.specialties ?? []).join(', '));
    setFActive(t.is_active);
    setFieldErrors({});
    setShowForm(true);
  };

  const validate = (): Record<string, string> => {
    const errors: Record<string, string> = {};
    if (fName.trim() === '') errors.name = pick(ui, 'Le nom est requis.', 'Name is required.');
    if (fDistrict.trim() === '') errors.district = pick(ui, 'Le district est requis.', 'District is required.');
    if (fPhone.trim() !== '' && fPhone.trim().length < 6) {
      errors.phone = pick(ui, 'Numéro de téléphone trop court.', 'Phone number too short.');
    }
    return errors;
  };

  const save = async () => {
    if (busy) return;
    const errors = validate();
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;
    setBusy(true);
    setMsg(null);
    try {
      const specialties = splitSpecialties(fSpecialties);
      if (editing) {
        const res = await api.updateTeam(editing.id, {
          name: fName.trim(),
          district: fDistrict.trim(),
          phone: fPhone.trim() || undefined,
          specialties,
          is_active: fActive,
        });
        setMsg(res.message);
      } else {
        const res = await api.createTeam({
          name: fName.trim(),
          district: fDistrict.trim(),
          phone: fPhone.trim() || undefined,
          specialties,
          is_active: fActive,
        });
        setMsg(res.message);
      }
      setShowForm(false);
      setEditing(null);
      await load();
    } catch (e) {
      setMsg(errMsg(e, ui));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (t: Team) => {
    if (deleting !== null) return;
    if (!window.confirm(pick(ui, `Supprimer l'équipe « ${t.name} » ?`, `Delete team "${t.name}"?`))) return;
    setDeleting(t.id);
    setMsg(null);
    try {
      const res = await api.deleteTeam(t.id);
      setMsg(res.message);
      await load();
    } catch (e) {
      setMsg(errMsg(e, ui));
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="mx-auto w-full max-w-6xl">
      <PageHeader
        title={pick(ui, 'Équipes', 'Teams')}
        description={pick(ui, `Équipes de maintenance — ${fmtNum(total)} au total.`, `Maintenance teams — ${fmtNum(total)} in total.`)}
        actions={
          admin ? (
            <Button variant="primary" onClick={() => (showForm ? setShowForm(false) : openCreate())}>
              {showForm ? pick(ui, 'Fermer', 'Close') : pick(ui, '+ Nouvelle équipe', '+ New team')}
            </Button>
          ) : undefined
        }
      />
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {showForm && (
        <Card className="mb-4 p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={pick(ui, 'Nom *', 'Name *')}>
              <input
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
            <Field label="District *">
              <input
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
            <Field label={pick(ui, 'Téléphone', 'Phone')}>
              <input
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
            <Field label={pick(ui, 'Spécialités (séparées par des virgules)', 'Specialties (comma-separated)')}>
              <input
                value={fSpecialties}
                onChange={(e) => setFSpecialties(e.target.value)}
                placeholder={pick(ui, 'forage, pompes manuelles', 'boreholes, hand pumps')}
                className={INPUT_CLS}
              />
            </Field>
            <label className="flex items-center gap-2 text-sm text-ink-soft">
              <input type="checkbox" checked={fActive} onChange={(e) => setFActive(e.target.checked)} />
              {pick(ui, 'Équipe active', 'Active team')}
            </label>
          </div>
          <div className="mt-3 flex gap-2">
            <Button variant="primary" disabled={busy} onClick={() => void save()}>
              {busy ? pick(ui, 'Enregistrement…', 'Saving…') : editing ? pick(ui, 'Mettre à jour', 'Update') : pick(ui, 'Enregistrer', 'Save')}
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
        <div className="sm:max-w-sm sm:flex-1">
          <input
            placeholder={pick(ui, 'Rechercher une équipe…', 'Search for a team…')}
            value={searchV}
            onChange={(e) => setSearchV(e.target.value)}
            aria-label={pick(ui, 'Rechercher une équipe', 'Search for a team')}
            className={INPUT_CLS}
          />
        </div>
        <div className="sm:max-w-xs sm:flex-1">
          <input
            placeholder={pick(ui, 'Filtrer par district…', 'Filter by district…')}
            value={districtV}
            onChange={(e) => setDistrictV(e.target.value)}
            aria-label={pick(ui, 'Filtrer par district', 'Filter by district')}
            className={INPUT_CLS}
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-ink-soft">
          <input
            type="checkbox"
            checked={activeOnly}
            onChange={(e) => {
              setActiveOnly(e.target.checked);
              setPage(1);
            }}
          />
          {pick(ui, 'Actives uniquement', 'Active only')}
        </label>
        {hasFilters && (
          <Button variant="ghost" onClick={resetFilters}>
            {pick(ui, 'Réinitialiser', 'Reset')}
          </Button>
        )}
      </div>
      <p aria-live="polite" className="mb-4 text-xs text-ink-soft">
        {loading && items.length === 0 ? pick(ui, 'Recherche en cours…', 'Searching…') : pick(ui, `${fmtNum(total)} résultat(s)`, `${fmtNum(total)} result(s)`)}
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
            <EmptyState
              icon="user"
              title={hasFilters ? pick(ui, 'Aucune équipe trouvée', 'No teams found') : pick(ui, 'Aucune équipe', 'No teams')}
              description={
                hasFilters
                  ? pick(ui, 'Aucune équipe ne correspond à ces critères.', 'No team matches these criteria.')
                  : pick(ui, 'Aucune équipe de maintenance pour le moment.', 'No maintenance teams yet.')
              }
              action={
                hasFilters ? (
                  <Button onClick={resetFilters}>{pick(ui, 'Réinitialiser les filtres', 'Reset filters')}</Button>
                ) : admin ? (
                  <Button variant="primary" onClick={openCreate}>
                    {pick(ui, '+ Nouvelle équipe', '+ New team')}
                  </Button>
                ) : undefined
              }
            />
          </Card>
        )}
        {items.map((t) => (
          <div key={t.id} className="rounded-xl border border-line bg-card p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-ink-faint">{t.district}</span>
              {t.is_active ? <Badge tone="success">Active</Badge> : <Badge tone="neutral">Inactive</Badge>}
            </div>
            <p className="mt-1 truncate text-sm font-semibold">{t.name}</p>
            <p className="mt-0.5 truncate text-xs text-ink-soft">
              {(t.specialties ?? []).length > 0 ? (t.specialties ?? []).join(' · ') : pick(ui, 'Sans spécialité renseignée', 'No specialty listed')}
              {t.phone ? ` — ${t.phone}` : ''}
            </p>
            {admin && (
              <div className="mt-2 flex gap-2">
                <Button size="sm" onClick={() => openEdit(t)}>
                  {pick(ui, 'Modifier', 'Edit')}
                </Button>
                <Button size="sm" variant="danger" disabled={deleting === t.id} onClick={() => void remove(t)}>
                  {deleting === t.id ? pick(ui, 'Suppression…', 'Deleting…') : pick(ui, 'Supprimer', 'Delete')}
                </Button>
              </div>
            )}
          </div>
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
    </div>
  );
}
