import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { IChartApi, ISeriesApi, SeriesType } from "lightweight-charts";
import { api, type LiveBar } from "./api";
import { DrawingsPrimitive, hitTest, Mapper, newId, POINTS, type Drawing, type Kind, type Pt, type RenderState } from "./drawings";
import { fmt } from "./format";

type Tool = Kind | "cursor";

interface Props {
  chart: IChartApi | null;
  series: ISeriesApi<SeriesType> | null;
  host: HTMLDivElement | null;     // the chart's container (mouse events)
  bars: React.MutableRefObject<LiveBar[]>;
  symbol: string;
  textColor: string;
}

const COLORS = ["#2962ff", "#f23645", "#089981", "#ff9800", "#9c27b0", "#00bcd4", "#787b86", "#131722"];
const DEFAULT_COLOR: Partial<Record<Kind, string>> = { fib: "#787b86", rect: "#9c27b0", channel: "#2962ff", text: "#2962ff" };

const TOOLS: { id: Tool; title: string; icon: ReactNode; key?: string }[] = [
  { id: "cursor", title: "Cursor (Esc)", icon: <path d="M5 3l12 7-5 1.5L9 17z" fill="currentColor" stroke="none" /> },
  { id: "trend", title: "Trend line (Alt+T)", key: "t", icon: <><line x1="4" y1="16" x2="16" y2="4" /><circle cx="4" cy="16" r="1.6" /><circle cx="16" cy="4" r="1.6" /></> },
  { id: "ray", title: "Ray", icon: <><line x1="4" y1="16" x2="19" y2="3" /><circle cx="4" cy="16" r="1.6" /><circle cx="10" cy="10.6" r="1.6" /></> },
  { id: "extended", title: "Extended line", icon: <><line x1="1" y1="18" x2="19" y2="2" /><circle cx="7" cy="12.7" r="1.6" /><circle cx="13" cy="7.3" r="1.6" /></> },
  { id: "arrow", title: "Arrow", icon: <><line x1="4" y1="16" x2="15" y2="5" /><path d="M10 4.5h5.5V10" /></> },
  { id: "hline", title: "Horizontal line (Alt+H)", key: "h", icon: <><line x1="1" y1="10" x2="19" y2="10" /><circle cx="10" cy="10" r="1.6" /></> },
  { id: "hray", title: "Horizontal ray", icon: <><line x1="6" y1="10" x2="19" y2="10" /><circle cx="6" cy="10" r="1.6" /></> },
  { id: "vline", title: "Vertical line (Alt+V)", key: "v", icon: <><line x1="10" y1="1" x2="10" y2="19" /><circle cx="10" cy="10" r="1.6" /></> },
  { id: "channel", title: "Parallel channel", icon: <><line x1="2" y1="12" x2="14" y2="4" /><line x1="6" y1="17" x2="18" y2="9" /></> },
  { id: "rect", title: "Rectangle", icon: <rect x="3" y="5" width="14" height="10" /> },
  { id: "fib", title: "Fibonacci retracement (Alt+F)", key: "f", icon: <><line x1="2" y1="4" x2="18" y2="4" /><line x1="2" y1="8" x2="18" y2="8" /><line x1="2" y1="11" x2="18" y2="11" /><line x1="2" y1="16" x2="18" y2="16" /></> },
  { id: "brush", title: "Brush", icon: <path d="M3 15c3-1 3-6 6-6s2 5 5 4 3-6 3-6" /> },
  { id: "text", title: "Text", icon: <path d="M4 4h12M10 4v13" /> },
  { id: "measure", title: "Measure price / time range", icon: <><path d="M3 17V3M3 17h14" /><path d="M7 13l4-4 3 2 3-5" /></> },
];

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4"
      strokeLinecap="round" strokeLinejoin="round">{children}</svg>
  );
}

const usePersistedBool = (key: string, init: boolean) => {
  const [v, setV] = useState(() => (localStorage.getItem(key) ?? String(init)) === "true");
  useEffect(() => localStorage.setItem(key, String(v)), [key, v]);
  return [v, setV] as const;
};

export default function DrawingTools({ chart, series, host, bars, symbol, textColor }: Props) {
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [tool, setTool] = useState<Tool>("cursor");
  const [selected, setSelected] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [draft, setDraft] = useState<Drawing | null>(null);
  const [magnet, setMagnet] = usePersistedBool("draw.magnet", false);
  const [locked, setLocked] = usePersistedBool("draw.lockAll", false);
  const [hidden, setHidden] = usePersistedBool("draw.hideAll", false);
  const [lastColor, setLastColor] = useState<string | null>(null);
  const dirty = useRef(false);
  const loadedFor = useRef<string | null>(null);

  // ---- mapping (cached bar times) ------------------------------------------------------
  const timesCache = useRef<{ n: number; first: number; last: number; arr: number[] }>({ n: -1, first: 0, last: 0, arr: [] });
  const times = () => {
    const b = bars.current, c = timesCache.current;
    const n = b.length;
    if (n !== c.n || (n && (b[0].t !== c.first || b[n - 1].t !== c.last))) {
      timesCache.current = { n, first: n ? b[0].t : 0, last: n ? b[n - 1].t : 0, arr: b.map((x) => x.t) };
    }
    return timesCache.current.arr;
  };
  const mapper = useMemo(() => (chart && series ? new Mapper(chart, series, times) : null), [chart, series]); // eslint-disable-line react-hooks/exhaustive-deps

  // latest state for the primitive and the native event handlers
  const st = useRef({ drawings, tool, selected, hover, draft, magnet, locked, hidden, mapper });
  st.current = { drawings, tool, selected, hover, draft, magnet, locked, hidden, mapper };

  const renderState = (): RenderState => ({
    drawings: st.current.hidden ? [] : st.current.drawings,
    draft: st.current.draft,
    selected: st.current.selected,
    hover: st.current.hover,
    mapper: st.current.mapper,
    fmt,
    barsBetween: (t1, t2) => {
      const m = st.current.mapper;
      return m ? Math.round(Math.abs(m.timeToLogical(t2) - m.timeToLogical(t1))) : 0;
    },
    textColor,
  });

  const prim = useMemo(() => new DrawingsPrimitive(() => renderState()), []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!series) return;
    series.attachPrimitive(prim);
    return () => series.detachPrimitive(prim);
  }, [series, prim]);
  useEffect(() => prim.update(), [prim, drawings, draft, selected, hover, hidden]);

  // ---- load / save per symbol ----------------------------------------------------------
  useEffect(() => {
    let live = true;
    loadedFor.current = null;
    setDrawings([]);
    setSelected(null);
    setDraft(null);
    api.drawings(symbol).then((r) => {
      if (!live) return;
      setDrawings(r.items as Drawing[]);
      loadedFor.current = symbol;
    }, () => (loadedFor.current = symbol));
    return () => { live = false; };
  }, [symbol]);

  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!dirty.current || loadedFor.current !== symbol) return;
    const h = setTimeout(() => {
      dirty.current = false;
      api.saveDrawings(symbol, drawings.filter((d) => d.kind !== "measure")).catch(() => {
        dirty.current = true; // e.g. database busy: try again shortly
        setTimeout(() => setRetry((r) => r + 1), 3000);
      });
    }, 500);
    return () => clearTimeout(h);
  }, [drawings, symbol, retry]);

  const change = (f: (ds: Drawing[]) => Drawing[]) => {
    dirty.current = true;
    setDrawings(f);
  };

  // pan/zoom stays with the chart unless a drawing tool is active
  useEffect(() => {
    chart?.applyOptions({ handleScroll: tool === "cursor", handleScale: tool === "cursor" });
  }, [chart, tool]);

  // ---- mouse --------------------------------------------------------------------------
  useEffect(() => {
    if (!host || !chart || !mapper) return;
    let swallow = false;           // this press belongs to us: hide it from the chart
    let drag: { id: string; handle: number | null; start: Pt; startL: number; orig: Pt[] } | null = null;
    let downAt: { x: number; y: number } | null = null;
    let creating = false;           // a draft was started by the current press

    const local = (e: MouseEvent) => {
      const r = host.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };
    const inPane = (x: number, y: number) =>
      y >= 0 && x >= 0 && y <= (chart.panes()[0]?.getHeight() ?? 0) && x <= chart.timeScale().width();
    const paneSize = () => ({ w: chart.timeScale().width(), h: chart.panes()[0]?.getHeight() ?? 0 });

    const snap = (x: number, y: number): Pt | null => {
      const pt = mapper.fromXY(x, y);
      if (!pt || !st.current.magnet) return pt;
      const i = mapper.barIndexAt(x);
      const b = i !== null ? bars.current[i] : undefined;
      if (!b) return pt;
      const best = [b.o, b.h, b.l, b.c].reduce((acc, p) => {
        const py = series!.priceToCoordinate(p);
        return py !== null && Math.abs(py - y) < acc.d ? { p, d: Math.abs(py - y) } : acc;
      }, { p: pt.p, d: 30 });
      return { t: b.t, p: best.p };
    };

    const commit = (d: Drawing) => {
      setDraft(null);
      if (d.kind === "measure") {
        setDraft(d); // stays visible until the next click or Esc, never saved
        setTool("cursor");
        return;
      }
      change((ds) => [...ds, d]);
      setSelected(d.id);
      setTool("cursor");
    };

    const onPointerDown = (e: PointerEvent) => {
      swallow = false;
      if (e.button !== 0) return;
      const { x, y } = local(e);
      if (!inPane(x, y)) return;
      const s = st.current;
      if (s.tool === "cursor") {
        if (s.draft?.kind === "measure") setDraft(null);
        const { w, h } = paneSize();
        const hit = s.hidden ? null : hitTest(s.drawings, mapper, { x, y }, w, h, s.selected);
        if (!hit) {
          setSelected(null);
          return;
        }
        setSelected(hit.id);
        const d = s.drawings.find((q) => q.id === hit.id)!;
        if (s.locked || d.locked) return;
        const start = mapper.fromXY(x, y);
        if (!start) return;
        drag = { id: hit.id, handle: hit.handle, start, startL: mapper.timeToLogical(start.t), orig: d.pts };
        swallow = true;
      } else {
        swallow = true;
        const pt = snap(x, y);
        if (!pt) return;
        downAt = { x, y };
        const need = POINTS[s.tool];
        const d = s.draft;
        if (!d || d.kind !== s.tool) {
          const color = lastColor ?? DEFAULT_COLOR[s.tool] ?? "#2962ff";
          const base: Drawing = { id: newId(), kind: s.tool, pts: [pt], color, width: s.tool === "brush" ? 2 : s.tool === "text" ? 3 : 2 };
          if (need === 1) {
            commit(s.tool === "text" ? { ...base, text: "Text" } : base);
            return;
          }
          creating = true;
          setDraft({ ...base, pts: s.tool === "brush" ? [pt] : [pt, pt] });
        } else if (d.pts.length < need) {
          // click-click mode: this click fixes the moving point
          const pts = [...d.pts.slice(0, -1), pt];
          if (pts.length >= need) commit({ ...d, pts });
          else setDraft({ ...d, pts: [...pts, pt] });
        } else {
          commit(d);
        }
      }
      if (swallow) {
        e.stopPropagation();
        e.preventDefault();
      }
    };
    const onMouseDown = (e: MouseEvent) => {
      if (swallow) {
        e.stopPropagation();
        e.preventDefault();
      }
    };

    const onMove = (e: PointerEvent) => {
      const { x, y } = local(e);
      const s = st.current;
      if (drag) {
        const now = mapper.fromXY(x, y);
        if (!now) return;
        const dg = drag;
        change((ds) => ds.map((d) => {
          if (d.id !== dg.id) return d;
          if (dg.handle !== null) {
            const p = snap(x, y) ?? now;
            return { ...d, pts: d.pts.map((q, i) => (i === dg.handle ? p : q)) };
          }
          const dl = mapper.timeToLogical(now.t) - dg.startL;
          const dp = now.p - dg.start.p;
          return { ...d, pts: dg.orig.map((q) => ({ t: mapper.logicalToTime(mapper.timeToLogical(q.t) + dl), p: q.p + dp })) };
        }));
        return;
      }
      if (s.draft && s.tool !== "cursor") {
        const pt = snap(x, y);
        if (!pt) return;
        if (s.draft.kind === "brush") {
          if (creating) setDraft({ ...s.draft, pts: [...s.draft.pts, pt] });
        } else {
          setDraft({ ...s.draft, pts: [...s.draft.pts.slice(0, -1), pt] });
        }
        return;
      }
      if (s.tool === "cursor" && inPane(x, y) && !s.hidden) {
        const { w, h } = paneSize();
        const hit = hitTest(s.drawings, mapper, { x, y }, w, h, s.selected);
        setHover(hit?.id ?? null);
        host.style.cursor = hit ? (hit.handle !== null ? "move" : "pointer") : "";
      } else {
        host.style.cursor = s.tool === "cursor" ? "" : "crosshair";
      }
    };

    const onUp = (e: PointerEvent) => {
      const s = st.current;
      if (drag) {
        drag = null;
        return;
      }
      if (creating && s.draft) {
        creating = false;
        const { x, y } = local(e);
        const moved = downAt ? Math.hypot(x - downAt.x, y - downAt.y) > 4 : false;
        if (s.draft.kind === "brush") {
          if (s.draft.pts.length > 1) commit(s.draft); else setDraft(null);
        } else if (moved) {
          // drag-to-draw: release fixes the second point
          const need = POINTS[s.draft.kind];
          if (s.draft.pts.length >= need) commit(s.draft);
          else {
            const pt = snap(x, y);
            if (pt) setDraft({ ...s.draft, pts: [...s.draft.pts, pt] });
          }
        }
      }
    };

    host.addEventListener("pointerdown", onPointerDown, true);
    host.addEventListener("mousedown", onMouseDown, true);
    host.addEventListener("touchstart", onMouseDown as unknown as EventListener, true);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      host.removeEventListener("pointerdown", onPointerDown, true);
      host.removeEventListener("mousedown", onMouseDown, true);
      host.removeEventListener("touchstart", onMouseDown as unknown as EventListener, true);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      host.style.cursor = "";
    };
  }, [host, chart, series, mapper, lastColor]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- keyboard -----------------------------------------------------------------------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable) return;
      const s = st.current;
      if (e.key === "Escape") {
        if (s.draft) setDraft(null);
        else if (s.tool !== "cursor") setTool("cursor");
        else setSelected(null);
      } else if ((e.key === "Delete" || e.key === "Backspace") && s.selected) {
        change((ds) => ds.filter((d) => d.id !== s.selected));
        setSelected(null);
      } else if (e.altKey && !e.ctrlKey) {
        const t = TOOLS.find((x) => x.key === e.key.toLowerCase());
        if (t) {
          e.preventDefault();
          setDraft(null);
          setTool(t.id);
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const sel = drawings.find((d) => d.id === selected);
  const patch = (p: Partial<Drawing>) => sel && change((ds) => ds.map((d) => (d.id === sel.id ? { ...d, ...p } : d)));

  return (
    <>
      <div className="draw-toolbar">
        {TOOLS.map((t) => (
          <button key={t.id} title={t.title} className={tool === t.id ? "active" : ""}
            onClick={() => { setDraft(null); setTool(tool === t.id && t.id !== "cursor" ? "cursor" : t.id); }}>
            <Icon>{t.icon}</Icon>
          </button>
        ))}
        <div className="draw-sep" />
        <button title="Magnet: snap to open/high/low/close" className={magnet ? "active" : ""} onClick={() => setMagnet(!magnet)}>
          <Icon><path d="M5 3v7a5 5 0 0010 0V3M5 6h3M12 6h3" /></Icon>
        </button>
        <button title={locked ? "Unlock all drawings" : "Lock all drawings"} className={locked ? "active" : ""} onClick={() => setLocked(!locked)}>
          <Icon>{locked ? <><rect x="4" y="9" width="12" height="8" rx="1" /><path d="M7 9V6a3 3 0 016 0v3" /></>
            : <><rect x="4" y="9" width="12" height="8" rx="1" /><path d="M7 9V6a3 3 0 016-1" /></>}</Icon>
        </button>
        <button title={hidden ? "Show drawings" : "Hide drawings"} className={hidden ? "active" : ""} onClick={() => setHidden(!hidden)}>
          <Icon>{hidden ? <><path d="M2 10s3-5 8-5 8 5 8 5-3 5-8 5-8-5-8-5z" /><line x1="3" y1="17" x2="17" y2="3" /></>
            : <><path d="M2 10s3-5 8-5 8 5 8 5-3 5-8 5-8-5-8-5z" /><circle cx="10" cy="10" r="2.5" /></>}</Icon>
        </button>
        <button title="Remove all drawings on this symbol" disabled={!drawings.length}
          onClick={() => confirm(`Remove all ${drawings.length} drawings on ${symbol}?`) && (change(() => []), setSelected(null))}>
          <Icon><path d="M4 6h12M8 6V4h4v2M6 6l1 11h6l1-11" /></Icon>
        </button>
      </div>

      {sel && (
        <div className="draw-stylebar" onPointerDown={(e) => e.stopPropagation()}>
          {COLORS.map((c) => (
            <button key={c} className={`swatch-btn${sel.color === c ? " on" : ""}`} style={{ background: c }}
              onClick={() => (patch({ color: c }), setLastColor(c))} title={c} />
          ))}
          <input type="color" value={sel.color.slice(0, 7)} onChange={(e) => (patch({ color: e.target.value }), setLastColor(e.target.value))} />
          <select value={sel.width} onChange={(e) => patch({ width: Number(e.target.value) })} title={sel.kind === "text" ? "Size" : "Width"}>
            {[1, 2, 3, 4, 5, 6].map((w) => <option key={w} value={w}>{sel.kind === "text" ? `${10 + w * 2}px` : `${w}px`}</option>)}
          </select>
          {sel.kind === "text" && (
            <input className="draw-text" value={sel.text ?? ""} autoFocus placeholder="Text" maxLength={500}
              onChange={(e) => patch({ text: e.target.value })} />
          )}
          <button title={sel.locked ? "Unlock" : "Lock"} className={sel.locked ? "active" : ""} onClick={() => patch({ locked: !sel.locked })}>
            {sel.locked ? "🔒" : "🔓"}
          </button>
          <button title="Clone" onClick={() => {
            const c = { ...sel, id: newId(), pts: sel.pts.map((q) => ({ ...q, p: q.p * 1.01 })) };
            change((ds) => [...ds, c]);
            setSelected(c.id);
          }}>⧉</button>
          <button title="Delete (Del)" onClick={() => (change((ds) => ds.filter((d) => d.id !== sel.id)), setSelected(null))}>🗑</button>
        </div>
      )}
      {tool !== "cursor" && (
        <div className="draw-hint">
          {tool === "brush" ? "Hold and drag to draw" : POINTS[tool] === 1 ? "Click to place"
            : tool === "channel" ? "Click two points for the line, then a third for the width"
            : "Click two points (or drag)"} · Esc to cancel{magnet ? " · magnet on" : ""}
        </div>
      )}
    </>
  );
}
