// The market registry on the UI side: every exchange's time zone, session and currency, from GET /markets
// (backend/app/markets.toml). Code asks here instead of naming exchanges; a new market needs no UI change.
// The built-in copy below is used until the list arrives (and by the unit tests).

export interface MarketInfo {
  code: string;            // NSE, NYSE, ... (the prefix of a symbol: NSE:RELIANCE)
  title: string;
  country: string;
  timezone: string;        // IANA zone of intraday bars
  tz_label: string;        // how the chart names it ("IST", "New York")
  open: string;            // "09:15" local
  close: string;
  currency: string;        // ISO 4217
  screen: boolean;         // listed in the Pattern Screener
  order: number;
}

const m = (code: string, title: string, country: string, timezone: string, tz_label: string, open: string,
           close: string, currency: string, screen: boolean, order: number): MarketInfo =>
  ({ code, title, country, timezone, tz_label, open, close, currency, screen, order });

export const BUILT_IN: MarketInfo[] = [
  m("NSE", "National Stock Exchange of India", "IN", "Asia/Kolkata", "IST", "09:15", "15:30", "INR", true, 0),
  m("BSE", "BSE (Bombay Stock Exchange)", "IN", "Asia/Kolkata", "IST", "09:15", "15:30", "INR", false, 1),
  m("NYSE", "New York Stock Exchange", "US", "America/New_York", "New York", "09:30", "16:00", "USD", true, 2),
  m("NASDAQ", "Nasdaq", "US", "America/New_York", "New York", "09:30", "16:00", "USD", true, 3),
];

let list: MarketInfo[] = BUILT_IN;
let byCode = new Map(list.map((x) => [x.code, x]));

/** Use this list of markets (GET /markets); an empty or broken answer keeps the built-in one. */
export function setMarkets(ms: MarketInfo[]): void {
  if (!Array.isArray(ms) || !ms.length) return;
  list = [...ms].sort((a, b) => a.order - b.order);
  byCode = new Map(list.map((x) => [x.code, x]));
}

/** Load the registry once, before the first render. */
export async function loadMarkets(api = "/api"): Promise<void> {
  try {
    const r = await fetch(`${api}/markets`);
    if (r.ok) setMarkets(await r.json());
  } catch {
    /* keep the built-in list */
  }
}

/** Every market, in display order (the first is the default). */
export const markets = (): MarketInfo[] => list;

/** A market by code or symbol ("NSE" or "NSE:RELIANCE"); unknown = the default market. */
export function marketOf(codeOrSymbol: string): MarketInfo {
  return byCode.get(codeOrSymbol.split(":")[0].toUpperCase()) ?? list[0];
}

export const currencyOf = (codeOrSymbol: string): string => marketOf(codeOrSymbol).currency;

/** The currency's sign: ₹, $, £, € ... (from the browser's own currency data). */
export function currencySymbol(currency: string): string {
  try {
    return new Intl.NumberFormat("en", { style: "currency", currency, currencyDisplay: "narrowSymbol" })
      .formatToParts(0).find((p) => p.type === "currency")?.value ?? currency;
  } catch {
    return currency;
  }
}

/** A full amount in a currency: ₹4,16,533 (Indian grouping for rupees), $416,533, £1,250. */
export function money(v: number, currency: string): string {
  const locale = currency === "INR" ? "en-IN" : "en-US";
  return `${currencySymbol(currency)}${Math.round(v).toLocaleString(locale)}`;
}

/** Large amounts (turnover): crore for rupees, millions otherwise. `unit` = the amount of one step. */
export function bigUnit(currency: string): { unit: number; label: string } {
  return currency === "INR" ? { unit: 1e7, label: "₹ Cr" } : { unit: 1e6, label: `${currencySymbol(currency)}M` };
}

/** `v` in big units: ₹12.5 Cr, $3.2M. */
export function bigMoney(v: number, currency: string): string {
  const { unit } = bigUnit(currency);
  const n = (v / unit).toFixed(v >= unit * 100 ? 0 : 1);
  return currency === "INR" ? `₹${n} Cr` : `${currencySymbol(currency)}${n}M`;
}

const offsetCache = new Map<string, number>();
const partsFmt = new Map<string, Intl.DateTimeFormat>();

/** Seconds east of UTC in time zone `tz` on the UTC day of t (DST switches happen at night, outside sessions). */
export function tzOffset(tz: string, t: number): number {
  const day = Math.floor(t / 86400);
  const key = `${tz}|${day}`;
  let off = offsetCache.get(key);
  if (off === undefined) {
    let f = partsFmt.get(tz);
    if (!f) {
      f = new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit",
        day: "2-digit", hour: "2-digit", minute: "2-digit" });
      partsFmt.set(tz, f);
    }
    const noon = day * 86400 + 43200;
    const p = Object.fromEntries(f.formatToParts(new Date(noon * 1000)).map((x) => [x.type, x.value]));
    off = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute) / 1000 - noon;
    offsetCache.set(key, off);
  }
  return off;
}
