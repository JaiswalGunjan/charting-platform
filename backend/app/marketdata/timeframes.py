"""Timeframe definitions and resampling from the stored base timeframes (1m, 1h, 1D).

Intraday buckets are aligned to the exchange's session open in its own time zone
(NSE/BSE 09:15 IST: 1h bars are 09:15-10:15, ...; NASDAQ/NYSE 09:30 New York time,
DST-aware). Weekly bars start on Monday, monthly on the 1st, yearly on 1 January.

Each timeframe lists the stored bases it can be built from, best first. 1h/2h/4h
prefer stored hourly bars (imported history) and fall back to 1m bars (Kite or
synthetic data); which one is used is decided per symbol by what is stored.
"""
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from math import ceil
from zoneinfo import ZoneInfo

import numpy as np

IST_OFFSET = 19800          # +05:30 in seconds
SESSION_OPEN_OFFSET = 33300  # 09:15 after IST midnight
DAY = 86400

STORED_TFS = ("1m", "1h", "1D")
_CALENDAR_SPAN = {"1D": 1, "1W": 7, "1M": 31, "1Y": 366}  # max daily bars per bucket


@dataclass(frozen=True)
class Timeframe:
    name: str
    minutes: int = 0     # intraday bucket size; 0 for calendar timeframes

    @property
    def intraday(self) -> bool:
        return self.minutes > 0

    @property
    def bases(self) -> tuple[str, ...]:
        if not self.intraday:
            return ("1D",)
        return ("1h", "1m") if self.minutes % 60 == 0 else ("1m",)

    @property
    def base(self) -> str:
        """Default (finest) base, used when nothing better is stored."""
        return self.bases[-1]

    def per_bar(self, base: str) -> int:
        """Upper bound of base bars in one bucket (for fetch sizing)."""
        if base == "1m":
            return self.minutes
        if base == "1h":
            return ceil(self.minutes / 60)
        return _CALENDAR_SPAN[self.name]

    @property
    def max_base_per_bar(self) -> int:
        return self.per_bar(self.base)


TIMEFRAMES: dict[str, Timeframe] = {
    tf.name: tf for tf in [
        Timeframe("1m", 1),
        Timeframe("3m", 3),
        Timeframe("5m", 5),
        Timeframe("15m", 15),
        Timeframe("30m", 30),
        Timeframe("1h", 60),
        Timeframe("2h", 120),
        Timeframe("4h", 240),
        Timeframe("1D"),
        Timeframe("1W"),
        Timeframe("1M"),
        Timeframe("1Y"),
    ]
}


def get_timeframe(name: str) -> Timeframe:
    try:
        return TIMEFRAMES[name]
    except KeyError:
        raise ValueError(f"unsupported timeframe {name!r}; one of {list(TIMEFRAMES)}") from None


@dataclass(frozen=True)
class Market:
    """Where intraday buckets are anchored: the exchange's time zone and session open."""
    tz: str
    open_minute: int  # minutes after local midnight

    def utc_offsets(self, ts: np.ndarray) -> np.ndarray:
        """Seconds east of UTC at each timestamp (DST-aware)."""
        ts = np.asarray(ts, dtype=np.int64)
        if self.tz == "Asia/Kolkata":
            return np.full(ts.shape, IST_OFFSET, dtype=np.int64)
        days = ts // DAY
        uniq, inv = np.unique(days, return_inverse=True)
        offs = np.array([_utc_offset(self.tz, int(d)) for d in uniq], dtype=np.int64)
        return offs[inv].reshape(ts.shape)


@lru_cache(maxsize=20_000)
def _utc_offset(tz: str, utc_day: int) -> int:
    # noon UTC of that day: US DST switches happen at ~07:00 UTC on Sundays, outside sessions
    return int(datetime.fromtimestamp(utc_day * DAY + DAY // 2, ZoneInfo(tz)).utcoffset().total_seconds())


IST_MARKET = Market("Asia/Kolkata", 9 * 60 + 15)
US_MARKET = Market("America/New_York", 9 * 60 + 30)


def market_for(exchange: str) -> Market:
    """The session anchor of an exchange, from the market registry (app/markets.toml)."""
    from app.markets import market

    m = market(exchange)
    return Market(m.timezone, m.open_minute)


def local_day(ts, market: Market = IST_MARKET) -> np.ndarray:
    """Exchange-local calendar day number (days since 1970-01-01) of each timestamp."""
    ts = np.asarray(ts, dtype=np.int64)
    return (ts + market.utc_offsets(ts)) // DAY


def bucket_starts(tf: Timeframe, ts: np.ndarray, market: Market = IST_MARKET) -> np.ndarray:
    """Bucket open time (epoch s) for each base-bar timestamp.

    Intraday buckets are anchored at the exchange's session open in its own time zone.
    Daily and longer bars are stamped at IST midnight of their (exchange-local) date for
    every exchange, the convention the stored daily bars use.
    """
    ts = np.asarray(ts, dtype=np.int64)
    if tf.name in ("1m", "1D"):
        return ts
    if tf.intraday:
        step = tf.minutes * 60
        off = market.utc_offsets(ts)
        open_ = ((ts + off) // DAY) * DAY - off + market.open_minute * 60
        return open_ + ((ts - open_) // step) * step
    days = (ts + IST_OFFSET) // DAY  # daily bars: IST midnight encodes the trading date
    d64 = days.astype("datetime64[D]")
    if tf.name == "1W":
        # 1970-01-01 was a Thursday -> Monday-based weekday = (days + 3) % 7
        start_days = days - (days + 3) % 7
    elif tf.name == "1M":
        start_days = d64.astype("datetime64[M]").astype("datetime64[D]").astype(np.int64)
    elif tf.name == "1Y":
        start_days = d64.astype("datetime64[Y]").astype("datetime64[D]").astype(np.int64)
    else:
        raise ValueError(tf.name)
    return start_days * DAY - IST_OFFSET


def resample(tf: Timeframe, t, o, h, l, c, v, market: Market = IST_MARKET):  # noqa: E741
    """Aggregate ascending base bars into tf bars. Returns (t, o, h, l, c, v) numpy arrays."""
    arrs = [np.asarray(x) for x in (t, o, h, l, c, v)]
    if tf.name in ("1m", "1D") or len(arrs[0]) == 0:
        return tuple(arrs)
    t, o, h, l, c, v = arrs  # noqa: E741
    keys = bucket_starts(tf, t, market)
    starts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
    ends = np.r_[starts[1:], len(keys)] - 1
    return (
        keys[starts],
        o[starts],
        np.maximum.reduceat(h, starts),
        np.minimum.reduceat(l, starts),
        c[ends],
        np.add.reduceat(v, starts),
    )
