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
  default: number;
  min: number;
  max: number;
  kind: string;
}

export interface IndicatorMeta {
  id: string;
  title: string;
  overlay: boolean;
  outputs: string[];
  params: IndicatorParam[];
  levels: number[];
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
  constructor(public status: number, message: string) {
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
    try {
      const body = await r.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* not JSON */
    }
    throw new ApiError(r.status, msg);
  }
  return r.status === 204 ? (undefined as T) : r.json();
}

const qs = (p: Record<string, string | number | undefined | null>) =>
  new URLSearchParams(
    Object.entries(p).filter(([, v]) => v !== undefined && v !== null).map(([k, v]) => [k, String(v)]),
  ).toString();

export const api = {
  searchSymbols: (q: string) => req<SymbolInfo[]>(`/symbols?${qs({ q, limit: 20 })}`),
  timeframes: () => req<string[]>("/timeframes"),
  history: (symbol: string, tf: string, limit: number, to?: number | null) =>
    req<History>(`/history?${qs({ symbol, tf, limit, to })}`),
  indicators: () => req<IndicatorMeta[]>("/indicators"),
  indicatorValues: (id: string, symbol: string, tf: string, limit: number, params: Record<string, number>) =>
    req<IndicatorValues>(`/indicators/${id}?${qs({ symbol, tf, limit, ...params })}`),
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
