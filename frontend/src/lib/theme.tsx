import { createContext, useContext, useEffect, type ReactNode } from "react";

export type ThemePreference = "light";

interface ThemeContextValue {
  preference: ThemePreference;
  setPreference: (p: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  preference: "light",
  setPreference: () => {},
});

export function ThemeProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    document.documentElement.dataset.theme = "light";
    try {
      localStorage.setItem("ftip-theme", "light");
    } catch {
      // ignore
    }
  }, []);

  return (
    <ThemeContext.Provider value={{ preference: "light", setPreference: () => {} }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
