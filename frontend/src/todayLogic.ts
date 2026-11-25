// Pure logic of the Pattern Screener dashboard (kept out of the component so it is unit-tested).
import type { TodayRow } from "./api";

export type SortKey = "ticker" | "name" | "close" | "change_pct" | "turnover" | "patterns";
export interface Sort { key: SortKey; dir: 1 | -1 }

const US = new Set(["NASDAQ", "NYSE"]);

/** Turnover in crore (India) or millions of dollars (US). */
export const turnoverText = (v: number, exchange: string) =>
  US.has(exchange) ? `$${(v / 1e6).toFixed(v >= 1e8 ? 0 : 1)}M` : `₹${(v / 1e7).toFixed(v >= 1e9 ? 0 : 1)} Cr`;

/** The minimum-turnover box is in crore for Indian exchanges and in $ millions for US ones. */
export const turnoverUnit = (exchange: string) => (US.has(exchange) ? 1e6 : 1e7);

export function liquidRows(rows: TodayRow[], minTurnover: number, exchange: string): TodayRow[] {
  const floor = minTurnover * turnoverUnit(exchange);
  return rows.filter((r) => r.turnover >= floor);
}

const matchesSearch = (r: TodayRow, q: string) => {
  const ql = q.trim().toLowerCase();
  return !ql || r.ticker.toLowerCase().includes(ql) || r.name.toLowerCase().includes(ql);
};

/** AND: a stock is shown only if it formed every selected pattern on its latest bar (no selection = all). */
export function matchRows(rows: TodayRow[], selected: Iterable<string>, q = ""): TodayRow[] {
  const sel = [...selected];
  return rows.filter((r) => matchesSearch(r, q) && sel.every((p) => r.patterns.includes(p)));
}

/** Per pattern: how many stocks would remain if it were ticked together with the other selected patterns. */
export function patternCounts(rows: TodayRow[], selected: Iterable<string>, q = ""): Record<string, number> {
  const sel = [...selected];
  const counts: Record<string, number> = {};
  for (const r of rows) {
    if (!matchesSearch(r, q)) continue;
    for (const p of r.patterns) {
      if (sel.every((x) => x === p || r.patterns.includes(x))) counts[p] = (counts[p] ?? 0) + 1;
    }
  }
  return counts;
}

/** Sort by a column; "patterns" sorts by how many patterns formed. Ties: the more liquid stock first. */
export function sortRows(rows: TodayRow[], s: Sort): TodayRow[] {
  const val = (r: TodayRow): number | string =>
    s.key === "patterns" ? r.patterns.length : s.key === "ticker" ? r.ticker : s.key === "name" ? r.name.toLowerCase()
      : (r[s.key] ?? -Infinity);
  return [...rows].sort((a, b) => {
    const x = val(a);
    const y = val(b);
    const c = typeof x === "string" ? x.localeCompare(String(y)) : (x as number) - (y as number);
    return c !== 0 ? c * s.dir : b.turnover - a.turnover;
  });
}

/** Clicking a column header: same column flips the direction, a new column starts at its natural direction. */
export const nextSort = (cur: Sort, key: SortKey, first: 1 | -1): Sort =>
  cur.key === key ? { key, dir: (cur.dir * -1) as 1 | -1 } : { key, dir: first };
