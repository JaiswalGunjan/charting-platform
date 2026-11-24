import { useEffect, useState } from "react";
import {
  api,
  type Alert,
  type AlertEvent,
  type AlertOp,
  type ExplainResult,
  type Quote,
  type Watchlist,
} from "./api";
import { live } from "./live";
import { fmt } from "./Chart";

// ---- Watchlist ------------------------------------------------------------------

export function WatchlistPanel({ current, onPick }: { current: string; onPick: (s: string) => void }) {
  const [wl, setWl] = useState<Watchlist | null>(null);
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [err, setErr] = useState("");

  useEffect(() => {
    api.watchlists().then((ws) => setWl(ws[0] ?? null), (e) => setErr(e.message));
  }, []);

  const symbols = wl?.symbols ?? [];
  const symKey = symbols.join(",");
  useEffect(() => {
    if (!symbols.length) return;
    api.quotes(symbols).then((qs) => setQuotes((old) => ({ ...old, ...Object.fromEntries(qs.map((q) => [q.symbol, q])) })), () => {});
    // a 1D subscription per symbol gives us streaming quote messages
    const unsubs = symbols.map((s) => live.subscribe(s, "1D"));
    const off = live.on((m) => {
      if (m.type === "quote") setQuotes((old) => ({ ...old, [m.symbol]: m }));
      else if (m.type === "subscribed") setQuotes((old) => ({ ...old, [m.symbol]: m.quote }));
    });
    return () => {
      unsubs.forEach((u) => u());
      off();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symKey]);

  const add = () => wl && api.addToWatchlist(wl.id, current).then(setWl, (e) => setErr(e.message));
  const remove = (s: string) => wl && api.removeFromWatchlist(wl.id, s).then(setWl, (e) => setErr(e.message));

  return (
    <div className="panel">
      <div className="panel-head">
        <span>{wl?.name ?? "Watchlist"}</span>
        {wl && !symbols.includes(current) && (
          <button className="small" onClick={add} title={`Add ${current}`}>+ {current.split(":")[1]}</button>
        )}
      </div>
      {err && <div className="error">{err}</div>}
      <table className="wl">
        <thead>
          <tr><th>Symbol</th><th>Last</th><th>Chg%</th><th /></tr>
        </thead>
        <tbody>
          {symbols.map((s) => {
            const q = quotes[s];
            const cls = (q?.change ?? 0) >= 0 ? "up" : "down";
            return (
              <tr key={s} className={s === current ? "sel" : ""} onClick={() => onPick(s)}>
                <td>{s.split(":")[1]}</td>
                <td className={cls}>{fmt(q?.ltp)}</td>
                <td className={cls}>{q?.change_pct == null ? "—" : `${q.change_pct >= 0 ? "+" : ""}${q.change_pct.toFixed(2)}%`}</td>
                <td>
                  <button className="icon" title="Remove" onClick={(e) => (e.stopPropagation(), remove(s))}>✕</button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---- Alerts ---------------------------------------------------------------------

const OPS: { op: AlertOp; label: string }[] = [
  { op: "crosses_above", label: "Crosses above" },
  { op: "crosses_below", label: "Crosses below" },
  { op: "above", label: "Is above" },
  { op: "below", label: "Is below" },
];

export function AlertsPanel({ symbol, lastPrice, alerts, reload }: {
  symbol: string;
  lastPrice: number | null;
  alerts: Alert[];
  reload: () => void;
}) {
  const [op, setOp] = useState<AlertOp>("crosses_above");
  const [price, setPrice] = useState("");
  const [once, setOnce] = useState(true);
  const [err, setErr] = useState("");
  const [events, setEvents] = useState<AlertEvent[]>([]);

  const loadEvents = () => api.alertEvents().then(setEvents, () => {});
  useEffect(() => {
    loadEvents();
    return live.on((m) => m.type === "alert" && loadEvents());
  }, []);
  useEffect(() => setPrice(lastPrice ? lastPrice.toFixed(2) : ""), [symbol]); // eslint-disable-line react-hooks/exhaustive-deps

  const create = (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    api.createAlert(symbol, op, Number(price), once).then(reload, (x) => setErr(x.message));
  };

  return (
    <div className="panel">
      <div className="panel-head"><span>New alert · {symbol.split(":")[1]}</span></div>
      <form className="alert-form" onSubmit={create}>
        <select value={op} onChange={(e) => setOp(e.target.value as AlertOp)}>
          {OPS.map((o) => <option key={o.op} value={o.op}>{o.label}</option>)}
        </select>
        <input type="number" step="0.05" min="0" value={price} onChange={(e) => setPrice(e.target.value)} required />
        <label className="check"><input type="checkbox" checked={once} onChange={(e) => setOnce(e.target.checked)} /> once</label>
        <button type="submit" className="primary">Create</button>
      </form>
      {lastPrice !== null && (
        <div className="hint">
          Last {fmt(lastPrice)} ·{" "}
          <a onClick={() => setPrice(lastPrice.toFixed(2))}>use last</a> ·{" "}
          <a onClick={() => setPrice((lastPrice * 1.002).toFixed(2))}>+0.2%</a> ·{" "}
          <a onClick={() => setPrice((lastPrice * 0.998).toFixed(2))}>−0.2%</a>
        </div>
      )}
      {err && <div className="error">{err}</div>}

      <div className="panel-head"><span>Alerts</span></div>
      <ul className="list">
        {alerts.length === 0 && <li className="muted">No alerts yet</li>}
        {alerts.map((a) => (
          <li key={a.id} className={a.status !== "active" ? "dim" : ""}>
            <div>
              <b>{a.symbol.split(":")[1]}</b> {a.condition.op.replace("_", " ")} {fmt(a.condition.price)}
              <div className="muted small">{a.status}{a.once ? " · once" : " · repeat"}</div>
            </div>
            <div className="row-actions">
              <button className="small" onClick={() => api.setAlertStatus(a.id, a.status === "active" ? "disabled" : "active").then(reload)}>
                {a.status === "active" ? "Pause" : "Arm"}
              </button>
              <button className="icon" title="Delete" onClick={() => api.deleteAlert(a.id).then(reload)}>✕</button>
            </div>
          </li>
        ))}
      </ul>

      <div className="panel-head"><span>Recent triggers</span></div>
      <ul className="list">
        {events.length === 0 && <li className="muted">None yet</li>}
        {events.map((e) => (
          <li key={e.id}>
            <div>
              {e.message}
              <div className="muted small">{new Date(e.ts * 1000).toLocaleTimeString("en-IN")} @ {fmt(e.price)}</div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---- AI analyst -----------------------------------------------------------------

export function AiPanel({ symbol, tf, result, setResult }: {
  symbol: string;
  tf: string;
  result: ExplainResult | null;
  setResult: (r: ExplainResult | null) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [showCtx, setShowCtx] = useState(false);

  const run = (dry: boolean) => {
    setBusy(true);
    setErr("");
    api.explain(symbol, tf, dry).then(setResult, (e) => setErr(`${e.status ?? ""} ${e.message}`)).finally(() => setBusy(false));
  };
  const stale = result && (result.symbol !== symbol || result.tf !== tf);
  const a = result?.analysis;

  return (
    <div className="panel">
      <div className="panel-head"><span>Explain this chart</span></div>
      <div className="ai-actions">
        <button className="primary" disabled={busy} onClick={() => run(false)}>{busy ? "Analysing…" : `Explain ${symbol.split(":")[1]} · ${tf}`}</button>
        <button className="small" disabled={busy} onClick={() => run(true)} title="Show the numbers the model would see, without calling it">Context only</button>
      </div>
      {err && <div className="error">{err}</div>}
      {stale && <div className="hint">Showing {result!.symbol} · {result!.tf}</div>}
      {a && (
        <div className="ai">
          <p>{a.summary}</p>
          <div className="pills">
            <span className={`pill ${a.trend}`}>{a.trend}</span>
            <span className="pill">{a.trend_strength}</span>
          </div>
          <h4>Momentum</h4><p>{a.momentum}</p>
          <h4>Volatility</h4><p>{a.volatility}</p>
          <h4>Volume</h4><p>{a.volume}</p>
          {a.key_levels.length > 0 && (
            <>
              <h4>Key levels <span className="muted small">(drawn on chart)</span></h4>
              <ul>{a.key_levels.map((k, i) => <li key={i}><b className={k.kind === "support" ? "up" : "down"}>{fmt(k.price)}</b> {k.kind} — {k.note}</li>)}</ul>
            </>
          )}
          {a.signals_conflicting.length > 0 && (<><h4>Conflicting signals</h4><ul>{a.signals_conflicting.map((s, i) => <li key={i}>{s}</li>)}</ul></>)}
          {a.what_to_watch.length > 0 && (<><h4>What to watch</h4><ul>{a.what_to_watch.map((s, i) => <li key={i}>{s}</li>)}</ul></>)}
          {result?.usage && <div className="muted small">{result.usage.model} · {result.usage.input_tokens}→{result.usage.output_tokens} tokens · {(result.usage.latency_ms / 1000).toFixed(1)}s</div>}
        </div>
      )}
      {result && (
        <>
          <div className="disclaimer">{result.disclaimer}</div>
          <button className="link" onClick={() => setShowCtx((s) => !s)}>{showCtx ? "Hide" : "Show"} model input</button>
          {showCtx && <pre className="ctx">{JSON.stringify(result.context, null, 2)}</pre>}
        </>
      )}
    </div>
  );
}
