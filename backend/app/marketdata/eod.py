"""Bulk import of end-of-day bars from a local `market_data_daily` folder.

Layout read (one CSV per trading day, back-adjusted for corporate actions):

    <root>/<EXCHANGE>/bhavcopy_adjusted/<EXCHANGE>_YYYYMMDD.csv
        <TICKER>,<PER>,<DTYYYYMMDD>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>
    Names: see app/marketdata/names.py (public exchange lists + tickers.csv for BSE)

Adjusted history is rewritten whenever a split/bonus lands, so an import always
replaces the exchange's daily bars wholesale instead of appending. It also replaces
the exchange's symbol list: symbols that are not in the files (e.g. synthetic demo
symbols) are deleted along with their candles, watchlist entries and alerts.
"""
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.marketdata.base import SymbolInfo
from app.marketdata.loader import upsert_symbols
from app.marketdata.names import NameInfo
from app.marketdata.names import load as _load_names
from app.marketdata.names import lookup as name_lookup
from app.marketdata.timeframes import market_for
from app.models import Candle, Symbol


def load_names(exchange: str, cache: Path | None, daily_root: Path | None) -> dict[str, NameInfo]:
    return _load_names(exchange, cache, daily_root)

log = logging.getLogger(__name__)

IST_OFFSET_S = 19800
TICK_SIZE = {"NSE": 0.05, "BSE": 0.01, "NASDAQ": 0.01, "NYSE": 0.01}
_CHUNK = 20_000
_COLS = ["ticker", "per", "date", "o", "h", "l", "c", "v"]


@dataclass
class ImportResult:
    exchange: str
    files: int
    symbols: int
    bars: int
    removed_symbols: int
    first_date: str
    last_date: str
    seconds: float


def exchange_files(root: Path, exchange: str) -> list[Path]:
    d = root / exchange / "bhavcopy_adjusted"
    if not d.is_dir():
        raise FileNotFoundError(f"no folder {d}")
    return sorted(d.glob(f"{exchange}_*.csv"))


def read_exchange(root: Path, exchange: str) -> tuple[pd.DataFrame, int]:
    """All daily bars of one exchange, one row per (ticker, date), sorted."""
    files = exchange_files(root, exchange)
    if not files:
        raise FileNotFoundError(f"no {exchange}_*.csv files under {root / exchange / 'bhavcopy_adjusted'}")
    frames = [
        pd.read_csv(f, header=0, names=_COLS, usecols=[0, 2, 3, 4, 5, 6, 7],
                    dtype={"ticker": str, "date": str}, keep_default_na=False, na_values=[""])
        for f in files
    ]
    df = pd.concat(frames, ignore_index=True)
    df["ticker"] = df["ticker"].str.strip().str.upper()
    df = df.dropna(subset=["ticker", "o", "h", "l", "c"])
    df = df[(df["ticker"] != "") & (df["c"] > 0)]
    df["v"] = df["v"].fillna(0)
    # bar time = IST midnight of the trading day (same convention as day_ts / Kite)
    days = pd.to_datetime(df["date"], format="%Y%m%d")
    df["ts"] = (days.to_numpy(dtype="datetime64[s]").astype(np.int64) - IST_OFFSET_S)
    df = df.drop_duplicates(["ticker", "ts"], keep="last").sort_values(["ticker", "ts"], ignore_index=True)
    return df, len(files)


def symbol_infos(exchange: str, tickers: list[str], names: dict[str, NameInfo]) -> list[SymbolInfo]:
    out = []
    for t in tickers:
        n = name_lookup(names, t, exchange)
        out.append(SymbolInfo(exchange=exchange, ticker=t, name=n.name if n else t, type=n.type if n else "EQ",
                              isin=n.isin if n else None, tick_size=TICK_SIZE.get(exchange, 0.01)))
    return out


def apply_names(session: Session, exchange: str, names: dict[str, NameInfo]) -> int:
    """Refresh names/types of the exchange's existing symbols (no candle changes). Returns how many got a name."""
    tickers = session.scalars(select(Symbol.ticker).where(Symbol.exchange == exchange)).all()
    infos = symbol_infos(exchange, list(tickers), names)
    upsert_symbols(session, infos)
    return sum(1 for i in infos if i.name != i.ticker)


def import_exchange(session: Session, root: Path, exchange: str,
                    names: dict[str, NameInfo] | None = None) -> ImportResult:
    t0 = time.perf_counter()
    exchange = exchange.upper()
    df, nfiles = read_exchange(root, exchange)
    names = names if names is not None else load_names(exchange, None, root)
    tickers = df["ticker"].unique().tolist()
    log.info("%s: read %d files, %d bars, %d tickers in %.1fs",
             exchange, nfiles, len(df), len(tickers), time.perf_counter() - t0)

    # symbols: drop the ones not in the files, upsert the rest
    stale = session.scalars(select(Symbol.id).where(Symbol.exchange == exchange,
                                                    Symbol.ticker.not_in(tickers))).all()
    for i in range(0, len(stale), 500):
        session.execute(delete(Symbol).where(Symbol.id.in_(stale[i:i + 500])))
    session.commit()
    upsert_symbols(session, symbol_infos(exchange, tickers, names))
    ids = dict(session.execute(select(Symbol.ticker, Symbol.id).where(Symbol.exchange == exchange)).all())

    # candles: replace the exchange's daily bars (and any 1m bars, which would be stale
    # relative to re-adjusted daily prices); imported hourly bars are kept
    _replace_candles(session, exchange, ("1D", "1m"), "1D", df, ids)

    dates = df["date"]
    res = ImportResult(exchange, nfiles, len(tickers), len(df), len(stale),
                       f"{dates.min()[:4]}-{dates.min()[4:6]}-{dates.min()[6:]}",
                       f"{dates.max()[:4]}-{dates.max()[4:6]}-{dates.max()[6:]}",
                       round(time.perf_counter() - t0, 1))
    log.info("%s: imported %s", exchange, res)
    return res


def _replace_candles(session: Session, exchange: str, drop_tfs: tuple[str, ...], tf: str,
                     df: pd.DataFrame, ids: dict[str, int]) -> None:
    """Delete the exchange's bars of `drop_tfs`, then bulk-insert df (ticker, ts, o..v) as `tf`."""
    session.execute(delete(Candle).where(
        Candle.symbol_id.in_(select(Symbol.id).where(Symbol.exchange == exchange)),
        Candle.tf.in_(drop_tfs)))
    sid = df["ticker"].map(ids).to_numpy(dtype=np.int64)
    cols = {k: df[k].to_numpy() for k in ("ts", "o", "h", "l", "c", "v")}
    stmt = insert(Candle)
    for i in range(0, len(df), _CHUNK):
        sl = slice(i, i + _CHUNK)
        rows = [
            {"symbol_id": int(s), "tf": tf, "ts": int(ts), "o": float(o), "h": float(h), "l": float(l),
             "c": float(c), "v": float(v), "oi": None}
            for s, ts, o, h, l, c, v in zip(sid[sl], cols["ts"][sl], cols["o"][sl], cols["h"][sl],  # noqa: E741
                                           cols["l"][sl], cols["c"][sl], cols["v"][sl])
        ]
        session.execute(stmt, rows)
    session.commit()


# ---- hourly ----------------------------------------------------------------
# <root>/<EXCHANGE>/<EXCHANGE>_YYYYMMDD_HHMM.csv, back-adjusted, one file per hour:
#     Symbol,Date,Time,Open,High,Low,Close,Volume   (Symbol = "NSE.RELIANCE", Time = HHMMSS local)
# Times are exchange-local (IST for NSE/BSE, New York for NASDAQ/NYSE) and converted to UTC.
_HOURLY_COLS = ["ticker", "date", "time", "o", "h", "l", "c", "v"]


def hourly_files(root: Path, exchange: str) -> list[Path]:
    d = root / exchange
    if not d.is_dir():
        raise FileNotFoundError(f"no folder {d}")
    return sorted(d.glob(f"{exchange}_????????_????.csv"))


def read_exchange_hourly(root: Path, exchange: str) -> tuple[pd.DataFrame, int]:
    files = hourly_files(root, exchange)
    if not files:
        raise FileNotFoundError(f"no {exchange}_YYYYMMDD_HHMM.csv files under {root / exchange}")
    frames = [
        pd.read_csv(f, header=0, names=_HOURLY_COLS, dtype={"ticker": str, "date": str, "time": str},
                    keep_default_na=False, na_values=[""])
        for f in files
    ]
    df = pd.concat(frames, ignore_index=True)
    t = df["ticker"].str.strip().str.upper()
    df["ticker"] = t.str.split(".", n=1).str[-1]   # "NSE.M&M" -> "M&M"
    df = df.dropna(subset=["ticker", "o", "h", "l", "c"])
    df = df[(df["ticker"] != "") & (df["c"] > 0)]
    df["v"] = df["v"].fillna(0)
    stamp = pd.to_datetime(df["date"] + df["time"].str.zfill(6), format="%Y%m%d%H%M%S")
    local = stamp.to_numpy(dtype="datetime64[s]").astype(np.int64)  # wall-clock time read as if UTC
    df["ts"] = local - market_for(exchange).utc_offsets(local)       # offset of that local date (DST-aware)
    df = df.drop_duplicates(["ticker", "ts"], keep="last").sort_values(["ticker", "ts"], ignore_index=True)
    return df, len(files)


def import_exchange_hourly(session: Session, root: Path, exchange: str,
                           names: dict[str, NameInfo] | None = None) -> ImportResult:
    """Replace the exchange's stored 1h bars. Symbols missing from the symbol master are added."""
    t0 = time.perf_counter()
    exchange = exchange.upper()
    df, nfiles = read_exchange_hourly(root, exchange)
    tickers = df["ticker"].unique().tolist()
    known = set(session.scalars(select(Symbol.ticker).where(Symbol.exchange == exchange)).all())
    new = [t for t in tickers if t not in known]
    if new:
        upsert_symbols(session, symbol_infos(exchange, new, names or {}))
    ids = dict(session.execute(select(Symbol.ticker, Symbol.id).where(Symbol.exchange == exchange)).all())
    _replace_candles(session, exchange, ("1h",), "1h", df, ids)
    dates = df["date"]
    res = ImportResult(exchange, nfiles, len(tickers), len(df), 0,
                       f"{dates.min()[:4]}-{dates.min()[4:6]}-{dates.min()[6:]}",
                       f"{dates.max()[:4]}-{dates.max()[4:6]}-{dates.max()[6:]}",
                       round(time.perf_counter() - t0, 1))
    log.info("%s hourly: imported %s", exchange, res)
    return res
