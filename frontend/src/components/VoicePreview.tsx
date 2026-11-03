import { Button } from './ui';
import { pick, useUILang } from '../lib/i18n';

const VOICE_LANGUAGE_LABELS: Record<string, string> = {
  fr: 'français',
  dua_Latn: 'douala',
  bassa: 'bassa',
  ewondo: 'ewondo',
  auto: 'détection auto',
};

const VOICE_LANGUAGE_LABELS_EN: Record<string, string> = {
  fr: 'French',
  dua_Latn: 'Duala',
  bassa: 'Bassa',
  ewondo: 'Ewondo',
  auto: 'auto-detect',
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
  const ui = useUILang();
  const count = countWords(transcript);
  const labels = ui === 'en' ? VOICE_LANGUAGE_LABELS_EN : VOICE_LANGUAGE_LABELS;
  const langLabel =
    languageEffective !== null && languageEffective !== ''
      ? (labels[languageEffective] ?? languageEffective)
      : null;
  return (
    <div role="group" aria-label={pick(ui, 'Aperçu de la dictée', 'Dictation preview')} className="mt-3 rounded-xl border border-line bg-card px-4 py-3">
      <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-faint">
        {pick(ui, `Dictée · ${count} mot${count > 1 ? 's' : ''}`, `Dictation · ${count} word${count > 1 ? 's' : ''}`)}
        {langLabel !== null ? pick(ui, ` · Transcrit en ${langLabel}`, ` · Transcribed in ${langLabel}`) : ''}
      </p>
      <p className="mt-1 whitespace-pre-wrap text-[15px] leading-relaxed text-ink">{transcript}</p>
      {audioUrl !== null && audioUrl !== '' && (
        <audio controls preload="none" src={audioUrl} aria-label={pick(ui, 'Réécouter l’enregistrement', 'Replay the recording')} className="mt-2 h-8 w-full" />
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button type="button" variant="primary" size="sm" onClick={onSend} disabled={disabled}>
          {pick(ui, 'Envoyer', 'Send')}
        </Button>
        <Button type="button" variant="secondary" size="sm" onClick={onEdit} disabled={disabled}>
          {pick(ui, 'Corriger', 'Edit')}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onDiscard}>
          {pick(ui, 'Jeter', 'Discard')}
        </Button>
      </div>
    </div>
  );
}
