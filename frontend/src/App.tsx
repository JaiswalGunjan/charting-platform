import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Alert, type ExplainResult, type IndicatorMeta, type Quote } from "./api";
import { live, type ConnState } from "./live";
import Chart, { fmt } from "./Chart";
import SymbolSearch from "./SymbolSearch";
import { AiPanel, AlertsPanel, WatchlistPanel } from "./Panels";
import { indicatorLabel, newIndicator, type ActiveIndicator } from "./indicatorStyle";

const TFS = ["1m", "5m", "15m", "1h", "1D", "1W", "1M"];
const MORE_TFS = ["3m", "30m", "2h", "4h"];

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

export default function App() {
  const [symbol, setSymbol] = usePersisted("symbol", "NSE:RELIANCE");
  const [tf, setTf] = usePersisted("tf", "5m");
  const [indicators, setIndicators] = usePersisted<ActiveIndicator[]>("indicators", []);
  const [metas, setMetas] = useState<Record<string, IndicatorMeta>>({});
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [tab, setTab] = usePersisted<"watchlist" | "alerts" | "ai">("tab", "watchlist");
  const [ai, setAi] = useState<ExplainResult | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [conn, setConn] = useState<ConnState>("connecting");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [menu, setMenu] = useState<"ind" | "tf" | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    live.connect();
    const offState = live.onState(setConn);
    api.indicators().then((ms) => setMetas(Object.fromEntries(ms.map((m) => [m.id, m]))), () => {});
    return offState;
  }, []);

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

  const aiLevels = useMemo(
    () => (ai?.analysis && ai.symbol === symbol ? ai.analysis.key_levels : []),
    [ai, symbol],
  );
  const metaList = Object.values(metas);
  const editingInd = indicators.find((i) => i.key === editing);
  const chg = quote?.change ?? 0;

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
        <div className="tfs">
          {TFS.map((t) => (
            <button key={t} className={t === tf ? "active" : ""} onClick={() => setTf(t)}>{t}</button>
          ))}
          <div className="menu-anchor">
            <button className={MORE_TFS.includes(tf) ? "active" : ""} onClick={() => setMenu(menu === "tf" ? null : "tf")}>
              {MORE_TFS.includes(tf) ? tf : "⋯"}
            </button>
            {menu === "tf" && (
              <ul className="menu">
                {MORE_TFS.map((t) => <li key={t} onClick={() => (setTf(t), setMenu(null))}>{t}</li>)}
              </ul>
            )}
          </div>
        </div>
        <div className="sep" />
        <div className="menu-anchor">
          <button onClick={() => setMenu(menu === "ind" ? null : "ind")}>ƒx Indicators</button>
          {menu === "ind" && (
            <ul className="menu wide">
              {metaList.map((m) => (
                <li key={m.id} onClick={() => (setIndicators((xs) => [...xs, newIndicator(m)]), setMenu(null))}>
                  {m.title} <span className="muted small">{m.overlay ? "overlay" : "pane"}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <button onClick={() => setTab("ai")}>✦ Explain</button>
        <div className="spacer" />
        <span className={`conn ${conn}`} title={`live feed: ${conn}`}>● {conn === "open" ? "Live" : conn}</span>
      </header>

      <main className="main">
        <Chart
          symbol={symbol}
          tf={tf}
          indicators={indicators}
          metas={metas}
          alerts={alerts}
          aiLevels={aiLevels}
          onRemoveIndicator={(k) => setIndicators((xs) => xs.filter((x) => x.key !== k))}
          onEditIndicator={setEditing}
        />
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
        <span>Demo data — synthetic unless Kite is configured. Not investment advice.</span>
        <span>
          Charts by <a href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a>
        </span>
      </footer>

      {editingInd && metas[editingInd.id] && (
        <div className="modal-bg" onMouseDown={() => setEditing(null)}>
          <form
            className="modal"
            onMouseDown={(e) => e.stopPropagation()}
            onSubmit={(e) => {
              e.preventDefault();
              const fd = new FormData(e.currentTarget);
              const params = Object.fromEntries(metas[editingInd.id].params.map((p) => [p.name, Number(fd.get(p.name))]));
              setIndicators((xs) => xs.map((x) => (x.key === editingInd.key ? { ...x, params } : x)));
              setEditing(null);
            }}
          >
            <h3>{indicatorLabel(editingInd, metas[editingInd.id])}</h3>
            {metas[editingInd.id].params.map((p) => (
              <label key={p.name}>
                {p.name}
                <input name={p.name} type="number" defaultValue={editingInd.params[p.name]} min={p.min} max={p.max}
                  step={p.kind === "int" ? 1 : 0.1} />
              </label>
            ))}
            <div className="modal-actions">
              <button type="button" onClick={() => setEditing(null)}>Cancel</button>
              <button type="submit" className="primary">Apply</button>
            </div>
          </form>
        </div>
      )}

      <div className="toasts">
        {toasts.map((t) => <div key={t.id} className="toast">{t.text}</div>)}
      </div>
    </div>
  );
}
