import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { Team } from '../lib/api';
import { useAuth } from '../auth/AuthContext';
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton } from '../components/ui';
import { ErrorBanner, Field, Pager } from '../components/crud';
import { INPUT_CLS, fmtNum } from '../lib/wash';
import { DEFAULT_PER_PAGE } from '../lib/pagination';
import { SEARCH_DEBOUNCE_MS } from '../lib/search';

const errMsg = (e: unknown): string => (e instanceof ApiError ? e.message : 'Erreur réseau.');
const errorCls = 'mt-1 text-xs font-medium text-danger';

// Spécialités saisies comme texte libre séparé par des virgules.
const splitSpecialties = (v: string): string[] =>
  v
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s !== '');

export default function TeamsPage() {
  const { user } = useAuth();
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
      setError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, [page, perPage, search, district, activeOnly]);

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
    if (fName.trim() === '') errors.name = 'Le nom est requis.';
    if (fDistrict.trim() === '') errors.district = 'Le district est requis.';
    if (fPhone.trim() !== '' && fPhone.trim().length < 6) {
      errors.phone = 'Numéro de téléphone trop court.';
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
      setMsg(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (t: Team) => {
    if (deleting !== null) return;
    if (!window.confirm(`Supprimer l'équipe « ${t.name} » ?`)) return;
    setDeleting(t.id);
    setMsg(null);
    try {
      const res = await api.deleteTeam(t.id);
      setMsg(res.message);
      await load();
    } catch (e) {
      setMsg(errMsg(e));
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="mx-auto w-full max-w-6xl">
      <PageHeader
        title="Équipes"
        description={`Équipes de maintenance — ${fmtNum(total)} au total.`}
        actions={
          admin ? (
            <Button variant="primary" onClick={() => (showForm ? setShowForm(false) : openCreate())}>
              {showForm ? 'Fermer' : '+ Nouvelle équipe'}
            </Button>
          ) : undefined
        }
      />
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {showForm && (
        <Card className="mb-4 p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Nom *">
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
            <Field label="Téléphone">
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
            <Field label="Spécialités (séparées par des virgules)">
              <input
                value={fSpecialties}
                onChange={(e) => setFSpecialties(e.target.value)}
                placeholder="forage, pompes manuelles"
                className={INPUT_CLS}
              />
            </Field>
            <label className="flex items-center gap-2 text-sm text-ink-soft">
              <input type="checkbox" checked={fActive} onChange={(e) => setFActive(e.target.checked)} />
              Équipe active
            </label>
          </div>
          <div className="mt-3 flex gap-2">
            <Button variant="primary" disabled={busy} onClick={() => void save()}>
              {busy ? 'Enregistrement…' : editing ? 'Mettre à jour' : 'Enregistrer'}
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

      <div className="mb-2 flex flex-col gap-2 sm:flex-row">
        <div className="sm:max-w-sm sm:flex-1">
          <input
            placeholder="Rechercher une équipe…"
            value={searchV}
            onChange={(e) => setSearchV(e.target.value)}
            aria-label="Rechercher une équipe"
            className={INPUT_CLS}
          />
        </div>
        <div className="sm:max-w-xs sm:flex-1">
          <input
            placeholder="Filtrer par district…"
            value={districtV}
            onChange={(e) => setDistrictV(e.target.value)}
            aria-label="Filtrer par district"
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
          Actives uniquement
        </label>
        {hasFilters && (
          <Button variant="ghost" onClick={resetFilters}>
            Réinitialiser
          </Button>
        )}
      </div>
      <p aria-live="polite" className="mb-4 text-xs text-ink-soft">
        {loading && items.length === 0 ? 'Recherche en cours…' : `${fmtNum(total)} résultat(s)`}
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
              title={hasFilters ? 'Aucune équipe trouvée' : 'Aucune équipe'}
              description={
                hasFilters
                  ? 'Aucune équipe ne correspond à ces critères.'
                  : 'Aucune équipe de maintenance pour le moment.'
              }
              action={
                hasFilters ? (
                  <Button onClick={resetFilters}>Réinitialiser les filtres</Button>
                ) : admin ? (
                  <Button variant="primary" onClick={openCreate}>
                    + Nouvelle équipe
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
              {(t.specialties ?? []).length > 0 ? (t.specialties ?? []).join(' · ') : 'Sans spécialité renseignée'}
              {t.phone ? ` — ${t.phone}` : ''}
            </p>
            {admin && (
              <div className="mt-2 flex gap-2">
                <Button size="sm" onClick={() => openEdit(t)}>
                  Modifier
                </Button>
                <Button size="sm" variant="danger" disabled={deleting === t.id} onClick={() => void remove(t)}>
                  {deleting === t.id ? 'Suppression…' : 'Supprimer'}
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
