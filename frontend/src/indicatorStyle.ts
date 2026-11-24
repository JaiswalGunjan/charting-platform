import type { IndicatorMeta } from "./api";

export interface ActiveIndicator {
  key: string; // unique per instance (two EMAs with different lengths)
  id: string;
  params: Record<string, number>;
}

interface OutStyle {
  color?: string;
  width?: 1 | 2 | 3 | 4;
  histogram?: boolean;
  hidden?: boolean;
}

const STYLES: Record<string, Record<string, OutStyle>> = {
  bb: { mid: { color: "#f0a43a" }, upper: { color: "#5b8def" }, lower: { color: "#5b8def" } },
  vwap: { vwap: { color: "#c678dd", width: 2 } },
  supertrend: { line: { width: 2 }, direction: { hidden: true } },
  rsi: { rsi: { color: "#c678dd" } },
  macd: { macd: { color: "#5b8def" }, signal: { color: "#f0a43a" }, hist: { histogram: true } },
  atr: { atr: { color: "#e06c75" } },
  stoch: { k: { color: "#5b8def" }, d: { color: "#f0a43a" } },
  obv: { obv: { color: "#56b6c2" } },
};

// moving averages cycle through these so several MAs stay distinguishable
const MA_COLORS = ["#f0a43a", "#5b8def", "#c678dd", "#56b6c2", "#e5c07b", "#98c379"];
let maCounter = 0;
const maColor = new Map<string, string>();

export function outputStyle(id: string, out: string, key?: string): OutStyle {
  const s = STYLES[id]?.[out];
  if (s) return s;
  const k = key ?? id;
  if (!maColor.has(k)) maColor.set(k, MA_COLORS[maCounter++ % MA_COLORS.length]);
  return { color: maColor.get(k), width: 2 };
}

export function indicatorLabel(ind: ActiveIndicator, meta?: IndicatorMeta): string {
  const name = meta?.title ?? ind.id.toUpperCase();
  const ps = Object.values(ind.params);
  return ps.length ? `${name} (${ps.join(", ")})` : name;
}

export function newIndicator(meta: IndicatorMeta): ActiveIndicator {
  return {
    key: `${meta.id}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
    id: meta.id,
    params: Object.fromEntries(meta.params.map((p) => [p.name, p.default])),
  };
}
