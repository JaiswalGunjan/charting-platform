import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type LogicalRange,
  type SeriesType,
  type UTCTimestamp,
} from "lightweight-charts";
import { api, type Alert, type IndicatorMeta, type KeyLevel, type LiveBar } from "./api";
import { live } from "./live";
import { indicatorLabel, outputStyle, type ActiveIndicator } from "./indicatorStyle";

// Lightweight Charts renders UTC; shift epoch seconds so axis labels read in IST.
const IST = 19800;
const toChart = (t: number) => (t + IST) as UTCTimestamp;
const PAGE = 500;
const MAX_IND_BARS = 5000;

const UP = "#26a69a";
const DOWN = "#ef5350";

interface Props {
  symbol: string;
  tf: string;
  indicators: ActiveIndicator[];
  metas: Record<string, IndicatorMeta>;
  alerts: Alert[];
  aiLevels: KeyLevel[];
  onRemoveIndicator: (key: string) => void;
  onEditIndicator: (key: string) => void;
}

interface Legend {
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export default function Chart(props: Props) {
  const { symbol, tf, indicators, metas, alerts, aiLevels } = props;
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volume = useRef<ISeriesApi<"Histogram"> | null>(null);
  const bars = useRef<LiveBar[]>([]);
  const nextTo = useRef<number | null>(null);
  const loadingOlder = useRef(false);
  const gen = useRef(0); // bumps on symbol/tf change; stale responses are dropped
  const [dataVersion, setDataVersion] = useState(0);
  const [status, setStatus] = useState<string>("loading…");
  const [legend, setLegend] = useState<Legend | null>(null);
  const [, setLiveBar] = useState<LiveBar | null>(null);

  // ---- chart lifecycle -------------------------------------------------------
  useEffect(() => {
    const c = createChart(box.current!, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#0f1218" },
        textColor: "#a7adbb",
        fontFamily: "Inter, Segoe UI, system-ui, sans-serif",
        attributionLogo: true, // required attribution for TradingView Lightweight Charts
        panes: { separatorColor: "#262b36", separatorHoverColor: "#3a4152", enableResize: true },
      },
      grid: { vertLines: { color: "#1a1f29" }, horzLines: { color: "#1a1f29" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#262b36" },
      timeScale: { borderColor: "#262b36", timeVisible: true, secondsVisible: false, rightOffset: 8 },
    });
    candles.current = c.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderVisible: false, wickUpColor: UP, wickDownColor: DOWN,
    });
    volume.current = c.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false,
    });
    c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

    c.subscribeCrosshairMove((p) => {
      const d = p.seriesData.get(candles.current!) as { open: number; high: number; low: number; close: number } | undefined;
      const vd = p.seriesData.get(volume.current!) as { value: number } | undefined;
      if (d) setLegend({ o: d.open, h: d.high, l: d.low, c: d.close, v: vd?.value ?? 0 });
      else setLegend(null);
    });
    chart.current = c;
    return () => {
      c.remove();
      chart.current = null;
    };
  }, []);

  // ---- data: history + live --------------------------------------------------
  useEffect(() => {
    const g = ++gen.current;
    bars.current = [];
    nextTo.current = null;
    setStatus("loading…");
    setLegend(null);
    let unsubscribe: (() => void) | null = null;

    const render = () => {
      candles.current!.setData(bars.current.map((b) => ({ time: toChart(b.t), open: b.o, high: b.h, low: b.l, close: b.c })));
      volume.current!.setData(bars.current.map(volPoint));
    };

    api.history(symbol, tf, PAGE).then(
      (h) => {
        if (g !== gen.current) return;
        bars.current = h.t.map((t, i) => ({ t, o: h.o[i], h: h.h[i], l: h.l[i], c: h.c[i], v: h.v[i] }));
        nextTo.current = h.next_to;
        render();
        chart.current!.timeScale().scrollToRealTime();
        setStatus(bars.current.length ? "" : "no data");
        setDataVersion((v) => v + 1);
        unsubscribe = live.subscribe(symbol, tf);
      },
      (e) => g === gen.current && setStatus(String(e.message ?? e)),
    );

    const offMsg = live.on((m) => {
      if (g !== gen.current) return;
      if ((m.type === "bar" || m.type === "subscribed") && m.symbol === symbol && m.tf === tf && m.bar) {
        applyLive(m.bar);
      }
    });

    const applyLive = (b: LiveBar) => {
      const arr = bars.current;
      const last = arr[arr.length - 1];
      if (!last || b.t < last.t) return;
      candles.current!.update({ time: toChart(b.t), open: b.o, high: b.h, low: b.l, close: b.c });
      volume.current!.update(volPoint(b));
      setLiveBar(b); // keeps the legend current when the crosshair is off-chart
      if (b.t === last.t) arr[arr.length - 1] = b;
      else {
        arr.push(b);
        setDataVersion((v) => v + 1); // new bar: refresh indicators
      }
    };

    // infinite scroll: fetch the previous page when the user nears the left edge
    const onRange = (r: LogicalRange | null) => {
      if (!r || r.from > 30 || nextTo.current === null || loadingOlder.current) return;
      loadingOlder.current = true;
      api.history(symbol, tf, PAGE, nextTo.current).then(
        (h) => {
          loadingOlder.current = false;
          if (g !== gen.current) return;
          const older = h.t.map((t, i) => ({ t, o: h.o[i], h: h.h[i], l: h.l[i], c: h.c[i], v: h.v[i] }));
          bars.current = [...older, ...bars.current];
          nextTo.current = h.next_to;
          render();
          setDataVersion((v) => v + 1);
        },
        () => (loadingOlder.current = false),
      );
    };
    const ts = chart.current!.timeScale();
    ts.subscribeVisibleLogicalRangeChange(onRange);

    return () => {
      gen.current++;
      unsubscribe?.();
      offMsg();
      ts.unsubscribeVisibleLogicalRangeChange(onRange);
    };
  }, [symbol, tf]);

  // ---- indicators ------------------------------------------------------------
  const indSeries = useRef<ISeriesApi<SeriesType>[]>([]);
  useEffect(() => {
    const c = chart.current!;
    const n = bars.current.length;
    let cancelled = false;
    if (!n) return;

    Promise.all(
      indicators.map((ind) =>
        api.indicatorValues(ind.id, symbol, tf, Math.min(n, MAX_IND_BARS), ind.params).catch(() => null),
      ),
    ).then((results) => {
      if (cancelled) return;
      indSeries.current.forEach((s) => c.removeSeries(s));
      indSeries.current = [];
      let pane = 0;
      results.forEach((res, i) => {
        const ind = indicators[i];
        const meta = metas[ind.id];
        if (!res || !meta) return;
        const paneIndex = meta.overlay ? 0 : ++pane;
        const times = res.t.map(toChart);
        let first: ISeriesApi<SeriesType> | null = null;

        for (const out of meta.outputs) {
          const st = outputStyle(ind.id, out, ind.key);
          if (st.hidden) continue;
          const vals = res.outputs[out];
          let s: ISeriesApi<SeriesType>;
          if (st.histogram) {
            s = c.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, paneIndex);
            s.setData(times.flatMap((time, k) =>
              vals[k] === null ? [] : [{ time, value: vals[k]!, color: vals[k]! >= 0 ? "#26a69a99" : "#ef535099" }]));
          } else {
            s = c.addSeries(LineSeries, {
              color: st.color, lineWidth: st.width ?? 1, priceLineVisible: false,
              lastValueVisible: !meta.overlay, crosshairMarkerVisible: false,
            }, paneIndex);
            const dir = ind.id === "supertrend" ? res.outputs["direction"] : null;
            s.setData(times.flatMap((time, k) => {
              if (vals[k] === null) return [];
              if (!dir) return [{ time, value: vals[k]! }];
              if (k > 0 && dir[k] !== dir[k - 1]) return [{ time }]; // break the line on a trend flip
              return [{ time, value: vals[k]!, color: dir[k]! > 0 ? UP : DOWN }];
            }));
          }
          indSeries.current.push(s);
          first ??= s;
        }
        if (first) {
          for (const lv of meta.levels) {
            first.createPriceLine({ price: lv, color: "#4b5263", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false });
          }
        }
      });
      const panes = c.panes();
      panes.forEach((p, k) => p.setStretchFactor(k === 0 ? 3 : 1));
    });
    return () => {
      cancelled = true;
    };
  }, [indicators, metas, dataVersion, symbol, tf]);

  // ---- price lines: alerts + AI key levels ------------------------------------
  useEffect(() => {
    const s = candles.current!;
    const lines: IPriceLine[] = [];
    for (const a of alerts) {
      if (a.symbol !== symbol || a.status !== "active") continue;
      lines.push(s.createPriceLine({
        price: a.condition.price, color: "#f0a43a", lineStyle: LineStyle.Dashed, lineWidth: 1,
        axisLabelVisible: true, title: `🔔 ${a.condition.op.replace("_", " ")}`,
      }));
    }
    for (const lv of aiLevels) {
      lines.push(s.createPriceLine({
        price: lv.price, color: lv.kind === "support" ? "#26a69a" : "#ef5350", lineStyle: LineStyle.Dotted,
        lineWidth: 1, axisLabelVisible: true, title: `AI ${lv.kind}`,
      }));
    }
    return () => lines.forEach((l) => s.removePriceLine(l));
  }, [alerts, aiLevels, symbol]);

  const last = bars.current[bars.current.length - 1];
  const lg = legend ?? (last ? { o: last.o, h: last.h, l: last.l, c: last.c, v: last.v } : null);
  const up = lg ? lg.c >= lg.o : true;

  return (
    <div className="chart-wrap">
      <div className="legend">
        <div className="legend-row">
          <span className="legend-sym">{symbol}</span>
          <span className="muted">· {tf}</span>
          {lg && (
            <span className={up ? "up" : "down"}>
              O <b>{fmt(lg.o)}</b> H <b>{fmt(lg.h)}</b> L <b>{fmt(lg.l)}</b> C <b>{fmt(lg.c)}</b>
              <span className="muted"> Vol {fmtVol(lg.v)}</span>
            </span>
          )}
          {status && <span className="muted">{status}</span>}
        </div>
        {indicators.map((ind) => (
          <div className="legend-row ind-chip" key={ind.key}>
            <span>{indicatorLabel(ind, metas[ind.id])}</span>
            {metas[ind.id]?.params.length ? (
              <button className="icon" title="Settings" onClick={() => props.onEditIndicator(ind.key)}>⚙</button>
            ) : null}
            <button className="icon" title="Remove" onClick={() => props.onRemoveIndicator(ind.key)}>✕</button>
          </div>
        ))}
      </div>
      <div className="chart" ref={box} />
    </div>
  );
}

function volPoint(b: LiveBar) {
  return { time: toChart(b.t), value: b.v, color: b.c >= b.o ? "#26a69a55" : "#ef535055" };
}

export const fmt = (x: number | null | undefined) =>
  x === null || x === undefined ? "—" : x.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const fmtVol = (v: number) =>
  v >= 1e7 ? `${(v / 1e7).toFixed(2)}Cr` : v >= 1e5 ? `${(v / 1e5).toFixed(2)}L` : v >= 1e3 ? `${(v / 1e3).toFixed(1)}K` : String(v);
