import { describe, expect, it } from "vitest";
import type { IndicatorMeta } from "../../src/api";
import { indicatorLabel, newIndicator, plotStyle } from "../../src/indicatorStyle";

const ema: IndicatorMeta = {
  id: "ema", title: "Exponential Moving Average", category: "Moving averages", overlay: true, outputs: ["ema"],
  plots: [{ name: "ema", style: "line", color: null }],
  params: [
    { name: "length", default: 20, min: 1, max: 500, kind: "int", options: [] },
    { name: "source", default: "close", min: 0, max: 0, kind: "source", options: ["close", "hl2"] },
  ],
  levels: [],
};
const macd: IndicatorMeta = {
  id: "macd", title: "MACD", category: "Momentum", overlay: false, outputs: ["macd", "signal", "hist"],
  plots: [
    { name: "macd", style: "line", color: "#2962ff" },
    { name: "signal", style: "line", color: "#ff9800" },
    { name: "hist", style: "histogram", color: null },
  ],
  params: [],
  levels: [0],
};

describe("indicator labels", () => {
  it("lists the inputs, hiding the default close source", () => {
    const ind = newIndicator(ema);
    expect(indicatorLabel(ind, ema)).toBe("Exponential Moving Average (20)");
    expect(indicatorLabel({ ...ind, params: { length: 50, source: "hl2" } }, ema)).toBe("Exponential Moving Average (50, hl2)");
    expect(indicatorLabel({ ...ind, params: { length: 0.8500000001, source: "close" } }, ema))
      .toBe("Exponential Moving Average (0.85)");
  });
  it("falls back to the id when metadata is missing (e.g. a deleted custom indicator)", () => {
    expect(indicatorLabel({ key: "k", id: "custom-9", params: {} })).toBe("CUSTOM-9");
  });
});

describe("new indicators", () => {
  it("start from the defaults with a unique key", () => {
    const a = newIndicator(ema);
    const b = newIndicator(ema);
    expect(a.params).toEqual({ length: 20, source: "close" });
    expect(a.key).not.toBe(b.key);
  });
});

describe("plot styles", () => {
  it("uses the declared colour and style, and user overrides win", () => {
    const ind = newIndicator(macd);
    expect(plotStyle(ind, macd, "macd")).toMatchObject({ style: "line", color: "#2962ff", width: 1 });
    expect(plotStyle(ind, macd, "hist").style).toBe("histogram");
    const o = { ...ind, style: { macd: { color: "#000000", width: 3 as const }, signal: { hidden: true } } };
    expect(plotStyle(o, macd, "macd")).toMatchObject({ color: "#000000", width: 3 });
    expect(plotStyle(o, macd, "signal").style).toBe("hidden");
  });
  it("gives two instances of one moving average different colours, and a 2px line on the price chart", () => {
    const a = newIndicator(ema);
    const b = newIndicator(ema);
    expect(plotStyle(a, ema, "ema").color).not.toBe(plotStyle(b, ema, "ema").color);
    expect(plotStyle(a, ema, "ema").color).toBe(plotStyle(a, ema, "ema").color); // stable per instance
    expect(plotStyle(a, ema, "ema").width).toBe(2);
  });
});
