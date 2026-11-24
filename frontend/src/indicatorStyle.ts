import type { IndicatorMeta, PlotStyle } from "./api";

export interface PlotOverride {
  color?: string;
  width?: 1 | 2 | 3 | 4;
  hidden?: boolean;
}

export interface ActiveIndicator {
  key: string; // unique per instance (two EMAs with different lengths)
  id: string;
  params: Record<string, number | string>;
  style?: Record<string, PlotOverride>; // per-output overrides from the settings dialog
  hidden?: boolean; // whole indicator toggled off from its legend chip
}

export interface ResolvedStyle {
  style: PlotStyle;
  color: string;
  width: 1 | 2 | 3 | 4;
}

// single-line indicators without a fixed colour (moving averages) cycle through these
// per instance, so several MAs on one chart stay distinguishable
const CYCLE = ["#ff9800", "#2962ff", "#9c27b0", "#00acc1", "#fbc02d", "#43a047", "#e91e63", "#795548"];
let counter = 0;
const assigned = new Map<string, string>();

function cycled(key: string): string {
  if (!assigned.has(key)) assigned.set(key, CYCLE[counter++ % CYCLE.length]);
  return assigned.get(key)!;
}

export function plotStyle(ind: ActiveIndicator, meta: IndicatorMeta, out: string): ResolvedStyle {
  const p = meta.plots.find((x) => x.name === out);
  const o = ind.style?.[out] ?? {};
  const idx = meta.plots.findIndex((x) => x.name === out);
  const base = p?.color ?? (idx <= 0 ? cycled(ind.key) : CYCLE[(idx + 1) % CYCLE.length]);
  const style: PlotStyle = o.hidden ? "hidden" : p?.style ?? "line";
  const defaultWidth = meta.overlay && meta.plots.length === 1 ? 2 : 1;
  return { style, color: o.color ?? base, width: o.width ?? defaultWidth };
}

const fmtParam = (v: number | string) => (typeof v === "number" ? String(+v.toFixed(4)) : v);

export function indicatorLabel(ind: ActiveIndicator, meta?: IndicatorMeta): string {
  const name = meta?.title ?? ind.id.toUpperCase();
  const ps = (meta?.params ?? []).map((p) => ind.params[p.name] ?? p.default)
    .filter((v) => v !== "close") // the default source is implied
    .map(fmtParam);
  return ps.length ? `${name} (${ps.join(", ")})` : name;
}

export function newIndicator(meta: IndicatorMeta): ActiveIndicator {
  return {
    key: `${meta.id}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
    id: meta.id,
    params: Object.fromEntries(meta.params.map((p) => [p.name, p.default])),
  };
}
