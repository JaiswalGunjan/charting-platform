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
page (footer link), and the TradingView logo shows at the bottom left of the chart; the footer credit is off.
Buttons at the bottom middle of the chart zoom in / out (keeping the latest bars) and move left / right; moving
stops at the first bar and just after the latest bar.
Without a live feed (Kite) prices are the last real close; `SIMULATE_TICKS=true` turns on random-walk demo
ticks (the end-to-end tests use it).

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
| Backend, pytest (393, + 5 more on PostgreSQL) | `backend/tests/` | data import (daily/hourly/names/CLI), every timeframe incl. US sessions and paging, all 50 indicators vs reference maths, formula language and its sandbox, live bars and WebSocket, alerts, watchlists, AI analyst (fake LLM), drawings API, chart patterns (parity with swingbt when present), screeners, the daily job, replaceable parts (fake adapters) and the API contract |
| Frontend unit, Vitest (78) | `frontend/tests/unit/` | date-range presets (incl. month-end clamping), time zones and DST, drawing geometry, time<->pixel mapping and hit-testing, indicator labels/styles, number formats |
| Browser end-to-end, Playwright (31) | `frontend/tests/e2e/` | every user flow in a real browser: load, live ticks, symbol search, timeframe menu, ranges, theme, indicators and settings, custom formulas, drawing tools and saving, pattern menu and counts, alerts |

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

**Kite Connect**:
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

## Pattern Screener (dashboard)

**▦ Pattern Screener ↗** in the top bar opens the screener as its own page in a new tab (`/?page=screener`). Pick
**1 Date** (calendar over the saved sessions; a weekend or holiday shows the session before it), **2 Exchange**
(NSE, NYSE, NASDAQ) and **3 Timeframe** (daily or weekly); it lists every stock whose bar of that session formed
one of the rulebook patterns. A stock opens in a Charting Lab tab (`/?symbol=NSE:TCS&tf=1D&patterns=pp`). Pick one
pattern or several (a stock must have formed **all** of them), set a minimum average turnover (₹ Cr / $M: the average of typical price x volume over the last 20 sessions;
**HTQ** marks a stock whose 20-day average is at its highest of the last quarter, and **HTQ only** keeps just those) and
search. Clicking a stock opens its chart with those patterns switched on. Results are screened in one pass per exchange
(bars read in batches; the rules run on the screened bar only: NSE ~45 s daily, ~65 s weekly). Each screen is saved in
`backend/data/screens/` under its session date (`NSE_1D_2026-11-20.json`; `NSE_1D.json` = the newest) and refreshed
with **Update screen** or:

    python -m app.cli screen --exchanges NSE,NYSE,NASDAQ --tf "1D,1W"            # latest session
    python -m app.cli screen --exchanges NSE --tf 1D --date 2026-11-20            # one past session
    python -m app.cli screen --exchanges NSE,NYSE,NASDAQ --tf "1D,1W" --days 30   # backfill what is missing

**▶ Run pattern screen** on the page screens the picked date (or the newest session with data) only when it
has no saved screen; a saved one shows **✓ Screened** and the API refuses it (409). Schedule the first after the nightly import. Weekly = the week up to that session (one screen per week in a
backfill). API: `GET /screener/patterns-today?exchange&tf[&date]` (with the saved `dates`), `POST .../run`
(`{exchange, tf, date?}`), `GET .../job`.

## SwingScanner connection

**▤ Setup Screener** (next to the Pattern Screener in the top bar) opens the scanner view below as its own page
(`/?page=setups`, same tab); a signal there opens its chart in a Charting Lab tab. The SwingScanner is the setup
scanner in use (`SETUP_SCANNER=swingscanner`); its code is all in `backend/app/adapters/swingscanner/`, and another
scanner can take its place (see [Replaceable parts](#replaceable-parts)).

Set `SCANNER_DIR` in `.env` to the SwingScanner folder (the one with `SwingScanner.exe`). The **Setup
Screener** page then shows its saved scans: pick **1 Date** (a calendar over the saved scans; a weekend or holiday
shows the session before it) and **2 Market** (NSE / NYSE / NASDAQ). Scans are read from its `scans` folder, also
while the scanner is closed; new scans are run in SwingScanner itself. It shows
the buy signals with entry (the signal day's close), SL and a quantity sized for the portfolio you enter (the full amount: NSE in rupees,
default ₹10,00,000; NYSE/NASDAQ in dollars, default $100,000) and your risk per trade (default 1%), plus near misses (with the hard rule that failed). Each row shows the company name; the symbol is a link to its chart (Entry / SL lines, the setup's pattern on).
Clicking a row opens its "why this trade" summary right under it (click again to close); it starts with the setup
itself (the scanner's own `explain.py` text, read as data). A search box (symbol or company) and setup chips filter
the table; several ticked setups match with AND (every ticked setup formed on the stock that day: its own, or one the scanner lists
with it, shown as "+PP" tags). When the market rule stops new entries (index impulse (-,-), a strong bear regime, or the index
below its 10-day low) a note above the table says which rule, and sizes are still shown at the full multiplier
(marked "if allowed"). The bottom of the page lists what the priority score is made of.
**▶ Run setup scan** (SwingScanner.exe running) scans the picked date or the newest data session only when no scan
of it is saved (a saved one shows **✓ Scanned**; `POST /scanner/run` refuses it, 409). If a US market's per-symbol
folder holds only stub files, `GET /scanner` flags it: SwingScanner.exe of 18 Nov 2026 then fails with 'no symbol
produced bars'; its current source falls back to the day files, so rebuild the bundle.) **full report ↗** opens
the scanner's HTML report restyled in the app's day/night theme (`/scanner/report/...`; its Watch / Enter trade /
Refresh buttons are passed to the scanner's server). Saved scans keep their data (signals, near misses, market, report page) but not the scanner's chart pages
(about 95% of a scan's size; Charting Lab draws its own charts): a scan run from the app has its `charts/` folder
removed when it finishes, and `python -m app.cli scanner-slim` does the same for scans run elsewhere
(`SCANNER_KEEP_CHARTS=true` keeps them). Apart from that, the app never writes into the scanner's folders. API:
`GET /scanner`, `/scanner/scans/{id}`, `/scanner/scans/{id}/explain`, `/scanner/setups`, `/scanner/portfolio`,
`POST /scanner/run`, `GET /scanner/job`, `GET|POST /scanner/report/...`.

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

## Sign-in and users

Nothing opens without signing in: every API route, the live WebSocket and the scanner's report pages need a signed-in
user, and any link (`/?symbol=…`, `/?page=setups`, `/?scan=…`) shows the sign-in page first, then returns to that link.

* **Google** (`AUTH_MODE=google`): "Sign in with Google" (OpenID Connect, basic scopes `openid email profile`: free, no
  Google review, no user limit once the app is published; 100 listed test users while it is in Testing). Set up once
  in Google Cloud Console: an OAuth client ID of type *Web application* with the redirect URI
  `http://localhost:5173/api/auth/google/callback` (and the live site's later), then in `.env`:
  `AUTH_MODE=google`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SESSION_SECRET` (a long random string),
  `ADMIN_EMAILS` (comma list), and on HTTPS `COOKIE_SECURE=true`, `PUBLIC_URL=https://…`.
* **Local** (`AUTH_MODE=local`, development and the tests): this computer is the built-in local user (id 1, the owner
  of the data from before sign-in existed); refused for any other address.
* Each user has their own watchlists, drawings, custom indicators and alerts (a fired alert goes to its owner's tabs
  only). Admins (`ADMIN_EMAILS`) run scans and screens by hand (the nightly job runs them for everyone) and see the
  **Users** page (`/?page=users`, the account menu): every user with sign-ins, last sign-in and activity, active time,
  days active, requests, last IP and place, and per user the stocks opened, features used, recent sign-ins (with
  refused ones) and daily activity; **Download CSV** for a spreadsheet; make admin, disable (signs out everywhere).
* What is recorded: Google's profile (name, email, verified, picture, language, Workspace domain, Google's user id);
  every sign-in (time, IP, browser, approximate location from DB-IP's free IP to City Lite database, kept on this
  server: `python -m app.cli update-geoip` downloads it, the nightly job refreshes it monthly; credited as "IP
  Geolocation by DB-IP" (CC BY 4.0) on the Users page);
  activity counted per request (active time = gaps under 5 minutes). Phone is not from Google (it needs a reviewed
  scope): a field the user can fill. The sign-in page says what is recorded; `python -m app.cli prune-activity`
  deletes records older than `ACTIVITY_RETENTION_DAYS` (365).
* Sessions: a random token in an HttpOnly, SameSite=Lax cookie (30 days, `SESSION_DAYS`); only its SHA-256 is stored;
  sign-out ends it at once. After sign-in only a path on this site is followed (no open redirect).

## Admin dashboard

`/?page=admin` (account menu → **Admin**; admins only, `ADMIN_EMAILS`):

* **Run**, for a market (NSE, or US = NYSE + NASDAQ) and a session (default: the latest):
  **⭳ Download EOD data** (download + import), **▤ Run setup screener**, **▦ Run pattern screener**,
  **⟳ Full update** (all of it, like the nightly job). Each runs the nightly job's own steps
  (`scripts/daily_update.py --only … --now`: the download tries once, at once) as a separate process; one job at a
  time; its output shows live, and the last 30 jobs (who ran them, how long, the result, their output) are kept.
* **Data**: per exchange its symbols, last daily and minute bar, last setup scan, last daily and weekly pattern screen.
* **Users** (`/?page=users`): see Sign-in and users.

Anyone else gets "Not available" on `/?page=admin` and `/?page=users`, whatever link they use (nothing of those pages
loads), the API refuses every `/admin/*` call (403) and the Run buttons, and no Run buttons or admin menu are shown.

## Replaceable parts

The product layer names none of the tools it runs on. Each sits behind a small interface (`backend/app/ports.py`)
and is chosen by a setting in `.env` (a built-in name, or any class as `package.module:Class`):

| Part | Setting | Built in | Several |
|---|---|---|---|
| Setup scanner | `SETUP_SCANNER` | `swingscanner`, `none` | `SETUP_SCANNERS` (side by side, picker on the Setup Screener) |
| Pattern detector | `PATTERN_ENGINE` | `rulebook` | `PATTERN_ENGINES` (one combined catalog) |
| Screen storage | `SCREEN_STORE` | `json` | |
| Price-bar storage | `BAR_STORE` | `sql` (SQLite or PostgreSQL/TimescaleDB by `DATABASE_URL`) | `BAR_STORES` (a store per timeframe, e.g. minute bars apart) |
| Live feed | `TICK_SOURCES` | `kite`, `synthetic`, `static` | a feed per exchange |
| Markets | `backend/app/markets.toml` (`GET /markets`) | NSE, BSE, NYSE, NASDAQ | a market = one entry |
| Market data source | `DATA_SOURCE` | `synthetic`, `kite`, `eod` | |
| Daily tools (downloader, import, scanner) | `scripts/daily_update.toml` | EOD downloader, `import-eod`, SwingScanner | |
| UI | `docs/api/openapi.json` and `docs/api/websocket.md` (the contracts; the HTTP one is checked by a test) | React app | |

Minute bars live in PostgreSQL + TimescaleDB, the last 2 years (`BAR_STORES=1m=timescale`, `MINUTE_DATABASE_URL`;
`run-demo.ps1` starts the local server; `python -m app.cli minute-store` shows its size and applies its compression
and retention policies). US minute bars come from Alpaca (`scripts/alpaca_minute.py` downloads them as Parquet files
into `EOD_Market_Data/market_data_minute/<EX>/`); `python -m app.cli import-minute --exchange NASDAQ` loads them:
regular session only (09:30-16:00 New York), put on the basis of our daily bars (price / factor, volume x factor; the
factor is Alpaca's official as-traded close / our daily close, exact between corporate actions), resumable (unchanged
files are skipped, so it can run while the download is still going). How to write a replacement, what each interface promises, and the plan for 10–12 markets:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
The tests plug in a fake of each (`backend/tests/test_m21_ports.py`) to prove the product works with it.

## Layout

```
backend/app/
  ports.py      the interfaces of the replaceable parts; providers.py picks an adapter for each from settings
  adapters/     swingscanner/ (the SwingScanner: folders, server, explanations, report), null.py (parts switched off)
  marketdata/   sources (synthetic, kite, eod), loader, barstore.py (the only SQL on bars), timeframes + resampling,
                history paging
  patterns/     rulebook rules (generated), engine (PatternEngine), screener, store.py (ScreenStore: JSON files)
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

## Wording (SEBI)

The app shows no "buy" / "sell" recommendations: a signal to enter is a **Breakout**, to exit a **Breakdown**, and other
uses become entry / exit words (e.g. "the entry price", "how the position exits"). Text that comes from the rulebook,
the SwingScanner or the generated pattern rules is rewritten by `backend/app/wording.py` on its way to the screen
(API answers and the restyled report); the source files are not changed.

## Daily updates (scheduled)

`scripts/daily_update.py --market NSE|US` runs from Windows Task Scheduler (register, change or remove both jobs with
`scripts/register_daily_update.ps1 [-NseAt 18:30] [-UsAt 08:00] [-Remove]`):

| Job | When (India time) | Session | Closed days skipped |
|---|---|---|---|
| Charting Lab - NSE daily update | weekdays 18:30 | today's NSE session | weekends, NSE trading holidays (NSE's own list from nseindia.com, cached per year in `backend/data/nse_holidays.json`) |
| Charting Lab - US daily update | every day 08:00 | the New York session that closed overnight | New York weekends, US market holidays (NYSE rules, computed) |

The tools each step runs are named only in `scripts/daily_update.toml` (another vendor or scanner = an edit
there). Today, each run downloads the day with the EOD downloader (`EOD_Market_Data/eod_downloader.py --exchanges NSE` or
`NYSE NASDAQ`) until every day file (`market_data_daily/<EX>/bhavcopy_adjusted/<EX>_<YYYYMMDD>.csv`) exists: the first try
starts a random 0-8 minutes late, then 5 retries ~5 minutes apart and 5 retries ~10 minutes apart (each wait +/-20% at
random), then it gives up for the day. After a download it imports the day into Charting Lab, runs the setup scan(s)
(NSE with `SwingScanner.exe --run-module swingbt.scan`; US from the scanner's source in `.tools/scanvenv`, as the 18 Nov
exe fails on the US stub files) and drops their chart pages, then the pattern screens (daily and weekly).

Logs: `backend/data/logs/daily_<market>_<date>.log`, the last result in `daily_<market>_status.json`. By hand:
`python scripts/daily_update.py --market NSE [--date YYYY-MM-DD] [--dry-run]`.

## PostgreSQL + TimescaleDB (local trial)

A portable PostgreSQL 18.7 with TimescaleDB 2.32.1 lives in `.tools/pgsql` (data in `.tools/pgdata`, git-ignored; no
Windows service, this PC only, port 5433, small settings: 256 MB cache, 20 connections). It runs only when started:

    powershell -ExecutionPolicy Bypass -File scripts\pg_local.ps1 start | stop | status
    python scripts/sqlite_to_postgres.py --exchanges NSE --tf 1D            # copy bars (SQLite is only read)
    $env:DATABASE_URL="postgresql+psycopg://charting@127.0.0.1:5433/charting"   # run the app on it
    $env:TEST_PG_URL="postgresql+psycopg://charting@127.0.0.1:5433/postgres"    # run the backend tests on it

Step 1 (NSE daily, 4.9 M bars): copied in 74 s; 817 MB -> 271 MB after compressing chunks older than 30 days; all
backend tests pass on it; about 350 MB of memory while running (85 MB private + the 256 MB shared cache). Same requests
on both: chart loads 30-60 ms each way; 20 users loading charts at once: PostgreSQL 52/s with 95% under 0.56 s, SQLite
38/s with 95% under 1.3 s.
