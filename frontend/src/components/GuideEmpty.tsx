import { Button } from './ui';
import { Icon } from './icons';

export interface GuideEmptyAction {
  label: string;
  question: string;
}

/**
 * État vide guidé : phrase simple + conseil concret + 1-2 actions
 * qui reposent une question dans le chat (via onAsk).
 */
export function GuideEmpty({
  phrase,
  conseil,
  actions = [],
  onAsk,
}: {
  phrase: string;
  conseil: string;
  actions?: GuideEmptyAction[];
  onAsk?: (q: string) => void;
}) {
  return (
    <div className="flex flex-col items-center py-4 text-center">
      <span
        aria-hidden="true"
        className="flex h-12 w-12 items-center justify-center rounded-full bg-teal-700/10 text-teal-800 dark:bg-teal-300/15 dark:text-teal-200"
      >
        <Icon name="inbox" className="h-6 w-6" />
      </span>
      <p className="mt-3 text-[15px] font-semibold leading-relaxed">{phrase}</p>
      <p className="mt-1 max-w-sm text-sm leading-relaxed text-stone-500 dark:text-stone-400">
        {conseil}
      </p>
      {onAsk !== undefined && actions.length > 0 && (
        <div className="mt-3 flex flex-wrap justify-center gap-2">
          {actions.map((a, i) => (
            <Button
              key={a.label}
              variant={i === 0 ? 'primary' : 'secondary'}
              size="sm"
              onClick={() => onAsk(a.question)}
            >
              {a.label}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
