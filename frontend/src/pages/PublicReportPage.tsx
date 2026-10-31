// Page publique (sans compte) : signalement citoyen d'une panne WASH d'école.
// Contrat backend strict (WashReportController@store, lecture seule) :
//   POST /api/v1/wash/reports { school_id, channel?, message? } (throttle 60/min)
//   -> 201 { message, is_duplicate, report, incident, extraction, visual }
// La catégorie, l'urgence estimée et les élèves affectés ne font pas partie
// du contrat : ils sont composés dans `message` (canal "text") pour le tri IA.
import { useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { ApiError, api } from '../lib/api';
import type { Incident, School } from '../lib/api';
import { Badge, Button, Card, Skeleton, StatusDot } from '../components/ui';
import { SentinelAvatar } from '../components/SentinelAvatar';
import { Icon } from '../components/icons';
import { CATEGORY_FR, INPUT_CLS, URGENCY_FR, urgencyTone } from '../lib/wash';

const CATEGORY_KEYS = ['water_point', 'toilets_latrines', 'handwashing', 'sewage_drainage'] as const;
const URGENCY_KEYS = ['low', 'medium', 'high', 'critical'] as const;
const DESCRIPTION_MAX = 4500;

type CategoryKey = (typeof CATEGORY_KEYS)[number];
type UrgencyKey = (typeof URGENCY_KEYS)[number];

interface SuccessState {
  message: string;
  isDuplicate: boolean;
  incident: Incident;
}

const labelCls = 'mb-1 block text-sm font-medium text-ink';
const hintCls = 'mt-1 text-xs text-ink-faint';
const errorCls = 'mt-1 text-xs font-medium text-danger';

function friendlySubmitError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429) return 'Trop de signalements rapprochés. Attendez une minute puis réessayez.';
    if (err.status >= 500) return 'Le service est momentanément indisponible. Réessayez dans quelques instants.';
    return err.message || 'Ce signalement a été refusé. Vérifiez les champs puis réessayez.';
  }
  if (err instanceof TypeError) return 'Pas de connexion internet. Vérifiez votre connexion puis réessayez.';
  return err instanceof Error ? err.message : 'Envoi impossible pour le moment. Réessayez.';
}

export default function PublicReportPage() {
  const [schools, setSchools] = useState<School[]>([]);
  const [schoolsLoading, setSchoolsLoading] = useState(true);
  const [schoolsError, setSchoolsError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [listOpen, setListOpen] = useState(false);

  const [schoolId, setSchoolId] = useState<number | null>(null);
  const [category, setCategory] = useState<CategoryKey | ''>('');
  const [urgency, setUrgency] = useState<UrgencyKey | ''>('');
  const [students, setStudents] = useState('');
  const [description, setDescription] = useState('');

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState<SuccessState | null>(null);

  const searchRef = useRef(0);

  useEffect(() => {
    const id = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(id);
  }, [search]);

  useEffect(() => {
    const run = searchRef.current + 1;
    searchRef.current = run;
    // États mis à jour uniquement dans les callbacks async (pas de setState synchrone).
    api
      .schools(debouncedSearch ? { search: debouncedSearch } : undefined)
      .then((page) => {
        if (searchRef.current !== run) return;
        setSchools(page.data);
        setSchoolsError(null);
      })
      .catch(() => {
        if (searchRef.current !== run) return;
        setSchoolsError("La liste des écoles n'a pas pu être chargée. Vérifiez votre connexion.");
      })
      .finally(() => {
        if (searchRef.current === run) setSchoolsLoading(false);
      });
  }, [debouncedSearch]);

  const selectedSchool = useMemo(
    () => schools.find((s) => s.id === schoolId) ?? null,
    [schools, schoolId],
  );

  const pickSchool = (school: School) => {
    setSchoolId(school.id);
    setSearch(school.name);
    setListOpen(false);
    setFieldErrors((e) => ({ ...e, school: '' }));
  };

  const parsedStudents = students.trim() === '' ? null : Number(students);

  const validate = (): boolean => {
    const errors: Record<string, string> = {};
    if (!schoolId) errors.school = 'Choisissez votre école dans la liste.';
    if (!category) errors.category = 'Choisissez le type de problème.';
    if (!urgency) errors.urgency = 'Choisissez un niveau d’urgence.';
    if (students.trim() !== '') {
      if (!Number.isInteger(parsedStudents) || (parsedStudents as number) < 0) {
        errors.students = 'Indiquez un nombre entier positif (ou laissez vide).';
      } else if ((parsedStudents as number) > 100000) {
        errors.students = 'Nombre trop élevé (maximum 100 000).';
      }
    }
    const desc = description.trim();
    if (desc.length < 10) errors.description = 'Décrivez le problème en au moins 10 caractères.';
    else if (desc.length > DESCRIPTION_MAX)
      errors.description = `Description trop longue (maximum ${DESCRIPTION_MAX} caractères).`;
    setFieldErrors(errors);
    return Object.values(errors).every((v) => !v);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitError(null);
    if (busy || !validate() || !schoolId) return;
    setBusy(true);
    try {
      const header = [
        '[Signalement citoyen]',
        `Catégorie : ${CATEGORY_FR[category as CategoryKey]}`,
        `Urgence estimée : ${URGENCY_FR[urgency as UrgencyKey]}`,
        ...(parsedStudents !== null ? [`Élèves affectés : ${parsedStudents}`] : []),
      ].join('\n');
      const message = `${header}\n\n${description.trim()}`;
      const res = await api.createReport({ school_id: schoolId, message });
      setSuccess({ message: res.message, isDuplicate: res.is_duplicate, incident: res.incident });
      window.scrollTo({ top: 0 });
    } catch (err) {
      setSubmitError(friendlySubmitError(err));
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setSuccess(null);
    setSchoolId(null);
    setSearch('');
    setCategory('');
    setUrgency('');
    setStudents('');
    setDescription('');
    setFieldErrors({});
    setSubmitError(null);
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-canvas px-4 py-8">
      <div aria-hidden="true" className="ambient" />
      <div className="relative z-10 mx-auto w-full max-w-xl">
        <div className="mb-6 flex items-center gap-3">
          <SentinelAvatar className="h-12 w-12 shrink-0" />
          <div>
            <h1 className="font-display text-xl font-bold tracking-tight">Signaler une panne</h1>
            <p className="text-sm text-ink-soft">
              Eau, toilettes, lavage des mains : prévenez l’équipe WASH de votre école.
            </p>
          </div>
        </div>

        {success ? (
          <Card className="p-6">
            <div className="flex flex-col items-center text-center">
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300">
                <Icon name="check" className="h-6 w-6" />
              </span>
              <h2 className="mt-4 font-display text-lg font-bold">Merci, c’est bien reçu !</h2>
              <p className="mt-1 text-sm text-ink-soft">{success.message}</p>
              {success.isDuplicate && (
                <p className="mt-1 text-xs text-ink-faint">
                  Un incident similaire existait déjà : votre signalement y a été rattaché.
                </p>
              )}
            </div>
            <dl className="mt-6 space-y-3 rounded-lg bg-raised p-4 text-sm">
              <div className="flex items-center justify-between gap-3">
                <dt className="text-ink-soft">Référence du dossier</dt>
                <dd className="font-mono font-bold">{success.incident.reference_code}</dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-ink-soft">Urgence</dt>
                <dd>
                  <Badge tone={urgencyTone(success.incident.urgency)}>
                    {URGENCY_FR[success.incident.urgency] ?? success.incident.urgency}
                  </Badge>
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-ink-soft">École</dt>
                <dd className="text-right font-medium">{success.incident.school?.name ?? '—'}</dd>
              </div>
            </dl>
            <p className="mt-4 text-xs text-ink-faint">
              Gardez cette référence : elle permet de suivre votre dossier auprès de l’école.
            </p>
            <Button variant="primary" className="mt-4 w-full" onClick={reset}>
              Faire un autre signalement
            </Button>
          </Card>
        ) : (
          <Card className="p-6">
            <form onSubmit={submit} noValidate className="space-y-5">
              <div>
                <label htmlFor="school-search" className={labelCls}>
                  Votre école <span className="text-danger">*</span>
                </label>
                <div className="relative">
                  <input
                    id="school-search"
                    type="text"
                    autoComplete="off"
                    placeholder="Tapez le nom de l’école…"
                    value={search}
                    onChange={(e) => {
                      setSearch(e.target.value);
                      setListOpen(true);
                      if (schoolId) setSchoolId(null);
                    }}
                    onFocus={() => setListOpen(true)}
                    className={INPUT_CLS}
                    aria-expanded={listOpen}
                    aria-controls="school-listbox"
                    role="combobox"
                    aria-autocomplete="list"
                  />
                  {listOpen && (
                    <div className="absolute inset-x-0 top-full z-20 mt-1 max-h-56 overflow-auto rounded-md border border-line bg-card shadow-lg">
                      {schoolsLoading ? (
                        <div className="space-y-2 p-3" aria-live="polite">
                          <Skeleton className="h-8 w-full" />
                          <Skeleton className="h-8 w-full" />
                        </div>
                      ) : schoolsError ? (
                        <p className="p-3 text-sm text-danger">{schoolsError}</p>
                      ) : schools.length === 0 ? (
                        <p className="p-3 text-sm text-ink-soft">
                          Aucune école trouvée. Essayez un autre nom.
                        </p>
                      ) : (
                        <ul id="school-listbox" role="listbox" aria-label="Écoles">
                          {schools.map((s) => (
                            <li key={s.id}>
                              <button
                                type="button"
                                role="option"
                                aria-selected={s.id === schoolId}
                                onClick={() => pickSchool(s)}
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
                {selectedSchool ? (
                  <p className="mt-1 flex items-center gap-1.5 text-xs text-ink-soft">
                    <StatusDot tone="live" />
                    {selectedSchool.name} — {selectedSchool.district}
                  </p>
                ) : (
                  <p className={hintCls}>Commencez à taper, puis touchez le nom de l’école.</p>
                )}
                {fieldErrors.school && <p className={errorCls}>{fieldErrors.school}</p>}
              </div>

              <fieldset>
                <legend className={labelCls}>
                  Type de problème <span className="text-danger">*</span>
                </legend>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2" role="radiogroup">
                  {CATEGORY_KEYS.map((key) => (
                    <button
                      key={key}
                      type="button"
                      role="radio"
                      aria-checked={category === key}
                      onClick={() => {
                        setCategory(key);
                        setFieldErrors((e) => ({ ...e, category: '' }));
                      }}
                      className={`rounded-md border px-3 py-2.5 text-left text-sm font-medium transition-colors ${
                        category === key
                          ? 'border-accent bg-accent/10 text-ink'
                          : 'border-line bg-card text-ink-soft hover:bg-raised'
                      }`}
                    >
                      {CATEGORY_FR[key]}
                    </button>
                  ))}
                </div>
                {fieldErrors.category && <p className={errorCls}>{fieldErrors.category}</p>}
              </fieldset>

              <fieldset>
                <legend className={labelCls}>
                  Urgence <span className="text-danger">*</span>
                </legend>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" role="radiogroup">
                  {URGENCY_KEYS.map((key) => (
                    <button
                      key={key}
                      type="button"
                      role="radio"
                      aria-checked={urgency === key}
                      onClick={() => {
                        setUrgency(key);
                        setFieldErrors((e) => ({ ...e, urgency: '' }));
                      }}
                      className={`rounded-md border px-2 py-2 text-center text-sm font-medium transition-colors ${
                        urgency === key
                          ? 'border-accent bg-accent/10 text-ink'
                          : 'border-line bg-card text-ink-soft hover:bg-raised'
                      }`}
                    >
                      {URGENCY_FR[key]}
                    </button>
                  ))}
                </div>
                <p className={hintCls}>
                  Critique = danger immédiat (eau contaminée, effondrement…). En cas de danger,
                  prévenez aussi l’école directement.
                </p>
                {fieldErrors.urgency && <p className={errorCls}>{fieldErrors.urgency}</p>}
              </fieldset>

              <div>
                <label htmlFor="students" className={labelCls}>
                  Élèves affectés (si vous savez)
                </label>
                <input
                  id="students"
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={100000}
                  step={1}
                  placeholder="Ex. 120"
                  value={students}
                  onChange={(e) => {
                    setStudents(e.target.value);
                    setFieldErrors((f) => ({ ...f, students: '' }));
                  }}
                  className={INPUT_CLS}
                />
                {fieldErrors.students && <p className={errorCls}>{fieldErrors.students}</p>}
              </div>

              <div>
                <label htmlFor="description" className={labelCls}>
                  Décrivez le problème <span className="text-danger">*</span>
                </label>
                <textarea
                  id="description"
                  rows={4}
                  maxLength={DESCRIPTION_MAX + 100}
                  placeholder="Ex. Le robinet de la cour ne coule plus depuis lundi, les élèves n’ont plus d’eau pour se laver les mains."
                  value={description}
                  onChange={(e) => {
                    setDescription(e.target.value);
                    setFieldErrors((f) => ({ ...f, description: '' }));
                  }}
                  className={INPUT_CLS}
                />
                <p className={hintCls}>
                  {description.trim().length}/{DESCRIPTION_MAX} caractères. Pas besoin de donner votre
                  nom.
                </p>
                {fieldErrors.description && <p className={errorCls}>{fieldErrors.description}</p>}
              </div>

              {submitError && (
                <p role="alert" className="rounded-md bg-danger-soft p-3 text-sm font-medium text-danger">
                  {submitError}
                </p>
              )}

              <Button type="submit" variant="primary" disabled={busy} className="w-full">
                {busy ? 'Envoi en cours…' : 'Envoyer le signalement'}
              </Button>
              <p className="text-center text-xs text-ink-faint">
                Gratuit, sans compte. Vos réponses servent uniquement à réparer plus vite.
              </p>
            </form>
          </Card>
        )}

        <p className="mt-4 text-center text-xs text-ink-faint">
          Membre de l’équipe WASH ?{' '}
          <Link to="/login" className="underline hover:text-ink-soft">
            Se connecter
          </Link>
        </p>
      </div>
    </div>
  );
}
