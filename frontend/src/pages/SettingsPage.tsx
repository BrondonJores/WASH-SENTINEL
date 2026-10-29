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
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton } from '../components/ui';
import type { FormInitial } from '../components/ProfileForm';

type Kind = 'llm' | 'stt';


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

  if (loading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-10">
      <div>
        <PageHeader
          title="Réglages IA"
          description="Basculez le moteur entre modèle local et API externe, sans redémarrage. Un seul profil actif par famille."
        />
        {error && (
          <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
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
          <h2 className="text-base font-semibold">{title}</h2>
          <p className="text-sm text-stone-600 dark:text-stone-400">{description}</p>
        </div>
        <Button variant="primary" onClick={props.onNew}>
          Nouveau profil
        </Button>
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
          <Card key={p.id} className="p-4">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-semibold">{p.name}</h3>
              <Badge>{typeLabel(types, driverOf(p))}</Badge>
              {p.is_active && <Badge tone="accent">ACTIF</Badge>}
              {p.last_test_status && (
                <Badge tone={p.last_test_status === 'success' ? 'success' : 'danger'} className="font-mono tabular-nums">
                  test {p.last_test_status === 'success' ? 'réussi' : 'échoué'}
                  {p.last_test_latency_ms ? ` · ${p.last_test_latency_ms} ms` : ''}
                </Badge>
              )}
            </div>
            <p className="mt-1 font-mono text-[13px] text-stone-600 dark:text-stone-400">
              {modelOf(p)}
              {p.api_key_masked ? ` · clé ${p.api_key_masked}` : ''}
            </p>

            {kind === 'stt' && (
              <div className="mt-2">
                <input
                  type="file"
                  accept="audio/*"
                  onChange={(e) => props.onFile?.(p.id, e.target.files?.[0])}
                  className="text-sm text-stone-600 dark:text-stone-400"
                />
              </div>
            )}

            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => props.onTest(p.id)} disabled={busy !== null}>
                Tester
              </Button>
              {!p.is_active && (
                <Button onClick={() => props.onActivate(p.id)} disabled={busy !== null}>
                  Activer
                </Button>
              )}
              <Button onClick={() => props.onEdit(p.id)} disabled={busy !== null}>
                Modifier
              </Button>
              <Button
                variant="danger"
                onClick={() => props.onDelete(p.id, p.name)}
                disabled={busy !== null || p.is_active}
              >
                Supprimer
              </Button>
            </div>

            {tests[p.id] && <TestResultView result={tests[p.id]} />}

            {editing?.kind === kind && editing.id === p.id && (
              <div className="mt-4">
                <ProfileForm
                  key={`${kind}-${p.id}`}
                  framed={false}
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
          </Card>
        ))}
        {profiles.length === 0 && (
          <Card>
            <EmptyState icon="sliders" title="Aucun profil" description="Créez votre premier profil pour activer ce moteur." />
          </Card>
        )}
      </div>
    </section>
  );
}

function TestResultView({ result }: { result: LlmTestResult | SttTestResult }) {
  const output = 'sample' in result ? result.sample : result.transcript;
  return (
    <div
      className={`mt-3 rounded-md border p-3 text-sm ${
        result.ok
          ? 'border-green-300 bg-green-50 text-green-900 dark:border-green-800 dark:bg-green-950 dark:text-green-200'
          : 'border-red-300 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200'
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
