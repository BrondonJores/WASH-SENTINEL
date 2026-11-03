import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { getUILang, pick } from './lib/i18n';

export type Theme = 'light' | 'dark';

interface ThemeState {
  theme: Theme;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeState | null>(null);

/** Clé localStorage du thème (cohérente avec TOKEN_STORAGE_KEY dans lib/api). */
const THEME_STORAGE_KEY = 'wash_admin_theme';

function initialTheme(): Theme {
  const saved = localStorage.getItem(THEME_STORAGE_KEY);
  if (saved === 'light' || saved === 'dark') return saved;
  return 'dark'; // Mission Control : sombre par défaut.
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => (t === 'dark' ? 'light' : 'dark'));
  }, []);

  const value = useMemo(() => ({ theme, toggle }), [theme, toggle]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

/* eslint-disable-next-line react-refresh/only-export-components -- hook co-localisé avec son provider. */
export function useTheme(): ThemeState {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error(pick(getUILang(), 'useTheme utilisé hors ThemeProvider', 'useTheme used outside ThemeProvider'));
  return ctx;
}
