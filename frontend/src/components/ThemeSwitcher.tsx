import { useTheme, type ThemePreference } from "../lib/theme";

export function ThemeSwitcher() {
  const { preference, setPreference } = useTheme();
  return (
    <select
      aria-label="Colour theme"
      value={preference}
      onChange={(e) => setPreference(e.target.value as ThemePreference)}
    >
      <option value="system">System theme</option>
      <option value="light">Light</option>
      <option value="dark">Dark</option>
    </select>
  );
}
