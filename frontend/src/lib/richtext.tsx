import type { ReactNode } from 'react';

const BULLET_RE = /^\s*([*\-•])\s+(.*)$/;
const NUMBERED_RE = /^\s*\d+[.)]\s+(.*)$/;
const BOLD_RE = /(\*\*[^*]+\*\*)/g;

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  return text.split(BOLD_RE).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') && part.length > 4 ? (
      <strong key={`${keyPrefix}-b${i}`} className="font-semibold text-ink">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <span key={`${keyPrefix}-t${i}`}>{part}</span>
    ),
  );
}

/**
 * Mini-markdown sûr (sans innerHTML) pour les réponses de l'agent :
 * puces `*`/`-`, listes numérotées, **gras**. Ligne par ligne donc
 * compatible avec l'affichage progressif du streaming.
 */
export function renderRichText(content: string): ReactNode[] {
  const lines = content.split('\n');
  const blocks: ReactNode[] = [];
  let items: string[] = [];
  let ordered = false;

  const flushList = () => {
    if (items.length === 0) return;
    const rows = items;
    const key = `l${blocks.length}`;
    items = [];
    blocks.push(
      ordered ? (
        <ol key={key} className="list-decimal space-y-1 pl-5 marker:font-mono marker:text-teal-700 dark:marker:text-teal-300">
          {rows.map((row, i) => (
            <li key={i}>{renderInline(row, `${key}-${i}`)}</li>
          ))}
        </ol>
      ) : (
        <ul key={key} className="list-disc space-y-1 pl-5 marker:text-teal-600 dark:marker:text-teal-300">
          {rows.map((row, i) => (
            <li key={i}>{renderInline(row, `${key}-${i}`)}</li>
          ))}
        </ul>
      ),
    );
  };

  lines.forEach((line, i) => {
    const bullet = line.match(BULLET_RE);
    const numbered = bullet ? null : line.match(NUMBERED_RE);
    if (bullet ?? numbered) {
      const wantOrdered = numbered !== null;
      if (items.length > 0 && wantOrdered !== ordered) flushList();
      ordered = wantOrdered;
      items.push((bullet ?? numbered)![1]);
      return;
    }
    flushList();
    if (line.trim() === '') {
      blocks.push(<span key={`s${i}`} className="block h-2" aria-hidden="true" />);
    } else {
      blocks.push(<p key={`p${i}`}>{renderInline(line, `p${i}`)}</p>);
    }
  });
  flushList();
  return blocks;
}
