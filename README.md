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
| M8 | Real data: adjusted daily + hourly CSV import; 12 timeframes incl. yearly; date-range presets | done |
| M9 | 50 indicators (5 categories, price-source input, per-plot style) + formula-based custom indicators | done |
| M10 | Day / night theme (day by default, one-click toggle) | done |
| M12 | Chart patterns from the owner's rulebook (S/R, pocket pivot, BBR, wedge pop, CWH, VCP, ... 19 toggles) | done |
| M11 | Drawing tools (13 tools, magnet, saved per symbol); NSE + BSE + NASDAQ + NYSE with company names; exchange-local sessions | done |

## Run the demo (one command)

```powershell
powershell -ExecutionPolicy Bypass -File .\run-demo.ps1
```

It seeds data on first run, starts the backend (:8000) and the frontend (:5173) in two windows,
and opens http://localhost:5173. Node comes from the portable copy in `.tools/node`
(gitignored) if present, otherwise from your system install.

The frontend includes symbol search, a timeframe dropdown (1m to yearly), an **Alert** button
(Alt+A: crosses/above/below a price, once or every time), date-range presets
(1D 5D 1M 3M 6M YTD 1Y 3Y 5Y 10Y All, switching to a fitting timeframe), infinite scroll back
through history, and live candles and quotes over WebSocket. It has 50 indicators (searchable
picker, inputs and per-line colour/width/visibility) and custom formula indicators. A ☀ Day / ☾ Night
button in the top bar switches the theme (day by default; the choice is remembered). The
Lightweight Charts attribution the licence requires (notice + link to tradingview.com) is on the **About**
page (footer link); the in-chart logo and footer credit are off.

Drawing tools (left toolbar): trend line, ray, extended line, arrow, horizontal line/ray, vertical
line, parallel channel, rectangle, Fibonacci retracement, brush, text and a measure tool. Use
click-click or drag. A magnet snaps to OHLC, and lock, hide and clear apply to all drawings. Select a
drawing to recolour, resize, lock, clone or delete it (Del). Esc cancels. Drawings are stored as (time, price), so they
keep their place across zoom and timeframes, and are saved per symbol (`/drawings`).
The sidebar has a watchlist with live quotes, alerts (shown as price lines, with toast
notifications) and "Explain this chart" (AI key levels are drawn on the chart).

## Tests

```powershell
powershell -ExecutionPolicy Bypass -File .
un-tests.ps1          # everything (~1.5 min)
powershell -ExecutionPolicy Bypass -File .
un-tests.ps1 -SkipE2E # without the browser tests
```

| Suite | Where | What it guards |
|---|---|---|
| Backend, pytest (224) | `backend/tests/` | data import (daily/hourly/names/CLI), every timeframe incl. US sessions and paging, all 50 indicators vs reference maths, formula language and its sandbox, live bars and WebSocket, alerts, watchlists, AI analyst (fake LLM), drawings API, chart patterns (parity with swingbt when present) |
| Frontend unit, Vitest (65) | `frontend/tests/unit/` | date-range presets (incl. month-end clamping), time zones and DST, drawing geometry, time<->pixel mapping and hit-testing, indicator labels/styles, number formats |
| Browser end-to-end, Playwright (19) | `frontend/tests/e2e/` | every user flow in a real browser: load, live ticks, symbol search, timeframe menu, ranges, theme, indicators and settings, custom formulas, drawing tools and saving, pattern menu and counts, alerts |

The end-to-end tests start their own backend on :8010 with a fresh, seeded synthetic database and a dev server
on :5180, so your data and running servers are never touched. Locally they use the installed Microsoft Edge;
GitHub Actions (`.github/workflows/ci.yml`) runs all three suites on every push with Chromium.

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

**Local end-of-day CSVs** (real history): set `DATA_SOURCE=eod` and `EOD_DIR` (a
`market_data_daily` folder with `<EXCHANGE>/bhavcopy_adjusted/<EXCHANGE>_YYYYMMDD.csv`), then
`python -m app.cli import-eod [--exchanges NSE,BSE,NASDAQ,NYSE]`. With `EOD_HOURLY_DIR` (a
`market_data_hourly` folder with `<EXCHANGE>/<EXCHANGE>_YYYYMMDD_HHMM.csv`) it also loads 1h bars,
which 1h/2h/4h charts then use (`--only hourly` reloads just those; NSE: 7.4M bars, 2024-10 onwards,
~150s). Each import replaces the
exchange's history (adjusted prices get rewritten on splits). It also removes symbols that aren't
in the files, along with their watchlist entries and alerts. NSE: 4.9M bars, 3,683 symbols,
2016-11 onwards, in about 85s. There is no minute data, so 1m-30m charts show just today's
simulated ticks. Those ticks start from the last real close and are never saved.

Company names come from the exchanges' public listing files (NSE equity/SME/ETF lists,
NASDAQ Trader's `nasdaqlisted`/`otherlisted`), downloaded on import into `backend/data/names/`,
plus `tickers.csv` for BSE (`python -m app.cli update-names` refreshes them). US intraday bars use
New York session times (09:30, DST-aware) and are shown in New York time. Daily bars of every
exchange are dated by their own trading date.

**Kite Connect** (private prototyping only — its data may not be redistributed):
set `KITE_API_KEY`/`KITE_API_SECRET`, run `python -m app.cli kite-login` each morning
for `KITE_ACCESS_TOKEN`, then `python -m app.cli load-symbols` and `load-candles`.

**AI analyst:** set `ANTHROPIC_API_KEY`. Uses `claude-opus-5-5` at effort `medium` with
server-side refusal fallback; tune with `AI_MODEL` / `AI_EFFORT`. `POST /ai/explain` with
`"dry_run": true` returns the exact context the model would see, without an API call.

## API overview

| Endpoint | Purpose |
|---|---|
| `GET /symbols?q=&exchange=` · `GET /symbols/{symbol}` · `GET /exchanges` | Symbol search (ticker or company name; exact ticker first) / lookup (`NSE:RELIANCE`, bare `RELIANCE` = NSE) / exchanges with counts |
| `GET/PUT /drawings?symbol=` | The user's chart drawings for a symbol |
| `GET /history?symbol&tf&limit&to&from` | Column arrays `t,o,h,l,c,v` + `next_to` cursor. TFs: 1m 3m 5m 15m 30m 1h 2h 4h 1D 1W 1M 1Y |
| `GET /indicators` · `GET /indicators/{id}?symbol&tf&...params` | Indicator metadata (category, params, plots) / values aligned with `/history` (warm-up handled server-side). Custom ones are `custom-<n>` |
| `/custom-indicators` (CRUD) · `POST /custom-indicators/check` | Formula indicators (see below) |
| `WS /ws` | `{"op":"subscribe","symbol","tf"}` → `subscribed`, `bar`, `quote`, `alert` messages |
| `GET /quotes?symbols=a,b` | Latest quotes (starts streaming if needed) |
| `/watchlists` (CRUD) · `/watchlists/{id}/items` | Watchlists |
| `/alerts` (CRUD) · `GET /alerts/events` | Price alerts: `crosses_above`, `crosses_below`, `above`, `below` |
| `POST /ai/explain` | `{symbol, tf, to?, dry_run?}` → structured analysis + disclaimer + context |

## Chart patterns

The **◈ Patterns** menu turns 19 patterns on or off: support/resistance, pocket pivot, change in
character, wedge pop, MA crossback, base and break, cup with handle, VCP, flat base, high tight flag,
bad break recovery, 1-2-3, oversold shaper, three-touch trendline, mini coil, natural reaction, squat,
momentum pullback and quiet breakout. The rules are the owner's rulebook code, copied unchanged from
`TranscriptExtract/swingbt/rules/` into `backend/app/patterns/rules.py` by
`python -m app.patterns.sync_rules`. Their features (`features.py`) port `swingbt/indicators.py`.
`tests/test_m12_patterns.py` checks bar-by-bar parity with swingbt when that folder exists.
`GET /patterns/scan?symbol&tf&ids&limit` returns markers, shapes (base, pivot, contractions, lines,
coil box) and S/R levels. Only hits that pass the rule's hard checks are shown.

## Patterns formed today (dashboard)

**▦ Patterns today** in the top bar lists every stock of an exchange whose latest **daily** or **weekly** bar formed
one of the rulebook patterns. Pick one pattern or several and match **any** of them or **all together**. You can
also set a minimum 50-bar median turnover (₹ Cr / $M) and search. Clicking a stock opens its chart with those
patterns switched on. Results are screened in one pass per exchange (bars read in batches; the rules run on the last
bar only: NSE ~45 s daily, ~65 s weekly). They are saved in `backend/data/screens/` and refreshed with **Screen now**
or `python -m app.cli screen --exchanges NSE --tf "1D,1W"`; schedule the command after the nightly import.
Weekly = the current week so far. API: `GET /screener/patterns-today?exchange&tf`, `POST .../run`, `GET .../job`.

## SwingScanner connection

Set `SCANNER_DIR` in `.env` to the SwingScanner folder (the one with `SwingScanner.exe`). The sidebar's
**Scanner** tab then lists its past scans (read from its `scans` folder, also while the scanner is closed). It shows
the buy setups with entry (the signal day's close), SL and quantity, plus all signals and near misses (with the rule
that failed). A guide explains each setup in the scan, using the scanner's own `explain.py` text read as data.
Clicking a row opens the chart with Entry/SL lines and the setup's pattern switched on. While `SwingScanner.exe` is
running (`SCANNER_URL`, default :8765), **Run scan** starts a new scan and shows its progress. The app never
writes into the scanner's folders. API: `GET /scanner`, `/scanner/scans/{id}`, `/scanner/setups`,
`/scanner/portfolio`, `POST /scanner/run`, `GET /scanner/job`.

## Custom indicators (formula language)

Inputs are named numbers; each plot is `name = expression`, and a plot can use the plots above it:

```
macd = ema(close, fast) - ema(close, slow)
sig  = ema(macd, 9)
hist = macd - sig            # style: histogram
```

Series `open high low close volume hl2 hlc3 ohlc4`; operators `+ - * / % **`, comparisons
(1/0), `and or not`; history `close[1]`; functions `sma ema wma rma hma dema tema linreg rsi roc
change stdev highest lowest sum atr vwma crossover crossunder where nz abs sqrt log exp max min`.
Parsing uses Python's `ast` with a whitelist of node types and names, and evaluation is a small
numpy interpreter, so nothing reaches `eval`. This is meant as the first slice of our own
scripting language, not a final syntax (`backend/app/indicators/formula.py`).

## Layout

```
backend/app/
  marketdata/   sources (synthetic, kite), loader, timeframes + resampling, history paging
  indicators/   numpy math (core, extra), registry of 50 (params, plots, warm-up), formula.py (custom)
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
  IndicatorDialogs.tsx  indicator picker, settings (inputs + style), custom formula editor
  ranges.ts / theme.ts  date-range presets; day/night theme
  drawings.ts / DrawingTools.tsx  drawing model, time<->pixel mapping, canvas primitive, toolbar + mouse handling
```

Frontend by hand: `cd frontend; npm install; npm run dev` (backend must be on :8000);
`npm run build` type-checks and bundles.
