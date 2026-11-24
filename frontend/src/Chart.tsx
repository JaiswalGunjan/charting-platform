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
import { createSeriesMarkers, type ISeriesMarkersPluginApi, type SeriesMarker, type Time } from "lightweight-charts";
import { api, type Alert, type IndicatorMeta, type KeyLevel, type LiveBar, type PatternMarker, type PatternScan, type ScannerSignal } from "./api";
import { DrawingsPrimitive, Mapper, type Drawing } from "./drawings";
import { live } from "./live";
import { indicatorLabel, plotStyle, type ActiveIndicator } from "./indicatorStyle";
import { rangeStart, type RangeId } from "./ranges";
import { CHART_THEME, type Theme } from "./theme";
import DrawingTools from "./DrawingTools";
import { fmt, fmtVol } from "./format";
import { exchangeTimeZone, shiftFor } from "./time";

export { fmt, fmtVol };

let shift: (t: number) => number = shiftFor("NSE:X", "1D");
const toChart = (t: number) => (t + shift(t)) as UTCTimestamp;
function setShift(symbol: string, tf: string) {
  shift = shiftFor(symbol, tf);
}
export { exchangeTimeZone };
const PAGE = 500;
const RANGE_PAGE = 5000;
const MAX_IND_BARS = 5000;

const UP = "#26a69a";
const DOWN = "#ef5350";

export interface RangeRequest {
  id: RangeId;
  nonce: number; // re-applies the same range (e.g. after a symbol change)
}

interface Props {
  symbol: string;
  tf: string;
  theme: Theme;
  range: RangeRequest | null;
  indicators: ActiveIndicator[];
  metas: Record<string, IndicatorMeta>;
  alerts: Alert[];
  aiLevels: KeyLevel[];
  onRemoveIndicator: (key: string) => void;
  onEditIndicator: (key: string) => void;
  onToggleIndicator: (key: string) => void;
  patterns: string[];                                   // enabled chart-pattern ids
  signal?: ScannerSignal | null;                        // a SwingScanner signal opened from the Scanner tab
  onPatternCounts?: (counts: Record<string, number>) => void;
  wantPatternCounts?: boolean;                          // pattern menu open: count every pattern, shown or not
}

interface Legend {
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function Chart(props: Props) {
  const { symbol, tf, theme, range, indicators, metas, alerts, aiLevels } = props;
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volume = useRef<ISeriesApi<"Histogram"> | null>(null);
  const bars = useRef<LiveBar[]>([]);
  const nextTo = useRef<number | null>(null);
  const loadingOlder = useRef(false);
  const gen = useRef(0); // bumps on symbol/tf change; stale responses are dropped
  const rangeRef = useRef<RangeRequest | null>(range);
  const applyRangeRef = useRef<((id: RangeId) => void) | null>(null);
  const [dataVersion, setDataVersion] = useState(0);
  const [status, setStatus] = useState<string>("loading…");
  const [legend, setLegend] = useState<Legend | null>(null);
  const [hoverTime, setHoverTime] = useState<number | null>(null);
  const [scanRes, setScanRes] = useState<PatternScan | null>(null);
  const [, setLiveBar] = useState<LiveBar | null>(null);
  const [apiObjs, setApiObjs] = useState<{ chart: IChartApi; series: ISeriesApi<"Candlestick"> } | null>(null);
  rangeRef.current = range;
  setShift(symbol, tf);

  // ---- chart lifecycle -------------------------------------------------------
  useEffect(() => {
    const c = createChart(box.current!, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: CHART_THEME[theme].bg },
        fontFamily: "Inter, Segoe UI, system-ui, sans-serif",
        // no logo on the chart: the attribution notice and link the licence asks for are on the About page
        // (footer "About" link, App.tsx)
        attributionLogo: false,
        panes: { enableResize: true },
      },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 8 },
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
      setHoverTime(p.time === undefined ? null : (p.time as number));
    });
    chart.current = c;
    setApiObjs({ chart: c, series: candles.current });
    return () => {
      setApiObjs(null);
      c.remove();
      chart.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- theme -------------------------------------------------------------------
  useEffect(() => {
    const p = CHART_THEME[theme];
    chart.current!.applyOptions({
      layout: {
        background: { type: ColorType.Solid, color: p.bg },
        textColor: p.text,
        panes: { separatorColor: p.border, separatorHoverColor: p.level },
      },
      grid: { vertLines: { color: p.grid }, horzLines: { color: p.grid } },
      crosshair: { vertLine: { color: p.crosshair, labelBackgroundColor: p.crosshair },
                   horzLine: { color: p.crosshair, labelBackgroundColor: p.crosshair } },
      rightPriceScale: { borderColor: p.border },
      timeScale: { borderColor: p.border },
    });
  }, [theme]);

  // ---- data: history + live --------------------------------------------------
  useEffect(() => {
    const g = ++gen.current;
    bars.current = [];
    nextTo.current = null;
    setStatus("loading…");
    setLegend(null);
    let unsubscribe: (() => void) | null = null;
    let loaded = false;

    const render = () => {
      candles.current!.setData(bars.current.map((b) => ({ time: toChart(b.t), open: b.o, high: b.h, low: b.l, close: b.c })));
      volume.current!.setData(bars.current.map(volPoint));
    };
    const toBars = (h: { t: number[]; o: number[]; h: number[]; l: number[]; c: number[]; v: number[] }) =>
      h.t.map((t, i) => ({ t, o: h.o[i], h: h.h[i], l: h.l[i], c: h.c[i], v: h.v[i] }));

    // date-range presets: page back until the range is covered, then zoom to it
    const applyRange = async (id: RangeId) => {
      if (!bars.current.length) return;
      const anchor = bars.current[bars.current.length - 1].t;
      const from = rangeStart(id, anchor);
      let grew = false;
      for (let pages = 0; nextTo.current !== null && bars.current[0].t > from && pages < 40; pages++) {
        while (loadingOlder.current) await sleep(30);
        if (g !== gen.current || nextTo.current === null) return;
        loadingOlder.current = true;
        setStatus("loading history…");
        try {
          const h = await api.history(symbol, tf, RANGE_PAGE, nextTo.current);
          if (g !== gen.current) return;
          bars.current = [...toBars(h), ...bars.current];
          nextTo.current = h.next_to;
          grew = true;
        } catch (e) {
          setStatus(String((e as Error).message ?? e));
          break;
        } finally {
          loadingOlder.current = false;
        }
      }
      if (g !== gen.current) return;
      setStatus("");
      if (grew) {
        render();
        setDataVersion((v) => v + 1);
      }
      const ts = chart.current!.timeScale();
      if (id === "All" || from <= bars.current[0].t) return ts.fitContent();
      // by bar index, not time: gaps in the data (e.g. stored hourly history ending weeks before
      // today's live bar) must not leave the view empty; show at least 20 bars
      const lastIdx = bars.current.length - 1;
      const firstIdx = Math.min(bars.current.findIndex((b) => b.t >= from), Math.max(0, lastIdx - 19));
      ts.setVisibleLogicalRange({ from: firstIdx - 0.5, to: lastIdx + 3 });
    };
    applyRangeRef.current = (id) => void applyRange(id);

    api.history(symbol, tf, PAGE).then(
      (h) => {
        if (g !== gen.current) return;
        bars.current = toBars(h);
        nextTo.current = h.next_to;
        loaded = true;
        render();
        // a manual symbol/timeframe pick starts at normal zoom (a range preset may have zoomed far out)
        if (!rangeRef.current) chart.current!.timeScale().applyOptions({ barSpacing: 6 });
        chart.current!.timeScale().scrollToRealTime();
        setStatus(bars.current.length ? "" : "no data");
        setDataVersion((v) => v + 1);
        unsubscribe = live.subscribe(symbol, tf);
        if (rangeRef.current) void applyRange(rangeRef.current.id);
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
      if (!last) {
        // no stored history for this timeframe (e.g. minutes on hourly/daily data): start from live bars
        if (!loaded) return;
        arr.push(b);
        render();
        setStatus("live bars only — no stored history for this timeframe");
        setLiveBar(b);
        return;
      }
      if (b.t < last.t) return;
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
          bars.current = [...toBars(h), ...bars.current];
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
      applyRangeRef.current = null;
      unsubscribe?.();
      offMsg();
      ts.unsubscribeVisibleLogicalRangeChange(onRange);
    };
  }, [symbol, tf]);

  // a range picked while the data is already loaded
  useEffect(() => {
    if (range && bars.current.length) applyRangeRef.current?.(range.id);
  }, [range?.nonce]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- indicators ------------------------------------------------------------
  const indSeries = useRef<ISeriesApi<SeriesType>[]>([]);
  useEffect(() => {
    const c = chart.current!;
    const n = bars.current.length;
    let cancelled = false;
    if (!n) return;
    const visible = indicators.filter((i) => !i.hidden && metas[i.id]);

    Promise.all(
      visible.map((ind) =>
        api.indicatorValues(ind.id, symbol, tf, Math.min(n, MAX_IND_BARS), ind.params).catch(() => null),
      ),
    ).then((results) => {
      if (cancelled) return;
      indSeries.current.forEach((s) => c.removeSeries(s));
      indSeries.current = [];
      let pane = 0;
      results.forEach((res, i) => {
        const ind = visible[i];
        const meta = metas[ind.id];
        if (!res) return;
        const paneIndex = meta.overlay ? 0 : ++pane;
        const times = res.t.map(toChart);
        let first: ISeriesApi<SeriesType> | null = null;

        for (const out of meta.outputs) {
          const st = plotStyle(ind, meta, out);
          if (st.style === "hidden") continue;
          const vals = res.outputs[out];
          let s: ISeriesApi<SeriesType>;
          if (st.style === "histogram") {
            const fixed = meta.plots.find((p) => p.name === out)?.color || ind.style?.[out]?.color;
            s = c.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, paneIndex);
            s.setData(times.flatMap((time, k) =>
              vals[k] === null ? [] : [{
                time, value: vals[k]!,
                color: fixed ? `${st.color}aa` : vals[k]! >= 0 ? "#26a69a99" : "#ef535099",
              }]));
          } else {
            const dots = st.style === "dots";
            s = c.addSeries(LineSeries, {
              color: st.color, lineWidth: st.width, priceLineVisible: false,
              lastValueVisible: !meta.overlay, crosshairMarkerVisible: false,
              lineVisible: !dots, pointMarkersVisible: dots, pointMarkersRadius: dots ? 1.5 : undefined,
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
            first.createPriceLine({ price: lv, color: CHART_THEME[theme].level, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false });
          }
        }
      });
      const panes = c.panes();
      panes.forEach((p, k) => p.setStretchFactor(k === 0 ? 3 : 1));
    });
    return () => {
      cancelled = true;
    };
  }, [indicators, metas, dataVersion, symbol, tf, theme]);

  // ---- chart patterns (rulebook rules, scanned server-side) ------------------------
  const markerApi = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const themeRef = useRef(CHART_THEME[theme].bg);
  themeRef.current = CHART_THEME[theme].bg;
  const overlay = useRef<Drawing[]>([]);
  const overlayPrim = useRef<DrawingsPrimitive | null>(null);
  const patternKey = props.patterns.join(",");
  useEffect(() => {
    if (!apiObjs) return;
    const { chart: c, series } = apiObjs;
    markerApi.current = createSeriesMarkers(series, []);
    const times = () => bars.current.map((b) => b.t);
    const mapper = new Mapper(c, series, times);
    const prim = new DrawingsPrimitive(() => ({
      drawings: overlay.current, draft: null, selected: null, hover: null, mapper,
      fmt, barsBetween: () => 0, textColor: CHART_THEME[theme].text, labelBg: `${themeRef.current}cc`,
    }));
    series.attachPrimitive(prim);
    overlayPrim.current = prim;
    return () => {
      series.detachPrimitive(prim);
      markerApi.current?.detach();
      markerApi.current = null;
      overlayPrim.current = null;
    };
  }, [apiObjs]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const n = bars.current.length;
    if (!patternKey || !n) {
      setScanRes(null);
      return;
    }
    let cancelled = false;
    const h = setTimeout(() => {
      api.patternScan(symbol, tf, props.patterns, Math.min(n, MAX_IND_BARS)).then(
        (r) => !cancelled && setScanRes(r),
        () => !cancelled && setScanRes(null),
      );
    }, 150);
    return () => {
      cancelled = true;
      clearTimeout(h);
    };
  }, [symbol, tf, patternKey, dataVersion]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const r = scanRes;
    const counts: Record<string, number> = {};
    for (const m of r?.markers ?? []) counts[m.pattern] = (counts[m.pattern] ?? 0) + 1;
    if (r?.levels.length) counts.sr = r.levels.length;
    const ms: SeriesMarker<Time>[] = (r?.markers ?? []).map((m) => ({
      time: toChart(m.t), position: "belowBar", color: m.color,
      shape: m.pattern === "cic" ? "circle" : "arrowUp", text: m.text, size: m.pattern === "cic" ? 0.6 : 1,
    }));
    ms.sort((a, b) => (a.time as number) - (b.time as number));
    markerApi.current?.setMarkers(ms);
    overlay.current = (r?.shapes ?? []).map((s, k) => ({
      id: `pat${k}`, kind: s.kind === "rect" ? "rect" : "trend", pts: s.pts, color: s.color, width: 1,
      dash: s.dash, label: s.label, labelAt: s.label_at,
    }));
    overlayPrim.current?.update();
    const series = candles.current!;
    const lines: IPriceLine[] = (r?.levels ?? []).map((lv) => series.createPriceLine({
      price: lv.price, color: lv.kind === "resistance" ? "#e5484d" : "#089981", lineStyle: LineStyle.LargeDashed,
      lineWidth: 1, axisLabelVisible: true, title: `${lv.kind === "resistance" ? "R" : "S"} ×${lv.touches}`,
    }));
    return () => lines.forEach((l) => series.removePriceLine(l));
  }, [scanRes]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const n = bars.current.length;
    if (!props.wantPatternCounts || !n) return;
    let cancelled = false;
    const h = setTimeout(() => {
      api.patternCounts(symbol, tf, Math.min(n, MAX_IND_BARS)).then(
        (r) => !cancelled && props.onPatternCounts?.(r.counts),
        () => {},
      );
    }, 100);
    return () => {
      cancelled = true;
      clearTimeout(h);
    };
  }, [symbol, tf, props.wantPatternCounts, dataVersion]); // eslint-disable-line react-hooks/exhaustive-deps

  // pattern hits on the hovered bar (or the last bar) for the legend
  const hoverHits: PatternMarker[] = (() => {
    const ms = scanRes?.markers ?? [];
    if (!ms.length) return [];
    const at = hoverTime ?? (bars.current.length ? toChart(bars.current[bars.current.length - 1].t) : null);
    return at === null ? [] : ms.filter((m) => toChart(m.t) === at);
  })();

  // ---- scanner signal: its stop and the signal-day close ---------------------------
  const sig = props.signal;
  useEffect(() => {
    if (!sig || !apiObjs) return;
    const series = apiObjs.series;
    const lines: IPriceLine[] = [];
    if (sig.stop != null) {
      lines.push(series.createPriceLine({
        price: sig.stop, color: "#e5484d", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true,
        title: `SL${sig.stop_pct != null ? ` -${sig.stop_pct.toFixed(1)}%` : ""}`,
      }));
    }
    if (sig.entry != null) {
      lines.push(series.createPriceLine({
        price: sig.entry, color: "#2f6bf2", lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: true,
        title: `Entry ${sig.setup}`,
      }));
    }
    return () => lines.forEach((l) => series.removePriceLine(l));
  }, [sig, apiObjs]);

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
      <DrawingTools chart={apiObjs?.chart ?? null} series={apiObjs?.series ?? null} host={box.current}
        bars={bars} symbol={symbol} textColor={CHART_THEME[theme].text} />
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
        {sig && (
          <div className="legend-row pattern-hit scanner-hit" title={[sig.notes, sig.stop_note].filter(Boolean).join("\n\n")}>
            <span className="pattern-tag scanner-tag">SCAN</span>
            <span>
              <b>{sig.setup_name || sig.setup}</b> {sig.date} · {sig.valid ? sig.status : `near miss: ${(sig.reject || sig.weak).split(";")[0]}`}
              {sig.entry != null && <> · entry {fmt(sig.entry)}</>}
              {sig.stop != null && <> · SL {fmt(sig.stop)}{sig.stop_pct != null && ` (-${sig.stop_pct.toFixed(1)}%)`}</>}
              {sig.buy && sig.shares != null && <> · qty {sig.shares}</>}
              {sig.score != null && <> · score {sig.score.toFixed(1)}</>}
            </span>
          </div>
        )}
        {hoverHits.map((m, k) => (
          <div className="legend-row pattern-hit" key={k} title={m.rules.join(", ")}>
            <span className="pattern-tag" style={{ background: m.color }}>{m.text}</span>
            <span>{m.notes[0] ?? ""}</span>
          </div>
        ))}
        {indicators.map((ind) => {
          const meta = metas[ind.id];
          const color = meta ? plotStyle(ind, meta, meta.outputs[0]).color : undefined;
          return (
            <div className={`legend-row ind-chip${ind.hidden ? " off" : ""}`} key={ind.key}>
              <span className="swatch" style={{ background: color }} />
              <button className="chip-label" title="Settings" onClick={() => props.onEditIndicator(ind.key)}>
                {indicatorLabel(ind, meta)}
              </button>
              <button className="icon" title={ind.hidden ? "Show" : "Hide"} onClick={() => props.onToggleIndicator(ind.key)}>
                {ind.hidden ? "◌" : "◉"}
              </button>
              <button className="icon" title="Settings" onClick={() => props.onEditIndicator(ind.key)}>⚙</button>
              <button className="icon" title="Remove" onClick={() => props.onRemoveIndicator(ind.key)}>✕</button>
            </div>
          );
        })}
      </div>
      <div className="chart" ref={box} />
    </div>
  );
}

function volPoint(b: LiveBar) {
  return { time: toChart(b.t), value: b.v, color: b.c >= b.o ? "#26a69a55" : "#ef535055" };
}
