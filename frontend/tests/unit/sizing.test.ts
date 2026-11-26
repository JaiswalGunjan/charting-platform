import { describe, expect, it } from "vitest";
import { dollars, lakhs, positionSize, rupees } from "../../src/sizing";

// MARICO BBR on 23 Nov 2026 in the scanner's report: entry 919.50, stop 891.91, 1% risk x 0.5 market multiplier
const marico = { entry: 919.5, stop: 891.91, riskPct: 1, riskMult: 0.5 };

describe("position size (the scanner's rule)", () => {
  it("matches the scanner's report at its Rs 10 lakh capital", () => {
    const s = positionSize({ ...marico, equity: 1_000_000 });
    expect(s.shares).toBe(181);
    expect(s.value).toBeCloseTo(166429.5, 2);
    expect(s.pctOfEquity).toBeCloseTo(16.6, 1);
    expect(s.atRisk).toBe(5000);
    expect(s.lossAtStop).toBeCloseTo(4993.79, 2);
    expect(s.sizedBy).toBe("risk");
  });
  it("scales with the equity", () => {
    expect(positionSize({ ...marico, equity: 2_500_000 }).shares).toBe(453);
    expect(positionSize({ ...marico, equity: 100_000 }).shares).toBe(18);
  });
  it("caps one position at 45% of equity", () => {
    const s = positionSize({ equity: 1_000_000, entry: 100, stop: 99.5, riskPct: 1, riskMult: 1 });
    expect(s.shares).toBe(4500);            // risk alone would allow 20,000 shares
    expect(s.sizedBy).toBe("max allocation");
  });
  it("applies the setup multiplier and refuses a stop at or above the entry", () => {
    expect(positionSize({ ...marico, equity: 1_000_000, sizeMult: 0.5 }).shares).toBe(90);
    expect(positionSize({ ...marico, equity: 1_000_000, stop: 919.5 }).shares).toBe(0);
  });
});

describe("amounts in lakh / crore", () => {
  it("formats", () => {
    expect(lakhs(1_000_000)).toBe("₹10 L");
    expect(lakhs(2_550_000)).toBe("₹25.5 L");
    expect(lakhs(25_000_000)).toBe("₹2.5 Cr");
    expect(lakhs(50_000)).toBe("₹50,000");
  });
});

describe("dollars (US portfolio)", () => {
  it("formats whole dollars and millions", () => {
    expect(dollars(100_000)).toBe("$100,000");
    expect(dollars(33_120.4)).toBe("$33,120");
    expect(dollars(1_250_000)).toBe("$1,250,000");                    // the full amount, like rupees
    expect(rupees(416_533.4)).toBe("₹4,16,533");
    expect(rupees(1_000_000)).toBe("₹10,00,000");
    expect(dollars(0)).toBe("$0");
  });
});
