"""Timeframe definitions and resampling from the stored base timeframes (1m, 1D).

Intraday buckets are aligned to the 09:15 IST session open (NSE convention:
1h bars are 09:15-10:15, ...), weekly bars to IST Monday, monthly to the 1st.
"""
from dataclasses import dataclass

import numpy as np

IST_OFFSET = 19800          # +05:30 in seconds
SESSION_OPEN_OFFSET = 33300  # 09:15 after IST midnight
DAY = 86400


@dataclass(frozen=True)
class Timeframe:
    name: str
    base: str            # "1m" or "1D"
    minutes: int = 0     # intraday bucket size
    max_base_per_bar: int = 1  # upper bound of base bars in one bucket (for fetch sizing)


TIMEFRAMES: dict[str, Timeframe] = {
    tf.name: tf for tf in [
        Timeframe("1m", "1m", 1, 1),
        Timeframe("3m", "1m", 3, 3),
        Timeframe("5m", "1m", 5, 5),
        Timeframe("15m", "1m", 15, 15),
        Timeframe("30m", "1m", 30, 30),
        Timeframe("1h", "1m", 60, 60),
        Timeframe("2h", "1m", 120, 120),
        Timeframe("4h", "1m", 240, 240),
        Timeframe("1D", "1D", 0, 1),
        Timeframe("1W", "1D", 0, 7),
        Timeframe("1M", "1D", 0, 31),
    ]
}


def get_timeframe(name: str) -> Timeframe:
    try:
        return TIMEFRAMES[name]
    except KeyError:
        raise ValueError(f"unsupported timeframe {name!r}; one of {list(TIMEFRAMES)}") from None


def _ist_midnight(ts: np.ndarray) -> np.ndarray:
    return ((ts + IST_OFFSET) // DAY) * DAY - IST_OFFSET


def bucket_starts(tf: Timeframe, ts: np.ndarray) -> np.ndarray:
    """Bucket open time (epoch s) for each base-bar timestamp."""
    ts = np.asarray(ts, dtype=np.int64)
    if tf.name in ("1m", "1D"):
        return ts
    if tf.base == "1m":
        step = tf.minutes * 60
        open_ = _ist_midnight(ts) + SESSION_OPEN_OFFSET
        return open_ + ((ts - open_) // step) * step
    days = (ts + IST_OFFSET) // DAY  # IST day number since epoch
    d64 = days.astype("datetime64[D]")
    if tf.name == "1W":
        # 1970-01-01 was a Thursday -> Monday-based weekday = (days + 3) % 7
        start_days = days - (days + 3) % 7
    elif tf.name == "1M":
        start_days = d64.astype("datetime64[M]").astype("datetime64[D]").astype(np.int64)
    else:
        raise ValueError(tf.name)
    return start_days * DAY - IST_OFFSET


def resample(tf: Timeframe, t, o, h, l, c, v):  # noqa: E741
    """Aggregate ascending base bars into tf bars. Returns (t, o, h, l, c, v) numpy arrays."""
    arrs = [np.asarray(x) for x in (t, o, h, l, c, v)]
    if tf.name in ("1m", "1D") or len(arrs[0]) == 0:
        return tuple(arrs)
    t, o, h, l, c, v = arrs  # noqa: E741
    keys = bucket_starts(tf, t)
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
