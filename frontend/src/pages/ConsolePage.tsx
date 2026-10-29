import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../lib/api';
import type { AgentCard, ChatHistoryMessage } from '../lib/api';
import { useAuth } from '../auth/AuthContext';
import { SentinelOrb } from '../components/SentinelOrb';
import type { OrbState } from '../components/SentinelOrb';
import { AgentCardList } from '../components/AgentCards';
import { Badge, Button, LiveClock, StatusDot } from '../components/ui';
import { Icon } from '../components/icons';

interface Msg {
  role: 'user' | 'assistant';
  content: string;
  tools: string[];
  cards: AgentCard[];
  model: string;
  at: number;
}

const SUGGESTIONS = [
  'Quelles écoles ont le plus besoin d\u2019aide ?',
  'Résume la situation du district',
  'Quel est l\u2019état des incidents ouverts ?',
  'Faut-il réparer ou remplacer à Ngok ?',
  'Tendances de Bonanjo sur 3 mois',
];

const CHUNK = 8;
const TICK_MS = 18;

const inputCls =
  'h-11 w-full rounded-md border border-stone-300 bg-white px-3 text-sm text-stone-900 placeholder:text-stone-400 focus:border-teal-700 focus:outline-none dark:border-stone-700 dark:bg-stone-900 dark:text-stone-100 dark:placeholder:text-stone-500';

const inputClsLarge =
  'h-14 w-full rounded-xl border border-stone-300 bg-white px-4 text-[15px] text-stone-900 placeholder:text-stone-400 focus:border-teal-700 focus:outline-none focus:ring-2 focus:ring-teal-600/30 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-100 dark:placeholder:text-stone-500 dark:focus:ring-teal-500/30';

function fmtTime(at: number): string {
  return new Date(at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
}

function greeting(hour: number): string {
  if (hour < 5) return 'Bonne nuit';
  if (hour < 18) return 'Bonjour';
  return 'Bonsoir';
}

function CopyAnswer({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard
          ?.writeText(text)
          .then(() => {
            setDone(true);
            window.setTimeout(() => setDone(false), 1500);
          })
          .catch(() => undefined);
      }}
      className="font-mono text-[11px] text-stone-500 hover:text-teal-700 dark:text-stone-400 dark:hover:text-teal-400"
    >
      {done ? 'Copié !' : 'Copier'}
    </button>
  );
}

export default function ConsolePage() {
  const { user } = useAuth();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamId, setStreamId] = useState<number | null>(null);
  const [visible, setVisible] = useState(0);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [calm] = useState(
    () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false,
  );
  const [hour] = useState(() => new Date().getHours());

  const streaming = streamId !== null;
  const orb: OrbState = busy ? 'thinking' : streaming ? 'speaking' : 'idle';
  const senseTone = error && !busy && !streaming ? 'sense-error' : busy || streaming ? 'sense-busy' : 'sense-idle';

  useEffect(() => {
    bottomRef.current?.scrollIntoView({
      behavior: !calm && !streaming ? 'smooth' : 'auto',
      block: 'end',
    });
  }, [messages, busy, visible, calm, streaming]);

  useEffect(() => {
    if (streamId === null) return;
    const t = window.setTimeout(() => {
      const full = messages[streamId]?.content ?? '';
      if (visible >= full.length) {
        setStreamId(null);
        inputRef.current?.focus();
      } else {
        setVisible((v) => v + CHUNK);
      }
    }, TICK_MS);
    return () => window.clearTimeout(t);
  }, [streamId, visible, messages]);

  const send = async (raw: string) => {
    const message = raw.trim();
    if (message === '' || busy || streaming) return;
    setError(null);
    setBusy(true);
    setInput('');
    const prior: ChatHistoryMessage[] = messages
      .slice(-19)
      .map((m) => ({ role: m.role, content: m.content }));
    const idx = messages.length + 1;
    setMessages((prev) => [...prev, { role: 'user', content: message, tools: [], cards: [], model: '', at: Date.now() }]);
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
          at: Date.now(),
        },
      ]);
      if (!calm && res.answer !== '') {
        setVisible(0);
        setStreamId(idx);
      }
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

  const placeholder = busy
    ? 'Sentinel consulte les données…'
    : streaming
      ? 'Sentinel rédige…'
      : 'Posez votre question à Sentinel…';

  const composer = (large: boolean) => (
    <form onSubmit={submit} className="flex items-center gap-2">
      <input
        ref={inputRef}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        maxLength={2000}
        placeholder={placeholder}
        aria-label="Message à Sentinel"
        disabled={busy || streaming}
        className={large ? inputClsLarge : inputCls}
      />
      <Button
        type="submit"
        variant="primary"
        disabled={busy || streaming || input.trim() === ''}
        aria-label="Envoyer"
        className={large ? 'h-14 w-14 shrink-0' : 'shrink-0'}
      >
        <Icon name="send" className="h-4 w-4" />
      </Button>
    </form>
  );

  const lastModel = [...messages].reverse().find((m) => m.role === 'assistant' && m.model !== '')?.model ?? '';

  const sense = (
    <div
      aria-hidden="true"
      className={`sense pointer-events-none fixed inset-0 ${senseTone} ${busy || streaming ? 'sense-thinking' : ''}`}
    />
  );

  const errorBox = error && (
    <p className="mt-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
      {error}
    </p>
  );

  if (messages.length === 0 && !busy) {
    const first = user?.name?.split(/\s+/)[0] ?? '';
    return (
      <div className="relative">
        {sense}
        <div className="relative z-10 mx-auto flex max-w-2xl flex-col items-center px-4 pb-10 pt-6 text-center sm:pt-10">
          <SentinelOrb state="idle" size="lg" />
          <p className="mt-5 font-mono text-[11px] uppercase tracking-[0.18em] text-stone-500 dark:text-stone-400">
            <LiveClock /> — console IA
          </p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight">
            {greeting(hour)}
            {first !== '' ? `, ${first}` : ''}.
          </h1>
          <p className="mt-2 max-w-md text-sm text-stone-600 dark:text-stone-400">
            Je consulte les écoles, les incidents et les coûts — et je montre mes outils et mes cartes.
          </p>
          <div className="mt-6 w-full">{composer(true)}</div>
          <div className="mt-3 flex w-full gap-2 overflow-x-auto pb-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => void send(s)}
                className="shrink-0 whitespace-nowrap rounded-full border border-stone-200 bg-white px-3 py-1.5 text-left text-[13px] text-stone-700 hover:border-teal-700 hover:text-stone-900 dark:border-stone-800 dark:bg-stone-900 dark:text-stone-300 dark:hover:border-teal-500 dark:hover:text-stone-100"
              >
                {s}
              </button>
            ))}
          </div>
          {errorBox}
        </div>
      </div>
    );
  }

  return (
    <div className="relative">
      {sense}
      <div className="relative z-10">
        <div className="mb-4 flex items-center gap-3 border-b border-stone-200 pb-3 dark:border-stone-800">
          <SentinelOrb state={orb} size="sm" />
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
              setStreamId(null);
            }}
          >
            Nouvelle discussion
          </Button>
        </div>

        <div className="space-y-5">
          {messages.map((m, i) =>
            m.role === 'user' ? (
              <div key={i}>
                <div className="msg-in rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-sm dark:border-stone-800 dark:bg-stone-900">
                  <span className="mr-2 font-mono font-bold text-teal-700 dark:text-teal-400">›</span>
                  {m.content}
                </div>
                <p className="mt-1 text-right font-mono text-[11px] text-stone-400 dark:text-stone-500">
                  {fmtTime(m.at)}
                </p>
              </div>
            ) : (
              <div key={i} className="msg-in space-y-2">
                <p className="whitespace-pre-wrap text-[15px] leading-7">
                  {streamId === i ? m.content.slice(0, visible) : m.content}
                  {streamId === i && <span className="stream-caret" aria-hidden="true" />}
                </p>
                {streamId !== i && (
                  <>
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-[11px] text-stone-400 dark:text-stone-500">
                        {fmtTime(m.at)}
                      </span>
                      <CopyAnswer text={m.content} />
                    </div>
                    {m.tools.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="font-mono text-[11px] text-stone-500 dark:text-stone-400">outils :</span>
                        {m.tools.map((t, j) => (
                          <Badge key={`${t}-${j}`} className="msg-in font-mono" >
                            {t}
                          </Badge>
                        ))}
                      </div>
                    )}
                    <div className="cards-in">
                      <AgentCardList cards={m.cards} />
                    </div>
                  </>
                )}
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

        {errorBox}

        <div className="sticky bottom-0 -mx-1 mt-4 bg-white/90 px-1 py-3 backdrop-blur dark:bg-stone-950/90">
          {composer(false)}
        </div>
      </div>
    </div>
  );
}
