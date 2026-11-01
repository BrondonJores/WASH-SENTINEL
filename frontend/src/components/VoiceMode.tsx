import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, api } from '../lib/api';
import type { AgentCard, ChatHistoryMessage, VoiceLanguage } from '../lib/api';
import { getCachedTtsUrl, getSynthesizedUrl, ttsCacheKey } from '../lib/ttsCache';
import { ELAPSED_TICK_MS, MAX_RECORD_BYTES, MAX_RECORD_MS, MAX_VOICE_MESSAGE, SPEECH_TEXT_MAX_LEN } from '../lib/voice-limits';
import { renderRichText } from '../lib/richtext';
import { SentinelOrb } from './SentinelOrb';
import type { OrbState } from './SentinelOrb';
import { AgentCardList, FollowUps } from './AgentCards';
import { WaitingSteps } from './StreamingStatus';
import { Icon } from './icons';

/* ============================================================================
 * Mode Voix plein écran (CANAL 1) — parcours mains-libres, zéro lecture
 * indispensable : l'orbe animé + 3 gros boutons image (Parler, Réécouter,
 * Oui/Non). Français simple partout, aria-live poli, touch targets ≥ 56px.
 *
 * Boucle : Parler → enregistre → transcribe → converse → réponse en cards ET
 * lue en TTS automatiquement (annulable : clic sur l'orbe ou Réécouter).
 * Répéter rejoue le dernier audio depuis le cache ttsCache (jamais de
 * re-synthèse). Oui/Non envoie « Oui »/« Non » comme message (dialogue
 * guidé backend, guided:true toujours envoyé). Aucun SSE : converse classique uniquement.
 * ========================================================================== */

/** Suffixe FR ajouté quand une longue dictée est coupée (une phrase simple, parcours analphabète). */
const LONG_MESSAGE_SUFFIX = '…(message long, suite coupée : précisez en une phrase)';

/** Longueur minimale gardée à la coupe (évite un résidu trop court). */
const MIN_KEPT_MESSAGE = 400;

/**
 * Coupe une transcription trop longue à la dernière fin de phrase ≤ 1800
 * caractères, puis ajoute le suffixe FR. Repli : dernière espace, puis coupe
 * dure. Le résultat reste sous la limite backend : jamais de 422, jamais perdu.
 */
function truncateLongVoiceMessage(text: string): string {
  if (text.length <= MAX_VOICE_MESSAGE) return text;
  const head = text.slice(0, MAX_VOICE_MESSAGE);
  let cut = -1;
  for (const end of ['.', '!', '?', '…', '\n']) cut = Math.max(cut, head.lastIndexOf(end));
  if (cut >= MIN_KEPT_MESSAGE) return `${head.slice(0, cut + 1).trimEnd()}${LONG_MESSAGE_SUFFIX}`;
  const space = head.lastIndexOf(' ');
  if (space >= MIN_KEPT_MESSAGE) return `${head.slice(0, space).trimEnd()}${LONG_MESSAGE_SUFFIX}`;
  return `${head.trimEnd()}${LONG_MESSAGE_SUFFIX}`;
}

/** Même clé que la console : le Mode Voix reprend la langue déjà choisie. */
const VOICE_LANG_KEY = 'wash_voice_lang';

/** Types MIME préférés pour MediaRecorder, du plus au moins souhaité. */
const PREFERRED_MIME_TYPES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/ogg;codecs=opus',
  'audio/wav',
];

function readVoiceLang(): VoiceLanguage {
  try {
    const v = localStorage.getItem(VOICE_LANG_KEY);
    if (v === 'fr' || v === 'dua_Latn' || v === 'bassa' || v === 'ewondo') return v;
  } catch {
    /* stockage indisponible : français par défaut */
  }
  return 'fr';
}

function pickMimeType(): string {
  if (typeof MediaRecorder === 'undefined') return '';
  for (const t of PREFERRED_MIME_TYPES) {
    try {
      if (MediaRecorder.isTypeSupported(t)) return t;
    } catch {
      /* type invalide pour ce navigateur : essayer le suivant */
    }
  }
  return '';
}

function formatChrono(ms: number): string {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

/** Allège la réponse pour la lecture vocale (liens, markdown, espaces). */
function cleanupForSpeech(text: string): string {
  return text
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[*_#>`]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, SPEECH_TEXT_MAX_LEN);
}

function micGuidance(err: unknown): string {
  if (err instanceof DOMException || err instanceof Error) {
    switch (err.name) {
      case 'NotAllowedError':
      case 'SecurityError':
        return 'Micro refusé. Autorisez le micro dans le navigateur, puis touchez Parler.';
      case 'NotFoundError':
      case 'OverconstrainedError':
        return 'Aucun micro sur cet appareil. Branchez un micro, puis réessayez.';
      case 'NotReadableError':
        return 'Micro déjà utilisé ailleurs. Fermez l’autre application, puis réessayez.';
      case 'AbortError':
        return 'Enregistrement interrompu. Touchez Parler pour réessayer.';
    }
  }
  return 'Micro impossible. Vérifiez votre micro, puis touchez Parler.';
}

// --- Icônes locales (gros boutons image, aria-hidden : le sens est en aria-label) ---

function MicIcon({ className = 'h-8 w-8' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <path d="M12 18v3" />
    </svg>
  );
}

function StopSquareIcon({ className = 'h-8 w-8' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden="true">
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  );
}

function ReplayIcon({ className = 'h-8 w-8' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      <path d="M3 12a9 9 0 1 0 2.6-6.4" />
      <path d="M3 4v5h5" />
      <path d="M10 9.5v5l4.5-2.5-4.5-2.5z" fill="currentColor" stroke="none" />
    </svg>
  );
}

// --- Bouton d'ouverture (visible depuis la console) ---------------------------

export function VoiceModeToggle({ onOpen, size = 'md' }: { onOpen: () => void; size?: 'md' | 'lg' }) {
  if (size === 'lg') {
    return (
      <button
        type="button"
        onClick={onOpen}
        aria-label="Ouvrir le Mode Voix : parler à Sentinel en plein écran"
        title="Mode Voix"
        className="group flex flex-col items-center gap-2 rounded-2xl px-6 py-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <span className="glass flex h-20 w-20 items-center justify-center rounded-full text-teal-700 transition-transform duration-150 ease-snap group-hover:scale-105 group-active:scale-95 motion-reduce:transition-none motion-reduce:group-hover:scale-100 dark:text-teal-300">
          <MicIcon className="h-9 w-9" />
        </span>
        <span aria-hidden="true" className="text-sm font-semibold text-ink-soft group-hover:text-ink">
          Mode Voix
        </span>
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label="Ouvrir le Mode Voix : parler à Sentinel en plein écran"
      title="Mode Voix"
      className="glass flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-ink-soft transition-[transform,color] duration-150 ease-snap hover:text-ink active:scale-95 motion-reduce:transition-none motion-reduce:active:scale-100"
    >
      <MicIcon className="h-5 w-5" />
    </button>
  );
}

// --- Mode Voix plein écran ----------------------------------------------------

type BusyKind = 'transcribe' | 'answer' | null;

export function VoiceMode({ onClose }: { onClose: () => void }) {
  const [voiceLang] = useState<VoiceLanguage>(() => readVoiceLang());
  const [calm] = useState(
    () =>
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true,
  );
  const [recording, setRecording] = useState(false);
  const [recElapsed, setRecElapsed] = useState(0);
  const [busy, setBusy] = useState(false);
  const [busyKind, setBusyKind] = useState<BusyKind>(null);
  const [requestStart, setRequestStart] = useState<number | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [needsTap, setNeedsTap] = useState(false);
  const [heard, setHeard] = useState<string | null>(null);
  const [answer, setAnswer] = useState<string | null>(null);
  const [cards, setCards] = useState<AgentCard[]>([]);
  const [followUps, setFollowUps] = useState<string[]>([]);
  const [history, setHistory] = useState<ChatHistoryMessage[]>([]);
  const [lastKey, setLastKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const talkRef = useRef<HTMLButtonElement>(null);
  const answerRef = useRef<HTMLDivElement>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const recTimerRef = useRef<number | null>(null);
  const recStartRef = useRef(0);
  const cancelledRef = useRef(false);
  const ctrlRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  const orb: OrbState = recording ? 'listening' : busy ? 'thinking' : playing ? 'speaking' : 'idle';

  const statusText = recording
    ? 'Parlez, je vous écoute.'
    : busyKind === 'transcribe'
      ? 'J’écris ce que vous avez dit.'
      : busy
        ? 'Je réfléchis.'
        : playing
          ? 'Écoutez. Touchez l’image pour couper le son.'
          : needsTap
            ? 'Touchez Réécouter pour entendre.'
            : answer !== null
              ? 'Touchez le micro pour continuer.'
              : 'Touchez le micro et parlez.';

  // --- Cycle de vie : focus, verrou du scroll, Échap, nettoyage ---------------

  useEffect(() => {
    mountedRef.current = true;
    talkRef.current?.focus();
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCloseRef.current();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      mountedRef.current = false;
      document.body.style.overflow = prev;
      window.removeEventListener('keydown', onKey);
      ctrlRef.current?.abort();
      ctrlRef.current = null;
      if (recTimerRef.current !== null) {
        window.clearInterval(recTimerRef.current);
        recTimerRef.current = null;
      }
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      recorderRef.current = null;
      audioRef.current?.pause();
      audioRef.current = null; // URL du cache : jamais révoquée, elle appartient à ttsCache
    };
  }, []);

  // Chrono d'attente (stepper) pendant transcribe + converse.
  useEffect(() => {
    if (!busy || requestStart === null) return;
    const t = window.setInterval(() => setElapsedMs(Date.now() - requestStart), ELAPSED_TICK_MS);
    return () => window.clearInterval(t);
  }, [busy, requestStart]);

  // La réponse reste visible sans chercher : on l'amène à l'écran.
  useEffect(() => {
    if (answer !== null) {
      answerRef.current?.scrollIntoView({ behavior: calm ? 'auto' : 'smooth', block: 'nearest' });
    }
  }, [answer, calm]);

  // --- Lecture audio (URL partagées du cache : jamais révoquées) ---------------

  const stopAudio = useCallback(() => {
    const el = audioRef.current;
    if (el !== null) {
      el.pause();
      el.removeAttribute('src');
      el.load();
    }
    if (mountedRef.current) setPlaying(false);
  }, []);

  const playUrl = useCallback(
    async (url: string) => {
      const prev = audioRef.current;
      if (prev !== null) {
        prev.pause();
        prev.removeAttribute('src');
        prev.load();
      }
      const el = new Audio(url);
      el.preload = 'none';
      el.addEventListener('ended', () => {
        if (mountedRef.current) setPlaying(false);
      });
      el.addEventListener('error', () => {
        if (mountedRef.current) {
          setPlaying(false);
          setNeedsTap(true);
        }
      });
      audioRef.current = el;
      try {
        await el.play();
        if (mountedRef.current) {
          setPlaying(true);
          setNeedsTap(false);
        }
      } catch {
        // Lecture auto refusée (politique du navigateur) : Répéter prend le relais.
        if (mountedRef.current) {
          setPlaying(false);
          setNeedsTap(true);
        }
      }
    },
    [],
  );

  /** Lit la réponse en TTS (synthèse mise en cache pour Répéter). */
  const speak = useCallback(
    async (text: string) => {
      const clean = cleanupForSpeech(text);
      if (clean === '') return;
      const key = ttsCacheKey(clean, { language: voiceLang });
      if (mountedRef.current) setLastKey(key);
      const url = await getSynthesizedUrl(clean, { language: voiceLang }, () =>
        api.synthesizeVoice(clean, { language: voiceLang }),
      );
      if (!mountedRef.current) return;
      if (url === null) {
        setNeedsTap(true);
        setError('Voix coupée : lisez la réponse, ou touchez le micro pour réessayer.');
        return;
      }
      await playUrl(url);
    },
    [playUrl, voiceLang],
  );

  /** Échange converse + affichage cards + lecture auto. Le verrou busy est déjà posé. */
  const converse = useCallback(
    async (message: string, prior: ChatHistoryMessage[]) => {
      const ctrl = new AbortController();
      ctrlRef.current = ctrl;
      try {
        // Parcours analphabète : toujours guidé (slots école→problème→oui/non, opt-in backend).
        const res = await api.converse(message, prior, ctrl.signal, { guided: true });
        if (!mountedRef.current || ctrl.signal.aborted) return;
        const text = res.answer ?? '';
        setHistory((prev) =>
          [...prev,
            { role: 'user', content: message } satisfies ChatHistoryMessage,
            { role: 'assistant', content: text } satisfies ChatHistoryMessage,
          ].slice(-20),
        );
        setAnswer(text);
        setCards(res.cards ?? []);
        setFollowUps(res.follow_ups ?? []);
        if (text.trim() !== '') await speak(text);
      } catch (err) {
        if (ctrl.signal.aborted || !mountedRef.current) return;
        // Jamais de 422 silencieuse : le message FR du backend s'affiche tel quel.
        if (err instanceof ApiError && err.status === 422) {
          setError(err.message);
        } else {
          setError(err instanceof Error ? err.message : 'Sentinel est injoignable. Touchez le micro pour réessayer.');
        }
      } finally {
        ctrlRef.current = null;
      }
    },
    [speak],
  );

  /** Envoie un texte (transcription, Oui/Non, relance) dans la boucle mains-libres. */
  const ask = useCallback(
    async (raw: string) => {
      const message = truncateLongVoiceMessage(raw.trim());
      if (message === '' || busy || recording) return;
      stopAudio();
      setNeedsTap(false);
      setError(null);
      setHeard(message);
      setBusy(true);
      setBusyKind('answer');
      setRequestStart(Date.now());
      setElapsedMs(0);
      try {
        await converse(message, history.slice(-19));
      } finally {
        if (mountedRef.current) {
          setBusy(false);
          setBusyKind(null);
          setRequestStart(null);
        }
      }
    },
    [busy, recording, converse, history, stopAudio],
  );

  const askRef = useRef(ask);
  useEffect(() => {
    askRef.current = ask;
  }, [ask]);

  // --- Enregistrement ----------------------------------------------------------

  const stopStream = useCallback(() => {
    if (recTimerRef.current !== null) {
      window.clearInterval(recTimerRef.current);
      recTimerRef.current = null;
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    recorderRef.current = null;
  }, []);

  const handleBlob = useCallback(
    async (blob: Blob) => {
      setError(null);
      setNeedsTap(false);
      setBusy(true);
      setBusyKind('transcribe');
      setRequestStart(Date.now());
      setElapsedMs(0);
      try {
        const res = await api.transcribeVoice(blob, voiceLang);
        if (!mountedRef.current) return;
        const raw = res.transcript.trim();
        if (raw === '') {
          setError('On n’a rien compris. Parlez plus près du micro, puis touchez Parler.');
          return;
        }
        // Longue dictée : texte coupé proprement + suffixe FR, entendu affiché tronqué.
        const text = truncateLongVoiceMessage(raw);
        setHeard(text);
        setBusyKind('answer');
        setRequestStart(Date.now());
        setElapsedMs(0);
        await converse(text, history.slice(-19));
      } catch (err) {
        if (!mountedRef.current) return;
        setError(err instanceof Error ? err.message : 'Transcription impossible. Touchez Parler pour réessayer.');
      } finally {
        if (mountedRef.current) {
          setBusy(false);
          setBusyKind(null);
          setRequestStart(null);
        }
      }
    },
    [converse, history, voiceLang],
  );

  const handleBlobRef = useRef(handleBlob);
  useEffect(() => {
    handleBlobRef.current = handleBlob;
  }, [handleBlob]);

  const startRecord = useCallback(async () => {
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setError('Ce navigateur ne permet pas de parler. Écrivez plutôt dans la console.');
      return;
    }
    if (typeof MediaRecorder === 'undefined') {
      setError('Ce navigateur ne permet pas de parler. Écrivez plutôt dans la console.');
      return;
    }
    if (typeof window !== 'undefined' && !window.isSecureContext) {
      setError('Parler demande une page sécurisée (HTTPS). Écrivez plutôt dans la console.');
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      setError(micGuidance(err));
      return;
    }
    const mimeType = pickMimeType();
    let recorder: MediaRecorder;
    try {
      recorder = mimeType !== '' ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    } catch {
      stream.getTracks().forEach((t) => t.stop());
      setError('Parler n’a pas démarré. Touchez Parler pour réessayer.');
      return;
    }
    streamRef.current = stream;
    recorderRef.current = recorder;
    chunksRef.current = [];
    cancelledRef.current = false;
    recorder.ondataavailable = (e: BlobEvent) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    recorder.onstop = () => {
      const wasCancelled = cancelledRef.current;
      cancelledRef.current = false;
      const type = recorder.mimeType !== '' ? recorder.mimeType : 'audio/webm';
      const blob = new Blob(chunksRef.current, { type });
      chunksRef.current = [];
      stopStream();
      if (mountedRef.current) {
        setRecording(false);
        setRecElapsed(0);
      }
      if (wasCancelled || !mountedRef.current) return;
      if (blob.size === 0) {
        setError('On n’a rien entendu. Parlez plus près du micro, puis touchez Parler.');
        return;
      }
      if (blob.size > MAX_RECORD_BYTES) {
        setError('Message trop long : parlez plus court, puis touchez Parler.');
        return;
      }
      void handleBlobRef.current(blob);
    };
    recorder.onerror = () => {
      stopStream();
      if (mountedRef.current) {
        setRecording(false);
        setRecElapsed(0);
        setError('Parler s’est interrompu. Touchez Parler pour réessayer.');
      }
    };
    try {
      recorder.start(250);
    } catch {
      stopStream();
      setError('Parler n’a pas démarré. Touchez Parler pour réessayer.');
      return;
    }
    recStartRef.current = Date.now();
    setRecElapsed(0);
    setRecording(true);
    recTimerRef.current = window.setInterval(() => {
      const ms = Date.now() - recStartRef.current;
      if (mountedRef.current) setRecElapsed(ms);
      if (ms >= MAX_RECORD_MS) {
        const rec = recorderRef.current;
        if (rec !== null && rec.state !== 'inactive') rec.stop();
      }
    }, 250);
  }, [stopStream]);

  const stopRecord = useCallback(
    (cancelled: boolean) => {
      const rec = recorderRef.current;
      if (rec !== null && rec.state !== 'inactive') {
        cancelledRef.current = cancelled;
        rec.stop(); // la suite (transcribe) part dans onstop, sauf si annulé
      } else {
        stopStream();
        setRecording(false);
        setRecElapsed(0);
      }
    },
    [stopStream],
  );

  // --- Actions des 3 gros boutons -----------------------------------------------

  const toggleTalk = useCallback(() => {
    if (busy) return;
    if (recording) {
      stopRecord(false); // arrêter → transcribe → converse → lecture auto
      return;
    }
    stopAudio();
    setNeedsTap(false);
    setError(null);
    void startRecord();
  }, [busy, recording, startRecord, stopAudio, stopRecord]);

  /** Rejoue le dernier audio depuis le cache : jamais de re-synthèse. */
  const repeat = useCallback(() => {
    if (busy || recording) return;
    if (playing) {
      stopAudio();
      return;
    }
    if (lastKey === null) return;
    const url = getCachedTtsUrl(lastKey);
    if (url === undefined) {
      setError('Réécoute impossible : touchez le micro pour poser une nouvelle question.');
      return;
    }
    setError(null);
    void playUrl(url);
  }, [busy, recording, playing, lastKey, playUrl, stopAudio]);

  /** Oui/Non envoyés comme message : prépare la confirmation guidée backend. */
  const answerYesNo = useCallback(
    (value: 'Oui' | 'Non') => {
      if (busy || recording) return;
      void askRef.current(value);
    },
    [busy, recording],
  );

  const close = useCallback(() => {
    stopRecord(true);
    ctrlRef.current?.abort();
    ctrlRef.current = null;
    stopAudio();
    onCloseRef.current();
  }, [stopAudio, stopRecord]);

  const roundBtn =
    'flex items-center justify-center rounded-full transition-transform duration-150 ease-snap focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent active:scale-95 motion-reduce:transition-none motion-reduce:active:scale-100 disabled:cursor-not-allowed disabled:opacity-40';

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Mode Voix : parler à Sentinel"
      className="fixed inset-0 z-[60] flex flex-col bg-canvas/95 backdrop-blur-md"
    >
      <div className="flex shrink-0 items-center justify-between px-4 pt-4 sm:px-6">
        <p aria-hidden="true" className="font-display text-lg font-bold tracking-tight">
          Mode Voix
        </p>
        <button
          type="button"
          onClick={close}
          aria-label="Fermer le Mode Voix"
          title="Fermer"
          className={`${roundBtn} h-14 w-14 border border-line bg-card text-ink`}
        >
          <Icon name="x" className="h-7 w-7" />
        </button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col items-center overflow-y-auto px-4 pb-4">
        {playing ? (
          <button
            type="button"
            onClick={stopAudio}
            aria-label="Arrêter la lecture"
            title="Arrêter la lecture"
            className="mt-1 shrink-0 rounded-full focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
          >
            <SentinelOrb state={orb} size="xl" />
          </button>
        ) : (
          <div className="mt-1 shrink-0">
            <SentinelOrb state={orb} size="xl" />
          </div>
        )}

        {busy ? (
          <div className="mt-3 flex w-full max-w-xl flex-col items-center gap-2">
            <p aria-hidden="true" className="text-center text-[15px] font-medium text-ink-soft">
              {statusText}
            </p>
            <div className="w-full">
              <WaitingSteps elapsedMs={elapsedMs} calm={calm} />
            </div>
          </div>
        ) : (
          <p role="status" aria-live="polite" className="mt-3 text-center text-[15px] font-medium text-ink-soft">
            {statusText}
            {recording && (
              <span aria-hidden="true" className="ml-2 inline-flex items-center gap-1.5 font-mono text-sm tabular-nums">
                <span className="inline-block h-2.5 w-2.5 rounded-full bg-red-500" />
                {formatChrono(recElapsed)}
              </span>
            )}
          </p>
        )}

        {error !== null && (
          <p role="alert" className="mt-3 w-full max-w-xl rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-[15px] leading-relaxed text-danger">
            {error}
          </p>
        )}

        {heard !== null && (
          <div className="mt-3 flex w-full max-w-xl justify-end">
            <p className="max-w-[85%] rounded-2xl rounded-br-md bg-teal-700 px-4 py-2.5 text-[15px] leading-relaxed text-white">
              {heard}
            </p>
          </div>
        )}

        {answer !== null && (
          <div ref={answerRef} className="mt-3 w-full max-w-xl scroll-mt-4 space-y-3">
            <div className="rounded-2xl border border-line bg-card p-4 text-[16px] leading-7">
              {renderRichText(answer)}
            </div>
            <AgentCardList cards={cards} onAsk={(q) => void askRef.current(q)} />
            <FollowUps items={followUps} onAsk={(q) => void askRef.current(q)} />
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-line/60 bg-card/70 px-4 pb-6 pt-4 backdrop-blur">
        <div className="mx-auto flex max-w-xl items-start justify-center gap-4 sm:gap-6">
          <span className="flex flex-col items-center gap-1.5">
            <button
              ref={talkRef}
              type="button"
              onClick={toggleTalk}
              disabled={busy}
              aria-label={recording ? 'Arrêter et envoyer' : 'Parler à Sentinel'}
              aria-pressed={recording}
              title={recording ? 'Arrêter et envoyer' : 'Parler'}
              className={`${roundBtn} h-20 w-20 text-white shadow-lg ${
                recording ? 'bg-red-600' : 'bg-teal-700 hover:bg-teal-600'
              }`}
            >
              {recording ? <StopSquareIcon /> : <MicIcon />}
            </button>
            <span aria-hidden="true" className="text-xs font-medium text-ink-soft">
              {recording ? 'Envoyer' : 'Parler'}
            </span>
          </span>

          <span className="flex flex-col items-center gap-1.5">
            <button
              type="button"
              onClick={repeat}
              disabled={busy || recording || (!playing && lastKey === null)}
              aria-label={playing ? 'Arrêter la lecture' : 'Réécouter la dernière réponse'}
              title={playing ? 'Arrêter' : 'Réécouter'}
              className={`${roundBtn} h-20 w-20 border-2 border-line bg-card text-teal-700 dark:text-teal-300 ${
                needsTap && !playing ? 'border-amber-400 ring-4 ring-amber-400/40 motion-safe:animate-pulse' : ''
              }`}
            >
              {playing ? <StopSquareIcon /> : <ReplayIcon />}
            </button>
            <span aria-hidden="true" className="text-xs font-medium text-ink-soft">
              Réécouter
            </span>
          </span>

          <span role="group" aria-label="Répondre par oui ou par non" className="flex gap-3">
            <span className="flex flex-col items-center gap-1.5">
              <button
                type="button"
                onClick={() => answerYesNo('Oui')}
                disabled={busy || recording}
                aria-label="Oui"
                title="Oui"
                className={`${roundBtn} h-16 w-16 bg-teal-700 text-white shadow-lg hover:bg-teal-600`}
              >
                <Icon name="check" className="h-8 w-8" />
              </button>
              <span aria-hidden="true" className="text-xs font-medium text-ink-soft">
                Oui
              </span>
            </span>
            <span className="flex flex-col items-center gap-1.5">
              <button
                type="button"
                onClick={() => answerYesNo('Non')}
                disabled={busy || recording}
                aria-label="Non"
                title="Non"
                className={`${roundBtn} h-16 w-16 border-2 border-red-700/50 bg-card text-red-700 dark:text-red-400`}
              >
                <Icon name="x" className="h-8 w-8" />
              </button>
              <span aria-hidden="true" className="text-xs font-medium text-ink-soft">
                Non
              </span>
            </span>
          </span>
        </div>
      </div>
    </div>
  );
}
