import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { API, api, type ScannerScan, type ScannerSignal, type ScannerStatus, type SignalExplanation } from "./api";
import { fmt } from "./format";
import { dollars, lakhs, positionSize, type Size } from "./sizing";

type View = "buy" | "near";
const MARKET_ORDER = ["NSE", "BSE", "NYSE", "NASDAQ"];
const VIEW_LABEL: Record<View, string> = { buy: "Buy signals", near: "Near misses" };
/** The portfolio box per currency: NSE/BSE scans in rupees (typed in lakh), NYSE/NASDAQ scans in dollars. */
type Cur = "INR" | "USD";
const CUR: Record<Cur, { unit: number; def: number; key: string; sym: string; word: string; fmt: (v: number) => string }> = {
  INR: { unit: 100_000, def: 1_000_000, key: "scanner.equity", sym: "₹", word: "lakh", fmt: lakhs },   // 1 = Rs 1,00,000
  USD: { unit: 1, def: 100_000, key: "scanner.equityUsd", sym: "$", word: "", fmt: dollars },
};
const US_MARKETS = new Set(["NYSE", "NASDAQ"]);
const DEFAULT_RISK = 1;           // % of the portfolio risked per trade

const niceDate = (d: string) =>
  new Date(`${d}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

/** Sidebar tab connected to the owner's SwingScanner: past scans (its saved history) with the trade plan of every
 * signal (entry, stop loss, quantity), filtered by setup, with "why this trade"; picked by date, then market.
 * Clicking a row opens its chart with the entry and stop-loss lines. */
/** A signal to open on arrival (a report chart link: /?scan=...&symbol=...&setup=...). */
export interface ScanOpen { scan: string; symbol: string; setup: string; near: boolean }

/** The saved scan of a market for a date: that session, else the one before it within 4 days (a weekend or holiday);
 * no date = the market's newest scan. `scans` are newest first. */
export function scanFor<T extends { market: string; date: string }>(scans: T[], market: string, day: string): T | null {
  const xs = scans.filter((x) => x.market === market);
  if (!day) return xs[0] ?? null;
  const at = Date.parse(`${day}T00:00:00Z`);
  return xs.find((x) => x.date <= day && at - Date.parse(`${x.date}T00:00:00Z`) <= 4 * 86_400_000) ?? null;
}

/** The chart link of a scanner signal: the chart tab opens it with Entry / SL (App reads ?scan=...). */
export function signalUrl(scanId: string, s: ScannerSignal): string {
  const q = new URLSearchParams({ scan: scanId, symbol: s.ticker, setup: s.setup });
  if (!s.valid) q.set("near", "1");
  return `/?${q}`;
}

export default function ScannerPanel(props: {
  selected: ScannerSignal | null;
  onPick: (s: ScannerSignal) => void;
  open?: ScanOpen | null;
  onOpened?: () => void;
  page?: boolean;                                              // full-page Setup Screener (SetupPage.tsx)
}) {
  const [status, setStatus] = useState<ScannerStatus | null>(null);
  const [scanId, setScanId] = useState<string>("");
  const [scan, setScan] = useState<ScannerScan | null>(null);
  const [view, setView] = useState<View>("buy");
  const [mkt, setMkt] = useState("");                  // the picked market ("" until the scans are listed)
  const [day, setDay] = useState("");                  // the picked date ("" = the market's newest scan)
  const cur: Cur = US_MARKETS.has(mkt || scanId.split("_")[0]) ? "USD" : "INR";
  const C = CUR[cur];
  const [eqBy, setEqBy] = useState<Record<Cur, number>>(() => ({
    INR: Number(localStorage.getItem(CUR.INR.key)) || CUR.INR.def,
    USD: Number(localStorage.getItem(CUR.USD.key)) || CUR.USD.def,
  }));
  // what is typed, per currency (lakh for rupees, dollars for dollars)
  const [eqTextBy, setEqTextBy] = useState<Record<Cur, string>>(() => ({
    INR: String(+(eqBy.INR / CUR.INR.unit).toFixed(4)), USD: String(eqBy.USD),
  }));
  const equity = eqBy[cur];
  const eqText = eqTextBy[cur];
  const setEqText = (t: string) => setEqTextBy((x) => ({ ...x, [cur]: t }));
  const money = C.fmt;
  const [riskPct, setRiskState] = useState<number>(() => Number(localStorage.getItem("scanner.riskPct")) || DEFAULT_RISK);
  const [riskText, setRiskText] = useState<string>(() => String(riskPct));
  const setRiskPct = (v: number) => {
    setRiskState(v);
    if (v > 0) localStorage.setItem("scanner.riskPct", String(v));
  };
  const setEquity = (v: number) => {
    setEqBy((x) => ({ ...x, [cur]: v }));
    if (v > 0) localStorage.setItem(C.key, String(v));
  };
  const [error, setError] = useState("");
  const [why, setWhy] = useState<SignalExplanation | null>(null);
  const [setupFilter, setSetupFilter] = useState<string | null>(null);
  const [whyErr, setWhyErr] = useState("");
  const [q, setQ] = useState("");                       // search: symbol or company
  const whyRef = useRef<HTMLDivElement>(null);

  /** Quantity and position at the user's equity, with the scanner's sizing rule. */
  const sized = (s: ScannerSignal): Size | null =>
    !scan || !(equity > 0) || !(riskPct > 0) || s.entry == null || s.stop == null || !s.valid ? null : positionSize({
      equity, entry: s.entry, stop: s.stop, riskPct, riskMult: scan.risk_mult ?? 1,
      sizeMult: s.size_mult ?? 1, maxAllocPct: scan.max_alloc_pct ?? 45,
    });
  const withSize = (s: ScannerSignal): ScannerSignal => {
    const z = sized(s);
    return z ? { ...s, shares: z.shares, value: z.value } : { ...s, shares: null, value: null };
  };
  const [picked, setPicked] = useState<{ s: ScannerSignal; near: boolean; scan: string } | null>(null);
  const scanRef = useRef(scanId);
  scanRef.current = scanId;
  const explainFor = (s: ScannerSignal, near: boolean, scroll: boolean) => {
    setWhyErr("");
    api.scannerExplain(scanId, s.ticker, s.setup, near, equity > 0 ? equity : undefined,
                       riskPct > 0 ? riskPct : undefined).then((e) => {
      setWhy(e);
      if (scroll) window.setTimeout(() => whyRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 50);
    }, (e) => setWhyErr(String(e.message ?? e)));
  };
  const isOpen = (s: ScannerSignal) => !!picked && picked.s.symbol === s.symbol && picked.s.setup === s.setup;
  /** A row click opens its trade summary under the row; a second click closes it. */
  const pick = (s: ScannerSignal, near: boolean) => {
    setWhy(null);
    setWhyErr("");
    if (isOpen(s)) {
      setPicked(null);
      return;
    }
    props.onPick(withSize(s));
    setPicked({ s, near, scan: scanId });
    explainFor(s, near, true);
  };
  // a new equity re-sizes the open explanation and the chart legend
  useEffect(() => {
    if (!picked || picked.scan !== scanId || !(equity > 0) || !(riskPct > 0)) return;
    const h = window.setTimeout(() => {
      if (picked.scan !== scanRef.current) return;      // another scan was opened meanwhile
      props.onPick(withSize(picked.s));
      explainFor(picked.s, picked.near, false);
    }, 300);
    return () => window.clearTimeout(h);
  }, [equity, riskPct]); // eslint-disable-line react-hooks/exhaustive-deps
  /** Reload the saved scans. A slow reply (the status call waits on the scanner's server) must not undo a market
   * or date picked meanwhile, so the defaults are applied only to what is still unset. */
  const loadStatus = useCallback(async () => {
    try {
      const st = await api.scanner();
      setStatus(st);
      const want = props.open && st.scans.find((x) => x.id === props.open!.scan);
      if (want) {
        setMkt(want.market);
        setDay(want.date);
      } else {
        // default: NSE (else the first market in NSE, BSE, NYSE, NASDAQ order that has scans), newest scan
        setMkt((cur) => cur || MARKET_ORDER.find((m) => st.scans.some((x) => x.market === m)) || "NSE");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => void loadStatus(), []); // eslint-disable-line react-hooks/exhaustive-deps
  // the scan of the picked market and date
  const target = status && mkt ? scanFor(status.scans, mkt, day) : null;
  useEffect(() => setScanId(target?.id ?? ""), [target?.id]);
  useEffect(() => {
    if (!scanId) {
      setScan(null);
      setPicked(null);
      return;
    }
    setScan(null);
    setWhy(null);
    setSetupFilter(null);
    setPicked(null);
    api.scannerScan(scanId).then((s) => {
      setScan(s);
      setView(s.signals.length ? "buy" : "near");
    }, (e) => setError(String(e.message ?? e)));
  }, [scanId]);
  // open the requested signal once its scan has loaded
  useEffect(() => {
    const o = props.open;
    if (!o || !scan || scan.id !== o.scan) return;
    const find = (list: ScannerSignal[]) => list.find((r) => r.ticker === o.symbol && r.setup === o.setup);
    const hit = o.near ? find(scan.near_misses) : find(scan.signals);
    const s = hit ?? find(scan.signals) ?? find(scan.near_misses);
    if (s) {
      const near = !scan.signals.includes(s);
      setView(near ? "near" : "buy");
      pick(s, near);
    } else setError(`${o.symbol} ${o.setup} is not in the scan of ${o.scan}`);
    props.onOpened?.();
  }, [scan, props.open]); // eslint-disable-line react-hooks/exhaustive-deps


  if (!status) return <div className="panel hint">{error || "Connecting to the scanner…"}</div>;
  if (!status.configured) return <div className="panel hint">{status.msg}</div>;

  // markets: NSE, NYSE, NASDAQ always (greyed out without scans), BSE when it has scans
  const shownMarkets = MARKET_ORDER.filter((m) => m !== "BSE" || status.scans.some((x) => x.market === m));
  const marketDates = status.scans.filter((x) => x.market === mkt).map((x) => x.date);   // newest first
  const byScore = (a: ScannerSignal, b: ScannerSignal) => (b.score ?? -Infinity) - (a.score ?? -Infinity);
  // buy signals: highest priority score first (signals without a score last)
  const viewRows: ScannerSignal[] = !scan ? [] : view === "buy" ? [...scan.signals].sort(byScore) : scan.near_misses;
  const ql = q.trim().toLowerCase();
  const rows = viewRows.filter((r) => (!setupFilter || r.setup === setupFilter) &&
    (!ql || r.ticker.toLowerCase().includes(ql) || (r.name ?? "").toLowerCase().includes(ql)));
  // setups in the open tab, most signals first: the filter chips above the table
  const setupCounts = Object.entries(viewRows.reduce<Record<string, number>>((acc, r) => {
    acc[r.setup] = (acc[r.setup] ?? 0) + 1;
    return acc;
  }, {})).sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0]));
  const count = (v: View) => (!scan ? 0 : v === "buy" ? scan.signals.length : scan.near_misses.length);
  const budget = scan ? equity * (riskPct / 100) * (scan.risk_mult ?? 1) : 0;
  const ncols = view === "buy" ? 6 : 5;

  return (
    <div className={`panel scanner${props.page ? " page" : ""}`}>
      <div className="panel-head">
        <span title="Trades from your SwingScanner rulebook: buy signals with entry, stop and quantity">Setup Scanner</span>
        <span className={`small ${status.online ? "up" : "muted"}`}
          title={status.online ? "SwingScanner.exe is running: new scans can be run from here"
            : "Start SwingScanner.exe to run new scans; past scans are still shown"}>
          ● {status.online ? "scanner running" : "scanner offline"}
        </span>
      </div>

      <div className="field scan-pick today-steps">
        <label className="step">
          <span className="step-n">1</span> Date
          <input type="date" aria-label="Scan date" value={day || marketDates[0] || ""}
            min={marketDates[marketDates.length - 1]} max={marketDates[0]}
            title="The session of the scan; a weekend or holiday shows the scan of the session before it"
            onChange={(e) => setDay(e.target.value === marketDates[0] ? "" : e.target.value)} />
          <button className={`small${day ? "" : " active"}`} onClick={() => setDay("")} title="The newest scan">Latest</button>
          <button className="small" title="Reload the list of saved scans" onClick={() => loadStatus()}>↻</button>
        </label>
        <div className="step" role="group" aria-label="Scan market">
          <span className="step-n">2</span> Market
          <nav className="tabs inline seg">
            {shownMarkets.map((m) => {
              const n = status.scans.filter((x) => x.market === m).length;
              return (
                <button key={m} className={mkt === m ? "active" : ""} disabled={!n} onClick={() => setMkt(m)}
                  title={n ? `${n} saved scans` : `No ${m} scans saved`}>{m}</button>
              );
            })}
          </nav>
        </div>
      </div>
      {mkt && !target && (
        <div className="hint scan-missing">No {mkt} scan is saved for {niceDate(day)}. Pick another date, or <button
          className="link" onClick={() => setDay("")}>the latest scan</button>.</div>
      )}
      {target && day && target.date !== day && (
        <div className="hint small">{niceDate(day)} was not a session: showing the scan of {niceDate(target.date)}.</div>
      )}

      {error && <div className="error">{error}</div>}

      {scan && (
        <>
          <div className="hint">
            Scan of <b>{niceDate(scan.date)}</b> · market <b>{scan.regime?.replace("_", " ") ?? "—"}</b>
            {scan.risk_mult != null && <> · risk ×{scan.risk_mult}</>}
            <> · <a href={API + scan.report_href} target="_blank" rel="noreferrer">full report ↗</a></>
          </div>

          <div className="field equity">
            <div className="row">
              <span className="equity-label">Portfolio size</span>
              <span className="muted">{C.sym}</span>
              <input type="number" min={0.01} step="any" value={eqText}
                aria-label={cur === "INR" ? "Portfolio size in lakh" : "Portfolio size in dollars"}
                title={cur === "INR" ? "Your portfolio size in lakh (1 = ₹1 lakh); quantities are sized with the scanner's rule"
                  : "Your portfolio size in US dollars; quantities are sized with the scanner's rule"}
                onChange={(e) => {
                  setEqText(e.target.value);
                  const l = Number(e.target.value);
                  setEquity(Number.isFinite(l) && l > 0 ? Math.round(l * C.unit) : 0);
                }} />
              {C.word && <span className="muted">{C.word}</span>}
              {equity !== C.def && (
                <button className="link small" title={`Back to ${C.fmt(C.def)}`}
                  onClick={() => { setEquity(C.def); setEqText(String(C.def / C.unit)); }}>reset</button>
              )}
            </div>
            <div className="row">
              <span className="equity-label">Risk per trade</span>
              <input type="number" min={0.01} max={100} step="any" value={riskText} aria-label="Risk per trade in percent"
                title="How much of the portfolio you are willing to lose on one trade if the stop is hit (default 1%)"
                onChange={(e) => {
                  setRiskText(e.target.value);
                  const r = Number(e.target.value);
                  setRiskPct(Number.isFinite(r) && r > 0 && r <= 100 ? r : 0);
                }} />
              <span className="muted">%</span>
              {riskPct !== DEFAULT_RISK && (
                <button className="link small" title="Back to 1%"
                  onClick={() => { setRiskPct(DEFAULT_RISK); setRiskText(String(DEFAULT_RISK)); }}>reset</button>
              )}
            </div>
            {equity > 0 && riskPct > 0 && (
              <span className="muted small">
                At risk per trade {money(budget)} = {riskPct}% x market multiplier {scan.risk_mult ?? 1}; max {scan.max_alloc_pct ?? 45}% of the portfolio in one stock.
              </span>
            )}
          </div>

          <nav className="tabs inline seg scan-views">
            {(Object.keys(VIEW_LABEL) as View[]).map((v) => (
              <button key={v} className={view === v ? "active" : ""} onClick={() => { setView(v); setSetupFilter(null); }}>
                {VIEW_LABEL[v]} <span className="seg-count">{count(v)}</span>
              </button>
            ))}
          </nav>

          <div className="scan-tools">
          <input className="scan-search" type="search" placeholder="Search symbol or company" aria-label="Search symbol or company"
            value={q} onChange={(e) => setQ(e.target.value)} />
          {setupCounts.length > 0 && (
            <div className="setup-filter" role="group" aria-label="Filter by setup">
              <span className="muted small">Setup:</span>
              <button className={`chip${setupFilter ? "" : " on"}`} onClick={() => setSetupFilter(null)}>
                All <span className="muted">{viewRows.length}</span>
              </button>
              {setupCounts.map(([code, n]) => {
                const info = scan.setups[code];
                return (
                  <button key={code} className={`chip${setupFilter === code ? " on" : ""}`}
                    onClick={() => setSetupFilter(setupFilter === code ? null : code)}
                    title={[info?.name ?? code, info?.what].filter(Boolean).join(": ")}>
                    {code} <span className="muted">{n}</span>
                  </button>
                );
              })}
            </div>
          )}
          </div>
          <table className="wl scan-table">
            <thead>
              <tr>
                <th title="The scanner's rank for the day">#</th>
                <th>Symbol · setup</th>
                <th title="Entry = the signal day's close">Entry</th>
                <th title="Stop loss (and its distance below the entry)">SL</th>
                <th title="The scanner's priority score: higher = bought first (sorted highest first)">Score ▼</th>
                {view === "buy" && <th title="Quantity at your equity, and the position's share of it">Qty</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => { const z = view === "near" ? null : sized(s); const open = isOpen(s); return (
                <Fragment key={`${s.symbol}-${s.setup}-${view}`}>
                <tr className={open ? "sel open" : ""} onClick={() => pick(s, view === "near")} aria-expanded={open}
                  title={[s.notes, s.risk != null && `Risk per share: ${fmt(s.risk)}`,
                          z && `Position ${fmt(z.value)} (${z.pctOfEquity.toFixed(1)}% of the portfolio), loss at the stop ${fmt(z.lossAtStop)}, sized by ${z.sizedBy}`,
                          s.reject && `Failed: ${s.reject}`, s.weak && `Weak: ${s.weak}`].filter(Boolean).join("\n\n")}>
                  <td>{view === "near" ? "" : s.rank ?? ""}</td>
                  <td>
                    <span className="muted twisty">{open ? "▾" : "▸"}</span>
                    <a className="scan-sym" href={signalUrl(scanId, s)} target="charting-lab" title={`Open the ${s.ticker} chart`}
                      onClick={(e) => e.stopPropagation()}>{s.ticker}</a>{" "}
                    <span className="tag" title={s.setup_name}>{s.setup}</span>
                    {s.name && <div className="scan-name small">{s.name}</div>}
                    <div className="muted small">{view === "near" ? firstRule(s.reject || s.weak) : s.status || s.setup_name}</div>
                  </td>
                  <td>{fmt(s.entry)}</td>
                  <td>{fmt(s.stop)}<div className="muted small">{s.stop_pct != null ? `-${s.stop_pct.toFixed(1)}%` : ""}</div></td>
                  <td className="scan-score">{s.score != null ? s.score.toFixed(2) : "—"}</td>
                  {view === "buy" && (
                    <td>
                      {z ? (
                        <>{z.shares.toLocaleString("en-IN")}<div className="muted small">{money(z.value)} · {z.pctOfEquity.toFixed(1)}%</div></>
                      ) : "—"}
                    </td>
                  )}
                </tr>
                {open && (
                  <tr className="why-row">
                    <td colSpan={ncols}>
                      {whyErr && <div className="error">{whyErr}</div>}
                      {!why && !whyErr && <div className="muted small">Loading the trade summary…</div>}
                      {why && (
                        <div className="why" ref={whyRef}>
                          <div className="panel-head">
                            <span>{view === "near" ? "Why it is not a trade" : "Why this trade"}: {why.symbol.split(":")[1]} · {why.setup} · {why.date}</span>
                            <button className="icon" title="Close" onClick={(e) => { e.stopPropagation(); setPicked(null); setWhy(null); }}>✕</button>
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
                    </td>
                  </tr>
                )}
                </Fragment>
              ); })}
              {!rows.length && (
                <tr><td colSpan={ncols} className="muted">
                  {ql ? `No ${view === "buy" ? "buy signal" : "near miss"} matches "${q.trim()}".`
                    : view === "buy" ? "No buy signals in this scan." : "No near misses."}
                </td></tr>
              )}
            </tbody>
          </table>


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
