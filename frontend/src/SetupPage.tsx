import { useEffect, useState } from "react";
import type { ScannerSignal } from "./api";
import Logo from "./Logo";
import ScannerPanel from "./ScannerPanel";
import { useTheme, type Theme } from "./theme";

function storedTheme(): Theme {
  try {
    return JSON.parse(localStorage.getItem("theme") || '"light"') === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

/** Setup Screener on its own page (/?page=setups): the SwingScanner's breakouts by date and market, with the
 * portfolio sizing and "why this trade". A signal opens its chart in the shared Charting Lab tab. */
export default function SetupPage() {
  const [theme, setTheme] = useState<Theme>(storedTheme);
  useTheme(theme);
  const [selected, setSelected] = useState<ScannerSignal | null>(null);
  useEffect(() => {
    document.title = "Setup Screener · Charting Lab";
    const onStorage = (e: StorageEvent) => { if (e.key === "theme") setTheme(storedTheme()); };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);
  const flip = () => {
    const t = theme === "dark" ? "light" : "dark";
    localStorage.setItem("theme", JSON.stringify(t));
    setTheme(t);
  };

  return (
    <div className="app setup-page">
      <header className="topbar">
        <a className="brand" href="/" title="Open the chart"><Logo /> Charting Lab</a>
        <span className="page-title">Setup Screener</span>
        <span className="muted small">Breakouts from your SwingScanner rulebook: entry, stop, quantity, and why</span>
        <span className="spacer" />
        <button className="theme-toggle" onClick={flip} title={theme === "dark" ? "Switch to day view" : "Switch to night view"}>
          {theme === "dark" ? "☾ Night" : "☀ Day"}
        </button>
      </header>
      <main className="main setup-main">
        <ScannerPanel page selected={selected} onPick={setSelected} />
      </main>
    </div>
  );
}
