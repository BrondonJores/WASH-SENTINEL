import { useState } from 'react';
import type { FormEvent } from 'react';
import type { ProfilePayload, ProviderType } from '../lib/api';
import { Button } from './ui';

export interface FormInitial {
  providerId: string;
  name: string;
  values: Record<string, string>;
  timeout: number;
  threads: number;
  language: string;
}

interface Props {
  framed?: boolean;
  kind: 'llm' | 'stt';
  types: ProviderType[];
  initial: FormInitial | null;
  submitting: boolean;
  serverError: string | null;
  onSubmit: (payload: ProfilePayload) => void;
  onCancel: () => void;
}

const inputCls =
  'w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 focus:border-teal-700 focus:outline-none dark:border-stone-700 dark:bg-stone-900 dark:text-stone-100';

export default function ProfileForm({ framed = true, kind, types, initial, submitting, serverError, onSubmit, onCancel }: Props) {
  const isEdit = initial !== null;
  const [providerId, setProviderId] = useState(initial?.providerId ?? types[0]?.id ?? '');
  const [name, setName] = useState(initial?.name ?? '');
  const [values, setValues] = useState<Record<string, string>>(initial?.values ?? {});
  const [apiKey, setApiKey] = useState('');
  const [timeout, setTimeout] = useState(initial?.timeout ?? 120);
  const [threads, setThreads] = useState(initial?.threads ?? 2);
  const [language, setLanguage] = useState(initial?.language ?? 'fr');

  const type = types.find((t) => t.id === providerId) ?? types[0];
  if (!type) return <p className="text-sm text-stone-600 dark:text-stone-400">Types de providers indisponibles.</p>;

  const setValue = (field: string, v: string) => setValues((m) => ({ ...m, [field]: v }));
  const clean = (v: string | undefined) => (v && v.trim() !== '' ? v.trim() : undefined);

  const changeProvider = (id: string) => {
    setProviderId(id);
    const next = types.find((t) => t.id === id);
    const fresh: Record<string, string> = {};
    for (const f of next?.fields ?? []) fresh[f.name] = f.default;
    setValues(fresh);
    setApiKey('');
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const payload: ProfilePayload = { name: name.trim(), timeout };
    if (kind === 'llm') {
      payload.provider = providerId;
      payload.base_url = values.base_url ?? '';
      payload.model = values.model ?? '';
      const vision = clean(values.vision_model);
      const embed = clean(values.embed_model);
      if (vision) payload.vision_model = vision;
      if (embed) payload.embed_model = embed;
    } else {
      payload.driver = providerId;
      const base = clean(values.base_url);
      const model = clean(values.model);
      const tokens = clean(values.tokens);
      if (base) payload.base_url = base;
      if (model) payload.model = model;
      if (tokens) payload.tokens_path = tokens;
      payload.default_language = language.trim() || 'fr';
      payload.threads = threads;
    }
    if (apiKey.trim() !== '') payload.api_key = apiKey;
    onSubmit(payload);
  };

  return (
    <form
      onSubmit={submit}
      className={
        framed
          ? 'space-y-4 rounded-lg border border-stone-200 bg-white p-5 dark:border-stone-800 dark:bg-stone-900'
          : 'space-y-4 border-t border-stone-200 pt-4 dark:border-stone-800'
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor={`name-${kind}`} className="mb-1 block text-sm font-medium text-stone-700 dark:text-stone-300">
            Nom du profil
          </label>
          <input
            id={`name-${kind}`}
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={kind === 'llm' ? 'Llama 3.2 Local' : 'Omnilingual douala'}
            className={inputCls}
          />
        </div>
        <div>
          <label htmlFor={`provider-${kind}`} className="mb-1 block text-sm font-medium text-stone-700 dark:text-stone-300">
            Fournisseur
          </label>
          <select
            id={`provider-${kind}`}
            value={providerId}
            onChange={(e) => changeProvider(e.target.value)}
            className={inputCls}
          >
            {types.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-stone-500 dark:text-stone-400">{type.description}</p>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {type.fields.map((f) => (
          <div key={f.name}>
            <label htmlFor={`${kind}-${f.name}`} className="mb-1 block text-sm font-medium text-stone-700 dark:text-stone-300">
              {f.label}
              {f.required && <span className="text-red-700 dark:text-red-400"> *</span>}
            </label>
            <input
              id={`${kind}-${f.name}`}
              type={f.type === 'number' ? 'number' : 'text'}
              required={f.required}
              value={values[f.name] ?? f.default}
              placeholder={f.default}
              onChange={(e) => setValue(f.name, e.target.value)}
              className={inputCls}
            />
          </div>
        ))}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor={`key-${kind}`} className="mb-1 block text-sm font-medium text-stone-700 dark:text-stone-300">
            Clé API {type.api_key_required && !isEdit ? <span className="text-red-700 dark:text-red-400">*</span> : '(optionnelle)'}
          </label>
          <input
            id={`key-${kind}`}
            type="password"
            autoComplete="off"
            value={apiKey}
            placeholder={isEdit ? 'Vide = inchangée' : 'sk-…'}
            onChange={(e) => setApiKey(e.target.value)}
            className={inputCls}
          />
        </div>
        <div>
          <label htmlFor={`timeout-${kind}`} className="mb-1 block text-sm font-medium text-stone-700 dark:text-stone-300">
            Timeout (secondes)
          </label>
          <input
            id={`timeout-${kind}`}
            type="number"
            min={5}
            max={600}
            value={timeout}
            onChange={(e) => setTimeout(Number(e.target.value))}
            className={inputCls}
          />
        </div>
      </div>

      {kind === 'stt' && (
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="stt-language" className="mb-1 block text-sm font-medium text-stone-700 dark:text-stone-300">
              Langue par défaut
            </label>
            <input
              id="stt-language"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              placeholder="fr, dua_Latn, …"
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="stt-threads" className="mb-1 block text-sm font-medium text-stone-700 dark:text-stone-300">
              Threads CPU
            </label>
            <input
              id="stt-threads"
              type="number"
              min={1}
              max={16}
              value={threads}
              onChange={(e) => setThreads(Number(e.target.value))}
              className={inputCls}
            />
          </div>
        </div>
      )}

      {serverError && <p className="text-sm font-medium text-red-700 dark:text-red-400">{serverError}</p>}

      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={submitting}>
          {submitting ? 'Enregistrement…' : isEdit ? 'Mettre à jour' : 'Créer le profil'}
        </Button>
        <Button type="button" onClick={onCancel}>
          Annuler
        </Button>
      </div>
    </form>
  );
}
