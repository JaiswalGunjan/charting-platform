// Typed client for the FastAPI backend (proxied at /api by Vite).

export const API = "/api";

export interface SymbolInfo {
  symbol: string;
  exchange: string;
  ticker: string;
  name: string;
  type: string;
  tick_size: number;
  lot_size: number;
}

export interface History {
  symbol: string;
  tf: string;
  t: number[];
  o: number[];
  h: number[];
  l: number[];
  c: number[];
  v: number[];
  next_to: number | null;
}

export interface IndicatorParam {
  name: string;
  default: number | string;
  min: number;
  max: number;
  kind: "int" | "float" | "source";
  options: string[];
}

export type PlotStyle = "line" | "histogram" | "dots" | "hidden";

export interface PlotMeta {
  name: string;
  style: PlotStyle;
  color: string | null;
}

export interface IndicatorMeta {
  id: string;
  title: string;
  category: string;
  overlay: boolean;
  outputs: string[];
  plots: PlotMeta[];
  params: IndicatorParam[];
  levels: number[];
}

export interface CustomDef {
  name: string;
  overlay: boolean;
  inputs: { name: string; default: number; min: number; max: number }[];
  plots: { name: string; expr: string; style: PlotStyle; color: string | null }[];
  levels: number[];
}

export interface CustomOut extends CustomDef {
  id: string;
  warmup: number;
}

export interface PatternMeta {
  id: string;
  title: string;
  group: string;
  short: string;
  color: string;
  rule: string;
  about: string;
  summary: string;       // one plain-English line
}

export interface PatternMarker {
  pattern: string;
  t: number;
  text: string;
  color: string;
  notes: string[];
  rules: string[];
}

export interface PatternShape {
  pattern: string;
  kind: "segment" | "rect";
  color: string;
  dash: boolean;
  label: string;
  label_at: "start" | "end";
  pts: { t: number; p: number }[];
}

export interface PatternLevel {
  price: number;
  touches: number;
  first_t: number;
  last_t: number;
  kind: "support" | "resistance";
}

export interface PatternScan {
  markers: PatternMarker[];
  shapes: PatternShape[];
  levels: PatternLevel[];
}

export interface ScannerSignal {
  date: string;
  symbol: string;        // "NSE:MARICO"
  ticker: string;
  setup: string;         // scanner setup code (BBR, PP, VCP, ...)
  setup_name: string;    // "Bad break recovery"
  entry: number | null;  // the scanner's entry = signal-day close
  risk: number | null;   // entry - stop, per share
  buy: boolean;          // valid and a breakout (the scanner's "would buy" status)
  size_mult: number | null;  // setup multiplier used in sizing
  setups?: string[];         // every setup that formed on the stock that day: its own first, then the others
  name?: string;             // company name from our symbol list ("" when unknown)
  pattern: string;       // matching chart pattern id, "" if none
  valid: boolean;
  status: string;        // "breakout", "blocked by the market rule", ... (shown as is)
  rank: number | null;
  close: number | null;
  stop: number | null;
  stop_pct: number | null;
  score: number | null;
  stage: number | null;
  phase: string;
  base_len: number | null;
  shares: number | null;
  value: number | null;
  notes: string;
  reject: string;
  weak: string;
  stop_note: string;
  chart_href: string;
}

export interface ScannerScanInfo {
  id: string;
  market: string;
  date: string;
  valid: number | null;
  near: number | null;
  regime: string | null;
}

export interface ScannerStatus {
  name?: string;               // the setup scanner in use (SETUP_SCANNER), e.g. "swingscanner"
  title?: string;              // its name on screen, e.g. "SwingScanner"
  configured: boolean;
  online: boolean;
  scanners?: { name: string; title: string }[];   // every setup scanner in use, the default first
  msg?: string;
  dir?: string;
  markets?: { market: string; ok: boolean; last: string | null; dates: string[]; warning?: string | null }[];
  scans: ScannerScanInfo[];
}

export interface MarketNote {
  blocked: boolean;            // no new entries that day (multiplier 0 or the 10-day-low warning)
  multiplier: number | null;
  index: string;               // the small-cap index the rule reads (Nifty SmallCap 250, Russell 2000)
  regime: string;
  impulse: string;
  title: string;
  lines: string[];
  rules: { id: string; text: string }[];
}

export interface ScannerScan {
  id: string;
  market: string;
  date: string;
  regime: string | null;
  risk_mult: number | null;
  report_href: string;
  capital: number | null;      // the scan's capital (its quantities were sized on this)
  market_note: MarketNote | null;   // why the market rule stops (or shrinks) new entries that day
  score_note: string;               // what the scanner's priority score is made of
  risk_pct: number;            // % of equity risked per trade
  max_alloc_pct: number;       // max % of equity in one position
  signals: ScannerSignal[];
  near_misses: ScannerSignal[];
  setups: Record<string, { name: string; what: string; why: string }>;
}

export interface SignalExplanation {
  symbol: string;
  setup: string;
  date: string;
  valid: boolean;
  sections: { title: string; lines: string[] }[];
}

export interface ScannerJob {
  state: "idle" | "running" | "done" | "error";
  market: string;
  date: string;
  ok: boolean | null;
  log: string[];
  next: number;
  hint?: string;          // a plain explanation of a known failure (e.g. US data that holds only stubs)
}

export interface TodayRow {
  symbol: string;
  ticker: string;
  name: string;
  type: string;
  close: number;
  change_pct: number | null;
  volume: number;
  turnover: number;          // average daily turnover, last 20 sessions (typical price x volume)
  turnover_day?: number;     // that session's turnover
  htq?: boolean;             // HTQ: the 20-day average at its highest of the last quarter
  patterns: string[];
  hits: { pattern: string; text: string; notes: string[] }[];
}

export interface ScreenJob {
  state: "idle" | "running" | "done" | "error";
  exchange: string;
  tf: string;
  done: number;
  total: number;
  msg: string;
}

export interface PatternsToday {
  exchange: string;
  tf: string;
  session?: string;           // trading date of the screened bar (YYYY-MM-DD)
  dates: string[];            // sessions with a saved screen, newest first
  latest_session?: string | null;   // the newest session with data (may not be screened yet)
  turnover_days?: number;           // turnover = the average of this many sessions (20)
  htq_days?: number;                // HTQ looks back this many sessions (a quarter, 63)
  as_of: number | null;       // the latest bar (epoch s)
  last_session?: number;
  rows: TodayRow[];
  scanned: number;
  symbols?: number;
  generated_at?: number;
  missing: boolean;
  job: ScreenJob;
}

export interface Health {
  status: string;
  data_source: string;
  live: boolean;
  simulated_ticks: boolean;
  ticks?: "live" | "simulated" | "none";   // none = prices are the last close of the stored data
  feeds?: Record<string, "live" | "simulated" | "none">;   // per exchange (a feed per market: TICK_SOURCES)
  intraday_history: "1m" | "1h";
}

export interface IndicatorValues {
  id: string;
  t: number[];
  outputs: Record<string, (number | null)[]>;
  next_to: number | null;
}

export interface Quote {
  symbol: string;
  ltp: number | null;
  change: number | null;
  change_pct: number | null;
  prev_close: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  ts: number | null;
}

export interface LiveBar {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface Watchlist {
  id: number;
  name: string;
  symbols: string[];
}

export type AlertOp = "crosses_above" | "crosses_below" | "above" | "below";

export interface Alert {
  id: number;
  symbol: string;
  condition: { op: AlertOp; price: number };
  message: string;
  once: boolean;
  status: string;
  created_at: number;
  triggered_at: number | null;
}

export interface AlertEvent {
  id: number;
  alert_id: number;
  ts: number;
  price: number;
  message: string;
}

export interface KeyLevel {
  kind: "support" | "resistance";
  price: number;
  source: string;
  note: string;
}

export interface ChartAnalysis {
  summary: string;
  trend: "uptrend" | "downtrend" | "sideways";
  trend_strength: "weak" | "moderate" | "strong";
  momentum: string;
  volatility: string;
  volume: string;
  key_levels: KeyLevel[];
  signals_conflicting: string[];
  what_to_watch: string[];
}

export interface ExplainResult {
  symbol: string;
  tf: string;
  analysis: ChartAnalysis | null;
  disclaimer: string;
  context: Record<string, unknown>;
  usage: { model: string; input_tokens: number; output_tokens: number; latency_ms: number } | null;
  log_id: number | null;
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(API + path, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
  });
  if (!r.ok) {
    let msg = r.statusText;
    let detail: unknown;
    try {
      const body = await r.json();
      detail = body.detail;
      msg = typeof detail === "string" ? detail
        : typeof (detail as { message?: string })?.message === "string" ? (detail as { message: string }).message
        : JSON.stringify(detail ?? body);
    } catch {
      /* not JSON */
    }
    throw new ApiError(r.status, msg, detail);
  }
  return r.status === 204 ? (undefined as T) : r.json();
}

const qs = (p: Record<string, string | number | undefined | null>) =>
  new URLSearchParams(
    Object.entries(p).filter(([, v]) => v !== undefined && v !== null).map(([k, v]) => [k, String(v)]),
  ).toString();

export const api = {
  health: () => req<Health>("/health"),
  searchSymbols: (q: string, exchange?: string) => req<SymbolInfo[]>(`/symbols?${qs({ q, exchange, limit: 30 })}`),
  timeframes: () => req<string[]>("/timeframes"),
  history: (symbol: string, tf: string, limit: number, to?: number | null) =>
    req<History>(`/history?${qs({ symbol, tf, limit, to })}`),
  indicators: () => req<IndicatorMeta[]>("/indicators"),
  indicatorValues: (id: string, symbol: string, tf: string, limit: number, params: Record<string, number | string>) =>
    req<IndicatorValues>(`/indicators/${id}?${qs({ symbol, tf, limit, ...params })}`),
  drawings: (symbol: string) => req<{ symbol: string; items: unknown[] }>(`/drawings?${qs({ symbol })}`),
  saveDrawings: (symbol: string, items: unknown[]) =>
    req<{ symbol: string; items: unknown[] }>(`/drawings?${qs({ symbol })}`, { method: "PUT", body: JSON.stringify({ items }) }),
  exchanges: () => req<{ exchange: string; symbols: number }[]>("/exchanges"),
  patterns: () => req<PatternMeta[]>("/patterns"),
  patternScan: (symbol: string, tf: string, ids: string[], limit: number) =>
    req<PatternScan>(`/patterns/scan?${qs({ symbol, tf, ids: ids.join(","), limit })}`),
  patternCounts: (symbol: string, tf: string, limit: number) =>
    req<{ counts: Record<string, number>; bars: number }>(`/patterns/counts?${qs({ symbol, tf, limit })}`),
  // `scanner`: a setup scanner's name (several can be in use); undefined = the default one
  scanner: (scanner?: string) => req<ScannerStatus>(`/scanner?${qs({ scanner })}`),
  scannerScan: (id: string, scanner?: string) => req<ScannerScan>(`/scanner/scans/${encodeURIComponent(id)}?${qs({ scanner })}`),
  scannerRun: (market: string, date?: string, scanner?: string) =>
    req<{ ok: boolean; msg: string }>("/scanner/run", { method: "POST", body: JSON.stringify({ market, date, scanner }) }),
  scannerExplain: (scanId: string, symbol: string, setup: string, near: boolean, equity?: number, riskPct?: number,
                   scanner?: string) =>
    req<SignalExplanation>(`/scanner/scans/${encodeURIComponent(scanId)}/explain?${qs({ symbol, setup, near: near ? "true" : "false", equity, risk_pct: riskPct, scanner })}`),
  scannerJob: (since: number, scanner?: string) => req<ScannerJob>(`/scanner/job?${qs({ since, scanner })}`),
  patternsToday: (exchange: string, tf: string, date?: string) =>
    req<PatternsToday>(`/screener/patterns-today?${qs({ exchange, tf, date: date || undefined })}`),
  runPatternsToday: (exchange: string, tf: string, date?: string) =>
    req<{ ok: boolean; job: ScreenJob }>("/screener/patterns-today/run",
      { method: "POST", body: JSON.stringify({ exchange, tf, date: date || null }) }),
  patternsTodayJob: () => req<ScreenJob>("/screener/patterns-today/job"),
  customIndicators: () => req<CustomOut[]>("/custom-indicators"),
  checkCustom: (d: CustomDef) =>
    req<{ ok: boolean; warmup: number }>("/custom-indicators/check", { method: "POST", body: JSON.stringify(d) }),
  createCustom: (d: CustomDef) => req<CustomOut>("/custom-indicators", { method: "POST", body: JSON.stringify(d) }),
  updateCustom: (id: string, d: CustomDef) =>
    req<CustomOut>(`/custom-indicators/${id}`, { method: "PUT", body: JSON.stringify(d) }),
  deleteCustom: (id: string) => req<void>(`/custom-indicators/${id}`, { method: "DELETE" }),
  quotes: (symbols: string[]) => req<Quote[]>(`/quotes?${qs({ symbols: symbols.join(",") })}`),

  watchlists: () => req<Watchlist[]>("/watchlists"),
  addToWatchlist: (wid: number, symbol: string) =>
    req<Watchlist>(`/watchlists/${wid}/items`, { method: "POST", body: JSON.stringify({ symbol }) }),
  removeFromWatchlist: (wid: number, symbol: string) =>
    req<Watchlist>(`/watchlists/${wid}/items/${encodeURIComponent(symbol)}`, { method: "DELETE" }),

  alerts: () => req<Alert[]>("/alerts"),
  alertEvents: () => req<AlertEvent[]>("/alerts/events?limit=20"),
  createAlert: (symbol: string, op: AlertOp, price: number, once: boolean, message = "") =>
    req<Alert>("/alerts", { method: "POST", body: JSON.stringify({ symbol, condition: { op, price }, once, message }) }),
  setAlertStatus: (id: number, status: "active" | "disabled") =>
    req<Alert>(`/alerts/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  deleteAlert: (id: number) => req<void>(`/alerts/${id}`, { method: "DELETE" }),

  explain: (symbol: string, tf: string, dryRun = false) =>
    req<ExplainResult>("/ai/explain", { method: "POST", body: JSON.stringify({ symbol, tf, dry_run: dryRun }) }),
};
