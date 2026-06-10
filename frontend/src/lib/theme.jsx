import React, { createContext, useContext, useEffect, useState } from 'react';

/**
 * Phase 1 dark-mode foundation.
 *
 * - Reads `localStorage.theme` ('light' | 'dark'); defaults to 'light'.
 * - Toggles the `dark` class on <html> so Tailwind's `darkMode: 'class'` works.
 * - Exposes `window.__setTheme('dark' | 'light')` for manual smoke testing.
 *
 * NOTE: Phase 4 will add a real UI toggle button. We intentionally do not
 * render one here — this slice only ships the plumbing.
 */
const _DEFAULT = Symbol('theme-context-not-mounted');
const ThemeContext = createContext(_DEFAULT);

function applyThemeClass(theme) {
  const root = document.documentElement;
  if (theme === 'dark') {
    root.classList.add('dark');
  } else {
    root.classList.remove('dark');
  }
}

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(() => {
    if (typeof window === 'undefined') return 'light';
    return window.localStorage.getItem('theme') || 'light';
  });

  useEffect(() => {
    applyThemeClass(theme);
    try {
      window.localStorage.setItem('theme', theme);
    } catch {
      /* localStorage may be blocked in some sandboxes — non-fatal */
    }
  }, [theme]);

  useEffect(() => {
    window.__setTheme = (t) => {
      if (t !== 'dark' && t !== 'light') {
        console.warn('[theme] expected "dark" | "light", got:', t);
        return;
      }
      setThemeState(t);
    };
    return () => {
      try {
        delete window.__setTheme;
      } catch {
        window.__setTheme = undefined;
      }
    };
  }, []);

  const value = React.useMemo(() => ({ theme, setTheme: setThemeState }), [theme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (ctx === _DEFAULT) {
    throw new Error('useTheme() must be used inside <ThemeProvider>');
  }
  return ctx;
}
