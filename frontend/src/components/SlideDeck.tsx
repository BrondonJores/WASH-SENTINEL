import { useCallback, useEffect, useState } from 'react';
import { Icon } from './icons';

export interface DeckStat {
  label: string;
  value: string;
}

export interface DeckSlide {
  kind: 'cover' | 'stats' | 'bullets';
  title: string;
  subtitle?: string;
  lines: string[];
  stats: DeckStat[];
  note?: string;
}

const navBtn =
  'flex h-8 w-8 items-center justify-center rounded-md border border-line text-ink-soft transition-[background-color,transform] duration-150 ease-snap hover:bg-raised active:scale-[0.97] motion-reduce:transition-none motion-reduce:active:scale-100';

export function SlideDeck({ slides }: { slides: DeckSlide[] }) {
  const total = slides.length;
  const [index, setIndex] = useState(0);
  const go = useCallback((dir: number) => setIndex((i) => (i + dir + total) % total), [total]);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName ?? '';
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      if (e.key === 'ArrowRight') go(1);
      if (e.key === 'ArrowLeft') go(-1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [go]);

  if (total === 0) return null;
  const slide = slides[index];

  const body =
    slide.kind === 'cover' ? (
      <div className="flex min-h-64 flex-col justify-center rounded-xl bg-teal-950 px-6 py-8 text-center text-white dark:bg-teal-900">
        <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-teal-300">
          Briefing Sentinel
        </p>
        <p className="mt-3 font-display text-2xl font-bold tracking-tight">{slide.title}</p>
        {slide.subtitle && <p className="mt-1 text-sm text-teal-200/80">{slide.subtitle}</p>}
        {slide.stats.length > 0 && (
          <div className="mx-auto mt-6 grid w-full max-w-lg grid-cols-3 gap-3">
            {slide.stats.map((s, i) => (
              <div key={i} className="rounded-lg bg-white/10 px-2 py-3">
                <p className="font-mono text-xl font-bold tabular-nums">{s.value}</p>
                <p className="mt-1 text-[11px] leading-tight text-teal-100/80">{s.label}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    ) : (
      <div className="min-h-64 px-1 py-2">
        <p className="text-lg font-bold tracking-tight">{slide.title}</p>
        {slide.stats.length > 0 && (
          <div className="mt-3 grid grid-cols-3 gap-3">
            {slide.stats.map((s, i) => (
              <div key={i} className="rounded-lg bg-raised px-2 py-3 text-center">
                <p className="font-mono text-lg font-bold tabular-nums">{s.value}</p>
                <p className="mt-1 text-[11px] leading-tight text-ink-soft">{s.label}</p>
              </div>
            ))}
          </div>
        )}
        {slide.lines.length > 0 && (
          <ul className="mt-3 space-y-2">
            {slide.lines.map((l, i) => (
              <li key={i} className="flex gap-2 text-sm leading-relaxed">
                <span aria-hidden="true" className="font-mono font-bold text-accent">
                  ›
                </span>
                <span>{l}</span>
              </li>
            ))}
          </ul>
        )}
        {slide.note && (
          <p className="mt-3 text-xs text-ink-faint">{slide.note}</p>
        )}
      </div>
    );

  return (
    <div>
      <div key={index} className="msg-in">
        {body}
      </div>
      {total > 1 && (
        <div className="mt-3 flex items-center gap-2">
          <button type="button" onClick={() => go(-1)} aria-label="Slide précédente" className={navBtn}>
            <Icon name="arrow-right" className="h-4 w-4 rotate-180" />
          </button>
          <button type="button" onClick={() => go(1)} aria-label="Slide suivante" className={navBtn}>
            <Icon name="arrow-right" className="h-4 w-4" />
          </button>
          <div className="ml-1 flex items-center gap-1.5">
            {slides.map((_, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setIndex(i)}
                aria-label={`Aller à la slide ${i + 1}`}
                className={`h-1.5 rounded-full transition-all ${
                  i === index
                    ? 'w-6 bg-accent'
                    : 'w-1.5 bg-line hover:bg-ink-faint'
                }`}
              />
            ))}
          </div>
          <div className="flex-1" />
          <span className="font-mono text-[11px] tabular-nums text-ink-faint">
            {index + 1} / {total}
          </span>
        </div>
      )}
    </div>
  );
}
