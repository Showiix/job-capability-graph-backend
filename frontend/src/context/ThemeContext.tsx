import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';

export type ThemeMode = 'dark' | 'light' | 'apollo';

interface ThemeContextValue {
  mode: ThemeMode;
  toggle: () => void;
  setMode: (m: ThemeMode) => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  mode: 'dark',
  toggle: () => {},
  setMode: () => {},
});

const STORAGE_KEY = 'theme';
const LEGACY_STORAGE_KEY = 'jsg-theme';
const THEME_CYCLE: Record<ThemeMode, ThemeMode> = {
  dark: 'light',
  light: 'apollo',
  apollo: 'dark',
};

const isThemeMode = (value: string | null): value is ThemeMode =>
  value === 'dark' || value === 'light' || value === 'apollo';

export const ThemeProvider = ({ children }: { children: ReactNode }) => {
  const [mode, setModeState] = useState<ThemeMode>(() => {
    const saved = localStorage.getItem(STORAGE_KEY) ?? localStorage.getItem(LEGACY_STORAGE_KEY);
    return isThemeMode(saved) ? saved : 'dark';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', mode);
    localStorage.setItem(STORAGE_KEY, mode);
  }, [mode]);

  const setMode = (m: ThemeMode) => setModeState(m);
  const toggle = () => setModeState((m) => THEME_CYCLE[m]);

  return (
    <ThemeContext.Provider value={{ mode, toggle, setMode }}>
      {children}
    </ThemeContext.Provider>
  );
};

// eslint-disable-next-line react-refresh/only-export-components
export const useTheme = () => useContext(ThemeContext);
