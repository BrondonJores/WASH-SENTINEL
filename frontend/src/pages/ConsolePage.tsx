import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../lib/api';
import type { AgentCard, ChatHistoryMessage } from '../lib/api';
import { SentinelOrb } from '../components/SentinelOrb';
import { AgentCardList } from '../components/AgentCards';
import { Badge, Button, StatusDot } from '../components/ui';
import { Icon } from '../components/icons';

interface Msg {
  role: 'user' | 'assistant';
  content: string;
  tools: string[];
  cards: AgentCard[];
  model: string;
}

const SUGGESTIONS = [
  'Quelles écoles ont le plus besoin d\u2019aide ?',
  'Résume la situation du district',
  'Quel est l\u2019état des incidents ouverts ?',
];

const inputCls =
  'h-11 w-full rounded-md border border-stone-300 bg-white px-3 text-sm text-stone-900 placeholder:text-stone-400 focus:border-teal-700 focus:outline-none dark:border-stone-700 dark:bg-stone-900 dark:text-stone-100 dark:placeholder:text-stone-500';

export default function ConsolePage() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const smooth = !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    bottomRef.current?.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'end' });
  }, [messages, busy]);

  const send = async (raw: string) => {
    const message = raw.trim();
    if (message === '' || busy) return;
    setError(null);
    setBusy(true);
    setInput('');
    const prior: ChatHistoryMessage[] = messages
      .slice(-19)
      .map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, { role: 'user', content: message, tools: [], cards: [], model: '' }]);
    try {
      const res = await api.converse(message, prior);
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: res.answer,
          tools: res.tools_executed ?? [],
          cards: res.cards ?? [],
          model: res.model_used ?? '',
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sentinel est injoignable.');
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void send(input);
  };

  const composer = (
    <form onSubmit={submit} className="flex items-center gap-2">
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        maxLength={2000}
        placeholder="Posez votre question à Sentinel…"
        aria-label="Message à Sentinel"
        className={inputCls}
      />
      <Button type="submit" variant="primary" disabled={busy || input.trim() === ''} aria-label="Envoyer">
        <Icon name="send" className="h-4 w-4" />
      </Button>
    </form>
  );

  const lastModel = [...messages].reverse().find((m) => m.role === 'assistant' && m.model !== '')?.model ?? '';

  if (messages.length === 0 && !busy) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col items-center px-4 pb-10 pt-8 text-center sm:pt-14">
        <SentinelOrb state="idle" size="lg" />
        <h1 className="mt-6 text-2xl font-bold tracking-tight">Sentinel</h1>
        <p className="mt-1 font-mono text-[11px] uppercase tracking-[0.18em] text-stone-500 dark:text-stone-400">
          Console IA — incidents, écoles, décisions
        </p>
        <p className="mt-3 max-w-md text-sm text-stone-600 dark:text-stone-400">
          Interrogez le territoire en langage naturel. Sentinel consulte les données, montre ses outils et répond
          en cartes vérifiables.
        </p>
        <div className="mt-5 flex w-full flex-col gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => void send(s)}
              className="rounded-md border border-stone-200 bg-white px-3 py-2 text-left text-sm text-stone-700 hover:border-teal-700 hover:text-stone-900 dark:border-stone-800 dark:bg-stone-900 dark:text-stone-300 dark:hover:border-teal-500 dark:hover:text-stone-100"
            >
              <span className="mr-2 font-mono text-teal-700 dark:text-teal-400">›</span>
              {s}
            </button>
          ))}
        </div>
        <div className="mt-4 w-full">{composer}</div>
        {error && (
          <p className="mt-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
            {error}
          </p>
        )}
      </div>
    );
  }

  return (
    <div>
      <div className="mb-4 flex items-center gap-3 border-b border-stone-200 pb-3 dark:border-stone-800">
        <SentinelOrb state={busy ? 'thinking' : 'idle'} size="sm" />
        <div className="min-w-0">
          <p className="text-[15px] font-bold leading-tight tracking-tight">Sentinel</p>
          <p className="truncate font-mono text-[11px] text-stone-500 dark:text-stone-400">
            {lastModel !== '' ? `modèle : ${lastModel}` : 'console IA'}
          </p>
        </div>
        <div className="flex-1" />
        <Button
          size="sm"
          onClick={() => {
            setMessages([]);
            setError(null);
          }}
        >
          Nouvelle discussion
        </Button>
      </div>

      <div className="space-y-5">
        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div
              key={i}
              className="rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-sm dark:border-stone-800 dark:bg-stone-900"
            >
              <span className="mr-2 font-mono font-bold text-teal-700 dark:text-teal-400">›</span>
              {m.content}
            </div>
          ) : (
            <div key={i} className="space-y-2">
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{m.content}</p>
              {m.tools.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-mono text-[11px] text-stone-500 dark:text-stone-400">outils :</span>
                  {m.tools.map((t) => (
                    <Badge key={t} className="font-mono">
                      {t}
                    </Badge>
                  ))}
                </div>
              )}
              <AgentCardList cards={m.cards} />
            </div>
          ),
        )}
        {busy && (
          <div className="flex items-center gap-2 text-sm text-stone-600 dark:text-stone-400">
            <StatusDot tone="live" pulse />
            Sentinel consulte les données…
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {error && (
        <p className="mt-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          {error}
        </p>
      )}

      <div className="sticky bottom-0 -mx-1 mt-4 bg-white/90 px-1 py-3 backdrop-blur dark:bg-stone-950/90">
        {composer}
      </div>
    </div>
  );
}
