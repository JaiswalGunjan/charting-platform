// Bar times -> chart axis times. Lightweight Charts renders UTC, so epoch seconds are shifted to read in
// exchange time: each market's own time zone for intraday bars (DST-aware; from the market registry). Daily and longer bars are
// stamped at IST midnight of their trading date for every exchange, so they always shift by IST.
import { marketOf, tzOffset } from "./markets";

export const IST = 19800;
const DAILY = new Set(["1D", "1W", "1M", "1Y"]);

/** Seconds east of UTC in New York on the UTC day of t (DST switches happen on Sunday nights). */
export const nyOffset = (t: number): number => tzOffset("America/New_York", t);

/** The time zone a chart's times are in: the market's own for intraday bars, IST for daily and longer bars (their
 * stamps encode the trading date at IST midnight, for every market). */
export function exchangeTimeZone(symbol: string, tf: string): string {
  return DAILY.has(tf) ? "IST" : marketOf(symbol).tz_label;
}

/** The shift (seconds) to add to a bar time for display on this symbol/timeframe's chart. */
export function shiftFor(symbol: string, tf: string): (t: number) => number {
  const tz = marketOf(symbol).timezone;
  if (DAILY.has(tf) || tz === "Asia/Kolkata") return () => IST;
  return (t: number) => tzOffset(tz, t);
}
