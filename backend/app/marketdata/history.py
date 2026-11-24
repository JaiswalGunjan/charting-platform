"""Read candles for any timeframe, paging backwards from a cursor."""
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.marketdata.timeframes import Timeframe, resample
from app.models import Candle


@dataclass
class Bars:
    t: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray  # noqa: E741
    c: np.ndarray
    v: np.ndarray
    has_more: bool  # older bars exist before t[0]

    def __len__(self) -> int:
        return len(self.t)


def get_bars(session: Session, symbol_id: int, tf: Timeframe, *, limit: int,
             to: int | None = None, frm: int | None = None) -> Bars:
    """Up to `limit` most recent tf bars with open time in [frm, to), ascending.

    `to` should be a bucket boundary (e.g. a previous response's first bar time)
    so that no bucket is split across pages.
    """
    fetch_n = limit * tf.max_base_per_bar + tf.max_base_per_bar
    stmt = (select(Candle.ts, Candle.o, Candle.h, Candle.l, Candle.c, Candle.v)
            .where(Candle.symbol_id == symbol_id, Candle.tf == tf.base))
    if to is not None:
        stmt = stmt.where(Candle.ts < to)
    if frm is not None:
        stmt = stmt.where(Candle.ts >= frm)
    rows = session.execute(stmt.order_by(Candle.ts.desc()).limit(fetch_n)).all()
    truncated = len(rows) == fetch_n
    if not rows:
        empty = np.array([], dtype=float)
        return Bars(empty.astype(np.int64), empty, empty, empty, empty, empty, False)

    cols = np.array(rows[::-1], dtype=float).T
    t, o, h, l, c, v = resample(tf, cols[0].astype(np.int64), *cols[1:])  # noqa: E741
    if truncated and tf.max_base_per_bar > 1:
        # oldest bucket may be missing base bars that fell past the fetch limit
        t, o, h, l, c, v = (a[1:] for a in (t, o, h, l, c, v))  # noqa: E741
    has_more = truncated or len(t) > limit
    t, o, h, l, c, v = (a[-limit:] for a in (t, o, h, l, c, v))  # noqa: E741
    return Bars(t, o, h, l, c, v, has_more)
