import { useCallback, useEffect, useState } from 'react';
import { api } from '../lib/api';
import type {
  LlmTestResult,
  ModelProfile,
  ProfilePayload,
  ProviderType,
  SttProfile,
  SttTestResult,
} from '../lib/api';
import ProfileForm from '../components/ProfileForm';
import type { FormInitial } from '../components/ProfileForm';

type Kind = 'llm' | 'stt';

const btnSecondary =
  'rounded-md border border-stone-300 px-3 py-1.5 text-sm font-medium text-stone-700 hover:bg-stone-100 disabled:opacity-50';
const btnPrimary =
  'rounded-md bg-teal-800 px-3 py-1.5 text-sm font-semibold text-white hover:bg-teal-900 disabled:opacity-50';
const btnDanger =
  'rounded-md border border-stone-300 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50';

function typeLabel(types: ProviderType[], id: string): string {
  return types.find((t) => t.id === id)?.label ?? id;
}

export default function SettingsPage() {
  const [llmTypes, setLlmTypes] = useState<ProviderType[]>([]);
  const [sttTypes, setSttTypes] = useState<ProviderType[]>([]);
  const [llmProfiles, setLlmProfiles] = useState<ModelProfile[]>([]);
  const [sttProfiles, setSttProfiles] = useState<SttProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ kind: Kind; id: number | null } | null>(null);
  const [formBusy, setFormBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [llmTests, setLlmTests] = useState<Record<number, LlmTestResult>>({});
  const [sttTests, setSttTests] = useState<Record<number, SttTestResult>>({});
  const [sttFiles, setSttFiles] = useState<Record<number, File | undefined>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [pt, pp, st, sp] = await Promise.all([
        api.providerTypes(),
        api.modelProfiles(),
        api.sttTypes(),
        api.sttProfiles(),
      ]);
      setLlmTypes(pt.providers);
      setLlmProfiles(pp);
      setSttTypes(st.drivers);
      setSttProfiles(sp);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Chargement impossible.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const editingInitial = (): FormInitial | null => {
    if (!editing || editing.id === null) return null;
    if (editing.kind === 'llm') {
      const p = llmProfiles.find((x) => x.id === editing.id);
      if (!p) return null;
      return {
        providerId: p.provider,
        name: p.name,
        values: {
          base_url: p.base_url,
          model: p.model,
          vision_model: p.vision_model ?? '',
          embed_model: p.embed_model ?? '',
        },
        timeout: p.timeout,
        threads: 2,
        language: 'fr',
      };
    }
    const p = sttProfiles.find((x) => x.id === editing.id);
    if (!p) return null;
    return {
      providerId: p.driver,
      name: p.name,
      values: { base_url: p.base_url ?? '', model: p.model ?? '', tokens: p.tokens_path ?? '' },
      timeout: p.timeout,
      threads: p.threads,
      language: p.default_language,
    };
  };

  const save = async (kind: Kind, payload: ProfilePayload) => {
    if (!editing) return;
    setFormBusy(true);
    setFormError(null);
    try {
      if (kind === 'llm') {
        if (editing.id === null) await api.createModelProfile(payload);
        else await api.updateModelProfile(editing.id, payload);
      } else {
        if (editing.id === null) await api.createSttProfile(payload);
        else await api.updateSttProfile(editing.id, payload);
      }
      setEditing(null);
      await load();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Enregistrement impossible.');
    } finally {
      setFormBusy(false);
    }
  };

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action impossible.');
    } finally {
      setBusy(null);
    }
  };

  const remove = (kind: Kind, id: number, name: string) => {
    if (!window.confirm(`Supprimer le profil « ${name} » ?`)) return;
    void run(`${kind}-del-${id}`, async () => {
      if (kind === 'llm') await api.deleteModelProfile(id);
      else await api.deleteSttProfile(id);
    });
  };

  if (loading) return <p className="text-sm text-stone-600">Chargement des réglages…</p>;

  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-xl font-bold">Réglages IA</h1>
        <p className="mt-1 text-sm text-stone-600">
          Basculez le moteur entre modèle local et API externe, sans redémarrage. Un seul profil actif par famille.
        </p>
        {error && (
          <div className="mt-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800">
            {error}{' '}
            <button onClick={() => void load()} className="font-semibold underline">
              Réessayer
            </button>
          </div>
        )}
      </div>

      <ProfileSection
        kind="llm"
        title="Modèles de langage"
        description="Extraction, analyse, agent conversationnel et embeddings."
        types={llmTypes}
        profiles={llmProfiles}
        tests={llmTests}
        busy={busy}
        editing={editing}
        editingInitial={editing?.kind === 'llm' ? editingInitial() : null}
        formBusy={formBusy}
        formError={formError}
        onNew={() => { setFormError(null); setEditing({ kind: 'llm', id: null }); }}
        onEdit={(id) => { setFormError(null); setEditing({ kind: 'llm', id }); }}
        onCancel={() => setEditing(null)}
        onSave={(p) => void save('llm', p)}
        onActivate={(id) => void run(`llm-act-${id}`, async () => { await api.activateModelProfile(id); })}
        onTest={(id) => void run(`llm-test-${id}`, async () => {
          const r = await api.testModelProfile(id);
          setLlmTests((m) => ({ ...m, [id]: r }));
        })}
        onDelete={(id, name) => remove('llm', id, name)}
      />

      <ProfileSection
        kind="stt"
        title="Transcription vocale"
        description="Whisper local, Omnilingual Meta (langues locales) ou API cloud."
        types={sttTypes}
        profiles={sttProfiles}
        tests={sttTests}
        busy={busy}
        editing={editing}
        editingInitial={editing?.kind === 'stt' ? editingInitial() : null}
        formBusy={formBusy}
        formError={formError}
        files={sttFiles}
        onFile={(id, f) => setSttFiles((m) => ({ ...m, [id]: f }))}
        onNew={() => { setFormError(null); setEditing({ kind: 'stt', id: null }); }}
        onEdit={(id) => { setFormError(null); setEditing({ kind: 'stt', id }); }}
        onCancel={() => setEditing(null)}
        onSave={(p) => void save('stt', p)}
        onActivate={(id) => void run(`stt-act-${id}`, async () => { await api.activateSttProfile(id); })}
        onTest={(id) => {
          const file = sttFiles[id];
          if (!file) {
            setError('Choisissez un fichier audio pour tester ce profil.');
            return;
          }
          void run(`stt-test-${id}`, async () => {
            const profile = sttProfiles.find((x) => x.id === id);
            const r = await api.testSttProfile(id, file, profile?.default_language);
            setSttTests((m) => ({ ...m, [id]: r }));
          });
        }}
        onDelete={(id, name) => remove('stt', id, name)}
      />
    </div>
  );
}

interface SectionProps {
  kind: Kind;
  title: string;
  description: string;
  types: ProviderType[];
  profiles: (ModelProfile | SttProfile)[];
  tests: Record<number, LlmTestResult | SttTestResult>;
  busy: string | null;
  editing: { kind: Kind; id: number | null } | null;
  editingInitial: FormInitial | null;
  formBusy: boolean;
  formError: string | null;
  files?: Record<number, File | undefined>;
  onFile?: (id: number, f: File | undefined) => void;
  onNew: () => void;
  onEdit: (id: number) => void;
  onCancel: () => void;
  onSave: (p: ProfilePayload) => void;
  onActivate: (id: number) => void;
  onTest: (id: number) => void;
  onDelete: (id: number, name: string) => void;
}

function ProfileSection(props: SectionProps) {
  const { kind, title, description, types, profiles, tests, busy, editing, editingInitial } = props;
  const driverOf = (p: ModelProfile | SttProfile) => ('provider' in p ? p.provider : p.driver);
  const modelOf = (p: ModelProfile | SttProfile) => p.model ?? '—';

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">{title}</h2>
          <p className="text-sm text-stone-600">{description}</p>
        </div>
        <button onClick={props.onNew} className={btnPrimary}>
          Nouveau profil
        </button>
      </div>

      {editing?.kind === kind && editing.id === null && (
        <div className="mb-4">
          <ProfileForm
            key={`${kind}-new`}
            kind={kind}
            types={types}
            initial={null}
            submitting={props.formBusy}
            serverError={props.formError}
            onSubmit={props.onSave}
            onCancel={props.onCancel}
          />
        </div>
      )}

      <div className="space-y-3">
        {profiles.map((p) => (
          <article key={p.id} className="rounded-lg border border-stone-200 bg-white p-4">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-semibold">{p.name}</h3>
              <span className="rounded bg-stone-100 px-2 py-0.5 text-xs text-stone-700">
                {typeLabel(types, driverOf(p))}
              </span>
              {p.is_active && (
                <span className="rounded bg-teal-800 px-2 py-0.5 text-xs font-semibold text-white">ACTIF</span>
              )}
              {p.last_test_status && (
                <span
                  className={`rounded px-2 py-0.5 text-xs ${
                    p.last_test_status === 'success' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                  }`}
                >
                  test {p.last_test_status === 'success' ? 'réussi' : 'échoué'}
                  {p.last_test_latency_ms ? ` · ${p.last_test_latency_ms} ms` : ''}
                </span>
              )}
            </div>
            <p className="mt-1 text-sm text-stone-600">
              {modelOf(p)}
              {p.api_key_masked ? ` · clé ${p.api_key_masked}` : ''}
            </p>

            {kind === 'stt' && (
              <div className="mt-2">
                <input
                  type="file"
                  accept="audio/*"
                  onChange={(e) => props.onFile?.(p.id, e.target.files?.[0])}
                  className="text-sm text-stone-600"
                />
              </div>
            )}

            <div className="mt-3 flex flex-wrap gap-2">
              <button onClick={() => props.onTest(p.id)} disabled={busy !== null} className={btnPrimary}>
                Tester
              </button>
              {!p.is_active && (
                <button onClick={() => props.onActivate(p.id)} disabled={busy !== null} className={btnSecondary}>
                  Activer
                </button>
              )}
              <button onClick={() => props.onEdit(p.id)} disabled={busy !== null} className={btnSecondary}>
                Modifier
              </button>
              <button onClick={() => props.onDelete(p.id, p.name)} disabled={busy !== null || p.is_active} className={btnDanger}>
                Supprimer
              </button>
            </div>

            {tests[p.id] && <TestResultView result={tests[p.id]} />}

            {editing?.kind === kind && editing.id === p.id && (
              <div className="mt-4">
                <ProfileForm
                  key={`${kind}-${p.id}`}
                  kind={kind}
                  types={types}
                  initial={editingInitial}
                  submitting={props.formBusy}
                  serverError={props.formError}
                  onSubmit={props.onSave}
                  onCancel={props.onCancel}
                />
              </div>
            )}
          </article>
        ))}
        {profiles.length === 0 && <p className="text-sm text-stone-600">Aucun profil pour le moment.</p>}
      </div>
    </section>
  );
}

function TestResultView({ result }: { result: LlmTestResult | SttTestResult }) {
  const output = 'sample' in result ? result.sample : result.transcript;
  return (
    <div
      className={`mt-3 rounded-md border p-3 text-sm ${
        result.ok ? 'border-green-300 bg-green-50 text-green-900' : 'border-red-300 bg-red-50 text-red-900'
      }`}
    >
      <p className="font-semibold">
        {result.ok ? `Test réussi en ${result.latency_ms} ms` : 'Test échoué'}
      </p>
      {result.ok && output && <pre className="mt-1 whitespace-pre-wrap text-xs">{output.slice(0, 400)}</pre>}
      {!result.ok && result.error && <pre className="mt-1 whitespace-pre-wrap text-xs">{result.error}</pre>}
    </div>
  );
}
