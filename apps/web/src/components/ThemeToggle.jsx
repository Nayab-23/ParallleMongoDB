import { useTheme } from "../context/ThemeContext";

export default function ThemeToggle({ collapsed = false }) {
  const { theme, toggleTheme } = useTheme();

  return (
    <button onClick={toggleTheme} className="theme-toggle-btn">
      {theme === "dark" ? "☀️" : "🌙"}
      {!collapsed && <span className="nav-text" style={{ marginLeft: 6 }}>{theme === "dark" ? "Light" : "Dark"}</span>}
    </button>
  );
}
