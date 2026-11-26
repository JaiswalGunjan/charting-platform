# Charting Platform (TradingView-style) — project context for Claude Code

This project continues a planning session held in the Claude app on 22–23 Nov 2026.
The full blueprint lives in `docs/BLUEPRINT.md` (also kept as a Claude doc:
https://claude.ai/artifact/2GCEK547Ebu3baWhQpa3gB). Read it before proposing work.

## What we are building
An AI-native charting and trading-analysis platform in the same product category as
TradingView: real-time charts, indicators, drawing tools, screener, alerts, watchlists,
paper trading, broker integration, community ideas. Markets: NSE/BSE first, plus US
stocks and crypto.

Hard rule: copy the category, not the product. Own brand, own UI, own scripting-language
syntax. No scraping TradingView, no reuse of its brand or design assets, no line-for-line
Pine Script clone.

Differentiator: AI from day one — AI chart analyst, natural-language screener,
strategy-from-English → script → backtest, trading copilot (LangGraph agents, Langfuse
observability).

## Decisions so far
- Chart engine: TradingView Lightweight Charts (Apache 2.0, attribution to TradingView
  required) for the MVP; custom Canvas/WebGL engine later. The footer credit is off at the owner's request
  (24 Nov 2026); the in-chart TradingView logo (bottom left) is on again at his request (25 Nov 2026). The licence still requires its attribution notice and a link to
  tradingview.com on a page available to users: that is the About dialog (footer "About" link,
  App.tsx). Never remove it.
- Frontend: React + TypeScript + Vite (Next.js only for public SEO pages).
- Hot path services (feed handlers, WebSocket fan-out, alerts): Go.
- Product/quant/AI services: Python (FastAPI).
- Kafka as the tick bus; ClickHouse for ticks/candles; PostgreSQL for product data;
  Redis for live quotes and forming bars.
- Data: Zerodha Kite Connect (₹500/month, live + historical) for private prototyping
  ONLY — its data may not be redistributed. Public launch needs an NSE/BSE-authorised
  data vendor licence; US data via Massive (formerly Polygon.io).

## Suggested first milestone (private prototype, 6–8 weeks)
Lightweight Charts + FastAPI + PostgreSQL/TimescaleDB + Redis + Kite Connect:
1. Symbol master + historical candle loader (NSE equities, 1m and 1D).
2. `GET /history` API with paging for infinite scroll.
3. Live ticks over WebSocket → forming-bar updates in Redis → client chart.
4. 10 built-in indicators (SMA, EMA, RSI, MACD, BB, VWAP, Supertrend…).
5. Watchlist + simple price alerts.
6. First AI feature: "explain this chart" from OHLCV + indicator context.

## Implementation status (24 Nov 2026)
Milestones M1–M12 are built: backend (`backend/`, 304 pytest tests; 71 Vitest + 24 Playwright tests in `frontend/tests`) and frontend (`frontend/`,
React 19 + Vite 7 + lightweight-charts 5.3, v5 `addSeries(XSeries, opts, paneIndex)` API).
`run-demo.ps1` starts everything. See README.md for the milestone table and API overview.
Node is a portable copy in `.tools/node` (gitignored); put it on PATH before running npm.
Real data: the owner keeps adjusted daily bhavcopies (NSE/BSE/NASDAQ/NYSE, 2016+) in a local
`market_data_daily` folder and adjusted hourly bars (2024-10+) in `market_data_hourly`;
`DATA_SOURCE=eod` + `import-eod` loads both (backend/app/marketdata/eod.py).
In that mode there are no ticks: quotes are the last real close (StaticTickSource; simulated ticks were removed at the
owner's request 25 Nov 2026, opt-in with SIMULATE_TICKS=true, which the e2e tests use); nothing is persisted.
Chart patterns: `backend/app/patterns/rules.py` is a generated verbatim copy of the owner's rule functions in
`TranscriptExtract/swingbt/rules/` (bases.py, shapers.py, pocket_pivot.py, cycle.py, support_resistance.py), so
the chart marks what his backtester trades; regenerate with `python -m app.patterns.sync_rules`, never hand-edit.
Pattern Screener (was "patterns today"): `app/patterns/screener.py` (screen per exchange, 1D/1W and session date,
saved as JSON in backend/data/screens, EX_TF_DATE.json + EX_TF.json = newest; `app.cli screen [--date|--days]`), API
`app/api/screener.py`, UI `frontend/src/PatternsToday.tsx` on its own page (`ScreenerPage.tsx`, `/?page=screener`).
Brand: our own logo, `frontend/src/Logo.tsx` = `frontend/public/favicon.svg` (tab icon).
Setup Screener page: `frontend/src/SetupPage.tsx` (`/?page=setups`, the ScannerPanel full width); pages are routed in main.tsx.
The chart page (App.tsx) has no alerts and no scanner tab (removed at the owner's request, 25 Nov 2026): the sidebar is
the watchlist; scanner links (/?scan=...&symbol=...&setup=...) open the signal on the chart directly. The SwingScanner tab is named "Setup Scanner".
SwingScanner: `backend/app/api/scanner.py` reads the owner's scanner bundle (`SCANNER_DIR`: scans/*/signals.csv,
near_misses.csv, market.json, portfolio.json) and proxies run/job to its local server (:8765); read-only.
It flags US data that holds only stubs (`data_warnings`): SwingScanner.exe of 18 Nov fails on it; the source does not.
Its HTML report is served restyled in our theme by `app/api/scanner_report.py` (theme in `app/static/scanner_report.*`,
files read, never written; the report's own /api actions are passed to the scanner's server).
Scans keep no chart pages: `drop_charts` removes `<scan>/charts` after an app-run scan and `app.cli scanner-slim`
for all (owner's choice, 26 Nov 2026; the only thing the app deletes in the scanner's folder).
Prototype-stage choices, all cheap to reverse: SQLite default via `DATABASE_URL` (Postgres/
Timescale ready), in-memory live store unless `REDIS_URL`, single local user (`user_id=1`,
no auth yet), JSON over WebSocket (binary frames later), live pipeline in Python (Go later).
Stored bases are 1m, 1h and 1D; other timeframes are resampled on read, aligned to the 09:15 IST
session open in the exchange's own time zone (`Market` in timeframes.py: NSE/BSE 09:15 IST, NASDAQ/
NYSE 09:30 New York, DST-aware); daily+ bars are stamped at IST midnight of their trading date for
every exchange. 1h/2h/4h use stored 1h bars when a symbol has them, else 1m. Drawings are a
Lightweight Charts series primitive (`frontend/src/drawings.ts`), stored per symbol in (time, price). 50 built-in indicators
live in `app/indicators/registry.py`. Custom indicators use a whitelisted-AST formula language
(`app/indicators/formula.py`), the agreed first slice of our own scripting language (chosen by the
owner 24 Nov 2026 over a no-code composer). Its syntax is still open to redesign.

Daily jobs: `scripts/daily_update.py --market NSE|US` (Task Scheduler via `scripts/register_daily_update.ps1`: NSE weekdays
18:30, US daily 08:00 India time); NSE holidays from nseindia.com, US holidays from NYSE rules; EOD downloader with
random start + 5x~5 and 5x~10 minute retries, then import, setup scan and pattern screens.

## Tests
`run-tests.ps1` runs backend pytest, frontend type check + Vitest and Playwright end-to-end (isolated seeded backend
:8010 + Vite :5180, local Edge). Run it before every commit; add tests with every feature (unit tests for logic,
an e2e flow for anything user-visible). CI: `.github/workflows/ci.yml`.

## Working preferences
- No "buy" / "sell" wording anywhere on screen (SEBI: no buy/sell recommendations; owner's rule, 25 Nov 2026).
  A signal to enter is a **Breakout**, to exit a **Breakdown**; other uses become entry / exit words. Text from the
  rulebook, the SwingScanner and the generated pattern rules goes through `app/wording.py` (`neutral`, `neutral_all`,
  `neutral_html`) on its way out; their files are never edited. `tests/test_m18_wording.py` sweeps every text answer.
- The owner is an experienced AI architect (LangGraph, Langfuse, A2A, RAG); skip
  basic explanations of those.
- Keep secrets (Kite API key/secret, data-vendor keys) in `.env`, never committed.
- Ask before choosing between options that are expensive to reverse (data vendor,
  database, scripting-language design).
