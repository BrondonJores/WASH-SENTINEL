import type { ReactNode } from 'react';
import { Button } from './ui';
import { Select } from './controls';
import { fmtNum } from '../lib/wash';

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-ink-soft">{label}</span>
      {children}
    </label>
  );
}

const PER_PAGE_OPTIONS = [10, 20, 50] as const;

type PageItem = number | '…';

/** Fenêtre de pages : 1 … 4 5 6 … 12 (page courante ± 1, bords élargis). */
function pageItems(page: number, lastPage: number): PageItem[] {
  if (lastPage <= 7) {
    return Array.from({ length: lastPage }, (_, i) => i + 1);
  }
  const keep = new Set<number>([1, lastPage, page - 1, page, page + 1]);
  if (page <= 3) {
    keep.add(2);
    keep.add(3);
    keep.add(4);
  }
  if (page >= lastPage - 2) {
    keep.add(lastPage - 3);
    keep.add(lastPage - 2);
    keep.add(lastPage - 1);
  }
  const sorted = [...keep].filter((p) => p >= 1 && p <= lastPage).sort((a, b) => a - b);
  const out: PageItem[] = [];
  let prev = 0;
  for (const p of sorted) {
    if (p - prev > 1) out.push('…');
    out.push(p);
    prev = p;
  }
  return out;
}

export function Pager({
  page,
  lastPage,
  onPage,
  total,
  perPage,
  onPerPage,
}: {
  page: number;
  lastPage: number;
  onPage: (p: number) => void;
  total?: number;
  perPage?: number;
  onPerPage?: (n: number) => void;
}) {
  const effectivePerPage = perPage ?? 20;
  if (lastPage <= 1 && (total === undefined || total <= effectivePerPage)) return null;

  const from = total === undefined || total === 0 ? 0 : (page - 1) * effectivePerPage + 1;
  const to = total === undefined ? 0 : Math.min(page * effectivePerPage, total);
  const showPerPage = onPerPage !== undefined && perPage !== undefined;

  return (
    <nav aria-label="Pagination" className="mt-4 flex flex-wrap items-center justify-between gap-3">
      <p aria-live="polite" className="font-mono text-xs tabular-nums text-ink-faint">
        {total === undefined ? (
          <>
            Page {page} / {lastPage}
          </>
        ) : (
          <>
            {fmtNum(from)}–{fmtNum(to)} sur {fmtNum(total)}
          </>
        )}
      </p>
      <div className="flex flex-wrap items-center gap-1.5">
        <Button
          size="sm"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
          aria-label="Page précédente"
        >
          ← Précédent
        </Button>
        {pageItems(page, lastPage).map((item, idx) =>
          item === '…' ? (
            <span key={`gap-${idx}`} aria-hidden="true" className="px-1 text-sm text-ink-faint">
              …
            </span>
          ) : (
            <Button
              key={item}
              size="sm"
              variant={item === page ? 'primary' : 'secondary'}
              disabled={item === page}
              onClick={() => onPage(item)}
              aria-label={`Aller à la page ${item}`}
              aria-current={item === page ? 'page' : undefined}
            >
              {item}
            </Button>
          ),
        )}
        <Button
          size="sm"
          disabled={page >= lastPage}
          onClick={() => onPage(page + 1)}
          aria-label="Page suivante"
        >
          Suivant →
        </Button>
      </div>
      {showPerPage && (
        <label className="flex items-center gap-2 text-sm text-ink-soft">
          <span aria-hidden="true">Afficher</span>
          <Select
            value={String(perPage)}
            onChange={(e) => onPerPage(Number(e.target.value))}
            ariaLabel="Nombre d'éléments par page"
            options={PER_PAGE_OPTIONS.map((n) => ({ value: String(n), label: `${n} / page` }))}
          />
        </label>
      )}
    </nav>
  );
}

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
      <span>{message}</span>
      {onRetry && (
        <Button size="sm" variant="ghost" onClick={onRetry}>
          Réessayer
        </Button>
      )}
    </div>
  );
}

export function Pretty({ data }: { data: unknown }) {
  if (data == null) return <span className="text-ink-faint">—</span>;
  return (
    <pre className="max-h-64 overflow-auto rounded-md bg-raised p-3 font-mono text-xs leading-relaxed">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}
