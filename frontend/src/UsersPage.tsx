import { useEffect, useState } from "react";
import { isAdmin } from "./auth";
import Logo from "./Logo";
import UserMenu from "./UserMenu";
import { useTheme, type Theme } from "./theme";

interface UserRow {
  id: number; name: string; email: string; phone: string; provider: string; is_admin: boolean; disabled: boolean;
  first_login_at: string; last_login_at: string; last_seen_at: string; login_count: number; request_count: number;
  active_minutes: number; days_active: number; last_ip: string; last_location: string; last_user_agent: string;
}
interface Detail {
  logins: { at: string; ok: boolean; reason: string; ip: string; country: string; city: string; user_agent: string }[];
  days: { day: string; requests: number; active_minutes: number }[];
  features: Record<string, number>;
  symbols: { symbol: string; count: number; last: string }[];
}

function storedTheme(): Theme {
  try {
    return JSON.parse(localStorage.getItem("theme") || '"light"') === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

const when = (iso: string) => (iso ? new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "—");
const hours = (m: number) => (m >= 60 ? `${(m / 60).toFixed(1)} h` : `${Math.round(m)} min`);

/** Admins: who uses Charting Lab and how (/?page=users). */
export default function UsersPage() {
  const [theme] = useState<Theme>(storedTheme);
  useTheme(theme);
  const [data, setData] = useState<{ users: UserRow[]; total: number; active_last_15_min: number;
    geoip?: { path: string; month: string; attribution: string } } | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const load = () => fetch("/api/admin/users").then(async (r) => {
    if (!r.ok) throw new Error((await r.json()).detail ?? r.statusText);
    setData(await r.json());
  }).catch((e) => setError(String(e.message ?? e)));
  useEffect(() => { document.title = "Users · Charting Lab"; void load(); }, []);
  useEffect(() => {
    setDetail(null);
    if (open != null) fetch(`/api/admin/users/${open}`).then((r) => r.json()).then(setDetail, () => {});
  }, [open]);
  const patch = async (id: number, body: object) => {
    const r = await fetch(`/api/admin/users/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) });
    if (!r.ok) setError((await r.json()).detail ?? r.statusText);
    void load();
  };

  return (
    <div className="app users-page">
      <header className="topbar">
        <a className="brand" href="/" title="Open the chart"><Logo /> Charting Lab</a>
        <span className="page-title">Users</span>
        {data && <span className="muted small">{data.total} users · {data.active_last_15_min} active in the last 15 minutes</span>}
        <span className="spacer" />
        <a className="toolbar-link" href="/api/admin/users.csv" download>⭳ Download CSV</a>
        <UserMenu />
      </header>
      <main className="main users-main">
        {!isAdmin() && <div className="hint">Admins only.</div>}
        {error && <div className="hint error">{error}</div>}
        {data && (
          <table className="scan-table users-table">
            <thead><tr><th>User</th><th>Sign-ins</th><th>Last sign-in</th><th>Last active</th><th>Active time</th>
              <th>Days</th><th>Requests</th><th>Last IP · place</th><th /></tr></thead>
            <tbody>
              {data.users.map((u) => [
                <tr key={u.id} className={open === u.id ? "open" : ""} onClick={() => setOpen(open === u.id ? null : u.id)}>
                  <td><b>{u.name || u.email}</b> {u.is_admin && <span className="tag">admin</span>}
                    {u.disabled && <span className="tag down">disabled</span>}<div className="muted small">{u.email}{u.phone ? ` · ${u.phone}` : ""}</div></td>
                  <td>{u.login_count}</td><td>{when(u.last_login_at)}</td><td>{when(u.last_seen_at)}</td>
                  <td>{hours(u.active_minutes)}</td><td>{u.days_active}</td><td>{u.request_count.toLocaleString("en-IN")}</td>
                  <td className="small">{u.last_ip || "—"}{u.last_location ? ` · ${u.last_location}` : ""}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    {u.provider !== "local" && (
                      <>
                        <button className="small" onClick={() => void patch(u.id, { is_admin: !u.is_admin })}>{u.is_admin ? "Remove admin" : "Make admin"}</button>{" "}
                        <button className="small" onClick={() => void patch(u.id, { disabled: !u.disabled })}>{u.disabled ? "Enable" : "Disable"}</button>
                      </>
                    )}
                  </td>
                </tr>,
                open === u.id && (
                  <tr key={`${u.id}-d`} className="why-row"><td colSpan={9}>
                    {!detail ? "Loading…" : (
                      <div className="user-detail">
                        <section><h4>Features used (90 days)</h4>
                          <ul>{Object.entries(detail.features).map(([f, n]) => <li key={f}>{f}: {n.toLocaleString("en-IN")}</li>)}</ul></section>
                        <section><h4>Stocks opened</h4>
                          <ul>{detail.symbols.slice(0, 15).map((s) => <li key={s.symbol}>{s.symbol}: {s.count} (last {when(s.last)})</li>)}</ul></section>
                        <section><h4>Recent sign-ins</h4>
                          <ul>{detail.logins.slice(0, 10).map((l, i) => (
                            <li key={i}>{when(l.at)} · {l.ok ? "ok" : `refused: ${l.reason}`} · {l.ip}{l.city ? ` · ${l.city}, ${l.country}` : ""}
                              <div className="muted small">{l.user_agent}</div></li>))}</ul></section>
                        <section><h4>Daily activity</h4>
                          <ul>{detail.days.slice(-14).reverse().map((d) => <li key={d.day}>{d.day}: {d.requests} requests, {hours(d.active_minutes)}</li>)}</ul></section>
                      </div>
                    )}
                  </td></tr>
                ),
              ])}
            </tbody>
          </table>
        )}
        {data && (
          <p className="muted small geo-credit">
            {data.geoip?.attribution
              ? <>Places from IP addresses: <a href="https://db-ip.com" target="_blank" rel="noopener">IP Geolocation by DB-IP</a> (CC BY 4.0), {data.geoip.month} edition, looked up on this server.</>
              : data.geoip?.path ? <>Places from IP addresses: {data.geoip.path}.</>
              : <>No IP location database yet: run <code>python -m app.cli update-geoip</code>.</>}
          </p>
        )}
      </main>
    </div>
  );
}
