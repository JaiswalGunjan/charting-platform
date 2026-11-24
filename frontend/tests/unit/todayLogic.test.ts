import { describe, expect, it } from "vitest";
import type { TodayRow } from "../../src/api";
import { liquidRows, matchRows, nextSort, patternCounts, sortRows, turnoverText, turnoverUnit } from "../../src/todayLogic";

const row = (ticker: string, patterns: string[], extra: Partial<TodayRow> = {}): TodayRow => ({
  symbol: `NSE:${ticker}`, ticker, name: `${ticker} Limited`, type: "EQ", close: 100, change_pct: 1, volume: 1000,
  turnover: 5e7, patterns, hits: patterns.map((p) => ({ pattern: p, text: p.toUpperCase(), notes: [] })), ...extra,
});

const rows: TodayRow[] = [
  row("AAA", ["pp", "bbr"], { close: 50, change_pct: 2.5, turnover: 9e8, name: "Zeta Industries" }),
  row("BBB", ["pp"], { close: 300, change_pct: -1, turnover: 2e7, name: "Alpha Motors" }),
  row("CCC", ["pp", "bbr", "tl3"], { close: 120, change_pct: 0.5, turnover: 4e8, name: "Mid Corp" }),
  row("DDD", ["cic"], { close: 80, change_pct: null, turnover: 1e6, name: "Small Ltd" }),
];

describe("AND filter (several selected patterns)", () => {
  it("shows every stock when nothing is selected", () => {
    expect(matchRows(rows, []).map((r) => r.ticker)).toEqual(["AAA", "BBB", "CCC", "DDD"]);
  });
  it("one pattern: stocks that formed it", () => {
    expect(matchRows(rows, ["pp"]).map((r) => r.ticker)).toEqual(["AAA", "BBB", "CCC"]);
  });
  it("two or more: only stocks that formed ALL of them (never any-of)", () => {
    expect(matchRows(rows, ["pp", "bbr"]).map((r) => r.ticker)).toEqual(["AAA", "CCC"]);
    expect(matchRows(rows, ["pp", "bbr", "tl3"]).map((r) => r.ticker)).toEqual(["CCC"]);
    expect(matchRows(rows, ["pp", "cic"])).toEqual([]);
  });
  it("search narrows by symbol or company name, case-insensitively", () => {
    expect(matchRows(rows, ["pp"], "alpha").map((r) => r.ticker)).toEqual(["BBB"]);
    expect(matchRows(rows, [], " ccc ").map((r) => r.ticker)).toEqual(["CCC"]);
  });
});

describe("counts on the pattern cards", () => {
  it("with no selection: how many stocks formed each pattern", () => {
    expect(patternCounts(rows, [])).toEqual({ pp: 3, bbr: 2, tl3: 1, cic: 1 });
  });
  it("with a selection: how many would remain if the pattern were ticked as well", () => {
    // pp selected: bbr together with pp -> AAA, CCC; cic never forms with pp -> no entry (shown as 0)
    expect(patternCounts(rows, ["pp"])).toEqual({ pp: 3, bbr: 2, tl3: 1 });
    // the count of an already selected pattern equals the stocks shown
    const c = patternCounts(rows, ["pp", "bbr"]);
    expect(c.pp).toBe(matchRows(rows, ["pp", "bbr"]).length);
    expect(c.tl3).toBe(1);
  });
  it("respects the search box", () => {
    expect(patternCounts(rows, [], "zeta")).toEqual({ pp: 1, bbr: 1 });
  });
});

describe("minimum turnover", () => {
  it("is in crore for Indian exchanges and $ millions for US ones", () => {
    expect(turnoverUnit("NSE")).toBe(1e7);
    expect(turnoverUnit("BSE")).toBe(1e7);
    expect(turnoverUnit("NASDAQ")).toBe(1e6);
    expect(liquidRows(rows, 1, "NSE").map((r) => r.ticker)).toEqual(["AAA", "BBB", "CCC"]);   // >= Rs 1 Cr
    expect(liquidRows(rows, 50, "NSE").map((r) => r.ticker)).toEqual(["AAA"]);               // >= Rs 50 Cr
    expect(liquidRows(rows, 0, "NSE")).toHaveLength(4);
    expect(liquidRows(rows, 1, "NYSE").map((r) => r.ticker)).toEqual(["AAA", "BBB", "CCC", "DDD"]); // >= $1M
  });
  it("is formatted per market", () => {
    expect(turnoverText(4.25e8, "NSE")).toBe("₹42.5 Cr");
    expect(turnoverText(9e9, "NSE")).toBe("₹900 Cr");
    expect(turnoverText(2.5e6, "NASDAQ")).toBe("$2.5M");
    expect(turnoverText(3e8, "NYSE")).toBe("$300M");
  });
});

describe("sorting", () => {
  const t = (s: Parameters<typeof sortRows>[1]) => sortRows(rows, s).map((r) => r.ticker);
  it("sorts by every column in both directions", () => {
    expect(t({ key: "ticker", dir: 1 })).toEqual(["AAA", "BBB", "CCC", "DDD"]);
    expect(t({ key: "ticker", dir: -1 })).toEqual(["DDD", "CCC", "BBB", "AAA"]);
    expect(t({ key: "name", dir: 1 })).toEqual(["BBB", "CCC", "DDD", "AAA"]);   // Alpha, Mid, Small, Zeta
    expect(t({ key: "close", dir: -1 })).toEqual(["BBB", "CCC", "DDD", "AAA"]);
    expect(t({ key: "turnover", dir: -1 })).toEqual(["AAA", "CCC", "BBB", "DDD"]);
    expect(t({ key: "change_pct", dir: -1 })).toEqual(["AAA", "CCC", "BBB", "DDD"]); // a missing change sorts last
  });
  it("the patterns column sorts by how many patterns formed; ties go to the more liquid stock", () => {
    expect(t({ key: "patterns", dir: -1 })).toEqual(["CCC", "AAA", "BBB", "DDD"]);  // 3, 2, 1 (2e7), 1 (1e6)
    expect(t({ key: "patterns", dir: 1 })).toEqual(["BBB", "DDD", "AAA", "CCC"]);
  });
  it("does not change the input order", () => {
    sortRows(rows, { key: "ticker", dir: -1 });
    expect(rows.map((r) => r.ticker)).toEqual(["AAA", "BBB", "CCC", "DDD"]);
  });
  it("a header click flips the same column, a new column starts at its natural direction", () => {
    expect(nextSort({ key: "close", dir: -1 }, "close", -1)).toEqual({ key: "close", dir: 1 });
    expect(nextSort({ key: "close", dir: 1 }, "close", -1)).toEqual({ key: "close", dir: -1 });
    expect(nextSort({ key: "close", dir: 1 }, "ticker", 1)).toEqual({ key: "ticker", dir: 1 });
  });
});
