import { useCallback, useEffect, useRef, useState } from 'react';

/* ============================================================================
 * Contrôles vocaux Sentinel — dicter (STT) + écouter (TTS).
 * Composants autonomes, zéro dépendance, FR, dark-mode, motion-reduce.
 *
 * CONTRAT STT CONSTATÉ (backend/ai-engine/app/main.py → POST /v1/voice/transcribe)
 *   Requête  : multipart/form-data { audio: <fichier>, language: "fr" }
 *              (le header x-stt-language a priorité sur le champ language)
 *   Réponse  : JSON { transcript: string, language: string,
 *                      duration_seconds: number | null }
 *   ⚠ Aucune route Laravel /v1/wash/* ne relaie la transcription (seul
 *     POST /v1/wash/agent/synthesize existe) : voir le guide de câblage.
 *
 * CONTRAT TTS CONSTATÉ (main.py → POST /v1/voice/synthesize, relais Laravel
 * POST /v1/wash/agent/synthesize { text } → passthrough JSON identique)
 *   Requête  : JSON { text: string, voice?: string } (défaut "fr_FR-upmc-medium")
 *   Réponse  : JSON { audio_base64: string, mime_type: "audio/wav", text: string }
 *   L'audio est un WAV encodé en base64 (pas d'URL). Le helper
 *   `ttsBase64ToObjectUrl` ci-dessous le convertit en URL locale pour
 *   <audio> / VoicePlayer. Jamais d'autoplay : la lecture part au clic.
 * ========================================================================== */

/** Durée maximale d'une dictée avant arrêt automatique (2 minutes). */
const MAX_RECORD_MS = 120_000;

/** Types MIME préférés pour MediaRecorder, du plus au moins souhaité. */
const PREFERRED_MIME_TYPES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/ogg;codecs=opus',
  'audio/wav',
];

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

function micErrorMessage(err: unknown): string {
  if (err instanceof DOMException || err instanceof Error) {
    switch (err.name) {
      case 'NotAllowedError':
      case 'SecurityError':
        return 'Micro refusé : autorisez l’accès au microphone dans votre navigateur, puis réessayez.';
      case 'NotFoundError':
      case 'OverconstrainedError':
        return 'Aucun microphone détecté sur cet appareil.';
      case 'NotReadableError':
        return 'Microphone déjà utilisé par une autre application.';
      case 'AbortError':
        return 'Enregistrement interrompu.';
    }
  }
  return 'Impossible d’accéder au microphone.';
}

/**
 * Convertit la réponse TTS (WAV base64, voir contrat ci-dessus) en URL locale
 * lisible par <audio> ou VoicePlayer. L’appelant doit libérer l’URL avec
 * `URL.revokeObjectURL(url)` quand l’audio n’est plus utile.
 */
export function ttsBase64ToObjectUrl(audioBase64: string, mimeType = 'audio/wav'): string {
  const bin = atob(audioBase64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes.buffer], { type: mimeType }));
}

// --- Icônes locales (icons.tsx ne fournit ni mic, ni stop, ni play) ---

function MicIcon({ className = 'h-5 w-5' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <path d="M12 18v3" />
    </svg>
  );
}

function StopIcon({ className = 'h-5 w-5' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden="true">
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  );
}

function PlayIcon({ className = 'h-5 w-5' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden="true">
      <path d="M8 5.5v13l11-6.5-11-6.5z" />
    </svg>
  );
}

function SpinnerIcon({ className = 'h-5 w-5' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}
      strokeLinecap="round" className={`${className} motion-safe:animate-spin motion-reduce:animate-none`}
      aria-hidden="true">
      <path d="M12 3a9 9 0 1 0 9 9" />
    </svg>
  );
}

// --- VoiceRecorder : dicter --------------------------------------------------

export interface VoiceRecorderProps {
  /** Appelé avec l’audio capturé (webm/opus si possible, sinon type supporté). */
  onAudio: (blob: Blob) => void;
  disabled?: boolean;
}

export function VoiceRecorder({ onAudio, disabled = false }: VoiceRecorderProps) {
  const [recording, setRecording] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<number | null>(null);
  const rafRef = useRef<number | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const startedAtRef = useRef(0);
  const onAudioRef = useRef(onAudio);
  useEffect(() => {
    onAudioRef.current = onAudio;
  }, [onAudio]);

  const cleanup = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (rafRef.current !== null) {
      window.cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    if (audioCtxRef.current !== null) {
      void audioCtxRef.current.close().catch(() => undefined);
      audioCtxRef.current = null;
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    recorderRef.current = null;
    setLevel(0);
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const stop = useCallback(() => {
    const rec = recorderRef.current;
    if (rec !== null && rec.state !== 'inactive') rec.stop();
    /* la livraison du blob se fait dans onstop (voir start) */
  }, []);

  const start = useCallback(async () => {
    setError(null);
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setError('Navigateur incompatible : l’enregistrement audio n’est pas pris en charge.');
      return;
    }
    if (typeof MediaRecorder === 'undefined') {
      setError('Navigateur incompatible : MediaRecorder n’est pas disponible.');
      return;
    }
    if (typeof window !== 'undefined' && !window.isSecureContext) {
      setError('L’enregistrement audio exige une connexion sécurisée (HTTPS) ou localhost.');
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      setError(micErrorMessage(err));
      return;
    }
    const mimeType = pickMimeType();
    let recorder: MediaRecorder;
    try {
      recorder = mimeType !== '' ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    } catch {
      stream.getTracks().forEach((t) => t.stop());
      setError('Navigateur incompatible : impossible de démarrer l’enregistrement.');
      return;
    }
    streamRef.current = stream;
    recorderRef.current = recorder;
    chunksRef.current = [];
    recorder.ondataavailable = (e: BlobEvent) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    recorder.onstop = () => {
      const type = recorder.mimeType !== '' ? recorder.mimeType : 'audio/webm';
      const blob = new Blob(chunksRef.current, { type });
      chunksRef.current = [];
      cleanup();
      setRecording(false);
      setElapsedMs(0);
      if (blob.size === 0) {
        setError('Enregistrement vide : aucun son capturé.');
        return;
      }
      onAudioRef.current(blob);
    };
    recorder.onerror = () => {
      cleanup();
      setRecording(false);
      setError('Erreur pendant l’enregistrement.');
    };
    try {
      recorder.start(250);
    } catch {
      cleanup();
      setError('Impossible de démarrer l’enregistrement.');
      return;
    }
    startedAtRef.current = Date.now();
    setRecording(true);
    timerRef.current = window.setInterval(() => {
      const ms = Date.now() - startedAtRef.current;
      setElapsedMs(ms);
      if (ms >= MAX_RECORD_MS) stop(); // arrêt automatique à 2 min
    }, 200);
    // Niveau sonore (optionnel : l’enregistrement continue sans lui).
    try {
      const AC = window.AudioContext
        ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (AC) {
        const ctx = new AC();
        audioCtxRef.current = ctx;
        const src = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        src.connect(analyser);
        const buf = new Uint8Array(analyser.fftSize);
        const tick = () => {
          analyser.getByteTimeDomainData(buf);
          let sum = 0;
          for (let i = 0; i < buf.length; i++) {
            const v = (buf[i] - 128) / 128;
            sum += v * v;
          }
          setLevel(Math.min(1, Math.sqrt(sum / buf.length) * 3));
          rafRef.current = window.requestAnimationFrame(tick);
        };
        rafRef.current = window.requestAnimationFrame(tick);
      }
    } catch {
      /* pas de niveau, l’enregistrement continue */
    }
  }, [cleanup, stop]);

  const toggle = () => {
    if (disabled) return;
    if (recording) stop();
    else void start();
  };

  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        onClick={toggle}
        disabled={disabled}
        aria-label={recording ? 'Arrêter l’enregistrement' : 'Dicter un message'}
        aria-pressed={recording}
        title={recording ? 'Arrêter l’enregistrement' : 'Dicter un message'}
        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full border transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none ${
          recording
            ? 'border-danger/50 bg-danger-soft text-danger'
            : 'border-line bg-card text-ink-soft hover:bg-raised hover:text-ink'
        }`}
      >
        {recording ? <StopIcon /> : <MicIcon />}
      </button>
      {recording && (
        <span className="inline-flex items-center gap-2" role="status" aria-label="Enregistrement en cours">
          <span aria-hidden="true" className="relative flex h-2 w-2">
            <span className="absolute h-full w-full rounded-full bg-red-500 opacity-60 motion-safe:animate-ping" />
            <span className="relative h-2 w-2 rounded-full bg-red-500" />
          </span>
          <span className="font-mono text-xs tabular-nums text-ink-soft">{formatChrono(elapsedMs)}</span>
          <span aria-hidden="true" className="h-1.5 w-16 overflow-hidden rounded-full bg-raised">
            <span
              className="block h-full rounded-full bg-teal-600 transition-[width] duration-100 dark:bg-teal-400 motion-reduce:transition-none"
              style={{ width: `${Math.round(level * 100)}%` }}
            />
          </span>
        </span>
      )}
      {error !== null && !recording && (
        <span role="alert" className="max-w-60 text-xs text-danger">{error}</span>
      )}
    </span>
  );
}

// --- VoicePlayer : écouter ---------------------------------------------------

export interface VoicePlayerProps {
  /** URL audio déjà prête (objet ou distante). Prioritaire sur onRequestAudio. Non révoquée : appartient au parent. */
  audioUrl?: string | null;
  /** Fournit l’URL à la demande (ex. synthèse TTS au clic). L’URL retournée est révoquée à la fin. */
  onRequestAudio?: () => Promise<string | null>;
  disabled?: boolean;
  className?: string;
}

type PlayerStatus = 'idle' | 'loading' | 'playing';

export function VoicePlayer({ audioUrl = null, onRequestAudio, disabled = false, className = '' }: VoicePlayerProps) {
  const [status, setStatus] = useState<PlayerStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const ownedUrlRef = useRef<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      audioRef.current?.pause();
      audioRef.current = null;
      if (ownedUrlRef.current !== null) {
        URL.revokeObjectURL(ownedUrlRef.current);
        ownedUrlRef.current = null;
      }
    };
  }, []);

  const releaseOwned = useCallback(() => {
    if (ownedUrlRef.current !== null) {
      URL.revokeObjectURL(ownedUrlRef.current);
      ownedUrlRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    const el = audioRef.current;
    if (el !== null) {
      el.pause();
      el.removeAttribute('src');
      el.load();
    }
    releaseOwned();
    if (mountedRef.current) {
      setStatus('idle');
      setError(null);
    }
  }, [releaseOwned]);

  // Si la source fournie par le parent change, arrêter la lecture en cours.
  useEffect(() => {
    stop();
  }, [audioUrl, stop]);

  const ensureAudio = useCallback(() => {
    let el = audioRef.current;
    if (el === null) {
      el = new Audio();
      el.preload = 'none'; // jamais de chargement ni de lecture sans clic
      el.onended = () => {
        releaseOwned(); // libère l’URL fournie à la demande à la fin
        if (mountedRef.current) setStatus('idle');
      };
      el.onerror = () => {
        releaseOwned();
        if (mountedRef.current) {
          setStatus('idle');
          setError('Lecture impossible : format audio non pris en charge.');
        }
      };
      audioRef.current = el;
    }
    return el;
  }, [releaseOwned]);

  const play = useCallback(async () => {
    setError(null);
    setStatus('loading');
    try {
      let src = audioUrl;
      if (src === null || src === undefined || src === '') {
        if (!onRequestAudio) throw new Error('Aucune source audio configurée pour ce message.');
        const provided = await onRequestAudio();
        if (!mountedRef.current) return;
        if (provided === null || provided === '') {
          throw new Error('Aucun audio disponible pour ce message.');
        }
        releaseOwned();
        ownedUrlRef.current = src = provided;
      }
      const el = ensureAudio();
      el.src = src;
      await el.play(); // geste utilisateur : pas d’autoplay
      if (mountedRef.current) setStatus('playing');
    } catch (err) {
      releaseOwned();
      if (!mountedRef.current) return;
      setStatus('idle');
      setError(err instanceof Error ? err.message : 'Lecture impossible.');
    }
  }, [audioUrl, onRequestAudio, ensureAudio, releaseOwned]);

  const toggle = () => {
    if (disabled || status === 'loading') return;
    if (status === 'playing') stop();
    else void play();
  };

  const label = status === 'playing'
    ? 'Arrêter la lecture'
    : status === 'loading'
      ? 'Chargement de l’audio…'
      : 'Écouter la réponse';

  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <button
        type="button"
        onClick={toggle}
        disabled={disabled || status === 'loading'}
        aria-label={label}
        title={label}
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-line bg-card text-ink-soft transition-colors duration-150 hover:bg-raised hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
      >
        {status === 'loading' ? <SpinnerIcon /> : status === 'playing' ? <StopIcon /> : <PlayIcon />}
      </button>
      {error !== null && (
        <span role="alert" className="max-w-60 text-xs text-danger">{error}</span>
      )}
    </span>
  );
}
