import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { School } from '../lib/api';
import { useAuth } from '../auth/AuthContext';
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton } from '../components/ui';
import { ErrorBanner, Field, Pager } from '../components/crud';
import {
  INPUT_CLS,
  STATUS_FR,
  URGENCY_FR,
  fmtDate,
  fmtNum,
  statusTone,
  urgencyTone,
} from '../lib/wash';

const errMsg = (e: unknown): string => (e instanceof ApiError ? e.message : 'Erreur réseau.');
const toNum = (v: string): number | undefined => (v === '' ? undefined : Number(v));

export default function SchoolsPage() {
  const { user } = useAuth();
  const admin = user?.roles.includes('wash_admin') ?? false;

  const [items, setItems] = useState<School[]>([]);
  const [page, setPage] = useState(1);
  const [lastPage, setLastPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [searchV, setSearchV] = useState('');

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<School | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [showForm, setShowForm] = useState(false);
  const [fName, setFName] = useState('');
  const [fCode, setFCode] = useState('');
  const [fDistrict, setFDistrict] = useState('');
  const [fStudents, setFStudents] = useState('');
  const [fTeachers, setFTeachers] = useState('');
  const [fPhone, setFPhone] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.schools({ page, search: search || undefined });
      setItems(res.data);
      setLastPage(res.last_page);
      setTotal(res.total);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, [page, search]);

  useEffect(() => {
    void load();
  }, [load]);

  const select = useCallback(async (id: number) => {
    setSelectedId(id);
    setDetailLoading(true);
    try {
      setDetail(await api.school(id));
    } catch (e) {
      setDetail(null);
      setMsg(errMsg(e));
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const create = async () => {
    if (busy || !fName || !fCode || !fDistrict) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.createSchool({
        name: fName,
        code: fCode,
        district: fDistrict,
        student_count: toNum(fStudents),
        teacher_count: toNum(fTeachers),
        contact_phone: fPhone || undefined,
      });
      setMsg(res.message);
      setShowForm(false);
      setFName('');
      setFCode('');
      setFDistrict('');
      setFStudents('');
      setFTeachers('');
      setFPhone('');
      await load();
      await select(res.school.id);
    } catch (e) {
      setMsg(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-6xl">
      <PageHeader
        title="Écoles"
        description={`Établissements suivis — ${fmtNum(total)} au total.`}
        actions={
          admin ? (
            <Button variant="primary" onClick={() => setShowForm((v) => !v)}>
              {showForm ? 'Fermer' : '+ Nouvelle école'}
            </Button>
          ) : undefined
        }
      />
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {showForm && (
        <Card className="mb-4 p-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Nom *">
              <input value={fName} onChange={(e) => setFName(e.target.value)} className={INPUT_CLS} />
            </Field>
            <Field label="Code *">
              <input value={fCode} onChange={(e) => setFCode(e.target.value)} className={INPUT_CLS} />
            </Field>
            <Field label="District *">
              <input
                value={fDistrict}
                onChange={(e) => setFDistrict(e.target.value)}
                className={INPUT_CLS}
              />
            </Field>
            <Field label="Élèves">
              <input
                type="number"
                min={0}
                value={fStudents}
                onChange={(e) => setFStudents(e.target.value)}
                className={INPUT_CLS}
              />
            </Field>
            <Field label="Enseignants">
              <input
                type="number"
                min={0}
                value={fTeachers}
                onChange={(e) => setFTeachers(e.target.value)}
                className={INPUT_CLS}
              />
            </Field>
            <Field label="Téléphone">
              <input value={fPhone} onChange={(e) => setFPhone(e.target.value)} className={INPUT_CLS} />
            </Field>
          </div>
          <div className="mt-3">
            <Button variant="primary" disabled={busy} onClick={() => void create()}>
              Enregistrer
            </Button>
          </div>
        </Card>
      )}
      {msg && <p className="mb-4 text-sm text-ink-soft">{msg}</p>}

      <form
        className="mb-4 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setSearch(searchV);
        }}
      >
        <input
          placeholder="Rechercher une école…"
          value={searchV}
          onChange={(e) => setSearchV(e.target.value)}
          className={`${INPUT_CLS} max-w-sm`}
        />
        <Button type="submit">Rechercher</Button>
      </form>

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
              <EmptyState icon="school" title="Aucune école" description="Aucun établissement trouvé." />
            </Card>
          )}
          {items.map((s) => (
            <button
              key={s.id}
              onClick={() => void select(s.id)}
              className={`w-full rounded-xl border p-3 text-left transition-colors ${
                selectedId === s.id
                  ? 'border-accent bg-accent/5'
                  : 'border-line bg-card hover:bg-raised'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-ink-faint">{s.code}</span>
                {(s.open_incidents_count ?? 0) > 0 && (
                  <Badge tone="warn">{s.open_incidents_count} ouvert(s)</Badge>
                )}
              </div>
              <p className="mt-1 truncate text-sm font-semibold">{s.name}</p>
              <p className="mt-0.5 truncate text-xs text-ink-soft">
                {s.district} · {fmtNum(s.student_count)} élèves · {s.reports_count ?? 0} signalement(s)
              </p>
            </button>
          ))}
          <Pager page={page} lastPage={lastPage} onPage={setPage} />
        </div>

        <div className="lg:col-span-3">
          {detailLoading && <Skeleton className="h-64" />}
          {!detailLoading && !detail && (
            <Card>
              <EmptyState
                icon="school"
                title="Sélectionnez une école"
                description="Cliquez sur une école pour voir ses incidents et son historique."
              />
            </Card>
          )}
          {!detailLoading && detail && (
            <Card className="space-y-4 p-4">
              <div>
                <span className="font-mono text-xs text-ink-faint">{detail.code}</span>
                <h2 className="mt-1 font-display text-lg font-bold">{detail.name}</h2>
                <p className="text-sm text-ink-soft">
                  {detail.district} · {fmtNum(detail.student_count)} élèves
                  {detail.female_students != null ? ` (dont ${fmtNum(detail.female_students)} filles)` : ''} ·{' '}
                  {fmtNum(detail.teacher_count)} enseignant(s)
                </p>
                <p className="mt-1 text-sm text-ink-soft">
                  {detail.contact_phone ? `Tél : ${detail.contact_phone} · ` : ''}
                  {detail.equipment_type ? `Équipement : ${detail.equipment_type} · ` : ''}
                  {detail.maintenance_logs_count ?? 0} intervention(s) journalisée(s)
                </p>
              </div>
              <div>
                <h3 className="mb-1 text-sm font-semibold">
                  Incidents ouverts ({detail.open_incidents?.length ?? 0})
                </h3>
                {(detail.open_incidents?.length ?? 0) === 0 && (
                  <p className="text-sm text-ink-faint">Aucun incident ouvert.</p>
                )}
                <ul className="space-y-1">
                  {(detail.open_incidents ?? []).map((i) => (
                    <li
                      key={i.id}
                      className="flex items-center justify-between gap-2 rounded-md bg-raised px-2 py-1 text-xs"
                    >
                      <span className="truncate">
                        <span className="font-mono text-ink-faint">{i.reference_code}</span> · {i.title}
                      </span>
                      <span className="flex shrink-0 gap-1">
                        <Badge tone={urgencyTone(i.urgency)}>{URGENCY_FR[i.urgency] ?? i.urgency}</Badge>
                        <Badge tone={statusTone(i.status)}>{STATUS_FR[i.status] ?? i.status}</Badge>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="mb-1 text-sm font-semibold">Dernières interventions</h3>
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
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
