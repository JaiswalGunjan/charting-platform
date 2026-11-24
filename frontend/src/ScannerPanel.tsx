import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type ScannerScan, type ScannerSignal, type ScannerStatus } from "./api";
import { fmt } from "./format";

type View = "buy" | "all" | "near";
const VIEW_LABEL: Record<View, string> = { buy: "Buy setups", all: "All signals", near: "Near misses" };

const niceDate = (d: string) =>
  new Date(`${d}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

/** Sidebar tab connected to the owner's SwingScanner: past scans (its saved history) with the trade plan of every
 * signal (entry, stop loss, quantity), the buy setups explained, and a new scan while the scanner is running.
 * Clicking a row opens its chart with the entry and stop-loss lines. */
export default function ScannerPanel(props: { selected: ScannerSignal | null; onPick: (s: ScannerSignal) => void }) {
  const [status, setStatus] = useState<ScannerStatus | null>(null);
  const [scanId, setScanId] = useState<string>("");
  const [scan, setScan] = useState<ScannerScan | null>(null);
  const [view, setView] = useState<View>("buy");
  const [market, setMarket] = useState("NSE");
  const [job, setJob] = useState<{ state: string; line: string } | null>(null);
  const [error, setError] = useState("");
  const [openSetup, setOpenSetup] = useState<string | null>(null);
  const polling = useRef<number | null>(null);

  const loadStatus = useCallback(async (pickNewest = false) => {
    try {
      const st = await api.scanner();
      setStatus(st);
      if (st.scans.length && (pickNewest || !scanId)) setScanId(st.scans[0].id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [scanId]);

  useEffect(() => void loadStatus(), []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!scanId) return;
    setScan(null);
    api.scannerScan(scanId).then((s) => {
      setScan(s);
      setView(s.signals.some((r) => r.buy) ? "buy" : s.signals.length ? "all" : "near");
    }, (e) => setError(String(e.message ?? e)));
  }, [scanId]);
  useEffect(() => () => { if (polling.current) window.clearInterval(polling.current); }, []);

  const run = async () => {
    setError("");
    try {
      await api.scannerRun(market);
      setJob({ state: "running", line: "starting…" });
      let since = 0;
      polling.current = window.setInterval(async () => {
        try {
          const j = await api.scannerJob(since);
          since = j.next;
          const line = j.log.length ? j.log[j.log.length - 1] : undefined;
          setJob((old) => ({ state: j.state, line: line ?? old?.line ?? "" }));
          if (j.state !== "running") {
            window.clearInterval(polling.current!);
            polling.current = null;
            if (j.state === "done") await loadStatus(true);
          }
        } catch {
          /* keep polling */
        }
      }, 1000);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  if (!status) return <div className="panel hint">{error || "Connecting to the scanner…"}</div>;
  if (!status.configured) return <div className="panel hint">{status.msg}</div>;

  const markets = (status.markets ?? []).filter((m) => m.ok);
  const running = job?.state === "running";
  const rows: ScannerSignal[] = !scan ? [] : view === "buy" ? scan.signals.filter((r) => r.buy)
    : view === "all" ? scan.signals : scan.near_misses;
  const count = (v: View) => (!scan ? 0 : v === "buy" ? scan.signals.filter((r) => r.buy).length
    : v === "all" ? scan.signals.length : scan.near_misses.length);
  const isSel = (s: ScannerSignal) =>
    props.selected?.symbol === s.symbol && props.selected?.setup === s.setup && props.selected?.date === s.date;

  return (
    <div className="panel scanner">
      <div className="panel-head">
        <span>Swing Scanner</span>
        <span className={`small ${status.online ? "up" : "muted"}`}
          title={status.online ? "SwingScanner.exe is running: new scans can be run from here"
            : "Start SwingScanner.exe to run new scans; past scans are still shown"}>
          ● {status.online ? "scanner running" : "scanner offline"}
        </span>
      </div>

      <label className="field">
        <span>Past scans (history)</span>
        <div className="row">
          <select className="grow" value={scanId} onChange={(e) => setScanId(e.target.value)}>
            {status.scans.map((s) => (
              <option key={s.id} value={s.id}>
                {niceDate(s.date)} · {s.market} · {s.valid ?? 0} signal{s.valid === 1 ? "" : "s"}
              </option>
            ))}
          </select>
          <button className="small" title="Reload the list of past scans" onClick={() => loadStatus()}>↻</button>
        </div>
      </label>

      {status.online && (
        <label className="field">
          <span>New scan</span>
          <div className="row scan-run">
            <select value={market} onChange={(e) => setMarket(e.target.value)} disabled={running}>
              {(markets.length ? markets : [{ market: "NSE", last: null }]).map((m) => (
                <option key={m.market} value={m.market}>
                  {m.market}{m.last ? ` · data to ${niceDate(m.last)}` : ""}
                </option>
              ))}
            </select>
            <button className="small primary" disabled={running} onClick={run}>{running ? "Scanning…" : "Run scan"}</button>
          </div>
        </label>
      )}
      {job && <div className={`hint scan-log${job.state === "error" ? " error" : ""}`}>{job.line}</div>}
      {error && <div className="error">{error}</div>}

      {scan && (
        <>
          <div className="hint">
            Scan of <b>{niceDate(scan.date)}</b> · market <b>{scan.regime?.replace("_", " ") ?? "—"}</b>
            {scan.risk_mult != null && <> · risk ×{scan.risk_mult}</>}
            {status.online && <> · <a href={scan.report_href} target="_blank" rel="noreferrer">full report ↗</a></>}
          </div>

          <nav className="tabs inline scan-views">
            {(Object.keys(VIEW_LABEL) as View[]).map((v) => (
              <button key={v} className={view === v ? "active" : ""} onClick={() => setView(v)}>
                {VIEW_LABEL[v]} <span className="muted small">{count(v)}</span>
              </button>
            ))}
          </nav>

          <table className="wl scan-table">
            <thead>
              <tr>
                <th title="The scanner's rank for the day">#</th>
                <th>Symbol · setup</th>
                <th title="Entry = the signal day's close">Entry</th>
                <th title="Stop loss (and its distance below the entry)">SL</th>
                <th title={view === "near" ? "Score" : "Quantity the scanner would buy (capital and risk rules)"}>
                  {view === "near" ? "Score" : "Qty"}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={`${s.symbol}-${s.setup}-${view}`} className={isSel(s) ? "sel" : ""} onClick={() => props.onPick(s)}
                  title={[s.notes, s.risk != null && `Risk per share: ${fmt(s.risk)}`, s.value != null && `Position value: ${fmt(s.value)}`,
                          s.reject && `Failed: ${s.reject}`, s.weak && `Weak: ${s.weak}`].filter(Boolean).join("\n\n")}>
                  <td>{view === "near" ? "" : s.rank ?? ""}</td>
                  <td>
                    <b>{s.ticker}</b> <span className="tag" title={s.setup_name}>{s.setup}</span>
                    <div className="muted small">{view === "near" ? firstRule(s.reject || s.weak) : s.status || s.setup_name}</div>
                  </td>
                  <td>{fmt(s.entry)}</td>
                  <td>{fmt(s.stop)}<div className="muted small">{s.stop_pct != null ? `-${s.stop_pct.toFixed(1)}%` : ""}</div></td>
                  <td>{view === "near" ? (s.score != null ? s.score.toFixed(1) : "") : (s.shares ?? "—")}</td>
                </tr>
              ))}
              {!rows.length && (
                <tr><td colSpan={5} className="muted">
                  {view === "buy" ? "No buy setups in this scan." : view === "all" ? "No signals in this scan." : "No near misses."}
                </td></tr>
              )}
            </tbody>
          </table>

          {Object.keys(scan.setups).length > 0 && (
            <div className="setup-guide">
              <div className="panel-head"><span>Buy setups in this scan</span></div>
              {Object.entries(scan.setups).map(([code, s]) => (
                <div key={code} className="setup-item">
                  <button className="setup-title" onClick={() => setOpenSetup(openSetup === code ? null : code)}>
                    <span className="tag">{code}</span> {s.name}
                    <span className="muted small"> · {scan.signals.filter((r) => r.setup === code).length} signal(s),{" "}
                      {scan.near_misses.filter((r) => r.setup === code).length} near</span>
                    <span className="muted">{openSetup === code ? "▾" : "▸"}</span>
                  </button>
                  {openSetup === code && (
                    <div className="setup-text">
                      {s.what && <p>{s.what}</p>}
                      {s.why && <p className="muted">{s.why}</p>}
                      {!s.what && !s.why && <p className="muted">No description in the scanner for this setup.</p>}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** "S8-R003: no ATR(1) contraction ...; S5B-R008: ..." -> the first reason, shortened. */
function firstRule(text: string): string {
  const first = text.split(";")[0].trim();
  return first.length > 48 ? `${first.slice(0, 46)}…` : first;
}
