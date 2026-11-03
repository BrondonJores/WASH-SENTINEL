import { Icon } from './icons';
import type { IconName } from './icons';
import { pick, useUILang } from '../lib/i18n';

/**
 * Premier écran qui parle : 3 exemples réels + bouton Parler + bandeau
 * d'alertes. Français simple, gros boutons (≥ 56 px), respect de
 * prefers-reduced-motion via les utilitaires motion-reduce.
 */
export interface WelcomeScreenProps {
  /** Nombre d'incidents critiques ouverts (0 = pas de bandeau). */
  count: number;
  /** Envoie une question dans la console. */
  onAsk: (question: string) => void;
  /** Ouvre le Mode Voix (dictée plein écran). */
  onSpeak: () => void;
  /** Lance la démo automatique (fil temporaire isolé). */
  onDemo: () => void;
}

interface WelcomeExample {
  label: string;
  labelEn: string;
  question: string;
  questionEn: string;
  hint: string;
  hintEn: string;
  icon: IconName;
}

const EXAMPLES: WelcomeExample[] = [
  {
    label: 'Signale une fuite à Bonanjo',
    labelEn: 'Report a leak in Bonanjo',
    question: 'Signale une fuite à Bonanjo',
    questionEn: 'Report a leak in Bonanjo',
    hint: 'Dire un problème d’eau',
    hintEn: 'Report a water problem',
    icon: 'droplet',
  },
  {
    label: 'Quelles écoles ont le plus besoin d’aide ?',
    labelEn: 'Which schools need help most?',
    question: 'Quelles écoles ont le plus besoin d’aide ?',
    questionEn: 'Which schools need help most?',
    hint: 'Voir où aider en premier',
    hintEn: 'See where to help first',
    icon: 'school',
  },
  {
    label: 'Tendances de Bonanjo sur 3 mois',
    labelEn: 'Bonanjo trends over 3 months',
    question: 'Tendances de Bonanjo sur 3 mois',
    questionEn: 'Bonanjo trends over 3 months',
    hint: 'Voir ce qui change',
    hintEn: 'See what is changing',
    icon: 'clock',
  },
];

/** Question envoyée par le bouton « Voir » du bandeau d'alertes. */
const criticalQuestion = (ui: string | undefined): string =>
  pick(ui, 'Voir les incidents ouverts', 'Show open incidents');

function MicIcon({ className = 'h-6 w-6' }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <path d="M12 18v3" />
    </svg>
  );
}

export function WelcomeScreen({ count, onAsk, onSpeak, onDemo }: WelcomeScreenProps) {
  const ui = useUILang();
  const plural = count > 1 ? 's' : '';
  return (
    <section aria-label={pick(ui, 'Pour commencer', 'To get started')} className="w-full text-left">
      {count > 0 && (
        <div
          role="status"
          className="flex items-center gap-3 rounded-2xl border border-danger/30 bg-danger-soft p-2 pl-4"
        >
          <Icon name="alert" className="h-6 w-6 shrink-0 text-danger" />
          <p className="min-w-0 flex-1 text-[15px] font-semibold leading-snug text-danger">
            {pick(
              ui,
              `${count} incident${plural} critique${plural} vous ${count > 1 ? 'attendent' : 'attend'}`,
              `${count} critical incident${plural} need${count > 1 ? '' : 's'} you`,
            )}
          </p>
          <button
            type="button"
            onClick={() => onAsk(criticalQuestion(ui))}
            aria-label={pick(ui, 'Voir les incidents critiques', 'See critical incidents')}
            className="min-h-[56px] shrink-0 rounded-xl bg-danger px-5 text-[16px] font-semibold text-danger-foreground transition-[background-color] duration-150 hover:bg-danger-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent motion-reduce:transition-none"
          >
            {pick(ui, 'Voir', 'See')}
          </button>
        </div>
      )}

      <h2 className="mt-5 font-display text-xl font-bold tracking-tight">
        {pick(ui, 'Que voulez-vous faire ?', 'What would you like to do?')}
      </h2>
      <p className="mt-1 text-[15px] text-ink-soft">
        {pick(ui, 'Touchez un bouton, je fais le reste.', 'Tap a button, I do the rest.')}
      </p>

      <div className="mt-3 flex flex-col gap-2.5">
        {EXAMPLES.map((ex) => (
          <button
            key={ex.label}
            type="button"
            onClick={() => onAsk(pick(ui, ex.question, ex.questionEn))}
            aria-label={pick(ui, `Demander : ${ex.label}`, `Ask: ${ex.labelEn}`)}
            className="flex min-h-[56px] w-full items-center gap-3 rounded-2xl border border-line bg-card px-4 py-3 text-left transition-[border-color] duration-150 ease-snap hover:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent motion-reduce:transition-none"
          >
            <span
              aria-hidden="true"
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-teal-700/10 text-teal-800 dark:bg-teal-300/15 dark:text-teal-200"
            >
              <Icon name={ex.icon} className="h-5 w-5" />
            </span>
            <span className="min-w-0">
              <span className="block text-[16px] font-semibold leading-snug">
                {pick(ui, ex.label, ex.labelEn)}
              </span>
              <span className="block text-sm text-ink-soft">{pick(ui, ex.hint, ex.hintEn)}</span>
            </span>
          </button>
        ))}

        <button
          type="button"
          onClick={onSpeak}
          aria-label={pick(ui, 'Parler à Sentinel avec le micro', 'Talk to Sentinel with the microphone')}
          className="flex min-h-[56px] w-full items-center justify-center gap-3 rounded-2xl bg-primary px-4 py-3 text-[16px] font-semibold text-primary-foreground transition-[background-color] duration-150 hover:bg-primary-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent motion-reduce:transition-none"
        >
          <MicIcon className="h-6 w-6" />
          {pick(ui, 'Parler', 'Talk')}
        </button>

        <button
          type="button"
          onClick={onDemo}
          aria-label={pick(ui, 'Voir une démonstration automatique', 'Watch an automatic demo')}
          className="flex min-h-[56px] w-full items-center justify-center gap-3 rounded-2xl border border-teal-700/30 bg-teal-700/10 px-4 py-3 text-[16px] font-semibold text-teal-800 transition-[border-color] duration-150 hover:border-teal-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent motion-reduce:transition-none dark:text-teal-200"
        >
          <Icon name="chat" className="h-6 w-6" />
          {pick(ui, 'Voir une démo', 'Watch a demo')}
        </button>
      </div>
    </section>
  );
}
