import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import type { AgentCard, ChatHistoryMessage } from '../lib/api';
import { DEMO_ASK_PAUSE_MS, DEMO_SCRIPT, DEMO_STEP_PAUSE_MS } from '../lib/demoScript';
import { renderRichText } from '../lib/richtext';
import { localeFor } from '../lib/locale';
import { pick, useUILang } from '../lib/i18n';
import { AgentCardList } from './AgentCards';
import { DetailDrawer } from './DetailDrawer';
import type { DetailKind, DetailTarget } from './DetailDrawer';
import { SentinelAvatar } from './SentinelAvatar';

const CHUNK = 8;
const TICK_MS = 18;

interface DemoMsg {
  role: 'user' | 'assistant';
  content: string;
  tools: string[];
  cards: AgentCard[];
  at: number;
  lang?: string;
}

type Phase = 'playing' | 'stopped' | 'done';

function fmtTime(at: number, lang: string): string {
  return new Date(at).toLocaleTimeString(localeFor(lang), { hour: '2-digit', minute: '2-digit' });
}

/**
 * Lecteur de démo rejouable : rejoue tout seul le scénario figé via le
 * vrai `api.converse`. Fil temporaire isolé : la vraie conversation n'est
 * ni lue ni modifiée. FR simple, aria-live poli, pas de typewriter si
 * prefers-reduced-motion.
 */
export function DemoPlayer({ onExit }: { onExit: () => void }) {
  const ui = useUILang();
  const [messages, setMessages] = useState<DemoMsg[]>([]);
  const [stepIdx, setStepIdx] = useState(0);
  const [phase, setPhase] = useState<Phase>('playing');
  const [busy, setBusy] = useState(false);
  const [streamIdx, setStreamIdx] = useState<number | null>(null);
  const [visible, setVisible] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<DetailTarget | null>(null);
  const [calm] = useState(
    () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false,
  );
  const runIdRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const timersRef = useRef<number[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);

  const clearTimers = useCallback(() => {
    for (const t of timersRef.current) window.clearTimeout(t);
    timersRef.current = [];
  }, []);

  const sleep = useCallback(
    (ms: number) =>
      new Promise<void>((resolve) => {
        timersRef.current.push(window.setTimeout(resolve, ms));
      }),
    [],
  );

  /** Interrompt la lecture en cours (requête + minuteurs), garde l'écran. */
  const stop = useCallback(() => {
    runIdRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    clearTimers();
    setBusy(false);
    setStreamIdx(null);
    setPhase((p) => (p === 'playing' ? 'stopped' : p));
  }, [clearTimers]);

  const start = useCallback(() => {
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;
    abortRef.current?.abort();
    abortRef.current = null;
    clearTimers();
    setMessages([]);
    setStepIdx(0);
    setError(null);
    setBusy(false);
    setStreamIdx(null);
    setVisible(0);
    setPhase('playing');

    void (async () => {
      const history: ChatHistoryMessage[] = [];
      for (let i = 0; i < DEMO_SCRIPT.length; i += 1) {
        const step = DEMO_SCRIPT[i];
        const ask = pick(ui, step.ask, step.askEn);
        if (runId !== runIdRef.current) return;
        setStepIdx(i);
        setMessages((prev) => [
          ...prev,
          { role: 'user', content: ask, tools: [], cards: [], at: Date.now() },
        ]);
        if (!calm) await sleep(DEMO_ASK_PAUSE_MS);
        if (runId !== runIdRef.current) return;
        setBusy(true);
        const ctrl = new AbortController();
        abortRef.current = ctrl;
        try {
          const res = await api.converse(ask, history, ctrl.signal);
          if (runId !== runIdRef.current) return;
          history.push({ role: 'user', content: ask });
          history.push({ role: 'assistant', content: res.answer });
          const assistantIdx = i * 2 + 1;
          setBusy(false);
          setMessages((prev) => [
            ...prev,
            {
              role: 'assistant',
              content: res.answer,
              tools: res.tools_executed ?? [],
              cards: res.cards ?? [],
              lang: res.lang ?? 'fr',
              at: Date.now(),
            },
          ]);
          if (!calm && res.answer !== '') {
            setVisible(0);
            setStreamIdx(assistantIdx);
            const total = res.answer.length;
            let n = 0;
            while (n < total) {
              await sleep(TICK_MS);
              if (runId !== runIdRef.current) return;
              n += CHUNK;
              setVisible(Math.min(n, total));
            }
            setStreamIdx(null);
          }
        } catch (err) {
          if (runId !== runIdRef.current) return;
          if (ctrl.signal.aborted) return;
          setBusy(false);
          setError(err instanceof Error ? err.message : pick(ui, 'La démo est interrompue.', 'The demo was interrupted.'));
          setPhase('stopped');
          return;
        }
        if (runId !== runIdRef.current) return;
        if (!calm) await sleep(DEMO_STEP_PAUSE_MS);
      }
      if (runId !== runIdRef.current) return;
      setPhase('done');
    })();
  }, [calm, clearTimers, sleep, ui]);

  useEffect(() => {
    // Lecture auto après le premier affichage (aucun setState synchrone).
    timersRef.current.push(window.setTimeout(() => start(), 0));
    titleRef.current?.focus();
    const timers = timersRef.current;
    return () => {
      runIdRef.current += 1;
      abortRef.current?.abort();
      for (const t of timers) window.clearTimeout(t);
    };
  }, [start]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'auto', block: 'end' });
  }, [messages, visible, busy, phase]);

  const openDetail = useCallback((kind: DetailKind, id: number) => {
    setDetail({ kind, id });
  }, []);

  const step = DEMO_SCRIPT[Math.min(stepIdx, DEMO_SCRIPT.length - 1)];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={pick(ui, 'Démonstration automatique', 'Automatic demo')}
      className="fixed inset-0 z-50 overflow-y-auto bg-canvas"
    >
      <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col px-4 py-6">
        <div className="flex flex-wrap items-center gap-3">
          <span
            aria-hidden="true"
            className="rounded-full bg-teal-700 px-3 py-1 font-mono text-[11px] font-bold uppercase tracking-[0.14em] text-white"
          >
            {pick(ui, 'Démo', 'Demo')}
          </span>
          <h2
            ref={titleRef}
            tabIndex={-1}
            className="font-display text-xl font-bold tracking-tight focus:outline-none"
          >
            {pick(ui, 'Sentinel travaille pour vous', 'Sentinel is working for you')}
          </h2>
          <div className="flex-1" />
          {phase === 'playing' ? (
            <button
              type="button"
              onClick={stop}
              className="min-h-[56px] rounded-2xl border border-line bg-card px-5 text-[16px] font-semibold transition-[border-color] duration-150 hover:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent motion-reduce:transition-none"
            >
              Stop
            </button>
          ) : (
            <button
              type="button"
              onClick={start}
              className="min-h-[56px] rounded-2xl border border-line bg-card px-5 text-[16px] font-semibold transition-[border-color] duration-150 hover:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent motion-reduce:transition-none"
            >
              {pick(ui, 'Rejouer la démo', 'Replay the demo')}
            </button>
          )}
          <button
            type="button"
            onClick={onExit}
            className="min-h-[56px] rounded-2xl bg-teal-700 px-5 text-[16px] font-semibold text-white transition-[background-color] duration-150 hover:bg-teal-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent motion-reduce:transition-none"
          >
            {phase === 'playing' ? pick(ui, 'Quitter', 'Exit') : pick(ui, 'Reprendre ma conversation', 'Resume my conversation')}
          </button>
        </div>

        <p role="status" className="mt-3 font-mono text-[11px] uppercase tracking-[0.14em] text-ink-faint">
          {phase === 'done' ? pick(ui, 'Démo terminée.', 'Demo finished.') : pick(ui, step.caption, step.captionEn)}
        </p>

        <div aria-live="polite" className="mt-4 flex-1 space-y-5">
          {messages.map((m, i) =>
            m.role === 'user' ? (
              <div key={i}>
                <div className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-md border border-line bg-card px-4 py-2.5 text-[15px] leading-relaxed">
                    {m.content}
                  </div>
                </div>
                <p className="mt-1 text-right font-mono text-[11px] text-ink-faint">
                  {fmtTime(m.at, ui)}
                </p>
              </div>
            ) : (
              <div key={i} className="flex gap-3">
                <SentinelAvatar className="mt-1 h-7 w-7 shrink-0" />
                <div className="min-w-0 flex-1 space-y-2">
                  <div className="space-y-1.5 text-[15px] leading-7">
                    {renderRichText(streamIdx === i ? m.content.slice(0, visible) : m.content)}
                    {streamIdx === i && <span className="stream-caret" aria-hidden="true" />}
                  </div>
                  <p className="font-mono text-[11px] text-ink-faint">{fmtTime(m.at, ui)}</p>
                  {m.tools.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-[12px] text-ink-faint">{pick(ui, 'Vérifié :', 'Verified:')}</span>
                      {m.tools.map((t, j) => (
                        <span
                          key={`${t}-${j}`}
                          className="rounded-full bg-teal-700/10 px-2.5 py-0.5 text-[12px] font-medium text-teal-800 dark:bg-teal-300/15 dark:text-teal-200"
                        >
                          {t.replace(/_/g, ' ')}
                        </span>
                      ))}
                    </div>
                  )}
                  <AgentCardList cards={m.cards} onDetail={openDetail} lang={m.lang} />
                </div>
              </div>
            ),
          )}
          {busy && (
            <div className="flex items-center gap-3">
              <SentinelAvatar className="h-7 w-7 shrink-0 motion-safe:animate-pulse" />
              <p className="text-[15px] text-ink-soft">{pick(ui, 'Sentinel consulte les données…', 'Sentinel is checking the data…')}</p>
            </div>
          )}
          {error !== null && (
            <div className="rounded-2xl border border-danger/30 bg-danger-soft px-4 py-3">
              <p className="text-[15px] text-danger">{error}</p>
              <button
                type="button"
                onClick={start}
                className="mt-2 min-h-[56px] rounded-2xl bg-danger px-5 text-[16px] font-semibold text-white"
              >
                {pick(ui, 'Rejouer la démo', 'Replay the demo')}
              </button>
            </div>
          )}
          {phase === 'done' && (
            <div className="rounded-2xl border border-teal-700/30 bg-teal-700/10 px-4 py-3">
              <p className="font-display text-[16px] font-bold text-teal-800 dark:text-teal-200">
                {pick(ui, 'Démo terminée. À vous : posez votre question.', 'Demo finished. Your turn: ask your question.')}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={start}
                  className="min-h-[56px] rounded-2xl border border-line bg-card px-5 text-[16px] font-semibold transition-[border-color] duration-150 hover:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent motion-reduce:transition-none"
                >
                  {pick(ui, 'Rejouer la démo', 'Replay the demo')}
                </button>
                <button
                  type="button"
                  onClick={onExit}
                  className="min-h-[56px] rounded-2xl bg-teal-700 px-5 text-[16px] font-semibold text-white transition-[background-color] duration-150 hover:bg-teal-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent motion-reduce:transition-none"
                >
                  {pick(ui, 'Reprendre ma conversation', 'Resume my conversation')}
                </button>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>
      <DetailDrawer detail={detail} onClose={() => setDetail(null)} onDetail={openDetail} lang={ui} />
    </div>
  );
}
