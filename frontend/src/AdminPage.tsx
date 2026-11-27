import { useEffect, useRef, useState } from "react";
import Logo from "./Logo";
import UserMenu from "./UserMenu";
import { useTheme, type Theme } from "./theme";

interface JobSummary {
  id: number; kind: string; title: string; market: string; date: string; by: string; started: number;
  finished: number | null; state: "running" | "done" | "error"; exit_code: number | null; lines: number; last_line: string;
}
interface ExchangeStatus {
  exchange: string; title: string; symbols: number; last_daily: string; last_minute: string; last_setup_scan: string;
  last_screen_1d: string; last_screen_1w: string;
}
interface Status {
  exchanges: ExchangeStatus[]; markets: Record<string, string[]>; kinds: { kind: string; title: string }[];
  running: JobSummary | null; jobs: JobSummary[];
}

function storedTheme(): Theme {
  try {
    return JSON.parse(localStorage.getItem("theme") || '"light"') === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

const when = (t: number | null) => (t ? new Date(t * 1000).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "—");
const took = (j: JobSummary) => {
  const s = Math.round(((j.finished ?? Date.now() / 1000) - j.started));
  return s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`;
};
const ICON: Record<string, string> = { download: "⭳", setup_scan: "▤", pattern_screen: "▦", full: "⟳" };

/** Admins: the data's state, and buttons that start the EOD download, the setup screener, the pattern screener or all
 * of it (the nightly job's own steps, at once), with the job's output as it runs. (/?page=admin) */
export default function AdminPage() {
  const [theme] = useState<Theme>(storedTheme);
  useTheme(theme);
  const [st, setSt] = useState<Status | null>(null);
  const [error, setError] = useState("");
  const [market, setMarket] = useState("NSE");
  const [day, setDay] = useState("");
  const [shown, setShown] = useState<number | null>(null);        // the job whose output is shown
  const [lines, setLines] = useState<string[]>([]);
  const [job, setJob] = useState<JobSummary | null>(null);
  const next = useRef(0);
  const logBox = useRef<HTMLPreElement>(null);

  const load = async () => {
    const r = await fetch("/api/admin/status");
    if (!r.ok) throw new Error((await r.json()).detail ?? r.statusText);
    const s = (await r.json()) as Status;
    setSt(s);
    return s;
  };
  useEffect(() => {
    document.title = "Admin · Charting Lab";
    load().then((s) => { if (s.running) setShown(s.running.id); else if (s.jobs[0]) setShown(s.jobs[0].id); },
      (e) => setError(String(e.message ?? e)));
  }, []);

  // follow the shown job: its output lines, new ones every 1.5 s while it runs
  useEffect(() => {
    if (shown == null) return;
    setLines([]);
    next.current = 0;
    let stop = false;
    const tick = async () => {
      const r = await fetch(`/api/admin/jobs/${shown}?since=${next.current}`);
      if (!r.ok || stop) return;
      const j = await r.json();
      next.current = j.next;
      setJob(j);
      if (j.lines.length) setLines((old) => [...old, ...j.lines]);
      if (j.state === "running") window.setTimeout(() => void tick(), 1500);
      else void load();                                                  // finished: the data status may have moved
    };
    void tick();
    return () => { stop = true; };
  }, [shown]);
  useEffect(() => { logBox.current?.scrollTo({ top: logBox.current.scrollHeight }); }, [lines]);

  const start = async (kind: string) => {
    setError("");
    const r = await fetch("/api/admin/jobs", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, market, date: day || null }) });
    const body = await r.json();
    if (!r.ok) {
      setError(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail));
      return;
    }
    setShown(body.id);
    void load();
  };
  const running = !!st?.running || job?.state === "running";

  return (
    <div className="app admin-page">
      <header className="topbar">
        <a className="brand" href="/" title="Open the chart"><Logo /> Charting Lab</a>
        <span className="page-title">Admin</span>
        <span className="spacer" />
        <a className="toolbar-link" href="/?page=users">Users</a>
        <UserMenu />
      </header>
      <main className="main admin-main">
        {error && <div className="hint error" role="alert">{error}</div>}

        <section className="admin-card">
          <h3>Run</h3>
          <p className="muted small">The nightly job's own steps, started now: the download tries once, at once (the nightly
            job retries for over an hour). One job at a time.</p>
          <div className="admin-run" role="group" aria-label="Run a job">
            <label>Market{" "}
              <select aria-label="Market" value={market} onChange={(e) => setMarket(e.target.value)}>
                {Object.entries(st?.markets ?? { NSE: ["NSE"] }).map(([m, ex]) => <option key={m} value={m}>{m}{ex.length > 1 ? ` (${ex.join(", ")})` : ""}</option>)}
              </select>
            </label>
            <label>Session{" "}
              <input type="date" aria-label="Session" value={day} onChange={(e) => setDay(e.target.value)} />
              {day ? <button className="small" onClick={() => setDay("")}>Latest</button> : <span className="muted small"> latest</span>}
            </label>
            <div className="admin-buttons">
              {(st?.kinds ?? []).map((k) => (
                <button key={k.kind} className={k.kind === "full" ? "" : "primary"} disabled={running}
                  onClick={() => void start(k.kind)} title={running ? "A job is running" : `${k.title}: ${market}${day ? `, ${day}` : ", the latest session"}`}>
                  {ICON[k.kind] ?? "▶"} {k.title}
                </button>
              ))}
            </div>
          </div>
          {job && (
            <div className="admin-job">
              <div className="small">
                <b>{job.title}</b> · {job.market}{job.date ? ` · ${job.date}` : ""} · started {when(job.started)} by {job.by} ·{" "}
                <span className={`job-state ${job.state}`}>{job.state === "running" ? `running (${took(job)})` : job.state === "done" ? `done in ${took(job)}` : `failed (exit ${job.exit_code ?? "?"})`}</span>
              </div>
              <pre className="job-log" ref={logBox} aria-label="Job output">{lines.join("\n")}</pre>
            </div>
          )}
        </section>

        <section className="admin-card">
          <h3>Data</h3>
          <table className="scan-table admin-data">
            <thead><tr><th>Exchange</th><th>Symbols</th><th>Last daily bar</th><th>Last minute bar</th>
              <th>Last setup scan</th><th>Pattern screen (daily)</th><th>Pattern screen (weekly)</th></tr></thead>
            <tbody>
              {(st?.exchanges ?? []).map((x) => (
                <tr key={x.exchange}>
                  <td><b>{x.exchange}</b> <span className="muted small">{x.title}</span></td>
                  <td>{x.symbols.toLocaleString("en-IN")}</td><td>{x.last_daily || "—"}</td>
                  <td>{x.last_minute ? x.last_minute.replace("T", " ").replace("Z", " UTC") : "—"}</td>
                  <td>{x.last_setup_scan || "—"}</td><td>{x.last_screen_1d || "—"}</td><td>{x.last_screen_1w || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="admin-card">
          <h3>Recent jobs</h3>
          {!st?.jobs.length ? <p className="muted small">None yet.</p> : (
            <table className="scan-table admin-jobs">
              <thead><tr><th>Job</th><th>Market</th><th>Session</th><th>By</th><th>Started</th><th>Took</th><th>Result</th></tr></thead>
              <tbody>
                {st.jobs.map((j) => (
                  <tr key={j.id} className={shown === j.id ? "open" : ""} onClick={() => setShown(j.id)} title="Show its output">
                    <td>{j.title}</td><td>{j.market}</td><td>{j.date || "latest"}</td><td className="small">{j.by}</td>
                    <td>{when(j.started)}</td><td>{took(j)}</td>
                    <td><span className={`job-state ${j.state}`}>{j.state === "error" ? `failed (${j.exit_code ?? "?"})` : j.state}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </main>
    </div>
  );
}
