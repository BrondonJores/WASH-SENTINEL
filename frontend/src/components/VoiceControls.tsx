import { useCallback, useEffect, useRef, useState } from 'react';
import { getCachedTtsUrl } from '../lib/ttsCache';
import { pick, useUILang } from '../lib/i18n';
import { MAX_RECORD_BYTES, MAX_RECORD_MS } from '../lib/voice-limits';

/* ============================================================================
 * Contrôles vocaux Sentinel — dicter (STT) + écouter (TTS).
 * Composants autonomes, zéro dépendance, FR, dark-mode, motion-reduce.
 *
 * CONTRAT STT CONSTATÉ (backend/ai-engine/app/main.py → POST /v1/voice/transcribe)
 *   Requête  : multipart/form-data { audio: <fichier>, language?: "fr"|"dua_Latn"|"bassa"|"ewondo" }
 *              (précédence : champ language > header x-stt-language du profil > "fr")
 *   Réponse  : JSON { transcript: string, language: string, language_effective: string,
 *                      driver: string | null, duration_seconds: number | null }
 *   Relais Laravel : POST /v1/wash/agent/transcribe { audio, language? }.
 *
 * CONTRAT TTS CONSTATÉ (main.py → POST /v1/voice/synthesize, relais Laravel
 * POST /v1/wash/agent/synthesize { text } → passthrough JSON identique)
 *   Requête  : JSON { text: string, voice?: string, language?: string } (défaut "fr_FR-upmc-medium" / "fr")
 *   Réponse  : JSON { audio_base64: string, mime_type: "audio/wav", text: string }
 *   L'audio est un WAV encodé en base64 (pas d'URL). Le helper
 *   `ttsBase64ToObjectUrl` ci-dessous le convertit en URL locale pour
 *   <audio> / VoicePlayer. Jamais d'autoplay : la lecture part au clic.
 * ========================================================================== */

/** Dictée trop lourde : guider vers un message plus court. */
const tooHeavyGuidance = (lang: string | undefined): string =>
  pick(lang, 'Enregistrement trop lourd : dictez un message plus court, puis réessayez.', 'Recording too heavy: dictate a shorter message, then try again.');

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

/** Nombre de barres de la waveform temps réel. */
const WAVE_BARS = 24;

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
  );
}

/** Couleur du canvas (suit text-teal-600 / dark:text-teal-400 via currentColor). */
function canvasColor(canvas: HTMLCanvasElement): string {
  try {
    return window.getComputedStyle(canvas).color || '#0d9488';
  } catch {
    return '#0d9488';
  }
}

/**
 * Dessine la waveform (barres teal). Sans analyseur (reduced-motion ou
 * AudioContext indisponible), dessine un motif statique déterministe.
 */
function drawWaveform(canvas: HTMLCanvasElement, analyser: AnalyserNode | null, color: string): void {
  const ctx = canvas.getContext('2d');
  if (ctx === null) return;
  const W = canvas.width;
  const H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  let freq: Uint8Array<ArrayBuffer> | null = null;
  if (analyser !== null) {
    freq = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(freq);
  }
  const gap = 2;
  const bw = Math.max(2, (W - gap * (WAVE_BARS - 1)) / WAVE_BARS);
  ctx.fillStyle = color;
  for (let i = 0; i < WAVE_BARS; i++) {
    let v: number;
    if (freq !== null) {
      const idx = Math.min(freq.length - 1, Math.floor((i / WAVE_BARS) * freq.length * 0.7));
      v = freq[idx] / 255;
    } else {
      v = 0.18 + 0.12 * (((i * 7) % 5) / 4); // motif statique
    }
    const h = Math.max(3, v * H);
    ctx.fillRect(i * (bw + gap), (H - h) / 2, bw, h);
  }
}

/**
 * Guidage affiché après une panne d’enregistrement : jamais un simple
 * « échec », toujours un message FR + une action (réessayer et/ou aide).
 */
interface RecorderGuidance {
  message: string;
  /** Bouton « Réessayer » qui relance l’enregistrement. */
  retry: boolean;
  /** Texte d’aide via le bouton « Aide » (absent = pas de bouton). */
  help?: string;
}

function micErrorGuidance(err: unknown, lang: string | undefined): RecorderGuidance {
  if (err instanceof DOMException || err instanceof Error) {
    switch (err.name) {
      case 'NotAllowedError':
      case 'SecurityError':
        return {
          message: pick(lang, 'Micro refusé. Autorisez le micro dans le navigateur, puis réessayez.', 'Microphone blocked. Allow the microphone in the browser, then try again.'),
          retry: false,
          help: pick(lang, 'Cliquez sur l’icône du micro (ou le cadenas) dans la barre d’adresse, autorisez le microphone pour ce site, puis réessayez. Sur mobile : réglages du navigateur > autorisations > microphone.', 'Click the microphone (or padlock) icon in the address bar, allow the microphone for this site, then try again. On mobile: browser settings > permissions > microphone.'),
        };
      case 'NotFoundError':
      case 'OverconstrainedError':
        return {
          message: pick(lang, 'Aucun microphone détecté sur cet appareil.', 'No microphone detected on this device.'),
          retry: true,
          help: pick(lang, 'Branchez ou activez un microphone, vérifiez qu’il n’est pas coupé, puis réessayez.', 'Plug in or enable a microphone, check that it is not muted, then try again.'),
        };
      case 'NotReadableError':
        return {
          message: pick(lang, 'Microphone déjà utilisé par une autre application. Fermez-la, puis réessayez.', 'Microphone already used by another app. Close it, then try again.'),
          retry: true,
        };
      case 'AbortError':
        return { message: pick(lang, 'Enregistrement interrompu. Réessayez quand vous êtes prêt.', 'Recording interrupted. Try again when ready.'), retry: true };
    }
  }
  return { message: pick(lang, 'Impossible d’accéder au microphone. Vérifiez votre micro, puis réessayez.', 'Cannot access the microphone. Check your microphone, then try again.'), retry: true };
}

/** Enregistrement sans aucun son capturé : guider vers une dictée audible. */
const silenceGuidance = (lang: string | undefined): RecorderGuidance => ({
  message: pick(lang, 'On n’a rien entendu. Parlez plus près du micro, dans un endroit calme, puis réessayez.', 'Heard nothing. Speak closer to the microphone, in a quiet place, then try again.'),
  retry: true,
});

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
  /** Libellé de langue pour l’accessibilité (ex. « douala »). */
  languageLabel?: string;
}

export function VoiceRecorder({ onAudio, disabled = false, languageLabel }: VoiceRecorderProps) {
  const ui = useUILang();
  const [recording, setRecording] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [guidance, setGuidanceState] = useState<RecorderGuidance | null>(null);
  const [showHelp, setShowHelp] = useState(false);
  const setGuidance = useCallback((g: RecorderGuidance | null) => {
    setShowHelp(false);
    setGuidanceState(g);
  }, []);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const colorRef = useRef<string | null>(null);
  const cancelledRef = useRef(false);
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
    analyserRef.current = null;
    colorRef.current = null;
  }, []);

  useEffect(() => cleanup, [cleanup]);

  // Waveform statique si prefers-reduced-motion (un seul rendu, pas de boucle).
  useEffect(() => {
    if (!recording || !prefersReducedMotion()) return;
    const canvas = canvasRef.current;
    if (canvas !== null) drawWaveform(canvas, null, canvasColor(canvas));
  }, [recording]);

  const stop = useCallback(() => {
    const rec = recorderRef.current;
    if (rec !== null && rec.state !== 'inactive') rec.stop();
    /* la livraison du blob se fait dans onstop (voir start) */
  }, []);

  const cancel = useCallback(() => {
    const rec = recorderRef.current;
    if (rec !== null && rec.state !== 'inactive') {
      cancelledRef.current = true; // onstop jettera le blob
      rec.stop();
    } else {
      cleanup();
      setRecording(false);
      setElapsedMs(0);
    }
  }, [cleanup]);

  const start = useCallback(async () => {
    setGuidance(null);
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setGuidance({
        message: pick(ui, 'Navigateur incompatible : l’enregistrement audio n’est pas pris en charge.', 'Unsupported browser: audio recording is not supported.'),
        retry: false,
        help: pick(ui, 'Utilisez une version récente de Chrome, Edge, Firefox ou Safari pour dicter un message.', 'Use a recent version of Chrome, Edge, Firefox or Safari to dictate a message.'),
      });
      return;
    }
    if (typeof MediaRecorder === 'undefined') {
      setGuidance({
        message: pick(ui, 'Navigateur incompatible : l’enregistrement audio n’est pas disponible.', 'Unsupported browser: audio recording is not available.'),
        retry: false,
        help: pick(ui, 'Utilisez une version récente de Chrome, Edge, Firefox ou Safari pour dicter un message.', 'Use a recent version of Chrome, Edge, Firefox or Safari to dictate a message.'),
      });
      return;
    }
    if (typeof window !== 'undefined' && !window.isSecureContext) {
      setGuidance({
        message: pick(ui, 'L’enregistrement audio exige une connexion sécurisée (HTTPS) ou localhost.', 'Audio recording requires a secure connection (HTTPS) or localhost.'),
        retry: false,
        help: pick(ui, 'Ouvrez la page en HTTPS (ou sur localhost) : les navigateurs bloquent le micro sur les pages non sécurisées.', 'Open the page over HTTPS (or on localhost): browsers block the microphone on insecure pages.'),
      });
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      setGuidance(micErrorGuidance(err, ui));
      return;
    }
    const mimeType = pickMimeType();
    let recorder: MediaRecorder;
    try {
      recorder = mimeType !== '' ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    } catch {
      stream.getTracks().forEach((t) => t.stop());
      setGuidance({
        message: pick(ui, 'L’enregistrement n’a pas démarré. Vérifiez votre micro, puis réessayez.', 'Recording did not start. Check your microphone, then try again.'),
        retry: true,
      });
      return;
    }
    streamRef.current = stream;
    recorderRef.current = recorder;
    chunksRef.current = [];
    recorder.ondataavailable = (e: BlobEvent) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    recorder.onstop = () => {
      const wasCancelled = cancelledRef.current;
      cancelledRef.current = false;
      const type = recorder.mimeType !== '' ? recorder.mimeType : 'audio/webm';
      const blob = new Blob(chunksRef.current, { type });
      chunksRef.current = [];
      cleanup();
      setRecording(false);
      setElapsedMs(0);
      if (wasCancelled) return;
      if (blob.size === 0) {
        setGuidance(silenceGuidance(ui));
        return;
      }
      if (blob.size > MAX_RECORD_BYTES) {
        setGuidance({ message: tooHeavyGuidance(ui), retry: true });
        return;
      }
      onAudioRef.current(blob);
    };
    recorder.onerror = () => {
      cleanup();
      setRecording(false);
      setGuidance({
        message: pick(ui, 'L’enregistrement a été interrompu. Vérifiez votre micro, puis réessayez.', 'Recording was interrupted. Check your microphone, then try again.'),
        retry: true,
      });
    };
    try {
      recorder.start(250);
    } catch {
      cleanup();
      setGuidance({
        message: pick(ui, 'L’enregistrement n’a pas démarré. Vérifiez votre micro, puis réessayez.', 'Recording did not start. Check your microphone, then try again.'),
        retry: true,
      });
      return;
    }
    startedAtRef.current = Date.now();
    setRecording(true);
    timerRef.current = window.setInterval(() => {
      const ms = Date.now() - startedAtRef.current;
      setElapsedMs(ms);
      if (ms >= MAX_RECORD_MS) stop(); // arrêt automatique à 2 min
    }, 200);
    // Waveform temps réel (optionnelle : l’enregistrement continue sans elle).
    try {
      const AC = window.AudioContext
        ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (AC) {
        const ctx = new AC();
        audioCtxRef.current = ctx;
        const src = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.75;
        src.connect(analyser);
        analyserRef.current = analyser;
      }
    } catch {
      /* pas de waveform, l’enregistrement continue */
    }
    if (!prefersReducedMotion()) {
      const tick = () => {
        const canvas = canvasRef.current;
        if (canvas !== null) {
          if (colorRef.current === null) colorRef.current = canvasColor(canvas);
          drawWaveform(canvas, analyserRef.current, colorRef.current);
        }
        rafRef.current = window.requestAnimationFrame(tick);
      };
      rafRef.current = window.requestAnimationFrame(tick);
    }
  }, [cleanup, stop, setGuidance, ui]);

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
        aria-label={
          recording
            ? pick(ui, 'Arrêter l’enregistrement', 'Stop recording')
            : languageLabel
              ? pick(ui, `Dicter un message en ${languageLabel}`, `Dictate a message in ${languageLabel}`)
              : pick(ui, 'Dicter un message', 'Dictate a message')
        }
        aria-pressed={recording}
        title={
          recording
            ? pick(ui, 'Arrêter l’enregistrement', 'Stop recording')
            : languageLabel
              ? pick(ui, `Dicter un message en ${languageLabel}`, `Dictate a message in ${languageLabel}`)
              : pick(ui, 'Dicter un message', 'Dictate a message')
        }
        className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full border transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none ${
          recording
            ? 'border-danger/50 bg-danger-soft text-danger'
            : 'border-line bg-card text-ink-soft ring-2 ring-teal-600/25 hover:bg-raised hover:text-ink dark:ring-teal-400/25'
        }`}
      >
        {recording ? <StopIcon /> : <MicIcon />}
      </button>
      {recording && (
        <span className="inline-flex items-center gap-2" role="status" aria-label={pick(ui, 'Enregistrement en cours', 'Recording in progress')}>
          <span aria-hidden="true" className="relative flex h-2 w-2">
            <span className="absolute h-full w-full rounded-full bg-red-500 opacity-60 motion-safe:animate-ping" />
            <span className="relative h-2 w-2 rounded-full bg-red-500" />
          </span>
          <span className="font-mono text-xs tabular-nums text-ink-soft">{formatChrono(elapsedMs)}</span>
          <canvas
            ref={canvasRef}
            width={120}
            height={28}
            aria-hidden="true"
            className="h-7 w-[120px] text-teal-600 dark:text-teal-400"
          />
          <button
            type="button"
            onClick={cancel}
            aria-label={pick(ui, 'Annuler l’enregistrement', 'Cancel recording')}
            title={pick(ui, 'Annuler', 'Cancel')}
            className="rounded px-1 py-1 text-xs text-ink-faint underline-offset-2 hover:text-danger hover:underline focus-visible:outline-2 focus-visible:outline-accent"
          >
            {pick(ui, 'Annuler', 'Cancel')}
          </button>
        </span>
      )}
      {guidance !== null && !recording && (
        <span role="alert" className="max-w-60 text-xs text-danger">
          {guidance.message}
          {guidance.retry && (
            <>
              {' '}
              <button
                type="button"
                onClick={() => {
                  if (!disabled) void start();
                }}
                disabled={disabled}
                className="rounded px-1 py-0.5 font-medium text-danger underline underline-offset-2 hover:opacity-80 focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
              >
                {pick(ui, 'Réessayer', 'Retry')}
              </button>
            </>
          )}
          {guidance.help !== undefined && (
            <>
              {' '}
              <button
                type="button"
                onClick={() => setShowHelp((v) => !v)}
                aria-expanded={showHelp}
                className="rounded px-1 py-0.5 font-medium text-ink-soft underline underline-offset-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-accent"
              >
                {pick(ui, 'Aide', 'Help')}
              </button>
            </>
          )}
          {showHelp && guidance.help !== undefined && (
            <span className="mt-1 block text-ink-soft">{guidance.help}</span>
          )}
        </span>
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
  /**
   * Clé du cache TTS (voir ttsCache). Si fournie : le cache est consulté avant
   * onRequestAudio, et les URL jouées sont partagées (jamais révoquées, elles
   * appartiennent au cache). Sans clé : comportement historique inchangé.
   */
  cacheKey?: string | null;
}

type PlayerStatus = 'idle' | 'loading' | 'playing';

export function VoicePlayer({ audioUrl = null, onRequestAudio, disabled = false, className = '', cacheKey = null }: VoicePlayerProps) {
  const ui = useUILang();
  const [status, setStatus] = useState<PlayerStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const ownedUrlRef = useRef<string | null>(null);
  const sharedRef = useRef(false);
  const mountedRef = useRef(true);
  const shared = cacheKey !== null && cacheKey !== undefined;

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
    if (sharedRef.current) {
      sharedRef.current = false; // URL du cache : ne jamais révoquer
      return;
    }
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
  }, [audioUrl, cacheKey, stop]);

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
          setError(pick(ui, 'Lecture impossible : format audio non pris en charge.', 'Cannot play: audio format not supported.'));
        }
      };
      audioRef.current = el;
    }
    return el;
  }, [releaseOwned, ui]);

  const play = useCallback(async () => {
    setError(null);
    setStatus('loading');
    try {
      let src = audioUrl;
      if (src === null || src === undefined || src === '') {
        const cached = shared && cacheKey !== null && cacheKey !== undefined
          ? getCachedTtsUrl(cacheKey)
          : undefined;
        if (cached !== undefined) {
          releaseOwned();
          sharedRef.current = true;
          src = cached;
        } else {
          if (!onRequestAudio) throw new Error(pick(ui, 'Aucune source audio configurée pour ce message.', 'No audio source configured for this message.'));
          const provided = await onRequestAudio();
          if (!mountedRef.current) return;
          if (provided === null || provided === '') {
            throw new Error(pick(ui, 'Aucun audio disponible pour ce message.', 'No audio available for this message.'));
          }
          releaseOwned();
          if (shared) {
            // Fournisseur adossé au cache (getSynthesizedUrl) : URL partagée.
            sharedRef.current = true;
            src = provided;
          } else {
            ownedUrlRef.current = src = provided;
          }
        }
      }
      const el = ensureAudio();
      el.src = src;
      await el.play(); // geste utilisateur : pas d’autoplay
      if (mountedRef.current) setStatus('playing');
    } catch (err) {
      releaseOwned();
      if (!mountedRef.current) return;
      setStatus('idle');
      setError(err instanceof Error ? err.message : pick(ui, 'Lecture impossible.', 'Cannot play.'));
    }
  }, [audioUrl, cacheKey, shared, onRequestAudio, ensureAudio, releaseOwned, ui]);

  const toggle = () => {
    if (disabled || status === 'loading') return;
    if (status === 'playing') stop();
    else void play();
  };

  const label = status === 'playing'
    ? pick(ui, 'Arrêter la lecture', 'Stop playback')
    : status === 'loading'
      ? pick(ui, 'Chargement de l’audio…', 'Loading audio…')
      : pick(ui, 'Écouter la réponse', 'Listen to the answer');

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
