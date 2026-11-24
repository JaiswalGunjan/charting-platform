import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Alert, type CustomDef, type ExplainResult, type Health, type IndicatorMeta, type Quote } from "./api";
import { live, type ConnState } from "./live";
import Chart, { exchangeTimeZone, fmt, type RangeRequest } from "./Chart";
import SymbolSearch from "./SymbolSearch";
import { AiPanel, AlertsPanel, WatchlistPanel } from "./Panels";
import { newIndicator, type ActiveIndicator } from "./indicatorStyle";
import { CustomEditor, IndicatorPicker, IndicatorSettings } from "./IndicatorDialogs";
import AlertDialog from "./AlertDialog";
import { RANGES, timeframeForRange, type RangeId } from "./ranges";
import { useTheme, type Theme } from "./theme";

const TF_SHORT: Record<string, string> = { "1D": "D", "1W": "W", "1M": "M", "1Y": "Y" };
const TF_GROUPS: [string, string[]][] = [
  ["Minutes", ["1m", "3m", "5m", "15m", "30m"]],
  ["Hours", ["1h", "2h", "4h"]],
  ["Days and longer", ["1D", "1W", "1M", "1Y"]],
];
const TF_TITLE: Record<string, string> = {
  "1m": "1 minute", "3m": "3 minutes", "5m": "5 minutes", "15m": "15 minutes", "30m": "30 minutes",
  "1h": "Hourly", "2h": "2 hours", "4h": "4 hours", "1D": "Daily", "1W": "Weekly", "1M": "Monthly", "1Y": "Yearly",
};
const MINUTE_TFS = new Set(TF_GROUPS[0][1]);

function usePersisted<T>(key: string, init: T): [T, (v: T | ((o: T) => T)) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      const s = localStorage.getItem(key);
      return s ? (JSON.parse(s) as T) : init;
    } catch {
      return init;
    }
  });
  useEffect(() => localStorage.setItem(key, JSON.stringify(v)), [key, v]);
  return [v, setV];
}

interface Toast { id: number; text: string }
type Dialog =
  | { kind: "picker" }
  | { kind: "alert" }
  | { kind: "settings"; key: string }
  | { kind: "custom"; id?: string; def?: CustomDef };

export default function App() {
  const [symbol, setSymbol] = usePersisted("symbol", "NSE:RELIANCE");
  const [tf, setTf] = usePersisted("tf", "1D");
  const [themeChoice, setThemeChoice] = usePersisted<Theme>("theme", "light"); // day view by default
  const theme = useTheme(themeChoice);
  const [health, setHealth] = useState<Health | null>(null);
  const [indicators, setIndicators] = usePersisted<ActiveIndicator[]>("indicators", []);
  const [metas, setMetas] = useState<Record<string, IndicatorMeta>>({});
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [tab, setTab] = usePersisted<"watchlist" | "alerts" | "ai">("tab", "watchlist");
  const [ai, setAi] = useState<ExplainResult | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [conn, setConn] = useState<ConnState>("connecting");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [menu, setMenu] = useState<"tf" | null>(null);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [range, setRange] = useState<RangeRequest | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const reloadMetas = useCallback(
    () => api.indicators().then((ms) => {
      const m = Object.fromEntries(ms.map((x) => [x.id, x]));
      setMetas(m);
      return m;
    }),
    [],
  );

  useEffect(() => {
    live.connect();
    const offState = live.onState(setConn);
    api.health().then(setHealth, () => {});
    // drop saved chart entries whose indicator no longer exists (e.g. a deleted custom one)
    reloadMetas().then((m) => setIndicators((xs) => xs.filter((x) => m[x.id])), () => {});
    return offState;
  }, [reloadMetas, setIndicators]);

  const reloadAlerts = useCallback(() => void api.alerts().then(setAlerts, () => {}), []);
  useEffect(reloadAlerts, [reloadAlerts]);

  // quotes for the open symbol + alert toasts
  useEffect(() => {
    setQuote(null);
    return live.on((m) => {
      if (m.type === "quote" && m.symbol === symbol) setQuote(m);
      else if (m.type === "subscribed" && m.symbol === symbol) setQuote(m.quote);
      else if (m.type === "alert") {
        const id = Date.now() + Math.random();
        setToasts((t) => [...t, { id, text: `🔔 ${m.message} @ ${fmt(m.price)}` }]);
        setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 8000);
        reloadAlerts();
      }
    });
  }, [symbol, reloadAlerts]);

  useEffect(() => {
    const close = (e: MouseEvent) => !menuRef.current?.contains(e.target as Node) && setMenu(null);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.altKey && !e.ctrlKey && e.key.toLowerCase() === "a") {
        e.preventDefault();
        setDialog({ kind: "alert" });
      }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);

  const aiLevels = useMemo(
    () => (ai?.analysis && ai.symbol === symbol ? ai.analysis.key_levels : []),
    [ai, symbol],
  );
  const chg = quote?.change ?? 0;
  const hourlyOnly = health?.intraday_history === "1h";

  const pickTf = (t: string) => {
    setTf(t);
    setRange(null);
    setMenu(null);
  };
  const pickRange = (id: RangeId) => {
    setTf(timeframeForRange(id, tf, health?.intraday_history ?? "1m"));
    setRange((r) => ({ id, nonce: (r?.nonce ?? 0) + 1 }));
  };
  const tfTitle = (t: string) =>
    TF_TITLE[t] + (hourlyOnly && MINUTE_TFS.has(t) ? " — no stored minute history (live bars only)" : "");

  const openCustom = async (id?: string) => {
    if (!id) return setDialog({ kind: "custom" });
    const all = await api.customIndicators();
    const c = all.find((x) => x.id === id);
    if (c) setDialog({ kind: "custom", id, def: { name: c.name, overlay: c.overlay, inputs: c.inputs, plots: c.plots, levels: c.levels } });
  };

  const settingsInd = dialog?.kind === "settings" ? indicators.find((i) => i.key === dialog.key) : undefined;

  return (
    <div className="app">
      <header className="topbar" ref={menuRef}>
        <div className="brand">◆ Charting Lab</div>
        <SymbolSearch value={symbol} onPick={setSymbol} />
        <div className="quote">
          <b>{fmt(quote?.ltp)}</b>
          {quote?.change_pct != null && (
            <span className={chg >= 0 ? "up" : "down"}>
              {chg >= 0 ? "+" : ""}{fmt(quote.change)} ({chg >= 0 ? "+" : ""}{quote.change_pct.toFixed(2)}%)
            </span>
          )}
        </div>
        <div className="sep" />
        <div className="menu-anchor">
          <button className={`tf-btn${menu === "tf" ? " active" : ""}`} title={`Timeframe: ${TF_TITLE[tf]}`}
            onClick={() => setMenu(menu === "tf" ? null : "tf")}>
            {TF_SHORT[tf] ?? tf} <span className="caret">▾</span>
          </button>
          {menu === "tf" && (
            <div className="menu tf-menu">
              {TF_GROUPS.map(([g, ts]) => (
                <div key={g}>
                  <div className="menu-head">{g}</div>
                  {ts.map((t) => (
                    <div key={t} className={`menu-item${t === tf ? " sel" : ""}${hourlyOnly && MINUTE_TFS.has(t) ? " nodata" : ""}`}
                      title={tfTitle(t)} onClick={() => pickTf(t)}>
                      <span>{TF_TITLE[t]}</span><span className="muted">{TF_SHORT[t] ?? t}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="sep" />
        <button onClick={() => setDialog({ kind: "picker" })}>ƒx Indicators</button>
        <button title="Create alert (Alt+A)" onClick={() => setDialog({ kind: "alert" })}>
          <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
            style={{ verticalAlign: "-3px", marginRight: 4 }}>
            <circle cx="10" cy="11" r="6.5" /><path d="M10 7.5V11l2.5 1.5M3 4.5l2.5-2M17 4.5l-2.5-2" />
          </svg>Alert
        </button>
        <button onClick={() => setTab("ai")}>✦ Explain</button>
        <div className="spacer" />
        <span
          className={`conn ${conn}${health?.simulated_ticks ? " sim" : ""}`}
          title={health?.simulated_ticks
            ? "Ticks are simulated (random walk from the last real close) and never saved"
            : `live feed: ${conn}`}
        >
          ● {conn !== "open" ? conn : health?.simulated_ticks ? "Simulated ticks" : "Live"}
        </span>
        <button className="theme-toggle" title={theme === "dark" ? "Switch to day view" : "Switch to night view"}
          onClick={() => setThemeChoice(theme === "dark" ? "light" : "dark")}>
          {theme === "dark" ? "☾ Night" : "☀ Day"}
        </button>
      </header>

      <main className="main">
        <div className="chart-col">
          <Chart
            symbol={symbol}
            tf={tf}
            theme={theme}
            range={range}
            indicators={indicators}
            metas={metas}
            alerts={alerts}
            aiLevels={aiLevels}
            onRemoveIndicator={(k) => setIndicators((xs) => xs.filter((x) => x.key !== k))}
            onEditIndicator={(key) => setDialog({ kind: "settings", key })}
            onToggleIndicator={(k) => setIndicators((xs) => xs.map((x) => (x.key === k ? { ...x, hidden: !x.hidden } : x)))}
          />
          <div className="rangebar">
            {RANGES.map((r) => (
              <button key={r} className={range?.id === r ? "active" : ""} onClick={() => pickRange(r)}
                title={r === "All" ? "Entire history" : r === "YTD" ? "Year to date" : `Last ${r}`}>{r}</button>
            ))}
            <span className="spacer" />
            <span className="muted small">{TF_TITLE[tf]} · times in {exchangeTimeZone(symbol, tf)}</span>
          </div>
        </div>
        <aside className="sidebar">
          <nav className="tabs">
            <button className={tab === "watchlist" ? "active" : ""} onClick={() => setTab("watchlist")}>Watchlist</button>
            <button className={tab === "alerts" ? "active" : ""} onClick={() => setTab("alerts")}>
              Alerts{alerts.some((a) => a.status === "active") ? ` (${alerts.filter((a) => a.status === "active").length})` : ""}
            </button>
            <button className={tab === "ai" ? "active" : ""} onClick={() => setTab("ai")}>AI</button>
          </nav>
          <div className="tab-body">
            {tab === "watchlist" && <WatchlistPanel current={symbol} onPick={setSymbol} />}
            {tab === "alerts" && <AlertsPanel symbol={symbol} lastPrice={quote?.ltp ?? null} alerts={alerts} reload={reloadAlerts} />}
            {tab === "ai" && <AiPanel symbol={symbol} tf={tf} result={ai} setResult={setAi} />}
          </div>
        </aside>
      </main>

      <footer className="footer">
        <span>
          {health?.data_source === "eod"
            ? "History: local adjusted daily + hourly CSVs. Intraday ticks are simulated."
            : health?.data_source === "kite" ? "Data: Kite Connect (private use only)." : "Demo data — synthetic."}
          {" "}Not investment advice.
        </span>
        <span>
          Charts by <a href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a>
        </span>
      </footer>

      {dialog?.kind === "alert" && (
        <AlertDialog
          symbol={symbol}
          lastPrice={quote?.ltp ?? null}
          onClose={() => setDialog(null)}
          onCreated={(text) => {
            setDialog(null);
            reloadAlerts();
            const id = Date.now() + Math.random();
            setToasts((t) => [...t, { id, text }]);
            setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
          }}
        />
      )}
      {dialog?.kind === "picker" && (
        <IndicatorPicker
          metas={Object.values(metas)}
          onAdd={(m) => (setIndicators((xs) => [...xs, newIndicator(m)]), setDialog(null))}
          onNewCustom={() => openCustom()}
          onEditCustom={(id) => void openCustom(id)}
          onDeleteCustom={async (id) => {
            await api.deleteCustom(id);
            setIndicators((xs) => xs.filter((x) => x.id !== id));
            await reloadMetas();
          }}
          onClose={() => setDialog(null)}
        />
      )}
      {settingsInd && metas[settingsInd.id] && (
        <IndicatorSettings
          ind={settingsInd}
          meta={metas[settingsInd.id]}
          onApply={(ind) => (setIndicators((xs) => xs.map((x) => (x.key === ind.key ? ind : x))), setDialog(null))}
          onClose={() => setDialog(null)}
          onEditFormula={settingsInd.id.startsWith("custom-") ? () => void openCustom(settingsInd.id) : undefined}
        />
      )}
      {dialog?.kind === "custom" && (
        <CustomEditor
          initial={dialog.id && dialog.def ? { id: dialog.id, def: dialog.def } : undefined}
          onClose={() => setDialog(null)}
          onSaved={async (id, isNew) => {
            const m = await reloadMetas();
            // keep instances in step with edited inputs: drop removed params, add new ones at their default
            setIndicators((xs) => {
              const next = xs.map((x) => x.id !== id ? x : {
                ...x, params: Object.fromEntries(m[id].params.map((p) => [p.name, x.params[p.name] ?? p.default])),
              });
              return isNew && m[id] ? [...next, newIndicator(m[id])] : next;
            });
            setDialog(null);
          }}
        />
      )}

      <div className="toasts">
        {toasts.map((t) => <div key={t.id} className="toast">{t.text}</div>)}
      </div>
    </div>
  );
}
