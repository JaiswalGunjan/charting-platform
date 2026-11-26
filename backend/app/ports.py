"""The parts of Charting Lab that can be replaced, as interfaces ("ports").

The product (the web API in app/api, the CLI, the daily job) talks only to these interfaces. Each part has one or more
implementations ("adapters", in app/adapters or elsewhere), chosen by a setting through app/providers.py:

    part                 setting            built-in adapters
    setup scanner        SETUP_SCANNER      swingscanner (the owner's SwingScanner), none
    pattern detector     PATTERN_ENGINE     rulebook (the generated rulebook rules + chart features)
    screen store         SCREEN_STORE       json (one JSON file per screen, backend/data/screens)
    bar store            BAR_STORE          sql (SQLAlchemy: SQLite or PostgreSQL/TimescaleDB by DATABASE_URL)
    market data source   DATA_SOURCE        synthetic, kite, eod (app/marketdata/base.MarketDataSource)

A setting may also name an adapter by its import path, "package.module:Class", so a new one plugs in without editing
any product code. docs/ARCHITECTURE.md says how to write one.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from app.marketdata.base import Bar


# ---------------------------------------------------------------------------------------------------- setup scanner
class ScannerError(Exception):
    """A setup scanner could not do what was asked; the message is shown to the user."""


class ScannerOffline(ScannerError):
    """The scanner (or the service behind it) is not running."""


class ScanRefused(ScannerError):
    """The scanner will not run this scan (already saved, no data for that market, ...)."""


@runtime_checkable
class SetupScanner(Protocol):
    """Something that finds trade setups for a market on a session and keeps each run as a saved scan.

    A scan id is opaque to the product. Shapes (dicts, so they travel as JSON unchanged):

    status():  {name, title, configured, online, msg?, markets: [{market, ok, last, dates, warning?}], ...}
    scans():   [{id, market, date, valid, near, regime, symbols}], newest first
    scan(id):  {id, market, date, regime, risk_mult, rules, symbols, capital, risk_pct, max_alloc_pct, report_href?,
                signals: [Row], near_misses: [Row], setups: {code: {name, what, why}},
                market_note: {title, lines, rules: [{id, text}]} | None, score_note: str}
    Row:       {symbol "EX:TICKER", ticker, setup, setups [codes], setup_name, pattern (chart pattern id or ""),
                valid, buy (a breakout today), status, close, entry, stop, risk, stop_pct, score, size_mult, rank,
                shares, value, stage, phase, base_len, rs60, dist_10d_high_pct, res_touches, notes, stop_note,
                stop_rule, reject, weak, soft, date, chart, chart_href}
    Text is the scanner's own: the product removes buy / sell words and rulebook codes before it is shown.
    """

    name: str
    title: str

    def status(self) -> dict: ...
    def scans(self) -> list[dict]: ...
    def scan(self, scan_id: str, near: bool = True) -> dict | None: ...
    def setups(self) -> dict[str, dict]: ...
    def explain(self, scan_id: str, ticker: str, setup: str, near: bool = False, equity: float | None = None,
                risk_pct: float | None = None) -> dict | None:
        """{title, sections: [{title, lines}], ...} for one row of a scan; None when the row is not there."""
    def portfolio(self) -> dict: ...
    def run(self, market: str, day: str | None = None) -> dict:
        """Start a scan; raises ScannerOffline / ScanRefused."""
    def job(self, since: int = 0) -> dict:
        """The running scan: {state: running|done|error, log, ...}; raises ScannerOffline."""
    def slim(self) -> tuple[int, int]:
        """Drop what saved scans do not need: (scans slimmed, bytes freed)."""
    def routers(self) -> list:
        """Extra FastAPI routers the scanner brings (e.g. its own report pages); [] for none."""


# ------------------------------------------------------------------------------------------------- pattern detector
@runtime_checkable
class PatternEngine(Protocol):
    """Finds chart patterns in a series of bars (numpy arrays t, o, h, l, c, v; t = epoch seconds, ascending).

    catalog(): [{id, title, group, short, color, rule, about, summary}], the patterns it knows (the chart's menu)
    scan():    {markers: [{pattern, t, text, notes, rules, ...}], shapes: [...], levels: [...]} for the bars from
               index `first` on; the bars before it are warm-up history. Rules must be causal: a bar's result never
               depends on later bars (the screener runs them on the last bar only).
    """

    name: str
    warmup: int                          # bars of history needed before the first bar marked

    def catalog(self) -> list[dict]: ...
    def ids(self) -> set[str]: ...
    def signal_ids(self) -> set[str]:
        """The patterns that are a signal on a bar (what the Pattern Screener looks for)."""
    def scan(self, t, o, h, l, c, v, ids: set[str], first: int = 0) -> dict: ...  # noqa: E741


# ----------------------------------------------------------------------------------------------------- screen store
@runtime_checkable
class ScreenStore(Protocol):
    """Keeps pattern screens. A screen = every symbol of an exchange screened on one session and timeframe:
    {exchange, tf, session "YYYY-MM-DD", last_session (epoch s), as_of, rows: [...], scanned, symbols, ...}."""

    name: str

    def read(self, exchange: str, tf: str, day: str | None = None) -> dict | None:
        """The screen saved for exactly session `day`; None = the newest screen."""
    def dates(self, exchange: str, tf: str) -> list[str]:
        """Sessions with a saved screen, newest first."""
    def write(self, res: dict, newest: bool) -> dict:
        """Save a screen; newest=True makes it the default (newest) one too."""


# -------------------------------------------------------------------------------------------------------- bar store
@runtime_checkable
class BarStore(Protocol):
    """Stored price bars of the base timeframes (1m, 1h, 1D), times in epoch seconds. Reads return numpy arrays, one
    row per bar, columns as named by `cols` (default ts, o, h, l, c, v), in time order. `session` is the caller's
    unit of work (a SQLAlchemy Session for the SQL store); a store that has none ignores it."""

    name: str

    def has(self, session: Any, symbol_id: int, tf: str) -> bool: ...
    def read_latest(self, session: Any, symbol_id: int, tf: str, limit: int, to: int | None = None,
                    frm: int | None = None, cols: Sequence[str] = ...) -> Any:
        """The newest `limit` bars with time in [frm, to)."""
    def read_after(self, session: Any, symbol_id: int, tf: str, frm: int, limit: int, cols: Sequence[str] = ...) -> Any:
        """The first `limit` bars with time >= frm."""
    def upsert(self, session: Any, symbol_id: int, tf: str, bars: Sequence[Bar]) -> int: ...
    def read_many(self, session: Any, symbol_ids: Sequence[int], tf: str, since: int, until: int,
                  cols: Sequence[str] = ...) -> Any:
        """Bars of many symbols with time in [since, until]: rows (symbol id, *cols), by symbol then time."""
    def last_time(self, session: Any, exchange: str, tf: str, upto: int | None = None) -> int | None: ...
    def times(self, session: Any, exchange: str, tf: str, since: int) -> list[int]: ...
    def replace_exchange(self, session: Any, exchange: str, drop_tfs: Sequence[str], tf: str, symbol_ids: Any,
                         data: dict) -> int:
        """Bulk load: drop the exchange's bars of `drop_tfs`, store `data` (ts, o, h, l, c, v arrays) as `tf`."""
    def delete_bars(self, session: Any, exchange: str, tfs: Sequence[str], since: int | None = None,
                    until: int | None = None, symbol_ids: Sequence[int] | None = None) -> None:
        """Drop the exchange's bars of `tfs` in [since, until] (re-importing a range, e.g. after a split); with
        `symbol_ids`, only those symbols' bars."""
    def append(self, session: Any, tf: str, symbol_ids: Any, data: dict) -> int:
        """Bulk insert of bars not stored yet (the chunked import path: an exchange-month at a time)."""
