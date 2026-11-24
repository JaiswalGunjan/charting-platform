# Charting Platform Blueprint (TradingView-style)

Nov 22, 2026 · Gunjan
Live doc: https://claude.ai/artifact/2GCEK547Ebu3baWhQpa3gB

## Overview

Build a web and mobile charting and social-trading platform with the same *category* of features as TradingView: real-time charts, indicators, a scripting language, screeners, alerts, watchlists, paper trading, broker integration and a community feed. Start with Indian markets (NSE/BSE) plus US stocks and crypto, then expand.

**Copy the product category, not the product.** Use your own name, logo, UI design and scripting-language syntax. Do not scrape TradingView data, reuse its brand, clone its UI pixel-for-pixel, or reimplement Pine Script line-for-line. Features and ideas are not protected; trademarks, code and design assets are.

**Differentiator to aim for:** an AI-native platform (natural-language screeners, AI chart analysis, strategy generation and backtesting from plain English). This is where a newcomer can beat an incumbent, and it plays to an AI-architect skill set.

## Feature map

Ship a sharp MVP in about 4 months, then layer scripting, social and brokers. Each phase should be usable on its own.

| Area | MVP (months 0–4) | v2 (months 5–9) | v3 (months 10–18) |
| --- | --- | --- | --- |
| Charts | Candles, line, bar, area, Heikin-Ashi; 1m to 1M timeframes; zoom/pan; crosshair | Multi-chart layouts (2/4/8), Renko, range bars, volume profile | Replay mode, footprint/order-flow charts |
| Indicators | 30 built-ins (SMA, EMA, RSI, MACD, BB, VWAP, Supertrend…) | 100+ built-ins, multiple panes, compare symbols | Community indicators marketplace |
| Drawing tools | Trendline, horizontal line, ray, rectangle, Fibonacci retracement, text | 50+ tools, templates, sync across devices | Pattern auto-detection |
| Data | NSE/BSE equities + indices, US stocks, top crypto; real-time + 10y history | F&O, options chains, forex, commodities (MCX) | Fundamentals, economic calendar, news |
| Watchlists & alerts | Watchlists, price alerts (push/email) | Indicator and drawing-based alerts, webhooks | Alert-driven automation to brokers |
| Screener | Basic filters (price, volume, % change, RSI) | Fundamental + technical screener, saved screens | Natural-language AI screener |
| Scripting | — | Own scripting language v1, editor, backtester | Strategy optimizer, publish/sell scripts |
| Trading | Paper trading | Broker integration (Zerodha, Upstox, Angel One, Dhan) | US brokers (Alpaca, IBKR), options strategy builder |
| Social | — | Ideas (published chart snapshots), follow, comments | Live streams, chat rooms |
| AI | AI chart summary ("what is this chart showing?") | Strategy-from-English to script, backtest explain | Personal AI trading copilot with memory |
| Platforms | Web (desktop-first, responsive) | iOS + Android apps | Desktop app (Electron/Tauri) |
| Monetization | Free tier + Pro | Pro+, Premium; ads on free tier | Marketplace revenue share, B2B chart widgets |

## System architecture

Five layers, one rule: every tick enters once, flows through Kafka, and is fanned out to every consumer.

```
1. DATA SOURCES     Indian exchanges (NSE/BSE vendor feed) | US markets (Massive) | Crypto exchanges (public WebSockets) | Broker APIs (orders: Kite, Upstox)
        │
2. INGEST & STREAM  Feed handlers (Go) ──► Kafka (replayable tick bus) ──► Candle builder (ticks → 1m…1D) | Alerts engine (checks every tick)
        │
3. STORAGE          ClickHouse (ticks, candles) | PostgreSQL (users, layouts, scripts) | Redis (live quotes, forming bars) | Object storage (archives, snapshots)
        │
4. SERVICES         API gateway (REST, GraphQL, auth) | WebSocket gateway (Go fan-out per symbol) | Quant services (screener, backtests) | AI services (LangGraph agents, RAG)
        │
5. CLIENTS          Web app (React + own chart engine) | Mobile apps (React Native, same engine) | Notifications (push, email, Telegram)
```

Go feed handlers normalise vendor ticks and publish them to Kafka. Candle builders and the alerts engine consume that stream and write to ClickHouse and Redis. The WebSocket gateway pushes live bars to clients; orders travel the other way, from clients through the API gateway to broker APIs.

## Tech stack

Recommended picks are first in each row. The core rule: hot path (ticks, candles, charts) in fast compiled code; everything else in boring, productive tools.

| Layer | Recommended | Alternatives | Why |
| --- | --- | --- | --- |
| Web frontend | React + TypeScript + Vite, Zustand for state, TanStack Query | Next.js (for SEO pages: symbol pages, ideas), SvelteKit | Huge ecosystem; Next.js only for public SEO pages |
| Chart engine | Lightweight Charts (Apache 2.0) for MVP, then a custom Canvas/WebGL engine | KLineChart, SciChart (paid), D3 + Canvas | Fastest start; custom engine later for drawing tools, replay, 8-chart layouts |
| Chart rendering (custom) | HTML5 Canvas 2D + OffscreenCanvas in Web Workers; WebGL2 for footprint/heatmaps | WebGPU (future) | Smooth 60 fps with 100k+ bars |
| Mobile | React Native (Expo) with the web chart in a WebView, or native Skia | Flutter | Reuse the same chart engine across web and mobile |
| API gateway | Kong or Envoy; REST + GraphQL (for app screens) | AWS API Gateway, Traefik | Auth, rate limits, routing |
| Core services | Go (market data, alerts, WebSocket fan-out) | Rust (if ultra-low latency), Java/Kotlin | High concurrency, low memory, simple deploys |
| Product services | Python (FastAPI) for AI, screener, backtests; Node/NestJS for social/CRUD | Django | Python owns the quant + AI ecosystem |
| Real-time push | WebSockets via a Go gateway; Centrifugo as a shortcut | Socket.IO, NATS WebSocket, Ably/Pusher (managed) | Millions of concurrent subscriptions |
| Message bus | Apache Kafka (or Redpanda) | NATS JetStream, Pulsar | Replayable tick stream feeding candles, alerts, storage |
| Stream processing | Go consumers for candle aggregation; Apache Flink later | Kafka Streams, Bytewax | Build 1s/1m/5m… candles from ticks |
| Time-series DB | ClickHouse (ticks + candles) | TimescaleDB, QuestDB, kdb+ (expensive) | Billions of rows, fast range scans |
| Relational DB | PostgreSQL | MySQL | Users, subscriptions, watchlists, layouts, ideas |
| Cache | Redis (latest quotes, sessions, rate limits) | Dragonfly, KeyDB | Sub-ms reads for quote snapshots |
| Search | Meilisearch or OpenSearch (symbol search, ideas) | Typesense, Elasticsearch | Instant symbol lookup |
| Object storage | S3 / Cloudflare R2 (chart snapshots, flat-file history) | MinIO (self-hosted) | Cheap bulk storage |
| Scripting runtime | Own DSL → compiled to WASM or JS, run in a sandbox (V8 isolates / Wasmtime) | Lua sandbox, Python via Pyodide | Safe execution of user code at scale |
| Backtesting | Vectorized engine in Python (NumPy/Polars) or Rust | Backtrader, vectorbt (study, don't embed) | Fast strategy runs |
| AI | LLM API + LangGraph agents, pgvector/Qdrant for RAG, Langfuse for observability | LlamaIndex, Weaviate | Chart analysis, NL screener, strategy generation |
| Auth | Keycloak or Auth0/Clerk; OAuth (Google, Apple) + OTP | Supabase Auth, Firebase Auth | MFA, social login |
| Payments | Razorpay (India), Stripe (global) | Cashfree, Paddle | Subscriptions, UPI autopay |
| Notifications | Firebase Cloud Messaging, APNs, Amazon SES / Resend, Telegram bot | OneSignal | Alert delivery |
| Infra | Kubernetes (EKS/GKE) + Terraform; Cloudflare CDN + WAF | Nomad, Fly.io for early stage | Scale, DDoS protection |
| Observability | Prometheus + Grafana, Loki, Tempo/OpenTelemetry, Sentry | Datadog, New Relic | Track feed latency end to end |
| CI/CD | GitHub Actions + Argo CD | GitLab CI | GitOps deploys |

## Market data sourcing

Data licensing, not code, is the hardest and most expensive part. Showing prices to the public needs a **redistribution licence**; a personal API key is not enough.

| Source | Markets | Cost (as checked, Nov 2026) | Use it for | Catch |
| --- | --- | --- | --- | --- |
| Zerodha Kite Connect | NSE, BSE, MCX | ₹500/month per API key; includes WebSocket live data and historical candles | Prototyping, your own testing, broker order routing | Zerodha says displaying or redistributing this data on external platforms violates exchange data vending policies |
| NSE/BSE authorised data vendors (e.g. TrueData, Global Datafeeds) or NSE directly | NSE, BSE, MCX | Quote needed; exchange fees per display user | Production Indian real-time data for your users | Exchange audits, per-user reporting, delayed vs real-time tiers |
| Massive (formerly Polygon.io) | US stocks, options, indices, forex, crypto | Stocks Starter $29/month; Stocks Advanced (real-time, all US exchanges) $199/month | US data prototype, then a business/redistribution plan | Individual plans are not for redistribution; business plans are priced separately |
| Crypto exchange APIs (Binance, Coinbase, Bybit, CoinDCX) | Crypto | Free public feeds | Crypto charts from day one | Check each exchange's display terms |
| Fundamentals/news (FMP, Finnhub, EODHD, Indian fundamentals providers) | Global + India | $20–$500/month typical | Fundamentals, earnings, news | Licence terms vary widely |

**Practical path:** build and test with Kite Connect + Massive + free crypto feeds; before public launch, sign a redistribution agreement with an NSE/BSE-authorised vendor and a Massive business plan. Start the free tier on 15-minute delayed data, which is far cheaper to license, and keep real-time for paid users.

Open question: exact exchange display fees for NSE/BSE real-time data need a vendor quote.

## Data model and storage

Split storage by access pattern: ticks and candles in ClickHouse, user data in PostgreSQL, live state in Redis.

**ClickHouse (market data)**

- `ticks(symbol_id, ts, price, qty, side, exchange)` — MergeTree, partitioned by day, ordered by (symbol_id, ts); 30–90 days hot, then to S3 as Parquet
- `candles_1m(symbol_id, ts, o, h, l, c, v, oi)` — built from ticks; materialized views roll up to 5m, 15m, 1h, 1D
- `corporate_actions(symbol_id, ex_date, type, ratio)` — splits/bonus/dividends for adjusted history

**PostgreSQL (product data)**

- `users`, `subscriptions`, `payments`, `devices`
- `symbols(id, ticker, exchange, type, isin, lot_size, tick_size, session_id)`, `trading_sessions`, `holidays`
- `watchlists`, `watchlist_items`
- `chart_layouts(user_id, name, json_state)` — drawings, indicators, panes stored as versioned JSON
- `alerts(user_id, symbol_id, condition_json, channels, status)`
- `scripts(owner_id, source, compiled_wasm_url, visibility, version)`
- `ideas`, `comments`, `follows`, `likes`
- `paper_accounts`, `paper_orders`, `paper_positions`

**Redis**

- `quote:{symbol}` — last price, change, volume (hash)
- `bar:{symbol}:{tf}` — the current forming candle
- Pub/sub channels per symbol for the WebSocket gateway; rate-limit counters; sessions

**Chart history API:** `GET /history?symbol=NSE:RELIANCE&tf=5m&from=&to=&limit=` returns compact arrays (or a binary format such as Arrow/Protobuf) so the client can page back infinitely as the user scrolls.

## Scripting language and indicator engine

Design your own small, series-oriented language rather than copying Pine Script; the concept (every variable is a time series, scripts run once per bar) is a common pattern, but syntax and built-in names should be yours.

1. **Language design:** typed, series-first DSL with `plot`, `input`, `alert`, `strategy.entry/exit`, history access (`close[1]`), and a standard library (`ta.ema`, `ta.rsi`…).
2. **Compiler pipeline:** parser (ANTLR or hand-written Pratt parser in TypeScript/Rust) → AST → type check → IR → JavaScript or WASM.
3. **Execution:** run in the browser for chart indicators (Web Worker, so the UI never freezes); run server-side for alerts, screeners and backtests in sandboxed V8 isolates or Wasmtime with CPU/memory limits.
4. **Editor:** Monaco editor with syntax highlighting, autocomplete, inline errors (Language Server Protocol).
5. **Backtester:** bar-by-bar event loop with commissions, slippage, Indian charges (STT, GST, stamp duty), position sizing; reports for equity curve, drawdown, win rate, Sharpe.
6. **Bonus:** let users also write strategies in Python (server-side only) to attract quant users.

## AI layer

The AI layer is the wedge: features an incumbent bolts on, you build in from day one.

| Feature | How it works | Stack |
| --- | --- | --- |
| AI chart analyst | Send OHLCV + computed indicators + drawn levels as structured context (and optionally a chart image) to an LLM; it explains trend, levels, patterns | LLM API with vision, tool calls into the indicator service |
| Natural-language screener | "Nifty 500 stocks above 200 EMA with RSI below 40 and rising volume" → LLM translates to a screener query → runs on ClickHouse | LangGraph agent, schema-constrained output (JSON), query validator |
| Strategy from English | Plain-English idea → script in your DSL → auto-backtest → explain results | Code-generation agent + compiler as a checker; retry loop on compile errors |
| News and earnings summariser | RAG over news, filings, concall transcripts per symbol | Vector DB (pgvector/Qdrant), embeddings, reranker |
| Trading copilot | Agent with tools: get_chart, run_screener, backtest, set_alert, place_paper_order | LangGraph, A2A for multi-agent, Langfuse for traces and evals |

**Guardrails:** keep AI outputs educational ("analysis", not "buy this"), log every response, run evals on hallucinated numbers, and never let an agent place real orders without explicit user confirmation.

## Scale, performance and reliability targets

Design for these numbers from the start, even if the MVP runs on a few servers.

| Metric | Target |
| --- | --- |
| Tick to screen latency (p95) | < 250 ms |
| Chart first paint with 1,000 bars | < 1 s |
| Smooth pan/zoom | 60 fps with 100k bars loaded |
| Alert evaluation delay (p95) | < 2 s after the triggering tick |
| Concurrent WebSocket connections (year 1) | 100k, horizontally scalable to millions |
| Uptime during market hours | 99.95% |

**Key techniques**

- Fan-out: one upstream subscription per symbol; the gateway multicasts to all users watching it
- Throttle and conflate updates to ~4–10 per second per symbol on the client; send only deltas
- Binary WebSocket frames (Protobuf/MessagePack) instead of JSON
- Cache recent candles in Redis and on the CDN edge for popular symbols (NIFTY, BANKNIFTY, BTCUSDT)
- Alerts engine: index alerts by symbol and price bucket so each tick checks only nearby alerts
- Market-open spike at 9:15 IST: pre-scale pods before open; load-test that exact minute
- Multi-AZ deployment, feed-handler hot standby, Kafka replication factor 3

## Team and cost estimate

An MVP needs about 8 people for 4 months; a v2 team grows to about 15. Figures below are approximate planning estimates for an India-based team, not quotes.

| Role | MVP | v2 | Focus |
| --- | --- | --- | --- |
| Tech lead / architect | 1 | 1 | Architecture, data pipeline, AI design |
| Frontend (chart + UI) | 2 | 4 | Chart engine, drawing tools, layouts |
| Backend (Go) | 2 | 3 | Feed handlers, WebSocket gateway, alerts |
| Backend (Python) | 1 | 2 | Screener, backtester, AI services |
| Mobile | 0 | 2 | React Native apps |
| DevOps / SRE | 1 | 1 | Kubernetes, observability, market-hours on-call |
| Product designer | 1 | 1 | UX for dense trading screens |
| QA | 0 | 1 | Data accuracy, load tests |

| Monthly running cost (approximate) | MVP / beta | v2 (~50k users) |
| --- | --- | --- |
| Cloud infra (compute, ClickHouse, Kafka, Redis, CDN) | ₹50k–₹1.5L | ₹4L–₹10L |
| Market data licences | ₹15k–₹50k (dev/delayed) | ₹5L+ (real-time redistribution; vendor quote) |
| LLM / AI APIs | ₹20k–₹50k | ₹2L–₹6L (scales with usage; cache aggressively) |
| Team (above) | ₹15L–₹25L | ₹35L–₹60L |

**Fastest solo/small-team path:** Lightweight Charts + FastAPI + PostgreSQL/TimescaleDB + Redis + Kite Connect for a private prototype in 6–8 weeks, then raise or recruit before paying for redistribution licences.

## Legal and compliance checklist

Clear these before public launch; most are cheap early and expensive late. Not legal advice — confirm each with counsel.

- [ ] Own brand name and logo; trademark search in India (and US/UAE if expanding)
- [ ] Exchange data redistribution agreements (NSE/BSE via an authorised vendor; US via a business data plan)
- [ ] Lightweight Charts licence: Apache 2.0 and requires naming TradingView as the product creator with an attribution notice (the built-in attribution logo option satisfies the link requirement); plan a custom engine if you want no attribution
- [ ] SEBI: avoid giving buy/sell recommendations without a Research Analyst / Investment Adviser registration; keep AI output educational with clear disclaimers
- [ ] Algo/API trading rules for retail (SEBI framework, broker-side registration of algos) before enabling automated order placement
- [ ] DPDP Act 2023 (India data protection): consent, privacy notice, data deletion
- [ ] GST on subscriptions; payment-gateway KYC
- [ ] Terms of use, risk disclosure, community moderation policy for ideas/chat

## Sources

- Lightweight Charts documentation — licence and attribution: https://tradingview.github.io/lightweight-charts/docs
- Lightweight Charts on npm (Apache-2.0): https://www.npmjs.com/package/lightweight-charts
- Zerodha: Kite Connect API FAQs (pricing, redistribution): https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs
- Zerodha: historical and live market data plan: https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/historical-data-and-live-market-data-payment-plan
- Massive vs Tiingo (Massive plan prices): https://massive.com/compare/massive-vs-tiingo
- Polygon.io is now Massive: https://massive.com/blog/case-study-fey

Cost, team and performance figures not linked above are planning estimates.
