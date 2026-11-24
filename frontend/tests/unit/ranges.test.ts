import { describe, expect, it } from "vitest";
import { RANGES, rangeStart, timeframeForRange } from "../../src/ranges";

const IST = 19800;
/** epoch seconds of IST midnight of y-m-d */
const istDay = (y: number, m: number, d: number) => Date.UTC(y, m - 1, d) / 1000 - IST;
/** a bar time during the IST trading day y-m-d (11:00 IST) */
const istBar = (y: number, m: number, d: number) => istDay(y, m, d) + 11 * 3600;

describe("rangeStart", () => {
  const anchor = istBar(2026, 11, 24);
  it.each([
    ["1D", istDay(2026, 11, 24)],
    ["5D", istDay(2026, 11, 18)],
    ["1M", istDay(2026, 10, 24)],
    ["3M", istDay(2026, 8, 24)],
    ["6M", istDay(2026, 5, 24)],
    ["YTD", istDay(2026, 1, 1)],
    ["1Y", istDay(2025, 11, 24)],
    ["3Y", istDay(2023, 11, 24)],
    ["5Y", istDay(2021, 11, 24)],
    ["10Y", istDay(2016, 11, 24)],
  ] as const)("%s starts at IST midnight of the right day", (id, want) => {
    expect(rangeStart(id, anchor)).toBe(want);
  });

  it("All means the whole history", () => expect(rangeStart("All", anchor)).toBe(0));

  it("uses the IST date even when the UTC date is the day before", () => {
    // 2026-11-24 00:30 IST = 2026-11-23 19:00 UTC
    expect(rangeStart("1D", istDay(2026, 11, 24) + 1800)).toBe(istDay(2026, 11, 24));
  });

  it("month ranges clamp to the end of a shorter month (31 Mar - 1M = 28 Feb, not 3 Mar)", () => {
    expect(rangeStart("1M", istBar(2026, 3, 31))).toBe(istDay(2026, 2, 28));
    expect(rangeStart("3M", istBar(2026, 5, 31))).toBe(istDay(2026, 2, 28));
    expect(rangeStart("6M", istBar(2026, 8, 31))).toBe(istDay(2026, 2, 28));
    expect(rangeStart("1Y", istBar(2028, 2, 29))).toBe(istDay(2027, 2, 28));
  });

  it("every preset is earlier than the anchor and longer presets reach further back", () => {
    const starts = RANGES.filter((r) => r !== "YTD").map((r) => rangeStart(r, anchor));
    for (let i = 1; i < starts.length; i++) expect(starts[i]).toBeLessThan(starts[i - 1]);
    for (const s of starts) expect(s).toBeLessThan(anchor);
  });
});

describe("timeframeForRange", () => {
  it("keeps the current timeframe when it shows the range sensibly", () => {
    expect(timeframeForRange("1Y", "1D", "1m")).toBe("1D");
    expect(timeframeForRange("3M", "1D", "1h")).toBe("1D");
    expect(timeframeForRange("1M", "1h", "1h")).toBe("1h");
  });
  it("switches to a natural timeframe when there would be too few or too many bars", () => {
    expect(timeframeForRange("5D", "1D", "1m")).toBe("15m");
    expect(timeframeForRange("1D", "1D", "1m")).toBe("5m");
    expect(timeframeForRange("10Y", "1D", "1m")).toBe("1M");
    expect(timeframeForRange("5Y", "15m", "1m")).toBe("1W");
  });
  it("never picks minute bars when only hourly history is stored", () => {
    expect(timeframeForRange("5D", "1D", "1h")).toBe("1h");
    expect(timeframeForRange("1D", "1D", "1h")).toBe("1h");
    expect(timeframeForRange("1M", "5m", "1h")).toBe("1h");
  });
  it("All always shows monthly bars", () => {
    for (const tf of ["1m", "1h", "1D", "1W", "1M"]) expect(timeframeForRange("All", tf, "1m")).toBe("1M");
  });
});
