// Bar times -> chart axis times. Lightweight Charts renders UTC, so epoch seconds are shifted to read in
// exchange time: IST for NSE/BSE, New York (DST-aware) for US intraday bars. Daily and longer bars are
// stamped at IST midnight of their trading date for every exchange, so they always shift by IST.
export const IST = 19800;
const US = new Set(["NASDAQ", "NYSE"]);
const DAILY = new Set(["1D", "1W", "1M", "1Y"]);

const nyParts = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York", hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit",
});
const nyCache = new Map<number, number>();

/** Seconds east of UTC in New York on the UTC day of t (DST switches happen on Sunday nights). */
export function nyOffset(t: number): number {
  const day = Math.floor(t / 86400);
  let off = nyCache.get(day);
  if (off === undefined) {
    const noon = day * 86400 + 43200;
    const p = Object.fromEntries(nyParts.formatToParts(new Date(noon * 1000)).map((x) => [x.type, x.value]));
    off = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute) / 1000 - noon;
    nyCache.set(day, off);
  }
  return off;
}

export function exchangeTimeZone(symbol: string, tf: string): "IST" | "New York" {
  return US.has(symbol.split(":")[0]) && !DAILY.has(tf) ? "New York" : "IST";
}

/** The shift (seconds) to add to a bar time for display on this symbol/timeframe's chart. */
export function shiftFor(symbol: string, tf: string): (t: number) => number {
  return exchangeTimeZone(symbol, tf) === "New York" ? nyOffset : () => IST;
}
