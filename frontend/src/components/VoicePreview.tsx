import { Button } from './ui';

const VOICE_LANGUAGE_LABELS: Record<string, string> = {
  fr: 'français',
  dua_Latn: 'douala',
  bassa: 'bassa',
  ewondo: 'ewondo',
  auto: 'détection auto',
};

export interface VoicePreviewProps {
  /** Transcription à relire avant envoi. */
  transcript: string;
  /** Envoyer la transcription comme message. */
  onSend: () => void;
  /** Remettre le texte dans le champ pour correction. */
  onEdit: () => void;
  /** Jeter la transcription. */
  onDiscard: () => void;
  /** Désactive Envoyer / Corriger pendant l’envoi ou le streaming. */
  disabled?: boolean;
  /** Langue effective renvoyée par le moteur (ex. "dua_Latn", "auto"). */
  languageEffective?: string | null;
  /** URL de l’enregistrement d’origine pour réécoute (optionnelle). */
  audioUrl?: string | null;
}

function countWords(text: string): number {
  const t = text.trim();
  return t === '' ? 0 : t.split(/\s+/).length;
}

/**
 * Bulle de prévisualisation d’une dictée : relecture + compte de mots.
 * Sobre, FR, style maison teal/stone. Sans synthèse vocale.
 */
export function VoicePreview({ transcript, onSend, onEdit, onDiscard, disabled = false, languageEffective = null, audioUrl = null }: VoicePreviewProps) {
  const count = countWords(transcript);
  const langLabel =
    languageEffective !== null && languageEffective !== ''
      ? (VOICE_LANGUAGE_LABELS[languageEffective] ?? languageEffective)
      : null;
  return (
    <div role="group" aria-label="Aperçu de la dictée" className="mt-3 rounded-xl border border-line bg-card px-4 py-3">
      <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-faint">
        Dictée · {count} mot{count > 1 ? 's' : ''}
        {langLabel !== null ? ` · Transcrit en ${langLabel}` : ''}
      </p>
      <p className="mt-1 whitespace-pre-wrap text-[15px] leading-relaxed text-ink">{transcript}</p>
      {audioUrl !== null && audioUrl !== '' && (
        <audio controls preload="none" src={audioUrl} aria-label="Réécouter l’enregistrement" className="mt-2 h-8 w-full" />
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button type="button" variant="primary" size="sm" onClick={onSend} disabled={disabled}>
          Envoyer
        </Button>
        <Button type="button" variant="secondary" size="sm" onClick={onEdit} disabled={disabled}>
          Corriger
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onDiscard}>
          Jeter
        </Button>
      </div>
    </div>
  );
}
