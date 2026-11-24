// Date-range presets (1D ... All) and the timeframe each one is best viewed in.

export const RANGES = ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "10Y", "All"] as const;
export type RangeId = (typeof RANGES)[number];

const IST = 19800;

/** Start (epoch s) of the range that ends at `anchor` (the last bar), in IST calendar terms. */
export function rangeStart(id: RangeId, anchor: number): number {
  if (id === "All") return 0;
  const d = new Date((anchor + IST) * 1000); // UTC fields of d now read as IST wall time
  d.setUTCHours(0, 0, 0, 0);
  switch (id) {
    case "1D": break;
    case "5D": d.setUTCDate(d.getUTCDate() - 6); break;
    case "1M": d.setUTCMonth(d.getUTCMonth() - 1); break;
    case "3M": d.setUTCMonth(d.getUTCMonth() - 3); break;
    case "6M": d.setUTCMonth(d.getUTCMonth() - 6); break;
    case "YTD": d.setUTCMonth(0, 1); break;
    case "1Y": d.setUTCFullYear(d.getUTCFullYear() - 1); break;
    case "3Y": d.setUTCFullYear(d.getUTCFullYear() - 3); break;
    case "5Y": d.setUTCFullYear(d.getUTCFullYear() - 5); break;
    case "10Y": d.setUTCFullYear(d.getUTCFullYear() - 10); break;
  }
  return d.getTime() / 1000 - IST;
}

const SPAN_DAYS: Record<RangeId, number> = {
  "1D": 1, "5D": 7, "1M": 30, "3M": 91, "6M": 182, YTD: 182, "1Y": 365, "3Y": 1095, "5Y": 1826, "10Y": 3652, All: 5000,
};

const MINUTES: Record<string, number> = { "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240 };

/** Rough number of bars a range spans in a timeframe (NSE: 375-minute sessions, 5 days a week). */
function estimateBars(tf: string, days: number): number {
  const sessions = days * 5 / 7;
  if (tf in MINUTES) return sessions * Math.ceil(375 / MINUTES[tf]);
  return { "1D": sessions, "1W": days / 7, "1M": days / 30.4, "1Y": days / 365 }[tf] ?? sessions;
}

/** Keep the current timeframe when it shows the range sensibly, otherwise switch to a natural one. */
export function timeframeForRange(id: RangeId, current: string, intraday: "1m" | "1h"): string {
  const n = estimateBars(current, SPAN_DAYS[id]);
  const intradayOk = intraday === "1m" || !(current in MINUTES) || MINUTES[current] >= 60;
  if (n >= 15 && n <= 1000 && intradayOk && id !== "All") return current;
  const fine = intraday === "1m";
  const pick: Record<RangeId, string> = {
    "1D": fine ? "5m" : "1h", "5D": fine ? "15m" : "1h", "1M": "1h", "3M": "1D", "6M": "1D", YTD: "1D",
    "1Y": "1D", "3Y": "1W", "5Y": "1W", "10Y": "1M", All: "1M",
  };
  return pick[id];
}
