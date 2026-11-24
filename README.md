# charting-platform

AI-native charting and trading-analysis platform (TradingView-style category).
Blueprint: `docs/BLUEPRINT.md`. Context for Claude Code: `CLAUDE.md`.

## Status — first milestone (private prototype)

| # | Milestone | State |
|---|---|---|
| M1 | Backend foundation, symbol master, historical candle loader (synthetic + Kite) | done |
| M2 | `GET /history` — any timeframe, cursor paging for infinite scroll | done |
| M3 | 11 indicators (SMA, EMA, WMA, BB, VWAP, Supertrend, RSI, MACD, ATR, Stoch, OBV) | done |
| M4 | Live ticks → forming bars (Redis/memory) → WebSocket fan-out, bars persisted | done |
| M5 | Watchlists + price alerts (edge-triggered, pushed over WS) | done |
| M6 | AI "explain this chart" (Claude, structured output, every call logged) | done |
| M7 | Frontend: Vite + React + TS + Lightweight Charts v5 | done |

## Run the demo (one command)

```powershell
powershell -ExecutionPolicy Bypass -File .\run-demo.ps1
```

It seeds data on first run, starts the backend (:8000) and the frontend (:5173) in two windows,
and opens http://localhost:5173. Node comes from the portable copy in `.tools/node`
(gitignored) if present, otherwise from your system install.

The frontend includes symbol search, 11 timeframes, infinite scroll back through history,
live candles and quotes over WebSocket, and indicator overlays and panes with editable params.
The sidebar has a watchlist with live quotes, alerts (shown as price lines, with toast
notifications) and "Explain this chart" (AI key levels are drawn on the chart).

## Run the backend

```powershell
cd backend
..\.venv\Scripts\python -m pip install -r requirements.txt
copy ..\.env.example ..\.env          # then edit; never commit .env
..\.venv\Scripts\python -m app.cli seed   # 20 NSE symbols, 30d of 1m + 5y of 1D (synthetic)
..\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs. Tests: `..\.venv\Scripts\python -m pytest -q` (from `backend/`).

Defaults need no external services: SQLite at `backend/data/charting.db`, an in-memory
live store, and synthetic market data whose live ticks run 24x7 so you can see updates
outside market hours. Set `DATABASE_URL` (Postgres/TimescaleDB), `REDIS_URL`, and
`DATA_SOURCE=kite` in `.env` to switch.

**Kite Connect** (private prototyping only — its data may not be redistributed):
set `KITE_API_KEY`/`KITE_API_SECRET`, run `python -m app.cli kite-login` each morning
for `KITE_ACCESS_TOKEN`, then `python -m app.cli load-symbols` and `load-candles`.

**AI analyst:** set `ANTHROPIC_API_KEY`. Uses `claude-opus-5-5` at effort `medium` with
server-side refusal fallback; tune with `AI_MODEL` / `AI_EFFORT`. `POST /ai/explain` with
`"dry_run": true` returns the exact context the model would see, without an API call.

## API overview

| Endpoint | Purpose |
|---|---|
| `GET /symbols?q=` · `GET /symbols/{symbol}` | Symbol search / lookup (`NSE:RELIANCE`, bare `RELIANCE` = NSE) |
| `GET /history?symbol&tf&limit&to&from` | Column arrays `t,o,h,l,c,v` + `next_to` cursor. TFs: 1m 3m 5m 15m 30m 1h 2h 4h 1D 1W 1M |
| `GET /indicators` · `GET /indicators/{id}?symbol&tf&...params` | Indicator metadata / values aligned with `/history` (warm-up handled server-side) |
| `WS /ws` | `{"op":"subscribe","symbol","tf"}` → `subscribed`, `bar`, `quote`, `alert` messages |
| `GET /quotes?symbols=a,b` | Latest quotes (starts streaming if needed) |
| `/watchlists` (CRUD) · `/watchlists/{id}/items` | Watchlists |
| `/alerts` (CRUD) · `GET /alerts/events` | Price alerts: `crosses_above`, `crosses_below`, `above`, `below` |
| `POST /ai/explain` | `{symbol, tf, to?, dry_run?}` → structured analysis + disclaimer + context |

## Layout

```
backend/app/
  marketdata/   sources (synthetic, kite), loader, timeframes + resampling, history paging
  indicators/   numpy indicator math + registry (params, warm-up, overlay/pane metadata)
  live/         tick sources, forming bars, live store (Redis/memory), LiveService + conflation
  alerts/       alert engine (tick listener)
  ai/           deterministic chart context + Claude analyst
  api/          FastAPI routers
backend/tests/  pytest suite per milestone (synthetic data, fake tick source, fake LLM)
frontend/src/
  api.ts        typed REST client (Vite proxies /api -> :8000, including the WebSocket)
  live.ts       shared WebSocket: ref-counted subscriptions, auto-reconnect
  Chart.tsx     Lightweight Charts: candles+volume, paging, live updates, indicator panes, price lines
  Panels.tsx    watchlist, alerts, AI analyst
```

Frontend by hand: `cd frontend; npm install; npm run dev` (backend must be on :8000);
`npm run build` type-checks and bundles.
