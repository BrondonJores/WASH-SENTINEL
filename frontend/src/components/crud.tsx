import type { ReactNode } from 'react';
import { Button } from './ui';

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-ink-soft">{label}</span>
      {children}
    </label>
  );
}

export function Pager({
  page,
  lastPage,
  onPage,
}: {
  page: number;
  lastPage: number;
  onPage: (p: number) => void;
}) {
  if (lastPage <= 1) return null;
  return (
    <div className="mt-4 flex items-center justify-between">
      <p className="font-mono text-xs text-ink-faint">
        Page {page} / {lastPage}
      </p>
      <div className="flex gap-2">
        <Button size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          ← Précédent
        </Button>
        <Button size="sm" disabled={page >= lastPage} onClick={() => onPage(page + 1)}>
          Suivant →
        </Button>
      </div>
    </div>
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
