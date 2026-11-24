import { describe, expect, it } from "vitest";
import { fmt, fmtVol } from "../../src/format";

describe("formatting", () => {
  it("prices use Indian digit grouping and 2 decimals; missing values show a dash", () => {
    expect(fmt(123456.7)).toBe("1,23,456.70");
    expect(fmt(0)).toBe("0.00");
    expect(fmt(null)).toBe("—");
    expect(fmt(undefined)).toBe("—");
  });
  it("volumes use crore / lakh / thousand", () => {
    expect(fmtVol(25_000_000)).toBe("2.50Cr");
    expect(fmtVol(150_000)).toBe("1.50L");
    expect(fmtVol(2_500)).toBe("2.5K");
    expect(fmtVol(999)).toBe("999");
  });
});
