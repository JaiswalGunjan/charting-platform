import { describe, expect, it } from "vitest";
import type { IChartApi, ISeriesApi, SeriesType } from "lightweight-charts";
import { FIB_LEVELS, hitTest, Mapper, POINTS, segments, type Drawing } from "../../src/drawings";

// Fake chart that behaves like Lightweight Charts: whole bar indexes map to x = 100 + 10 * index; fractional
// indexes are NOT converted (the real library returns 0 for them, which once drew drawings at the left edge).
const DAY = 86400;
const fakeChart = {
  timeScale: () => ({
    logicalToCoordinate: (l: number) => (Number.isInteger(l) ? 100 + 10 * l : 0),
    coordinateToLogical: (x: number) => Math.round((x - 100) / 10),
  }),
} as unknown as IChartApi;
const fakeSeries = {
  priceToCoordinate: (p: number) => 500 - p,
  coordinateToPrice: (y: number) => 500 - y,
} as unknown as ISeriesApi<SeriesType>;

// daily bars with a weekend gap: Mon..Fri, Mon..Fri
const base = 1_700_000_000 - (1_700_000_000 % DAY);
const times = [0, 1, 2, 3, 4, 7, 8, 9, 10, 11].map((d) => base + d * DAY);
const m = new Mapper(fakeChart, fakeSeries, () => times);

describe("Mapper (time <-> bar index <-> pixels)", () => {
  it("maps bar times to their index and back", () => {
    times.forEach((t, i) => {
      expect(m.timeToLogical(t)).toBe(i);
      expect(m.logicalToTime(i)).toBe(t);
    });
  });
  it("interpolates between bars, so the weekend counts as one bar step", () => {
    expect(m.timeToLogical(times[4] + 1.5 * DAY)).toBeCloseTo(4.5);
    expect(m.logicalToTime(4.5)).toBeCloseTo(times[4] + 1.5 * DAY);
  });
  it("extrapolates past both ends with the typical bar interval", () => {
    expect(m.timeToLogical(times[9] + 3 * DAY)).toBeCloseTo(12);
    expect(m.timeToLogical(times[0] - 2 * DAY)).toBeCloseTo(-2);
    expect(m.logicalToTime(12)).toBeCloseTo(times[9] + 3 * DAY);
  });
  it("puts points between bars at the right x (regression: fractional indexes)", () => {
    const xy = m.toXY({ t: times[2] + DAY / 2, p: 120 })!;
    expect(xy.x).toBeCloseTo(125); // index 2.5
    expect(xy.y).toBe(380);
  });
  it("pixel -> point -> pixel round-trips, also between bars", () => {
    for (const x of [100, 137, 163.3, 205]) {
      const pt = m.fromXY(x, 250)!;
      const back = m.toXY(pt)!;
      expect(back.x).toBeCloseTo(x, 6);
      expect(back.y).toBeCloseTo(250, 6);
    }
  });
  it("does not crash before any bars are loaded", () => {
    const empty = new Mapper(fakeChart, fakeSeries, () => []);
    expect(empty.timeToLogical(123)).toBe(0);
  });
});

const W = 1000;
const H = 600;
const d = (kind: Drawing["kind"], n: number, extra: Partial<Drawing> = {}): Drawing => ({
  id: kind, kind, color: "#2962ff", width: 2,
  pts: Array.from({ length: n }, (_, i) => ({ t: times[i], p: 100 + i })), ...extra,
});

describe("drawing geometry", () => {
  const A = { x: 100, y: 300 };
  const B = { x: 200, y: 250 };
  const C = { x: 200, y: 350 };
  it("trend line is one segment; ray and extended line reach past the pane", () => {
    expect(segments(d("trend", 2), [A, B], W, H)).toEqual([[A, B]]);
    const [[r0, r1]] = segments(d("ray", 2), [A, B], W, H);
    expect(r0).toEqual(A);
    expect(r1.x).toBeGreaterThan(W);
    const [[e0, e1]] = segments(d("extended", 2), [A, B], W, H);
    expect(e0.x).toBeLessThan(0);
    expect(e1.x).toBeGreaterThan(W);
  });
  it("horizontal and vertical lines span the pane", () => {
    expect(segments(d("hline", 1), [A], W, H)).toEqual([[{ x: 0, y: 300 }, { x: W, y: 300 }]]);
    expect(segments(d("hray", 1), [A], W, H)).toEqual([[A, { x: W, y: 300 }]]);
    expect(segments(d("vline", 1), [A], W, H)).toEqual([[{ x: 100, y: 0 }, { x: 100, y: H }]]);
  });
  it("rectangle has four sides; channel draws a parallel line through the third point", () => {
    expect(segments(d("rect", 2), [A, B], W, H)).toHaveLength(4);
    const [l1, l2] = segments(d("channel", 3), [A, B, C], W, H);
    expect(l1).toEqual([A, B]);
    expect(l2[0].y - l1[0].y).toBeCloseTo(l2[1].y - l1[1].y); // parallel
    expect(l2[1]).toEqual(C);
  });
  it("Fibonacci retracement has one level per ratio between the two prices", () => {
    const segs = segments(d("fib", 2), [A, B], W, H);
    expect(segs).toHaveLength(FIB_LEVELS.length);
    expect(segs[0][0].y).toBe(B.y); // level 0 at the second point
    expect(segs[segs.length - 1][0].y).toBe(A.y); // level 1 at the first point
  });
  it("brush is a polyline; every tool declares how many clicks it needs", () => {
    expect(segments(d("brush", 3), [A, B, C], W, H)).toHaveLength(2);
    expect(POINTS).toMatchObject({ trend: 2, hline: 1, vline: 1, text: 1, channel: 3, fib: 2, rect: 2 });
    expect(POINTS.brush).toBe(Infinity);
  });
});

describe("hit testing", () => {
  const trend = d("trend", 2, { id: "t" }); // pixels (100, 400) -> (110, 399)
  it("finds a line near the pointer and misses far away", () => {
    expect(hitTest([trend], m, { x: 105, y: 401 }, W, H, null)).toEqual({ id: "t", handle: null });
    expect(hitTest([trend], m, { x: 105, y: 430 }, W, H, null)).toBeNull();
  });
  it("prefers a handle of the selected drawing", () => {
    expect(hitTest([trend], m, { x: 110, y: 399 }, W, H, "t")).toEqual({ id: "t", handle: 1 });
  });
  it("hits inside a rectangle, skips hidden drawings and the measure tool, and picks the topmost", () => {
    const rect: Drawing = {
      id: "r", kind: "rect", color: "#000000", width: 1,
      pts: [{ t: times[0], p: 200 }, { t: times[5], p: 100 }],
    };
    expect(hitTest([rect], m, { x: 120, y: 350 }, W, H, null)?.id).toBe("r");
    expect(hitTest([{ ...rect, hidden: true }], m, { x: 120, y: 350 }, W, H, null)).toBeNull();
    expect(hitTest([{ ...rect, kind: "measure" }], m, { x: 120, y: 350 }, W, H, null)).toBeNull();
    const top = { ...rect, id: "top" };
    expect(hitTest([rect, top], m, { x: 120, y: 350 }, W, H, null)?.id).toBe("top");
  });
});
