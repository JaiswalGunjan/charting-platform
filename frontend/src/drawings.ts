// Drawing model, coordinate mapping, rendering and hit-testing.
//
// A drawing is stored as points in (bar time, price) so it survives zoom, scroll, timeframe
// changes and reloads. Times map to x through the loaded bars' logical index (interpolated
// between bars, extrapolated beyond either end with the typical bar interval).
import type { IChartApi, IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesApi, ISeriesPrimitive, Logical, SeriesType, Time } from "lightweight-charts";

export type Kind = "trend" | "ray" | "extended" | "arrow" | "hline" | "hray" | "vline" | "rect" | "channel" | "fib"
  | "brush" | "text" | "measure";

export interface Pt { t: number; p: number }

export interface Drawing {
  id: string;
  kind: Kind;
  pts: Pt[];
  color: string;
  width: number;
  text?: string;
  locked?: boolean;
  hidden?: boolean;
}

/** Points a tool needs (brush: open-ended, finished on mouse-up). */
export const POINTS: Record<Kind, number> = {
  trend: 2, ray: 2, extended: 2, arrow: 2, hline: 1, hray: 1, vline: 1, rect: 2, channel: 3, fib: 2, brush: Infinity,
  text: 1, measure: 2,
};

export const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
const FIB_COLORS = ["#787b86", "#f23645", "#ff9800", "#4caf50", "#089981", "#00bcd4", "#787b86"];

export interface XY { x: number; y: number }

/** Maps between (time, price) and pixel coordinates of the price pane. */
export class Mapper {
  constructor(private chart: IChartApi, private series: ISeriesApi<SeriesType>, private times: () => number[]) {}

  private step(ts: number[]): number {
    if (ts.length < 2) return 86400;
    const d: number[] = [];
    for (let i = Math.max(1, ts.length - 30); i < ts.length; i++) d.push(ts[i] - ts[i - 1]);
    d.sort((a, b) => a - b);
    return d[Math.floor(d.length / 2)] || 86400;
  }

  timeToLogical(t: number): number {
    const ts = this.times();
    if (!ts.length) return 0;
    const n = ts.length;
    if (t <= ts[0]) return (t - ts[0]) / this.step(ts.slice(0, 31));
    if (t >= ts[n - 1]) return n - 1 + (t - ts[n - 1]) / this.step(ts);
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (ts[mid] <= t) lo = mid; else hi = mid;
    }
    return lo + (t - ts[lo]) / (ts[hi] - ts[lo]);
  }

  logicalToTime(l: number): number {
    const ts = this.times();
    if (!ts.length) return 0;
    const n = ts.length;
    if (l <= 0) return ts[0] + l * this.step(ts.slice(0, 31));
    if (l >= n - 1) return ts[n - 1] + (l - (n - 1)) * this.step(ts);
    const i = Math.floor(l);
    return ts[i] + (l - i) * (ts[i + 1] - ts[i]);
  }

  // The time scale only converts whole bar indexes; interpolate between neighbours for the rest.
  private logicalToX(l: number): number | null {
    const ts = this.chart.timeScale();
    const i = Math.floor(l);
    const x0 = ts.logicalToCoordinate(i as Logical);
    const x1 = ts.logicalToCoordinate((i + 1) as Logical);
    return x0 === null || x1 === null ? null : x0 + (l - i) * (x1 - x0);
  }

  private xToLogical(x: number): number | null {
    const ts = this.chart.timeScale();
    const i = ts.coordinateToLogical(x);
    if (i === null) return null;
    const xi = ts.logicalToCoordinate(i);
    const xn = ts.logicalToCoordinate((i + 1) as Logical);
    if (xi === null || xn === null || xn === xi) return i;
    return i + (x - xi) / (xn - xi);
  }

  toXY(pt: Pt): XY | null {
    const x = this.logicalToX(this.timeToLogical(pt.t));
    const y = this.series.priceToCoordinate(pt.p);
    return x === null || y === null ? null : { x, y };
  }

  fromXY(x: number, y: number): Pt | null {
    const l = this.xToLogical(x);
    const p = this.series.coordinateToPrice(y);
    return l === null || p === null ? null : { t: this.logicalToTime(l), p };
  }

  barIndexAt(x: number): number | null {
    const l = this.xToLogical(x);
    return l === null ? null : Math.round(l);
  }
}

// ---- geometry --------------------------------------------------------------------
const dist = (a: XY, b: XY) => Math.hypot(a.x - b.x, a.y - b.y);

function distToSegment(p: XY, a: XY, b: XY): number {
  const dx = b.x - a.x, dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return dist(p, a);
  const k = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2));
  return dist(p, { x: a.x + k * dx, y: a.y + k * dy });
}

/** Extend segment a->b to the pane edges: forward only (ray) or both ways. */
function extend(a: XY, b: XY, w: number, h: number, both: boolean): [XY, XY] {
  const dx = b.x - a.x, dy = b.y - a.y;
  if (dx === 0 && dy === 0) return [a, b];
  const big = 4 * (w + h) / Math.max(1e-9, Math.hypot(dx, dy));
  const far = { x: a.x + dx * big, y: a.y + dy * big };
  const back = both ? { x: a.x - dx * big, y: a.y - dy * big } : a;
  return [back, far];
}

/** The pixel segments that make up a drawing (used for both rendering and hit-testing). */
export function segments(d: Drawing, xy: (XY | null)[], w: number, h: number): [XY, XY][] {
  const [a, b, c] = xy;
  if (!a) return [];
  switch (d.kind) {
    case "trend": case "arrow": case "measure": return b ? [[a, b]] : [];
    case "ray": return b ? [extend(a, b, w, h, false)] : [];
    case "extended": return b ? [extend(a, b, w, h, true)] : [];
    case "hline": return [[{ x: 0, y: a.y }, { x: w, y: a.y }]];
    case "hray": return [[a, { x: w, y: a.y }]];
    case "vline": return [[{ x: a.x, y: 0 }, { x: a.x, y: h }]];
    case "rect": {
      if (!b) return [];
      const p = [a, { x: b.x, y: a.y }, b, { x: a.x, y: b.y }];
      return p.map((q, i) => [q, p[(i + 1) % 4]] as [XY, XY]);
    }
    case "channel": {
      if (!b) return [];
      if (!c) return [[a, b]];
      const off = c.y - (a.y + (b.y - a.y) * ((c.x - a.x) / ((b.x - a.x) || 1e-9)));
      return [[a, b], [{ x: a.x, y: a.y + off }, { x: b.x, y: b.y + off }]];
    }
    case "fib": {
      if (!b) return [];
      return FIB_LEVELS.map((lv) => {
        const y = b.y + (a.y - b.y) * lv;
        return [{ x: Math.min(a.x, b.x), y }, { x: Math.max(a.x, b.x), y }] as [XY, XY];
      });
    }
    case "brush": {
      const out: [XY, XY][] = [];
      for (let i = 1; i < xy.length; i++) if (xy[i - 1] && xy[i]) out.push([xy[i - 1]!, xy[i]!]);
      return out;
    }
    case "text": return [];
  }
}

export type Hit = { id: string; handle: number | null };

export function hitTest(ds: Drawing[], m: Mapper, p: XY, w: number, h: number, selected: string | null): Hit | null {
  // handles of the selected drawing win
  const sel = ds.find((d) => d.id === selected);
  if (sel && sel.kind !== "brush") {
    const pts = sel.pts.map((q) => m.toXY(q));
    for (let i = 0; i < pts.length; i++) if (pts[i] && dist(pts[i]!, p) <= 7) return { id: sel.id, handle: i };
  }
  for (let k = ds.length - 1; k >= 0; k--) {
    const d = ds[k];
    if (d.hidden || d.kind === "measure") continue;
    const xy = d.pts.map((q) => m.toXY(q));
    if (d.kind === "text") {
      if (xy[0] && p.x >= xy[0].x - 4 && p.x <= xy[0].x + textWidth(d) + 8 && Math.abs(p.y - xy[0].y) <= 12) return { id: d.id, handle: null };
      continue;
    }
    if (d.kind === "rect" && xy[0] && xy[1]) {
      const [x0, x1] = [Math.min(xy[0].x, xy[1].x), Math.max(xy[0].x, xy[1].x)];
      const [y0, y1] = [Math.min(xy[0].y, xy[1].y), Math.max(xy[0].y, xy[1].y)];
      if (p.x >= x0 && p.x <= x1 && p.y >= y0 && p.y <= y1) return { id: d.id, handle: null };
    }
    if (segments(d, xy, w, h).some(([a, b]) => distToSegment(p, a, b) <= 5)) return { id: d.id, handle: null };
  }
  return null;
}

let measureCtx: CanvasRenderingContext2D | null = null;
function textWidth(d: Drawing): number {
  measureCtx ??= document.createElement("canvas").getContext("2d");
  if (!measureCtx) return 60;
  measureCtx.font = font(d);
  return measureCtx.measureText(d.text || "Text").width;
}
const font = (d: Drawing) => `${10 + d.width * 2}px Inter, Segoe UI, sans-serif`;

// ---- rendering -------------------------------------------------------------------
export interface RenderState {
  drawings: Drawing[];
  draft: Drawing | null;
  selected: string | null;
  hover: string | null;
  mapper: Mapper | null;
  fmt: (p: number) => string;
  barsBetween: (t1: number, t2: number) => number;
  textColor: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, s: RenderState) {
  const m = s.mapper;
  if (!m) return;
  const all = s.draft ? [...s.drawings, s.draft] : s.drawings;
  for (const d of all) {
    if (d.hidden) continue;
    const xy = d.pts.map((q) => m.toXY(q));
    const emph = d.id === s.selected || d.id === s.hover;
    ctx.save();
    ctx.strokeStyle = d.color;
    ctx.fillStyle = d.color;
    ctx.lineWidth = d.width + (emph && d.id !== s.selected ? 0.5 : 0);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    if (d.kind === "rect" && xy[0] && xy[1]) {
      ctx.globalAlpha = 0.12;
      ctx.fillRect(xy[0].x, xy[0].y, xy[1].x - xy[0].x, xy[1].y - xy[0].y);
      ctx.globalAlpha = 1;
    }
    if (d.kind === "channel" && xy[0] && xy[1] && xy[2]) {
      const [l1, l2] = segments(d, xy, w, h);
      ctx.globalAlpha = 0.1;
      ctx.beginPath();
      ctx.moveTo(l1[0].x, l1[0].y); ctx.lineTo(l1[1].x, l1[1].y); ctx.lineTo(l2[1].x, l2[1].y); ctx.lineTo(l2[0].x, l2[0].y);
      ctx.fill();
      ctx.globalAlpha = 1;
    }
    if (d.kind === "measure" && xy[0] && xy[1]) {
      drawMeasure(ctx, d, xy[0], xy[1], s);
      ctx.restore();
      continue;
    }

    if (d.kind === "fib" && xy[0] && xy[1]) {
      const segs = segments(d, xy, w, h);
      ctx.font = "11px Inter, Segoe UI, sans-serif";
      segs.forEach(([a, b], i) => {
        ctx.strokeStyle = FIB_COLORS[i];
        ctx.fillStyle = FIB_COLORS[i];
        line(ctx, a, b);
        const price = d.pts[1].p + (d.pts[0].p - d.pts[1].p) * FIB_LEVELS[i];
        ctx.fillText(`${FIB_LEVELS[i]} (${s.fmt(price)})`, a.x + 4, a.y - 3);
      });
      ctx.strokeStyle = d.color;
      ctx.setLineDash([4, 4]);
      line(ctx, xy[0], xy[1]);
      ctx.setLineDash([]);
    } else if (d.kind === "text" && xy[0]) {
      ctx.font = font(d);
      ctx.textBaseline = "middle";
      ctx.fillText(d.text || "Text", xy[0].x + 4, xy[0].y);
      if (d.id === s.selected) {
        ctx.setLineDash([3, 3]);
        ctx.lineWidth = 1;
        ctx.strokeRect(xy[0].x, xy[0].y - 11, textWidth(d) + 8, 22);
        ctx.setLineDash([]);
      }
    } else {
      for (const [a, b] of segments(d, xy, w, h)) line(ctx, a, b);
      if (d.kind === "arrow" && xy[0] && xy[1]) arrowHead(ctx, xy[0], xy[1], 8 + d.width * 2);
      if ((d.kind === "hline" || d.kind === "hray") && xy[0]) {
        priceTag(ctx, s.fmt(d.pts[0].p), w - 2, xy[0].y, d.color);
      }
    }

    if (d.id === s.selected && d.kind !== "brush") {
      for (const q of xy) if (q) handle(ctx, q, d.color);
    }
    ctx.restore();
  }
}

function line(ctx: CanvasRenderingContext2D, a: XY, b: XY) {
  ctx.beginPath();
  ctx.moveTo(a.x, a.y);
  ctx.lineTo(b.x, b.y);
  ctx.stroke();
}

function handle(ctx: CanvasRenderingContext2D, q: XY, color: string) {
  ctx.beginPath();
  ctx.arc(q.x, q.y, 5, 0, Math.PI * 2);
  ctx.fillStyle = "#ffffff";
  ctx.fill();
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = color;
  ctx.stroke();
}

function arrowHead(ctx: CanvasRenderingContext2D, a: XY, b: XY, size: number) {
  const ang = Math.atan2(b.y - a.y, b.x - a.x);
  ctx.beginPath();
  ctx.moveTo(b.x, b.y);
  ctx.lineTo(b.x - size * Math.cos(ang - 0.45), b.y - size * Math.sin(ang - 0.45));
  ctx.lineTo(b.x - size * Math.cos(ang + 0.45), b.y - size * Math.sin(ang + 0.45));
  ctx.closePath();
  ctx.fill();
}

function priceTag(ctx: CanvasRenderingContext2D, text: string, right: number, y: number, color: string) {
  ctx.font = "11px Inter, Segoe UI, sans-serif";
  const tw = ctx.measureText(text).width + 8;
  ctx.fillStyle = color;
  ctx.fillRect(right - tw, y - 8, tw, 16);
  ctx.fillStyle = "#ffffff";
  ctx.textBaseline = "middle";
  ctx.fillText(text, right - tw + 4, y);
}

function drawMeasure(ctx: CanvasRenderingContext2D, d: Drawing, a: XY, b: XY, s: RenderState) {
  const up = d.pts[1].p >= d.pts[0].p;
  const col = up ? "#2962ff" : "#f23645";
  ctx.fillStyle = col;
  ctx.globalAlpha = 0.15;
  ctx.fillRect(a.x, a.y, b.x - a.x, b.y - a.y);
  ctx.globalAlpha = 1;
  ctx.strokeStyle = col;
  ctx.lineWidth = 1;
  const midX = (a.x + b.x) / 2, midY = (a.y + b.y) / 2;
  line(ctx, { x: midX, y: a.y }, { x: midX, y: b.y });
  line(ctx, { x: a.x, y: midY }, { x: b.x, y: midY });
  arrowHead(ctx, { x: midX, y: a.y }, { x: midX, y: b.y }, 7);
  const diff = d.pts[1].p - d.pts[0].p;
  const pct = (100 * diff) / d.pts[0].p;
  const bars = s.barsBetween(d.pts[0].t, d.pts[1].t);
  const label = `${diff >= 0 ? "+" : ""}${s.fmt(diff)} (${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%) · ${bars} bars`;
  ctx.font = "12px Inter, Segoe UI, sans-serif";
  const tw = ctx.measureText(label).width + 12;
  const ly = up ? Math.min(a.y, b.y) - 26 : Math.max(a.y, b.y) + 6;
  ctx.fillStyle = col;
  ctx.fillRect(midX - tw / 2, ly, tw, 20);
  ctx.fillStyle = "#ffffff";
  ctx.textBaseline = "middle";
  ctx.fillText(label, midX - tw / 2 + 6, ly + 10);
}

/** Lightweight Charts series primitive that paints all drawings on top of the price pane. */
export class DrawingsPrimitive implements ISeriesPrimitive<Time> {
  private request: (() => void) | null = null;
  constructor(private state: () => RenderState) {}

  attached(p: { requestUpdate: () => void }) {
    this.request = p.requestUpdate;
  }
  detached() {
    this.request = null;
  }
  update() {
    this.request?.();
  }
  updateAllViews() {}

  paneViews(): readonly IPrimitivePaneView[] {
    const renderer: IPrimitivePaneRenderer = {
      draw: (target) => target.useMediaCoordinateSpace(({ context, mediaSize }) =>
        draw(context, mediaSize.width, mediaSize.height, this.state())),
    };
    return [{ zOrder: () => "top", renderer: () => renderer }];
  }
}

export const newId = () => Math.random().toString(36).slice(2, 10);
