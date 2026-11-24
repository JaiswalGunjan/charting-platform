import { describe, expect, it } from "vitest";
import { exchangeTimeZone, IST, nyOffset, shiftFor } from "../../src/time";

const utc = (y: number, mo: number, d: number, h = 0, mi = 0) => Date.UTC(y, mo - 1, d, h, mi) / 1000;

describe("New York offset", () => {
  it("is -4h in summer (EDT) and -5h in winter (EST)", () => {
    expect(nyOffset(utc(2026, 7, 1, 13, 30))).toBe(-4 * 3600);
    expect(nyOffset(utc(2026, 12, 1, 14, 30))).toBe(-5 * 3600);
  });
  it("switches on the DST weekends", () => {
    expect(nyOffset(utc(2026, 3, 6, 15))).toBe(-5 * 3600);   // Fri before the 8 Mar 2026 switch
    expect(nyOffset(utc(2026, 3, 9, 15))).toBe(-4 * 3600);   // Mon after
    expect(nyOffset(utc(2026, 10, 30, 15))).toBe(-4 * 3600); // Fri before the 1 Nov 2026 switch
    expect(nyOffset(utc(2026, 11, 2, 15))).toBe(-5 * 3600);  // Mon after
  });
});

describe("exchange time zone", () => {
  it("US intraday charts read in New York time, everything else in IST", () => {
    expect(exchangeTimeZone("NASDAQ:AAPL", "1h")).toBe("New York");
    expect(exchangeTimeZone("NYSE:BRK.B", "5m")).toBe("New York");
    for (const tf of ["1D", "1W", "1M", "1Y"]) expect(exchangeTimeZone("NASDAQ:AAPL", tf)).toBe("IST");
    expect(exchangeTimeZone("NSE:RELIANCE", "1h")).toBe("IST");
    expect(exchangeTimeZone("BSE:RELIANCE", "1D")).toBe("IST");
  });
  it("a 09:30 New York bar shows at 09:30 on the axis; a daily bar at midnight of its own date", () => {
    const bar = utc(2026, 7, 1, 13, 30);
    const shown = new Date((bar + shiftFor("NASDAQ:AAPL", "1h")(bar)) * 1000);
    expect([shown.getUTCHours(), shown.getUTCMinutes()]).toEqual([9, 30]);
    const daily = utc(2026, 7, 1) - IST; // stored daily bar: IST midnight of 1 Jul
    const d = new Date((daily + shiftFor("NASDAQ:AAPL", "1D")(daily)) * 1000);
    expect([d.getUTCDate(), d.getUTCHours()]).toEqual([1, 0]);
  });
});
