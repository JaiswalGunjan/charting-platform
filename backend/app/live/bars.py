"""Forming bars: fold ticks into the current bar of every timeframe."""
from dataclasses import dataclass

import numpy as np

from app.marketdata.timeframes import DAY, IST_OFFSET, SESSION_OPEN_OFFSET, TIMEFRAMES, Timeframe, bucket_starts


@dataclass
class LiveBar:
    t: int
    o: float
    h: float
    l: float  # noqa: E741
    c: float
    v: float

    def update(self, price: float, qty: float) -> None:
        self.h = max(self.h, price)
        self.l = min(self.l, price)
        self.c = price
        self.v += qty

    def as_dict(self) -> dict:
        return {"t": self.t, "o": _r(self.o), "h": _r(self.h), "l": _r(self.l), "c": _r(self.c), "v": self.v}


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


def live_bucket(tf: Timeframe, ts: float) -> int:
    """Bucket open for an arbitrary (unaligned) timestamp."""
    ts = int(ts)
    midnight = ((ts + IST_OFFSET) // DAY) * DAY - IST_OFFSET
    if tf.base == "1m":
        open_ = midnight + SESSION_OPEN_OFFSET
        step = tf.minutes * 60
        return open_ + ((ts - open_) // step) * step
    if tf.name == "1D":
        return midnight
    return int(bucket_starts(tf, np.array([midnight]))[0])


@dataclass
class TickResult:
    updated: dict[str, LiveBar]       # tf -> current forming bar (after this tick)
    closed_1m: LiveBar | None         # the 1m bar that this tick closed, if any
    day_rolled: bool


class FormingBars:
    def __init__(self, symbol: str, seed: dict[str, LiveBar | None], prev_close: float | None,
                 tfs: tuple[str, ...] = tuple(TIMEFRAMES)):
        self.symbol = symbol
        self.tfs = {name: TIMEFRAMES[name] for name in tfs}
        self.bars: dict[str, LiveBar | None] = {name: seed.get(name) for name in tfs}
        self.prev_close = prev_close   # previous session's close, for change %
        self.last_price: float | None = None
        self.last_ts: float | None = None

    def apply(self, ts: float, price: float, qty: float) -> TickResult:
        closed_1m = None
        day_rolled = False
        for name, tf in self.tfs.items():
            b = live_bucket(tf, ts)
            cur = self.bars[name]
            if cur is None or b > cur.t:
                if name == "1m" and cur is not None:
                    closed_1m = cur
                if name == "1D" and cur is not None:
                    self.prev_close = cur.c
                    day_rolled = True
                self.bars[name] = LiveBar(b, price, price, price, price, qty)
            else:  # same bucket (or a late tick: fold into the current bar)
                cur.update(price, qty)
        self.last_price, self.last_ts = price, ts
        return TickResult(self.current(), closed_1m, day_rolled)

    def current(self) -> dict[str, LiveBar]:
        return {k: v for k, v in self.bars.items() if v is not None}

    def quote(self) -> dict:
        day = self.bars.get("1D")
        ltp = self.last_price if self.last_price is not None else (day.c if day else None)
        chg = pct = None
        if ltp is not None and self.prev_close:
            chg = round(ltp - self.prev_close, 4)
            pct = round(100 * chg / self.prev_close, 3)
        return {
            "symbol": self.symbol, "ltp": _r(ltp), "change": chg, "change_pct": pct,
            "prev_close": _r(self.prev_close), "ts": self.last_ts,
            "open": _r(day.o) if day else None, "high": _r(day.h) if day else None,
            "low": _r(day.l) if day else None, "volume": day.v if day else None,
        }
