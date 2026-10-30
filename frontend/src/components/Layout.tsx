import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import CommandPalette from './CommandPalette';
import EdgeDock from './EdgeDock';

export default function Layout({ children }: { children: ReactNode }) {
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className="relative min-h-screen overflow-x-clip bg-canvas text-ink">
      <div aria-hidden="true" className="ambient" />
      <EdgeDock onSearch={() => setPaletteOpen(true)} />
      <main className="relative z-10 mx-auto w-full max-w-7xl px-4 py-5 sm:px-8">{children}</main>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
