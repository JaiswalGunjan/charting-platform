import { describe, expect, it } from "vitest";
import { scanFor, scoreAttributes } from "../../src/ScannerPanel";

// saved scans, newest first (as GET /scanner lists them)
const scans = [
  { id: "NSE_daily_2026-11-23", market: "NSE", date: "2026-11-23" },
  { id: "NYSE_daily_2026-11-20", market: "NYSE", date: "2026-11-20" },
  { id: "NSE_daily_2026-11-20", market: "NSE", date: "2026-11-20" },
];
// the scanner's data sessions for NSE (it has 24 Nov data that is not scanned yet)
const sessions = ["2026-11-24", "2026-11-23", "2026-11-20", "2026-11-19"];

describe("which saved scan a date shows (and whether it can be run)", () => {
  it("no date: the newest scan of the market", () => {
    expect(scanFor(scans, "NSE", "")?.id).toBe("NSE_daily_2026-11-23");
    expect(scanFor(scans, "NYSE", "")?.id).toBe("NYSE_daily_2026-11-20");
    expect(scanFor(scans, "NASDAQ", "")).toBeNull();
  });
  it("a saved session shows its own scan", () => {
    expect(scanFor(scans, "NSE", "2026-11-20", sessions)?.id).toBe("NSE_daily_2026-11-20");
  });
  it("a data session without a scan is not scanned (the run button), not the scan before it", () => {
    expect(scanFor(scans, "NSE", "2026-11-24", sessions)).toBeNull();
    expect(scanFor(scans, "NSE", "2026-11-19", sessions)).toBeNull();
  });
  it("a weekend or holiday shows the scan of the session before it (within 4 days)", () => {
    expect(scanFor(scans, "NSE", "2026-11-22", sessions)?.id).toBe("NSE_daily_2026-11-20");
    expect(scanFor(scans, "NSE", "2026-11-28", sessions)).toBeNull();          // too far from any scan
  });
});

describe("score attributes: names only", () => {
  const note = "Score = the backtester's priority score (rules/priority.py): cycle phase x 0.8 + setup weight (VCP 1.0, " +
    "HTF/TL3 0.9, CWH/1-2-3/oversold 0.8) + pocket pivots in the pattern x 0.15 + closeness to the 10-day high + tight " +
    "stop + relative strength + OBV high, minus 0.25 per soft miss. Higher = entered first; it is not a probability.";
  it("lists the attributes without weights, multipliers or the source file", () => {
    expect(scoreAttributes(note)).toEqual(["Cycle phase", "Setup weight", "Pocket pivots in the pattern",
      "Closeness to the 10-day high", "Tight stop", "Relative strength", "OBV high", "Soft misses (lower the score)"]);
    expect(scoreAttributes(note).join(" ")).not.toMatch(/\d\.\d|priority\.py|rules\//);
  });
});
