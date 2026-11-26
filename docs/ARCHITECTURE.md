# Architecture: a product layer with replaceable parts

Charting Lab's own logic (the product layer) never names the tools it runs on, or the markets it covers. Each tool
sits behind a small interface (a *port*, `backend/app/ports.py`) and is plugged in by a setting
(`backend/app/providers.py`) or a config file. Each market is one entry in the market registry. Replacing a tool,
adding a second one beside it, or adding a market changes a setting, an adapter or a registry entry, not the product
code.

```
 UI (frontend/)   ── contracts: docs/api/openapi.json (HTTP) · docs/api/websocket.md (live) · GET /markets
                        │
 product layer    ── app/api/*  app/patterns/screener.py  app/marketdata/history.py  app/live/service.py  app/cli.py
                        │  talks only to ports and the market registry
 ports            ── SetupScanner(s) · PatternEngine(s) · ScreenStore · BarStore (per timeframe) · TickSource (per
                        │  exchange) · MarketDataSource · LiveStore
 adapters         ── swingscanner │ rulebook │ json │ sql (SQLite / PostgreSQL+TimescaleDB) │ kite, synthetic, static
 market registry  ── backend/app/markets.toml (time zone, session, currency of every exchange)
 daily job        ── scripts/daily_update.py (calendar, retries, order)  +  scripts/daily_update.toml (the tools)
```

## The parts

| Part | Setting | Built in | Several at once | Proven by (tests) |
|---|---|---|---|---|
| Setup scanner | `SETUP_SCANNER` | `swingscanner`, `none` | `SETUP_SCANNERS=swingscanner,pkg.mod:Fast`: side by side, picked by name (`?scanner=`), a picker on the Setup Screener | `test_m21_ports.py` (fake scanners), e2e "several setup scanners" |
| Pattern detector | `PATTERN_ENGINE` | `rulebook` | `PATTERN_ENGINES=rulebook,pkg.mod:Candles`: one combined catalog; each id belongs to one engine | `test_m21_ports.py` (an "up day" engine alone and combined with the rulebook) |
| Screen storage | `SCREEN_STORE` | `json` (`backend/data/screens` or `SCREENS_DIR`) | one store | in-memory store test |
| Price-bar storage | `BAR_STORE` | `sql` (the `candles` table; SQLite or PostgreSQL/TimescaleDB by `DATABASE_URL`), `timescale` (1m bars, last 2 years) | `BAR_STORES=1m=timescale`: a store per stored timeframe | in-memory store serves identical charts and screens; minute bars routed to their own store |
| Live feed | `TICK_SOURCES` (and `DATA_SOURCE`, `SIMULATE_TICKS` for the default) | `kite`, `synthetic`, `static` | a feed per exchange: `NSE=kite,NYSE=pkg.mod:Ticks` | `test_m23_live_feeds.py` |
| Live quote store | `REDIS_URL` | memory, Redis | one store | `test_m4_live.py` |
| Market data source | `DATA_SOURCE` | `synthetic`, `kite`, `eod` (local CSVs: `app.cli import-eod`) | one store | existing suites |
| Markets | `MARKETS_FILE` (default `backend/app/markets.toml`) | NSE, BSE, NYSE, NASDAQ | any number | `test_m21_ports.py` (a London market added), `markets.test.ts` |
| Daily tools | `scripts/daily_update.toml` | EOD downloader, `import-eod`, SwingScanner | a market = an entry with its exchanges, calendar and scan profile | `test_m20_daily_update.py` (another vendor and scanner from config alone) |
| UI | none | React app in `frontend/` | not applicable | `test_m22_api_contract.py` (any API change fails until the contract is refreshed) |

A setting takes a built-in name, or any class by import path (`package.module:Class`, made with no arguments). The
class must have its port's methods: `isinstance(obj, SetupScanner)` checks that, and the tests check it for every
built-in adapter.

### Setup scanners

The Setup Screener API (`app/api/scanner.py`) asks a scanner for:
- `status()`, `scans()`
- `scan(id)`, `explain(id, ticker, setup)`, `setups()`, `portfolio()`
- `run(market, day)`, `job(since)`
- `slim()`, `routers()`

The shapes are on the port. The product does its own part:
- ranks the rows;
- adds company names;
- removes buy / sell words and rulebook codes from the text it shows.

Several scanners run side by side:
- every endpoint takes `scanner` (a name; default: the first);
- `GET /scanner` lists them all (`scanners`);
- the Setup Screener shows a picker when there is more than one;
- chart links carry `&scanner=`.

Scan ids belong to their scanner. Each scanner may add routes under a prefix of its own through `routers()`: the
SwingScanner adds its HTML report under `/scanner/report/...`. Everything SwingScanner-specific lives in
`app/adapters/swingscanner/`.

### Pattern engines

`scan(t, o, h, l, c, v, ids, first)` returns markers, shapes and levels for numpy arrays of bars. Rules must be causal,
because the screener runs them on the last bar only. `warmup` is the history the rules need, and `signal_ids()` are
the patterns the screener looks for.

`PATTERN_ENGINES` combines engines (`app/patterns/combined.py`):
- the catalog is the union, each entry tagged with its `engine`;
- a scan asks each engine only for its own ids;
- the warm-up is the largest of them;
- two engines claiming one id fail at start-up, so an id always means the same pattern.

The chart's pattern menu already groups and searches patterns, so a long catalog stays usable.

### Markets

`backend/app/markets.toml` holds every market's code, time zone, session open and close, currency, chart time-zone
label, and whether the Pattern Screener lists it. `GET /markets` serves it, and the UI loads it before its first
render (`frontend/src/markets.ts`, with a built-in copy of today's four as a fallback). What reads it:
- intraday bucketing (`market_for`);
- the default market of a bare ticker;
- exchange ordering;
- the chart's time zones (any IANA zone, DST-aware);
- currencies of positions and turnover (crore for rupees, millions otherwise);
- the exchange lists of both screeners.

Adding a market takes:
1. its entry in `markets.toml`;
2. its data (an import, or a `MarketDataSource`);
3. for the daily job, an entry in `scripts/daily_update.toml` with a holiday calendar;
4. optionally a live feed in `TICK_SOURCES`.

Daily bars stay stamped at IST midnight of their trading date for every market (a storage convention that encodes
the date).

### Price bars

Only the bar store touches stored bars (`app/marketdata/barstore.py` for SQL). Reads return numpy arrays of base bars
(1m, 1h, 1D); resampling, session alignment and paging stay in the product (`app/marketdata/history.py`). The
operations:
- `has`
- `read_latest`, `read_after`, `read_many`
- `last_time`, `times`
- `upsert`
- `append` and `delete_bars`, the chunked bulk path: one exchange-month of minute bars at a time keeps memory flat,
  and a re-import (after a split) replaces just its range
- `replace_exchange`

`BAR_STORES` routes a stored timeframe to its own store (`RoutedBarStore`), e.g. minute bars to a column store while
daily and hourly bars stay in SQL. Charts read 1h/2h/4h from stored hourly bars and daily+ from daily bars, so only
charts below an hour touch minute bars.

### Live data

A feed per exchange (`TICK_SOURCES`, `RoutedTickSource`); each feed says what it delivers (`live`, `simulated`,
`none`). Closed 1-minute bars of `live` feeds are saved through the bar store; simulated ones never are, over real
history. `GET /health` → `feeds` tells the UI each market's feed, and the chart's badge shows the feed of the
symbol's own exchange (Live / Simulated ticks / Last close). The WebSocket messages are a contract
(`docs/api/websocket.md`), so the Python live service can be swapped for the planned Go fan-out over Kafka and Redis
without touching the UI.

### The daily job

`scripts/daily_update.py` owns:
- the calendars (NSE holidays, NYSE rules);
- which session a run updates;
- the retries (5 × ~5 minutes, then 5 × ~10 minutes, random);
- the logs and the order of the steps.

`scripts/daily_update.toml` names the tools: `download` (with a `done` file per exchange), `import`,
`scan.<profile>`, `slim` and `screen`. A new market is a `[markets.X]` entry. A market with a new kind of calendar
needs its holiday rule in the script (the one market-specific code left there).

## Scale: 10–12 markets, 10 years of daily and minute bars

These are rough sizes, to plan with. They assume about 3,000 actively traded symbols per market (US markets list
more), about 375 one-minute bars a session and 250 sessions a year.

| | Rows | SQLite | PostgreSQL + TimescaleDB, compressed | Column store (ClickHouse) |
|---|---|---|---|---|
| Daily bars, 12 markets × 10 years | ~90 million | workable, slow to import | ~5 GB, fine | not needed |
| Hourly bars | ~0.6 billion | no | ~30 GB, fine | either |
| Minute bars | **~30–40 billion** | no | ~1.5–2 TB at the ~55 bytes a row measured in our trial (4.93 M bars in 271 MB with indexes); heavy on one server | ~0.2–0.4 TB (5–10 bytes a row with delta codecs), fast range scans |

What follows from this:
1. **Minute bars need their own store.** The seam is in place: `BAR_STORES=1m=<store>`. The product database
   (symbols, watchlists, drawings, alerts) and the daily and hourly bars can stay in PostgreSQL/TimescaleDB.
2. **Decided (owner, 26 Nov 2026): minute bars go into PostgreSQL + TimescaleDB, the last 2 years**
   (`BAR_STORES=1m=timescale`, `app/marketdata/minute_store.py`). The store works as follows:
   - its own hypertable `candles_1m` in weekly chunks;
   - a compression policy after 30 days (`MINUTE_COMPRESS_AFTER_DAYS`);
   - a retention policy that drops whole chunks older than 730 days (`MINUTE_RETENTION_DAYS`);
   - bars older than the window are not written at all;
   - it has its own connection (`MINUTE_DATABASE_URL`), so the main database can stay SQLite.

   At 2 years that is about 6–8 billion rows for 12 markets, roughly 0.3–0.4 TB compressed.
   US minute bars come from Alpaca's Parquet files (`app/marketdata/alpaca_minute.py`, `app.cli import-minute`):
   - regular session only (09:30–16:00 New York);
   - put on our daily bars' basis by a per-day factor: Alpaca's official as-traded close / our close, which is exact
     between corporate actions; after the daily file's last day, the factor carries on and changes only on a
     sustained, self-consistent jump of more than 8% over 3 days (a split);
   - resumable, as it records each file it imported.
   Checked on 20 NASDAQ symbols: the day's last minute close matches our daily close (median gap 0–0.3%, last trade
   against the official close), and liquid names match the stored hourly bars in 99%+ of hours. Thin names match in
   about 85% of hours, because Alpaca's 30-minute bars (our hourly bars' source) count trades the 1-minute bars do
   not. Maintenance:
   `python -m app.cli minute-store [--compress] [--prune]` (the policies also run on their own while the server is
   up). If 10 years of minute bars are wanted later, a ClickHouse store is one more adapter behind the same
   `BAR_STORES` setting; tests: `backend/tests/test_m24_minute_store.py` (needs `TEST_PG_URL`).
3. **Imports go a chunk at a time** (`delete_bars` + `append` per exchange-month); one exchange's whole minute
   history at once would not fit in memory. The minute CSV layout is not known yet; its reader goes beside
   `app/marketdata/eod.py` and writes through the bar store.
4. **Pattern Screener:** daily and weekly screens read daily bars only, so minute data does not slow them. 12
   markets × 2 timeframes at about 45–65 seconds each is roughly 20 minutes a night; the screens run per market, so
   they can run in parallel.
5. **More patterns:** the chart's pattern counts run every pattern on the loaded bars. With many more patterns they
   should be cached per (symbol, timeframe, last bar) or computed in the nightly screen.
6. **Live data:** one feed per market or vendor (`TICK_SOURCES`). Beyond one server, the WebSocket contract stays
   and the service behind it moves to the planned Go + Kafka + Redis path.

## Writing an adapter: a checklist

1. Write the class with the port's methods (`backend/app/ports.py`). The fakes in `backend/tests/test_m21_ports.py`
   are small working examples of every part.
2. Point the setting at it (`SETUP_SCANNERS=...,package.module:Class`, `BAR_STORES=1m=package.module:Class`,
   `TICK_SOURCES=NYSE=package.module:Class`, ...), or add a short name to `REGISTRY` in `app/providers.py`.
3. Add a test that plugs it in with `providers.use(part, adapter)` and calls the API, as `test_m21_ports.py` does.
4. Run `run-tests.ps1`.
