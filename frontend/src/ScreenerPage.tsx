import { useEffect, useState } from "react";
import { api, type PatternMeta, type TodayRow } from "./api";
import Logo from "./Logo";
import PatternsToday from "./PatternsToday";
import { useTheme, type Theme } from "./theme";

/** The chart link of a screened stock: /?symbol=NSE:TCS&tf=1D&patterns=pp,bbr (read by App on load). */
export function chartUrl(row: TodayRow, tf: string, patterns: string[]): string {
  const q = new URLSearchParams({ symbol: row.symbol, tf });
  if (patterns.length) q.set("patterns", patterns.join(","));
  return `/?${q}`;
}

function storedTheme(): Theme {
  try {
    return JSON.parse(localStorage.getItem("theme") || '"light"') === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

/** Pattern Screener on its own page (/?page=screener): opened in a new browser tab from the chart's top bar.
 * A stock opens in one shared chart tab ("charting-lab"), so the screener stays where it is. */
export default function ScreenerPage() {
  const [theme, setTheme] = useState<Theme>(storedTheme);
  useTheme(theme);
  const [metas, setMetas] = useState<PatternMeta[]>([]);
  useEffect(() => {
    document.title = "Pattern Screener · Charting Lab";
    api.patterns().then(setMetas, () => {});
    const onStorage = (e: StorageEvent) => { if (e.key === "theme") setTheme(storedTheme()); }; // switched elsewhere
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);
  const flip = () => {
    const t = theme === "dark" ? "light" : "dark";
    localStorage.setItem("theme", JSON.stringify(t));
    setTheme(t);
  };

  return (
    <div className="app screener-page">
      <header className="topbar">
        <a className="brand" href="/" title="Open the chart"><Logo /> Charting Lab</a>
        <span className="page-title">Pattern Screener</span>
        <span className="spacer" />
        <button className="theme-toggle" onClick={flip} title={theme === "dark" ? "Switch to day view" : "Switch to night view"}>
          {theme === "dark" ? "☾ Night" : "☀ Day"}
        </button>
      </header>
      <main className="main">
        <PatternsToday
          metas={metas}
          onOpen={(row, tf, pats) => window.open(chartUrl(row, tf, pats), "charting-lab")}
        />
      </main>
    </div>
  );
}
