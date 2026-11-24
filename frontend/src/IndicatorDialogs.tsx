import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError, type CustomDef, type IndicatorMeta, type PlotStyle } from "./api";
import { indicatorLabel, plotStyle, type ActiveIndicator, type PlotOverride } from "./indicatorStyle";

const CATEGORY_ORDER = ["Custom", "Moving averages", "Trend & bands", "Momentum", "Volatility", "Volume"];

// ---- picker ----------------------------------------------------------------------
export function IndicatorPicker(props: {
  metas: IndicatorMeta[];
  onAdd: (m: IndicatorMeta) => void;
  onNewCustom: () => void;
  onEditCustom: (id: string) => void;
  onDeleteCustom: (id: string) => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("All");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);

  const shown = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return props.metas.filter((m) =>
      (cat === "All" || m.category === cat) &&
      (!ql || m.title.toLowerCase().includes(ql) || m.id.toLowerCase().includes(ql)));
  }, [props.metas, q, cat]);
  const groups = CATEGORY_ORDER.map((c) => [c, shown.filter((m) => m.category === c)] as const).filter(([, xs]) => xs.length);
  const counts = (c: string) => props.metas.filter((m) => c === "All" || m.category === c).length;

  return (
    <Modal onClose={props.onClose} className="picker">
      <div className="picker-head">
        <h3>Indicators</h3>
        <input ref={input} placeholder="Search 50+ indicators…" value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && shown[0]) props.onAdd(shown[0]); }} />
        <button className="icon" onClick={props.onClose}>✕</button>
      </div>
      <div className="picker-body">
        <nav className="picker-cats">
          {["All", ...CATEGORY_ORDER].map((c) => (
            <button key={c} className={c === cat ? "active" : ""} onClick={() => setCat(c)}>
              {c} <span className="muted small">{counts(c)}</span>
            </button>
          ))}
          <button className="primary new-custom" onClick={props.onNewCustom}>+ Custom indicator</button>
        </nav>
        <div className="picker-list">
          {groups.map(([c, xs]) => (
            <section key={c}>
              <div className="panel-head">{c}</div>
              {xs.map((m) => (
                <div key={m.id} className="picker-row" onClick={() => props.onAdd(m)}>
                  <span>{m.title}</span>
                  <span className="row-actions">
                    {m.category === "Custom" && (
                      <>
                        <button className="icon" title="Edit formula" onClick={(e) => (e.stopPropagation(), props.onEditCustom(m.id))}>✎</button>
                        <button className="icon" title="Delete" onClick={(e) => {
                          e.stopPropagation();
                          if (confirm(`Delete custom indicator "${m.title}"?`)) props.onDeleteCustom(m.id);
                        }}>🗑</button>
                      </>
                    )}
                    <span className="tag">{m.overlay ? "overlay" : "pane"}</span>
                  </span>
                </div>
              ))}
            </section>
          ))}
          {!groups.length && <div className="hint">No indicator matches “{q}”.</div>}
          {cat === "Custom" && !groups.length && (
            <div className="hint">Write your own with formulas, e.g. <code>ema(close, 12) - ema(close, 26)</code>.</div>
          )}
        </div>
      </div>
    </Modal>
  );
}

// ---- settings for one instance ---------------------------------------------------------
export function IndicatorSettings(props: {
  ind: ActiveIndicator;
  meta: IndicatorMeta;
  onApply: (ind: ActiveIndicator) => void;
  onClose: () => void;
  onEditFormula?: () => void;
}) {
  const { ind, meta } = props;
  const [tab, setTab] = useState<"inputs" | "style">(meta.params.length ? "inputs" : "style");
  const [params, setParams] = useState<Record<string, number | string>>({ ...ind.params });
  const [style, setStyle] = useState<Record<string, PlotOverride>>({ ...(ind.style ?? {}) });
  const [error, setError] = useState("");
  const plots = meta.plots.filter((p) => p.style !== "hidden");

  const apply = (e: FormEvent) => {
    e.preventDefault();
    for (const p of meta.params) {
      const v = params[p.name];
      if (p.kind === "source") continue;
      const n = Number(v);
      if (!Number.isFinite(n) || n < p.min || n > p.max || (p.kind === "int" && !Number.isInteger(n))) {
        setError(`${p.name} must be ${p.kind === "int" ? "a whole number" : "a number"} from ${p.min} to ${p.max}`);
        setTab("inputs");
        return;
      }
    }
    const clean = Object.fromEntries(meta.params.map((p) => [p.name, p.kind === "source" ? params[p.name] : Number(params[p.name])]));
    props.onApply({ ...ind, params: clean, style });
  };
  const setPlot = (name: string, o: PlotOverride) => setStyle((s) => ({ ...s, [name]: { ...s[name], ...o } }));

  return (
    <Modal onClose={props.onClose}>
      <form onSubmit={apply} className="settings">
        <h3>{indicatorLabel({ ...ind, params }, meta)}</h3>
        <nav className="tabs inline">
          <button type="button" className={tab === "inputs" ? "active" : ""} onClick={() => setTab("inputs")}>Inputs</button>
          <button type="button" className={tab === "style" ? "active" : ""} onClick={() => setTab("style")}>Style</button>
        </nav>
        {tab === "inputs" && (
          <div className="form-grid">
            {!meta.params.length && <div className="hint">This indicator has no inputs.</div>}
            {meta.params.map((p) => (
              <label key={p.name}>
                <span>{humanize(p.name)}</span>
                {p.kind === "source" ? (
                  <select value={String(params[p.name])} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })}>
                    {p.options.map((o) => <option key={o}>{o}</option>)}
                  </select>
                ) : (
                  <input type="number" value={params[p.name]} min={p.min} max={p.max} step={p.kind === "int" ? 1 : "any"}
                    onChange={(e) => setParams({ ...params, [p.name]: e.target.value })} />
                )}
              </label>
            ))}
          </div>
        )}
        {tab === "style" && (
          <div className="form-grid">
            {plots.map((p) => {
              const st = plotStyle({ ...ind, style }, meta, p.name);
              const hidden = !!style[p.name]?.hidden;
              return (
                <label key={p.name} className="style-row">
                  <input type="checkbox" checked={!hidden} onChange={(e) => setPlot(p.name, { hidden: !e.target.checked })} />
                  <span>{humanize(p.name)}</span>
                  <input type="color" value={st.color.slice(0, 7)} onChange={(e) => setPlot(p.name, { color: e.target.value })} />
                  {p.style !== "histogram" && (
                    <select value={st.width} onChange={(e) => setPlot(p.name, { width: Number(e.target.value) as 1 | 2 | 3 | 4 })}>
                      {[1, 2, 3, 4].map((w) => <option key={w} value={w}>{w}px</option>)}
                    </select>
                  )}
                </label>
              );
            })}
          </div>
        )}
        {error && <div className="error">{error}</div>}
        <div className="modal-actions">
          {props.onEditFormula && <button type="button" className="link" onClick={props.onEditFormula}>Edit formula…</button>}
          <span className="spacer" />
          <button type="button" onClick={() => (setParams(Object.fromEntries(meta.params.map((p) => [p.name, p.default]))), setStyle({}))}>
            Defaults
          </button>
          <button type="button" onClick={props.onClose}>Cancel</button>
          <button type="submit" className="primary">Apply</button>
        </div>
      </form>
    </Modal>
  );
}

// ---- custom formula editor ------------------------------------------------------------
const FUNCS = [
  ["sma(x, n)", "simple MA"], ["ema(x, n)", "exponential MA"], ["wma(x, n)", "weighted MA"], ["rma(x, n)", "Wilder MA"],
  ["hma / dema / tema(x, n)", "fast MAs"], ["linreg(x, n)", "regression line"], ["rsi(x, n)", "RSI"],
  ["roc(x, n)", "rate of change %"], ["change(x, n=1)", "x − x[n]"], ["stdev(x, n)", "std deviation"],
  ["highest / lowest(x, n)", "rolling max / min"], ["sum(x, n)", "rolling sum"], ["atr(n)", "average true range"],
  ["vwma(x, n)", "volume-weighted MA"], ["crossover / crossunder(a, b)", "1 on the cross bar"],
  ["where(cond, a, b)", "a if cond else b"], ["nz(x, v)", "replace missing"], ["abs sqrt log exp", ""], ["max / min(a, b)", ""],
];

const EMPTY: CustomDef = {
  name: "My indicator", overlay: false,
  inputs: [{ name: "length", default: 20, min: 1, max: 500 }],
  plots: [{ name: "value", expr: "ema(close, length) - sma(close, length)", style: "line", color: "#2962ff" }],
  levels: [0],
};

export function CustomEditor(props: {
  initial?: { id: string; def: CustomDef };
  onSaved: (id: string, isNew: boolean) => void;
  onClose: () => void;
}) {
  const [def, setDef] = useState<CustomDef>(props.initial?.def ?? EMPTY);
  const [levels, setLevels] = useState((props.initial?.def ?? EMPTY).levels.join(", "));
  const [msg, setMsg] = useState<{ ok: boolean; text: string; plot?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [help, setHelp] = useState(!props.initial);

  const current = (): CustomDef => ({
    ...def,
    inputs: def.inputs.map((i) => ({ ...i, default: Number(i.default), min: Number(i.min), max: Number(i.max) })),
    levels: levels.split(",").map((s) => s.trim()).filter(Boolean).map(Number).filter(Number.isFinite),
  });
  const fail = (e: unknown) => {
    const d = e instanceof ApiError ? (e.detail as { plot?: string } | undefined) : undefined;
    setMsg({ ok: false, text: e instanceof Error ? e.message : String(e), plot: d?.plot });
  };
  const check = async () => {
    setBusy(true);
    try {
      const r = await api.checkCustom(current());
      setMsg({ ok: true, text: `Looks good — needs ${r.warmup} bars of warm-up.` });
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const out = props.initial ? await api.updateCustom(props.initial.id, current()) : await api.createCustom(current());
      props.onSaved(out.id, !props.initial);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };
  const setInput = (k: number, patch: Partial<CustomDef["inputs"][0]>) =>
    setDef({ ...def, inputs: def.inputs.map((x, i) => (i === k ? { ...x, ...patch } : x)) });
  const setPlot = (k: number, patch: Partial<CustomDef["plots"][0]>) =>
    setDef({ ...def, plots: def.plots.map((x, i) => (i === k ? { ...x, ...patch } : x)) });

  return (
    <Modal onClose={props.onClose} className="editor">
      <form onSubmit={save}>
        <div className="picker-head">
          <h3>{props.initial ? "Edit custom indicator" : "New custom indicator"}</h3>
          <button type="button" className="link" onClick={() => setHelp(!help)}>{help ? "Hide" : "Show"} reference</button>
        </div>
        <div className="editor-body">
          <div className="editor-main">
            <div className="row">
              <input className="grow" value={def.name} maxLength={80} onChange={(e) => setDef({ ...def, name: e.target.value })} placeholder="Name" />
              <select value={def.overlay ? "overlay" : "pane"} onChange={(e) => setDef({ ...def, overlay: e.target.value === "overlay" })}>
                <option value="overlay">On price chart</option>
                <option value="pane">Separate pane</option>
              </select>
            </div>

            <div className="panel-head">Inputs <button type="button" className="small" disabled={def.inputs.length >= 8}
              onClick={() => setDef({ ...def, inputs: [...def.inputs, { name: `input${def.inputs.length + 1}`, default: 14, min: 1, max: 500 }] })}>+ input</button></div>
            {def.inputs.map((inp, k) => (
              <div className="row" key={k}>
                <input className="name" value={inp.name} onChange={(e) => setInput(k, { name: e.target.value })} />
                <label className="mini">default<input type="number" step="any" value={inp.default} onChange={(e) => setInput(k, { default: e.target.value as unknown as number })} /></label>
                <label className="mini">min<input type="number" step="any" value={inp.min} onChange={(e) => setInput(k, { min: e.target.value as unknown as number })} /></label>
                <label className="mini">max<input type="number" step="any" value={inp.max} onChange={(e) => setInput(k, { max: e.target.value as unknown as number })} /></label>
                <button type="button" className="icon" onClick={() => setDef({ ...def, inputs: def.inputs.filter((_, i) => i !== k) })}>✕</button>
              </div>
            ))}

            <div className="panel-head">Plots <button type="button" className="small" disabled={def.plots.length >= 8}
              onClick={() => setDef({ ...def, plots: [...def.plots, { name: `plot${def.plots.length + 1}`, expr: "", style: "line", color: null }] })}>+ plot</button></div>
            {def.plots.map((p, k) => (
              <div className={`plot-row${msg?.plot === p.name ? " bad" : ""}`} key={k}>
                <div className="row">
                  <input className="name" value={p.name} onChange={(e) => setPlot(k, { name: e.target.value })} />
                  <span className="muted">=</span>
                  <input className="grow mono" value={p.expr} placeholder="e.g. sma(close, length)" spellCheck={false}
                    onChange={(e) => setPlot(k, { expr: e.target.value })} />
                </div>
                <div className="row sub">
                  <select value={p.style} onChange={(e) => setPlot(k, { style: e.target.value as PlotStyle })}>
                    <option value="line">line</option><option value="histogram">histogram</option>
                    <option value="dots">dots</option><option value="hidden">hidden (helper)</option>
                  </select>
                  <input type="color" value={p.color ?? "#2962ff"} onChange={(e) => setPlot(k, { color: e.target.value })} />
                  <span className="spacer" />
                  <button type="button" className="icon" disabled={def.plots.length < 2}
                    onClick={() => setDef({ ...def, plots: def.plots.filter((_, i) => i !== k) })}>✕</button>
                </div>
              </div>
            ))}

            <label className="row">
              <span className="muted">Level lines</span>
              <input className="grow" value={levels} placeholder="e.g. 30, 70" onChange={(e) => setLevels(e.target.value)} />
            </label>
            {msg && <div className={msg.ok ? "ok" : "error"}>{msg.text}</div>}
          </div>
          {help && (
            <aside className="editor-help">
              <p><b>Series:</b> <code>open high low close volume hl2 hlc3 ohlc4</code>, your inputs, and plots defined above.</p>
              <p><b>Operators:</b> <code>+ − * / % **</code>, comparisons <code>&gt; &lt; &gt;= &lt;= == !=</code> (1/0), <code>and or not</code>.</p>
              <p><b>History:</b> <code>close[1]</code> is the previous bar.</p>
              <table className="funcs"><tbody>
                {FUNCS.map(([f, d]) => <tr key={f}><td><code>{f}</code></td><td className="muted">{d}</td></tr>)}
              </tbody></table>
              <p className="muted small">Window lengths (n) must be numbers or input names. Formulas run on the server in a
                sandboxed evaluator; there is no code execution.</p>
            </aside>
          )}
        </div>
        <div className="modal-actions">
          <button type="button" onClick={check} disabled={busy}>Check</button>
          <span className="spacer" />
          <button type="button" onClick={props.onClose}>Cancel</button>
          <button type="submit" className="primary" disabled={busy}>{props.initial ? "Save" : "Save & add to chart"}</button>
        </div>
      </form>
    </Modal>
  );
}

// ---- shared ---------------------------------------------------------------------
export function Modal(props: { children: ReactNode; onClose: () => void; className?: string }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && props.onClose();
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [props]);
  return (
    <div className="modal-bg" onMouseDown={props.onClose}>
      <div className={`modal ${props.className ?? ""}`} onMouseDown={(e) => e.stopPropagation()}>{props.children}</div>
    </div>
  );
}

const humanize = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
