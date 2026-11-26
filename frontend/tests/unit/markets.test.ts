import { afterEach, describe, expect, it } from "vitest";
import { BUILT_IN, bigMoney, currencyOf, marketOf, markets, money, setMarkets, tzOffset } from "../../src/markets";
import { exchangeTimeZone, IST, shiftFor } from "../../src/time";
import { turnoverLabel, turnoverText, turnoverUnit } from "../../src/todayLogic";

const LSE = { code: "LSE", title: "London Stock Exchange", country: "GB", timezone: "Europe/London", tz_label: "London",
  open: "08:00", close: "16:30", currency: "GBP", screen: true, order: 4 };
const utc = (y: number, mo: number, d: number, h = 0) => Date.UTC(y, mo - 1, d, h) / 1000;

describe("market registry", () => {
  afterEach(() => setMarkets(BUILT_IN));

  it("knows today's four markets before the list arrives", () => {
    expect(markets().map((m) => m.code)).toEqual(["NSE", "BSE", "NYSE", "NASDAQ"]);
    expect(currencyOf("NSE:RELIANCE")).toBe("INR");
    expect(currencyOf("NASDAQ")).toBe("USD");
    expect(marketOf("XYZ:ABC").code).toBe("NSE");                                // unknown: the default market
  });

  it("a new market from GET /markets: its time zone, currency and units, no code change", () => {
    setMarkets([...BUILT_IN, LSE]);
    expect(markets().map((m) => m.code)).toEqual(["NSE", "BSE", "NYSE", "NASDAQ", "LSE"]);
    expect(exchangeTimeZone("LSE:VOD", "1h")).toBe("London");
    expect(exchangeTimeZone("LSE:VOD", "1D")).toBe("IST");                        // daily stamps: IST midnight
    expect(shiftFor("LSE:VOD", "15m")(utc(2026, 7, 1, 9))).toBe(3600);            // BST
    expect(shiftFor("LSE:VOD", "15m")(utc(2026, 1, 5, 9))).toBe(0);               // GMT
    expect(shiftFor("NSE:TCS", "15m")(utc(2026, 7, 1, 9))).toBe(IST);
    expect(money(1_250_000, "GBP")).toBe("£1,250,000");
    expect(turnoverText(32_000_000, "LSE")).toBe("£32.0M");
    expect(turnoverUnit("LSE")).toBe(1e6);
    expect(turnoverLabel("LSE")).toBe("£M");
  });

  it("amounts keep each currency's own style", () => {
    expect(money(416_533.4, "INR")).toBe("₹4,16,533");
    expect(money(416_533.4, "USD")).toBe("$416,533");
    expect(bigMoney(125_000_000, "INR")).toBe("₹12.5 Cr");
    expect(turnoverText(3_200_000, "NYSE")).toBe("$3.2M");
    expect(tzOffset("America/New_York", utc(2026, 12, 1, 15))).toBe(-5 * 3600);
  });

  it("a broken or empty list keeps the built-in one", () => {
    setMarkets([]);
    expect(markets()).toBe(markets());
    expect(markets().length).toBe(4);
  });
});
