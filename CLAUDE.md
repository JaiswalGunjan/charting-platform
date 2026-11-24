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
  required) for the MVP; custom Canvas/WebGL engine later.
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

## Implementation status (23 Nov 2026)
Milestones M1–M7 are built: backend (`backend/`, 68 pytest tests) and frontend (`frontend/`,
React 19 + Vite 7 + lightweight-charts 5.3, v5 `addSeries(XSeries, opts, paneIndex)` API).
`run-demo.ps1` starts everything. See README.md for the milestone table and API overview.
Node is a portable copy in `.tools/node` (gitignored); put it on PATH before running npm.
Prototype-stage choices, all cheap to reverse: SQLite default via `DATABASE_URL` (Postgres/
Timescale ready), in-memory live store unless `REDIS_URL`, single local user (`user_id=1`,
no auth yet), JSON over WebSocket (binary frames later), live pipeline in Python (Go later).
Only 1m and 1D candles are stored; all other timeframes are resampled on read, aligned to
the 09:15 IST session open.

## Working preferences
- The owner is an experienced AI architect (LangGraph, Langfuse, A2A, RAG); skip
  basic explanations of those.
- Keep secrets (Kite API key/secret, data-vendor keys) in `.env`, never committed.
- Ask before choosing between options that are expensive to reverse (data vendor,
  database, scripting-language design).
