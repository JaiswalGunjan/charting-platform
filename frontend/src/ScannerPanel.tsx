import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type ScannerScan, type ScannerSignal, type ScannerStatus, type SignalExplanation } from "./api";
import { fmt } from "./format";
import { lakhs, positionSize, type Size } from "./sizing";

type View = "buy" | "near";
const VIEW_LABEL: Record<View, string> = { buy: "Buy setups", near: "Near misses" };
const DEFAULT_EQUITY = 1_000_000; // Rs 10 lakh, the scanner's default capital
const LAKH = 100_000;             // the equity box is in lakh: 1 = Rs 1,00,000

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
  const [equity, setEquityState] = useState<number>(() => Number(localStorage.getItem("scanner.equity")) || DEFAULT_EQUITY);
  const [eqText, setEqText] = useState<string>(() => String(+(equity / LAKH).toFixed(4)));   // what is typed, in lakh
  const setEquity = (v: number) => {
    setEquityState(v);
    if (v > 0) localStorage.setItem("scanner.equity", String(v));
  };
  const [market, setMarket] = useState("NSE");
  const [job, setJob] = useState<{ state: string; line: string } | null>(null);
  const [error, setError] = useState("");
  const [openSetup, setOpenSetup] = useState<string | null>(null);
  const [why, setWhy] = useState<SignalExplanation | null>(null);
  const [setupFilter, setSetupFilter] = useState<string | null>(null);
  const tableRef = useRef<HTMLTableElement>(null);
  const showSetup = (code: string, v: View) => {
    setSetupFilter(code);
    setView(v);
    window.setTimeout(() => tableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  };
  const [whyErr, setWhyErr] = useState("");
  const whyRef = useRef<HTMLDivElement>(null);

  /** Quantity and position at the user's equity, with the scanner's sizing rule. */
  const sized = (s: ScannerSignal): Size | null =>
    !scan || !(equity > 0) || s.entry == null || s.stop == null || !s.valid ? null : positionSize({
      equity, entry: s.entry, stop: s.stop, riskPct: scan.risk_pct ?? 1, riskMult: scan.risk_mult ?? 1,
      sizeMult: s.size_mult ?? 1, maxAllocPct: scan.max_alloc_pct ?? 45,
    });
  const withSize = (s: ScannerSignal): ScannerSignal => {
    const z = sized(s);
    return z ? { ...s, shares: z.shares, value: z.value } : { ...s, shares: null, value: null };
  };
  const [picked, setPicked] = useState<{ s: ScannerSignal; near: boolean } | null>(null);
  const explainFor = (s: ScannerSignal, near: boolean, scroll: boolean) => {
    setWhyErr("");
    api.scannerExplain(scanId, s.ticker, s.setup, near, equity > 0 ? equity : undefined).then((e) => {
      setWhy(e);
      if (scroll) window.setTimeout(() => whyRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    }, (e) => setWhyErr(String(e.message ?? e)));
  };
  const pick = (s: ScannerSignal, near: boolean) => {
    props.onPick(withSize(s));
    setPicked({ s, near });
    setWhy(null);
    explainFor(s, near, true);
  };
  // a new equity re-sizes the open explanation and the chart legend
  useEffect(() => {
    if (!picked || !(equity > 0)) return;
    const h = window.setTimeout(() => {
      props.onPick(withSize(picked.s));
      explainFor(picked.s, picked.near, false);
    }, 300);
    return () => window.clearTimeout(h);
  }, [equity]); // eslint-disable-line react-hooks/exhaustive-deps
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
    setWhy(null);
    setSetupFilter(null);
    setPicked(null);
    api.scannerScan(scanId).then((s) => {
      setScan(s);
      setView(s.signals.length ? "buy" : "near");
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
  const rows: ScannerSignal[] = (!scan ? [] : view === "buy" ? scan.signals : scan.near_misses)
    .filter((r) => !setupFilter || r.setup === setupFilter);
  const count = (v: View) => (!scan ? 0 : v === "buy" ? scan.signals.length : scan.near_misses.length);
  const budget = scan ? equity * ((scan.risk_pct ?? 1) / 100) * (scan.risk_mult ?? 1) : 0;
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

          <label className="field equity">
            <div className="row">
              <span className="muted">₹</span>
              <input type="number" min={0.01} step="any" value={eqText} aria-label="Equity in lakh"
                title="Your equity in lakh (1 = ₹1 lakh); quantities are sized with the scanner's rule"
                onChange={(e) => {
                  setEqText(e.target.value);
                  const l = Number(e.target.value);
                  setEquity(Number.isFinite(l) && l > 0 ? Math.round(l * LAKH) : 0);
                }} />
              <span className="muted">lakh</span>
              {equity !== DEFAULT_EQUITY && (
                <button className="link small" title="Back to 10 lakh"
                  onClick={() => { setEquity(DEFAULT_EQUITY); setEqText(String(DEFAULT_EQUITY / LAKH)); }}>reset</button>
              )}
            </div>
            {equity > 0 && (
              <span className="muted small">
                Risk per trade {lakhs(budget)} = {scan.risk_pct ?? 1}% x market multiplier {scan.risk_mult ?? 1}; max {scan.max_alloc_pct ?? 45}% in one stock.
              </span>
            )}
          </label>

          <nav className="tabs inline scan-views">
            {(Object.keys(VIEW_LABEL) as View[]).map((v) => (
              <button key={v} className={view === v ? "active" : ""} onClick={() => setView(v)}>
                {VIEW_LABEL[v]} <span className="muted small">{count(v)}</span>
              </button>
            ))}
          </nav>

          {setupFilter && (
            <div className="setup-filter">
              Showing <span className="tag">{setupFilter}</span> {scan.setups[setupFilter]?.name ?? ""} only
              <button className="link" onClick={() => setSetupFilter(null)}>show all setups ✕</button>
            </div>
          )}
          <table className="wl scan-table" ref={tableRef}>
            <thead>
              <tr>
                <th title="The scanner's rank for the day">#</th>
                <th>Symbol · setup</th>
                <th title="Entry = the signal day's close">Entry</th>
                <th title="Stop loss (and its distance below the entry)">SL</th>
                <th title={view === "near" ? "Score" : "Quantity at your equity, and the position's share of it"}>
                  {view === "near" ? "Score" : "Qty"}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => { const z = view === "near" ? null : sized(s); return (
                <tr key={`${s.symbol}-${s.setup}-${view}`} className={isSel(s) ? "sel" : ""} onClick={() => pick(s, view === "near")}
                  title={[s.notes, s.risk != null && `Risk per share: ${fmt(s.risk)}`,
                          z && `Position ${fmt(z.value)} (${z.pctOfEquity.toFixed(1)}% of equity), loss at the stop ${fmt(z.lossAtStop)}, sized by ${z.sizedBy}`,
                          s.reject && `Failed: ${s.reject}`, s.weak && `Weak: ${s.weak}`].filter(Boolean).join("\n\n")}>
                  <td>{view === "near" ? "" : s.rank ?? ""}</td>
                  <td>
                    <b>{s.ticker}</b> <span className="tag" title={s.setup_name}>{s.setup}</span>
                    <div className="muted small">{view === "near" ? firstRule(s.reject || s.weak) : s.status || s.setup_name}</div>
                  </td>
                  <td>{fmt(s.entry)}</td>
                  <td>{fmt(s.stop)}<div className="muted small">{s.stop_pct != null ? `-${s.stop_pct.toFixed(1)}%` : ""}</div></td>
                  <td>
                    {view === "near" ? (s.score != null ? s.score.toFixed(1) : "") : z ? (
                      <>{z.shares.toLocaleString("en-IN")}<div className="muted small">{lakhs(z.value)} · {z.pctOfEquity.toFixed(1)}%</div></>
                    ) : "—"}
                  </td>
                </tr>
              ); })}
              {!rows.length && (
                <tr><td colSpan={5} className="muted">
                  {view === "buy" ? "No buy setups in this scan." : "No near misses."}
                </td></tr>
              )}
            </tbody>
          </table>

          {whyErr && <div className="error">{whyErr}</div>}
          {why && (
            <div className="why" ref={whyRef}>
              <div className="panel-head">
                <span>Why this trade: {why.symbol.split(":")[1]} · {why.setup} · {why.date}</span>
                <button className="icon" title="Close" onClick={() => setWhy(null)}>✕</button>
              </div>
              <ol>
                {why.sections.map((sec) => (
                  <li key={sec.title}>
                    <b>{sec.title}</b>
                    <ul>{sec.lines.map((l, k) => <li key={k}>{l}</li>)}</ul>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {Object.keys(scan.setups).length > 0 && (
            <div className="setup-guide">
              <div className="panel-head"><span>Buy setups in this scan</span></div>
              {Object.entries(scan.setups).map(([code, s]) => (
                <div key={code} className="setup-item">
                  <div className="setup-title">
                    <button className="setup-name" title="What this setup is and why it works"
                      onClick={() => setOpenSetup(openSetup === code ? null : code)}>
                      <span className="muted">{openSetup === code ? "▾" : "▸"}</span> <span className="tag">{code}</span> {s.name}
                    </button>
                    <span className="setup-counts small">
                      {(() => {
                        const nSig = scan.signals.filter((r) => r.setup === code).length;
                        const nNear = scan.near_misses.filter((r) => r.setup === code).length;
                        return (
                          <>
                            <button className="link" disabled={!nSig} onClick={() => showSetup(code, "buy")}
                              title="Stocks where this setup formed and passed every hard rule: the scanner's trades">
                              {nSig} buy signal{nSig === 1 ? "" : "s"}
                            </button>
                            {" · "}
                            <button className="link" disabled={!nNear} onClick={() => showSetup(code, "near")}
                              title="Stocks where this setup formed but failed at least one hard rule: not bought">
                              {nNear} near miss{nNear === 1 ? "" : "es"}
                            </button>
                            <span className="muted"> (formed, failed a hard rule)</span>
                          </>
                        );
                      })()}
                    </span>
                  </div>
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
