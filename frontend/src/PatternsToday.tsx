import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type PatternMeta, type PatternsToday as Screen, type TodayRow } from "./api";
import { fmt } from "./format";
import { liquidRows, matchRows, nextSort, patternCounts, sortRows, turnoverText, type Sort, type SortKey } from "./todayLogic";

function usePersisted<T>(key: string, init: T): [T, (v: T) => void] {
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

const US = new Set(["NASDAQ", "NYSE"]);
const SCREEN_EXCHANGES = ["NSE", "NYSE", "NASDAQ"];
const IST = 19800;
const day = (t: number) =>
  new Date((t + IST) * 1000).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const niceDay = (d: string) =>
  new Date(`${d}T00:00:00Z`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const stamp = (ts: number) =>
  new Date(ts * 1000).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

const COLS: { key: SortKey; label: string; title: string; first: 1 | -1 }[] = [
  { key: "ticker", label: "Symbol", title: "Sort by symbol", first: 1 },
  { key: "name", label: "Company", title: "Sort by company name", first: 1 },
  { key: "close", label: "Close", title: "Sort by the latest close", first: -1 },
  { key: "change_pct", label: "Chg %", title: "Sort by the latest change in %", first: -1 },
  { key: "turnover", label: "Turnover", title: "Sort by the 50-bar median turnover", first: -1 },
  { key: "patterns", label: "Patterns on the latest bar", title: "Sort by how many patterns formed", first: -1 },
];

/** Pattern Screener: the rulebook patterns that fired on the latest (or a chosen past) daily or weekly bar of every
 * stock of an exchange. Screens are run on request (or by `app.cli screen`) and saved; opening the page only reads them.
 * Selecting several patterns shows the stocks that formed ALL of them on the same bar. */
export default function PatternsToday(props: {
  metas: PatternMeta[];
  onOpen: (row: TodayRow, tf: string, patterns: string[]) => void;
}) {
  const [exchanges, setExchanges] = useState<string[]>(SCREEN_EXCHANGES);
  const [exchange, setExchange] = usePersisted("today.exchange", "NSE");
  const [tf, setTf] = usePersisted<"1D" | "1W">("today.tf", "1D");
  const [selected, setSelected] = usePersisted<string[]>("today.patterns", []);
  const [minTurnover, setMinTurnover] = usePersisted<number>("today.minTurnover", 1);  // crore (India) / $M (US)
  const [sort, setSort] = usePersisted<Sort>("today.sort", { key: "patterns", dir: -1 });
  const [q, setQ] = useState("");
  const [session, setSession] = useState("");            // "" = the newest saved screen
  const [screen, setScreen] = useState<Screen | null>(null);
  const [job, setJob] = useState<Screen["job"] | null>(null);
  const [error, setError] = useState("");
  const poll = useRef<number | null>(null);

  const metas = props.metas.filter((m) => m.id !== "sr");
  const metaById = useMemo(() => Object.fromEntries(metas.map((m) => [m.id, m])), [metas]);

  useEffect(() => {
    api.exchanges().then((xs) => {
      const have = SCREEN_EXCHANGES.filter((e) => xs.some((x) => x.exchange === e));
      if (have.length) setExchanges(have);
    }, () => {});
  }, []);

  const load = () => {
    setError("");
    api.patternsToday(exchange, tf, session).then((s) => {
      setScreen(s);
      if (s.job.state === "running") follow();
    }, (e) => setError(String(e.message ?? e)));
  };
  useEffect(load, [exchange, tf, session]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { if (poll.current) window.clearInterval(poll.current); }, []);

  const follow = () => {
    if (poll.current) return;
    poll.current = window.setInterval(async () => {
      try {
        const j = await api.patternsTodayJob();
        setJob(j);
        if (j.state !== "running") {
          window.clearInterval(poll.current!);
          poll.current = null;
          if (j.state === "done") load();
        }
      } catch {
        /* keep polling */
      }
    }, 1000);
  };
  const run = async () => {
    setError("");
    try {
      const r = await api.runPatternsToday(exchange, tf, session);
      setJob(r.job);
      follow();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  const liquid = liquidRows(screen?.rows ?? [], minTurnover, exchange);
  const sel = new Set(selected.filter((id) => metaById[id]));
  // AND: a stock must have formed every selected pattern on its latest bar
  const rows = sortRows(matchRows(liquid, sel, q), sort);
  const shown = rows.slice(0, 500);
  // count per pattern among the stocks that already match the other selected patterns (what ticking it would leave)
  const counts = patternCounts(liquid, sel, q);
  const groups = [...new Set(metas.map((m) => m.group))];
  const toggle = (id: string) => setSelected(sel.has(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  const running = job?.state === "running" || screen?.job.state === "running";
  const dates = screen?.dates ?? [];
  const sortBy = (c: (typeof COLS)[number]) => setSort(nextSort(sort, c.key, c.first));

  return (
    <div className="today">
      <div className="today-head today-steps">
        <label className="step">
          <span className="step-n">1</span> Date
          <input type="date" aria-label="Session date" value={session || dates[0] || ""}
            min={dates[dates.length - 1]} max={dates[0]}
            title="The session whose bar is screened; a weekend or holiday shows the session before it"
            onChange={(e) => setSession(e.target.value === dates[0] ? "" : e.target.value)} />
          <button className={`small${session ? "" : " active"}`} onClick={() => setSession("")}
            title="The latest session">Latest</button>
        </label>
        <div className="step" role="group" aria-label="Exchange">
          <span className="step-n">2</span> Exchange
          <nav className="tabs inline seg">
            {SCREEN_EXCHANGES.map((x) => (
              <button key={x} className={exchange === x ? "active" : ""} onClick={() => setExchange(x)}
                disabled={!exchanges.includes(x)} title={exchanges.includes(x) ? undefined : `No ${x} data imported`}>{x}</button>
            ))}
          </nav>
        </div>
        <div className="step" role="group" aria-label="Timeframe">
          <span className="step-n">3</span> Timeframe
          <nav className="tabs inline seg">
            {(["1D", "1W"] as const).map((t) => (
              <button key={t} className={tf === t ? "active" : ""} onClick={() => setTf(t)}>{t === "1D" ? "Daily" : "Weekly"}</button>
            ))}
          </nav>
        </div>
        <span className="spacer" />
        <button className="small" disabled={running} onClick={run}
          title="Screen every stock again and save the result (about a minute). Opening this page never re-screens.">
          {running ? "Screening…" : screen?.missing ? `Screen ${exchange} now` : session ? `↻ Re-screen ${niceDay(screen?.session ?? session)}` : "↻ Update screen"}
        </button>
      </div>
      <div className="today-status">
        <span className="muted small today-asof">
          {screen?.as_of ? <>Saved screen · {tf === "1D" ? (session ? "bar of" : "latest bar") : "week of"} <b>{day(screen.as_of)}</b>
            {tf === "1W" && screen.last_session && <> (to {day(screen.last_session)}{session ? "" : ", week in progress"})</>}
            {" "}· {screen.scanned.toLocaleString()} stocks · screened {screen.generated_at ? stamp(screen.generated_at) : ""}</> : null}
          {session && screen?.session && screen.session !== session && !screen.missing && (
            <> · <b>{niceDay(session)}</b> was not a session: showing {niceDay(screen.session)}</>
          )}
          {dates.length > 0 && <> · {dates.length} saved session{dates.length === 1 ? "" : "s"}, {niceDay(dates[dates.length - 1])} – {niceDay(dates[0])}</>}
        </span>
      </div>
      {running && job && <div className="hint today-progress">Screening {job.exchange} {job.tf === "1D" ? "daily" : "weekly"}: {job.msg}</div>}
      {job?.state === "error" && <div className="error">{job.msg}</div>}
      {error && <div className="error">{error}</div>}

      {screen?.missing && !running && (
        <div className="today-empty">
          <p>{exchange} {tf === "1D" ? "daily" : "weekly"}{session ? ` for ${niceDay(session)}` : ""} has not been screened yet.</p>
          <button className="primary" onClick={run}>Screen {exchange} now</button>
          <p className="muted small">The result is saved; this page shows it until you update it.
            You can also run <code>python -m app.cli screen</code> after each data import.</p>
        </div>
      )}

      {screen && !screen.missing && (
        <div className="today-body">
          <div className="today-selection">
            {sel.size ? (
              <>
                <span>Showing stocks that formed <b>all</b> of:</span>
                {[...sel].map((id) => (
                  <button key={id} className="chip on" onClick={() => toggle(id)} title="Remove from the selection">
                    <span className="pattern-tag" style={{ background: metaById[id].color }}>{metaById[id].short}</span>
                    {metaById[id].title} ✕
                  </button>
                ))}
              </>
            ) : (
              <span className="muted">No pattern selected: showing every stock with at least one pattern. Tick patterns
                below to narrow it down (a stock must have all ticked patterns).</span>
            )}
            <span className="spacer" />
            <button className="small" disabled={!sel.size} onClick={() => setSelected([])}>Clear selection</button>
          </div>

          <div className="today-sections">
            {groups.map((g) => {
              const ms = metas.filter((m) => m.group === g);
              const n = ms.filter((m) => sel.has(m.id)).length;
              return (
                <section key={g} className="today-section">
                  <h3>{g}{n ? <span className="muted small"> · {n} selected</span> : null}</h3>
                  {ms.map((m) => (
                    <label key={m.id} className={`pcard${sel.has(m.id) ? " on" : ""}${counts[m.id] ? "" : " zero"}`} title={m.about}>
                      <input type="checkbox" checked={sel.has(m.id)} onChange={() => toggle(m.id)} />
                      <span className="pattern-tag" style={{ background: m.color }}>{m.short}</span>
                      <span className="pcard-text">
                        <b>{m.title}</b>
                        <span className="muted small">{m.summary}</span>
                      </span>
                      <span className="pcard-count" title="Stocks with this pattern (and every other selected one)">
                        {counts[m.id] ?? 0}
                      </span>
                    </label>
                  ))}
                </section>
              );
            })}
          </div>

          <div className="row today-row2">
            <label className="mini">Min turnover
              <input type="number" min={0} step="any" value={minTurnover}
                onChange={(e) => setMinTurnover(Math.max(0, Number(e.target.value) || 0))} />
              {US.has(exchange) ? "$M" : "₹ Cr"}
            </label>
            <input className="grow" placeholder="Search symbol or company" value={q} onChange={(e) => setQ(e.target.value)} />
            <b className="today-count">{rows.length.toLocaleString()} stock{rows.length === 1 ? "" : "s"}</b>
          </div>

          <table className="wl today-table">
            <thead>
              <tr>
                {COLS.map((c) => (
                  <th key={c.key} className={`sortable${sort.key === c.key ? " sorted" : ""}`} title={c.title}
                    onClick={() => sortBy(c)} aria-sort={sort.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
                    {c.label} <span className="sort-arrow">{sort.key === c.key ? (sort.dir === 1 ? "▲" : "▼") : "↕"}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.symbol} onClick={() => props.onOpen(r, tf, sel.size ? [...sel] : r.patterns)}>
                  <td><b>{r.ticker}</b></td>
                  <td className="muted today-name">{r.name !== r.ticker ? r.name : ""}</td>
                  <td>{fmt(r.close)}</td>
                  <td className={(r.change_pct ?? 0) >= 0 ? "up" : "down"}>
                    {r.change_pct != null ? `${r.change_pct >= 0 ? "+" : ""}${r.change_pct.toFixed(2)}%` : ""}
                  </td>
                  <td>{turnoverText(r.turnover, exchange)}</td>
                  <td className="today-pats">
                    <span className="pcount" title="Patterns formed on the latest bar">{r.patterns.length}</span>
                    {r.hits.map((h) => (
                      <span key={h.pattern} className={`pattern-tag${sel.size && !sel.has(h.pattern) ? " dim" : ""}`}
                        style={{ background: metaById[h.pattern]?.color }}
                        title={`${metaById[h.pattern]?.title ?? h.pattern}\n${h.notes.join("\n")}`}>
                        {h.text}
                      </span>
                    ))}
                  </td>
                </tr>
              ))}
              {!rows.length && (
                <tr><td colSpan={6} className="muted">
                  No stock formed {sel.size > 1 ? "all the selected patterns together" : "the selected pattern"}
                  {minTurnover ? ` with turnover above ${minTurnover} ${US.has(exchange) ? "$M" : "₹ Cr"}` : ""}.
                </td></tr>
              )}
            </tbody>
          </table>
          {rows.length > shown.length && <div className="hint">Showing the first 500 of {rows.length}; narrow the filters.</div>}
        </div>
      )}
    </div>
  );
}
