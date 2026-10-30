import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../lib/api';
import type { ChatHistoryMessage, TerritoryPulse } from '../lib/api';
import type { DialogueMessage as Msg } from '../lib/dialogues';
import { useAuth } from '../auth/AuthContext';
import { useDialogues } from '../dialogues/context';
import { SentinelOrb } from '../components/SentinelOrb';
import { SentinelAvatar } from '../components/SentinelAvatar';
import type { OrbState } from '../components/SentinelOrb';
import { AgentCardList } from '../components/AgentCards';
import { Button, StatusDot } from '../components/ui';
import { Icon } from '../components/icons';

const CHUNK = 8;
const TICK_MS = 18;

const BUBBLES = [
  { left: 4, size: 10, dur: 14, delay: 0 },
  { left: 11, size: 16, dur: 19, delay: 4 },
  { left: 19, size: 8, dur: 12, delay: 9 },
  { left: 27, size: 14, dur: 22, delay: 2 },
  { left: 36, size: 7, dur: 16, delay: 12 },
  { left: 47, size: 18, dur: 25, delay: 6 },
  { left: 55, size: 9, dur: 13, delay: 15 },
  { left: 64, size: 15, dur: 21, delay: 1 },
  { left: 72, size: 8, dur: 15, delay: 8 },
  { left: 81, size: 13, dur: 24, delay: 11 },
  { left: 89, size: 10, dur: 17, delay: 5 },
  { left: 95, size: 17, dur: 23, delay: 13 },
];

const HINTS = [
  'Combien d\u2019\u00e9coles sont sans eau aujourd\u2019hui ?',
  'Faut-il r\u00e9parer ou remplacer le mat\u00e9riel \u00e0 Ngok ?',
  'R\u00e9sume la situation du district en un briefing.',
  'Quelles \u00e9coles ont le plus besoin d\u2019aide ?',
  'Tendances de Bonanjo sur 3 mois.',
  'Montre-moi la carte du territoire.',
];

const TOOL_FR: Record<string, string> = {
  summarize_district: 'Synthèse du district',
  rank_schools_by_need: 'Classement des écoles',
  analyze_school: 'Analyse école',
  repair_trends: 'Tendances réparations',
  explain_incident: 'Détail incident',
  prepare_report: 'Signalement',
  territory_overview: 'Carte du territoire',
  build_briefing: 'Briefing',
};

function fmtTime(at: number): string {
  return new Date(at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
}

function greeting(hour: number): string {
  if (hour < 5) return 'Bonne nuit';
  if (hour < 18) return 'Bonjour';
  return 'Bonsoir';
}

function dayMoment(hour: number): string {
  if (hour < 5) return 'Cette nuit';
  if (hour < 12) return 'Ce matin';
  if (hour < 18) return 'Cet après-midi';
  return 'Ce soir';
}

function whisperText(pulse: TerritoryPulse, hour: number): string {
  const schools = `${pulse.schools_tracked} \u00e9cole${pulse.schools_tracked > 1 ? 's' : ''}`;
  if (pulse.open_incidents === 0) return `Tout est calme, je veille sur ${schools}.`;
  const urg = `${pulse.open_incidents} urgence${pulse.open_incidents > 1 ? 's' : ''} ouverte${pulse.open_incidents > 1 ? 's' : ''}`;
  const kids =
    pulse.affected_students > 0
      ? `, ${pulse.affected_students.toLocaleString('fr-FR')} \u00e9l\u00e8ves concern\u00e9s`
      : '';
  return `${dayMoment(hour)} : ${urg}${kids} \u2014 je veille sur ${schools}.`;
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
  const { activeChat, syncMessages, newChat, registerLoader } = useDialogues();
  const [messages, setMessages] = useState<Msg[]>(() => activeChat?.messages ?? []);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamId, setStreamId] = useState<number | null>(null);
  const [visible, setVisible] = useState(0);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const sceneRef = useRef<HTMLDivElement>(null);
  const [headerHidden, setHeaderHidden] = useState(false);
  const lastScrollY = useRef(0);
  const [calm] = useState(
    () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false,
  );
  const [hour] = useState(() => new Date().getHours());
  const [hint, setHint] = useState(0);
  const [hintPaused, setHintPaused] = useState(false);
  const [composerFocus, setComposerFocus] = useState(false);
  const [pulse, setPulse] = useState<TerritoryPulse | null>(null);

  const streaming = streamId !== null;
  const orb: OrbState = busy ? 'thinking' : streaming ? 'speaking' : 'idle';
  const sceneOrb: OrbState = input.trim() !== '' || composerFocus ? 'listening' : 'idle';
  const senseTone = error && !busy && !streaming ? 'sense-error' : busy || streaming ? 'sense-busy' : 'sense-idle';

  useEffect(() => {
    bottomRef.current?.scrollIntoView({
      behavior: !calm && !streaming ? 'smooth' : 'auto',
      block: 'end',
    });
  }, [messages, busy, visible, calm, streaming]);

  useEffect(() => {
    if (messages.length > 0 || busy || hintPaused) return;
    const t = window.setInterval(() => setHint((h) => (h + 1) % HINTS.length), 4200);
    return () => window.clearInterval(t);
  }, [messages.length, busy, hintPaused]);

  useEffect(() => {
    if (messages.length > 0 || busy) return;
    let cancelled = false;
    void (async () => {
      try {
        const data = await api.overview();
        if (!cancelled) setPulse(data);
      } catch {
        /* scène reste pure sans chiffres */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [messages.length, busy]);

  useEffect(() => {
    if (messages.length === 0) return;
    lastScrollY.current = window.scrollY;
    const onScroll = () => {
      const y = window.scrollY;
      const prev = lastScrollY.current;
      if (y > 140 && y > prev + 4) setHeaderHidden(true);
      else if (y < prev - 4 || y <= 140) setHeaderHidden(false);
      lastScrollY.current = y;
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, [messages.length]);

  useEffect(() => {
    registerLoader((chat) => {
      setMessages(chat?.messages ?? []);
      setError(null);
      setStreamId(null);
      setVisible(0);
      setInput('');
      setHeaderHidden(false);
    });
  }, [registerLoader]);

  useEffect(() => {
    if (messages.length === 0) return;
    syncMessages(messages);
  }, [messages, syncMessages]);


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

  const send = useCallback(async (raw: string) => {
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
  }, [busy, streaming, messages, calm]);

  const ask = useCallback(
    (q: string) => {
      void send(q);
    },
    [send],
  );

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setHeaderHidden(false);
    void send(input);
  };

  const placeholder = busy
    ? 'Sentinel consulte les données…'
    : streaming
      ? 'Sentinel rédige…'
      : 'Posez votre question à Sentinel…';

  const composer = (large: boolean) =>
    large ? (
      <form
        onSubmit={submit}
        className="composer-hero glass flex items-center gap-3 rounded-2xl p-2 pl-5 text-left"
      >
        <span aria-hidden="true" className="composer-aura" />
        <svg
          aria-hidden="true"
          viewBox="0 0 20 12"
          className="wave-drift h-4 w-5 shrink-0 text-teal-600 dark:text-teal-300"
        >
          <path
            d="M1 4 Q5.5 1.5 10 4 T19 4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
          <path
            d="M1 9 Q5.5 6.5 10 9 T19 9"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            opacity="0.55"
          />
        </svg>
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          maxLength={2000}
          placeholder={placeholder}
          aria-label="Message à Sentinel"
          disabled={busy || streaming}
          onFocus={() => setComposerFocus(true)}
          onBlur={() => setComposerFocus(false)}
          className="h-12 w-full bg-transparent text-[16px] caret-accent text-ink placeholder:text-ink-faint focus:outline-none"
        />
        <Button
          type="submit"
          variant="primary"
          disabled={busy || streaming || input.trim() === ''}
          aria-label="Envoyer"
          className="btn-drop h-12 w-12 shrink-0"
        >
          <Icon name="send" className="h-5 w-5 -rotate-45" />
        </Button>
      </form>
    ) : (
      <form
        onSubmit={submit}
        className="composer-hero glass flex items-center gap-2 rounded-xl p-1.5 pl-4 text-left"
      >
        <span aria-hidden="true" className="composer-aura" />
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          maxLength={2000}
          placeholder={placeholder}
          aria-label="Message à Sentinel"
          disabled={busy || streaming}
          className="h-10 w-full bg-transparent text-sm caret-accent text-ink placeholder:text-ink-faint focus:outline-none"
        />
        <Button
          type="submit"
          variant="primary"
          disabled={busy || streaming || input.trim() === ''}
          aria-label="Envoyer"
          className="btn-drop h-10 w-10 shrink-0"
        >
          <Icon name="send" className="h-4 w-4 -rotate-45" />
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
    <p className="mt-3 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
      {error}
    </p>
  );

  if (messages.length === 0 && !busy) {
    const first = user?.name?.split(/\s+/)[0] ?? '';
    return (
      <div
        ref={sceneRef}
        onMouseMove={(e) => {
          const el = sceneRef.current;
          if (el === null || calm) return;
          const r = el.getBoundingClientRect();
          el.style.setProperty('--px', ((e.clientX - r.left) / r.width - 0.5).toFixed(3));
          el.style.setProperty('--py', ((e.clientY - r.top) / r.height - 0.5).toFixed(3));
        }}
        className="relative left-1/2 -my-5 w-screen -translate-x-1/2 overflow-hidden"
      >
        <div aria-hidden="true" className="scene-bg" />
        <div aria-hidden="true" className="scene-drift scene-drift-a" />
        <div aria-hidden="true" className="scene-drift scene-drift-b" />
        {BUBBLES.map((b, i) => (
          <span
            key={i}
            aria-hidden="true"
            className="bubble"
            style={{
              left: `${b.left}%`,
              width: b.size,
              height: b.size,
              animationDuration: `${b.dur}s`,
              animationDelay: `${b.delay}s`,
            }}
          />
        ))}
        {sense}
        <div className="relative z-10 mx-auto flex min-h-[100svh] w-full max-w-3xl flex-col items-center justify-center px-4 py-10 text-center">
          <div className="stage-in scene-parallax drop-shadow-[0_36px_70px_rgb(20_184_166/0.4)]">
            <SentinelOrb state={sceneOrb} size="hero" className="orb-birth" />
          </div>
          <h1 className="stage-in stage-2 scene-title mt-6 font-display font-bold tracking-tight">
            {first !== '' ? (
              <>
                <span className="block text-3xl font-semibold text-ink-soft sm:text-4xl">
                  {greeting(hour)},
                </span>
                <span className="relative mt-1 inline-block text-7xl font-extrabold sm:text-8xl">
                  {first}.
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 200 12"
                    preserveAspectRatio="none"
                    className="absolute -bottom-3 left-0 h-3 w-full overflow-visible"
                  >
                    <path
                      d="M2 8 Q 26 2 50 8 T 100 8 T 150 8 T 198 8"
                      fill="none"
                      strokeWidth="4"
                      strokeLinecap="round"
                      className="wave-flow stroke-teal-500 dark:stroke-teal-300"
                    />
                  </svg>
                </span>
              </>
            ) : (
              <span className="text-6xl sm:text-7xl">{greeting(hour)}.</span>
            )}
          </h1>
          <button
            type="button"
            onClick={() => void send(HINTS[hint])}
            onMouseEnter={() => setHintPaused(true)}
            onMouseLeave={() => setHintPaused(false)}
            onFocus={() => setHintPaused(true)}
            onBlur={() => setHintPaused(false)}
            title="Envoyer cette question"
            className="stage-in stage-3 group mt-4 max-w-md text-[15px] text-ink-soft transition-colors hover:text-ink"
          >
            <span className="mr-2 font-mono font-bold text-accent">›</span>
            <span key={hint} className="hint-in">
              {HINTS[hint]}
            </span>
          </button>
          {pulse !== null && (
            <p className="mt-3 font-mono text-[11px] uppercase tracking-[0.14em] text-ink-faint">
              <span className="hint-in">
                <StatusDot tone="live" pulse className="mr-2" />
                {whisperText(pulse, hour)}
              </span>
            </p>
          )}
          <div className="stage-in stage-4 mt-8 w-full">{composer(true)}</div>
          {errorBox}
        </div>
      </div>
    );
  }

  return (
    <div className="relative">
      {sense}
      <div aria-hidden="true" className="scene-bg scene-calm scene-fixed" />
      <div className="relative z-10">
        <div
          className={`msg-in sticky top-0 z-20 -mx-1 mb-2 flex items-center gap-2.5 bg-gradient-to-b from-canvas via-canvas/85 to-transparent px-1 pb-4 pt-2 transition-[transform,opacity] duration-300 ease-snap motion-reduce:transition-none ${headerHidden ? 'pointer-events-none -translate-y-[120%] opacity-0' : ''}`}
        >
          <SentinelOrb state={orb} size="sm" />
          <div className="min-w-0">
            <p className="font-display text-[16px] font-bold leading-tight tracking-tight">Sentinel</p>
            <p className="mt-0.5">
              <span
                className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-line/70 bg-card/60 py-0.5 pl-2 pr-2.5 font-mono text-[10px] text-ink-faint backdrop-blur-md"
                title={lastModel !== '' ? `Modèle IA actif : ${lastModel}` : 'Console IA'}
              >
                <StatusDot tone="live" pulse />
                <span className="truncate">{lastModel !== '' ? lastModel : 'console IA'}</span>
              </span>
            </p>
          </div>
          <div className="flex-1" />
          <button
            type="button"
            onClick={() => newChat()}
            title="Nouvelle discussion"
            aria-label="Nouvelle discussion"
            className="glass flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-ink-soft transition-[transform,color] duration-150 ease-snap hover:text-ink active:scale-95 motion-reduce:transition-none motion-reduce:active:scale-100"
          >
            <Icon name="plus" className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-5">
          {messages.map((m, i) =>
            m.role === 'user' ? (
              <div key={i}>
                <div className="flex justify-end">
                  <div className="msg-in glass max-w-[85%] rounded-2xl rounded-br-md px-4 py-2.5 text-[15px] leading-relaxed">
                    {m.content}
                  </div>
                </div>
                <p className="mt-1 text-right font-mono text-[11px] text-stone-400 dark:text-stone-500">
                  {fmtTime(m.at)}
                </p>
              </div>
            ) : (
              <div key={i} className="msg-in flex gap-3">
                <SentinelAvatar className="mt-1 h-7 w-7 shrink-0" />
                <div className="min-w-0 flex-1 space-y-2">
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
                        <span className="inline-flex items-center gap-1 text-[12px] text-ink-faint">
                          <Icon name="check" className="h-3.5 w-3.5 text-teal-600 dark:text-teal-300" />
                          Vérifié :
                        </span>
                        {m.tools.map((t, j) => (
                          <span
                            key={`${t}-${j}`}
                            className="msg-in rounded-full bg-teal-700/10 px-2.5 py-0.5 text-[12px] font-medium text-teal-800 dark:bg-teal-300/15 dark:text-teal-200"
                          >
                            {TOOL_FR[t] ?? t}
                          </span>
                        ))}
                      </div>
                    )}
                    <div className="cards-in">
                      <AgentCardList cards={m.cards} onAsk={ask} />
                    </div>
                  </>
                )}
                </div>
              </div>
            ),
          )}
          {busy && (
            <div className="msg-in flex items-center gap-3">
              <SentinelAvatar className="h-7 w-7 shrink-0 motion-safe:animate-pulse" />
              <p className="text-sm text-ink-soft">Sentinel consulte les données</p>
              <span className="inline-flex items-center gap-1.5" aria-hidden="true">
                <span className="think-dot" />
                <span className="think-dot" />
                <span className="think-dot" />
              </span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {errorBox}

        <div className="sticky bottom-5 -mx-1 -mb-5 mt-4 bg-gradient-to-t from-canvas via-canvas/70 to-transparent px-1 pb-3 pt-6">
          {composer(false)}
        </div>
      </div>
    </div>
  );
}
