"""Read candles for any timeframe, paging backwards from a cursor. Stored bars come from the bar store in use
(BAR_STORE, app.ports.BarStore); other timeframes are resampled here."""
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.marketdata.timeframes import IST_MARKET, Market, Timeframe, market_for, resample
from app.models import Symbol
from app.providers import bar_store


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


def symbol_market(session: Session, symbol_id: int) -> Market:
    """Session anchor of the symbol's exchange (NSE 09:15 IST, NASDAQ 09:30 New York, ...)."""
    ex = session.scalar(select(Symbol.exchange).where(Symbol.id == symbol_id))
    return market_for(ex) if ex else IST_MARKET


def pick_base(session: Session, symbol_id: int, tf: Timeframe) -> str:
    """The best stored base for this symbol (e.g. imported 1h bars over 1m)."""
    if len(tf.bases) == 1:
        return tf.base
    store = bar_store()
    for base in tf.bases[:-1]:
        if store.has(session, symbol_id, base):
            return base
    return tf.base


def get_bars(session: Session, symbol_id: int, tf: Timeframe, *, limit: int,
             to: int | None = None, frm: int | None = None) -> Bars:
    """Up to `limit` most recent tf bars with open time in [frm, to), ascending.

    `to` should be a bucket boundary (e.g. a previous response's first bar time)
    so that no bucket is split across pages.
    """
    base = pick_base(session, symbol_id, tf)
    per_bar = tf.per_bar(base)
    fetch_n = limit * per_bar + per_bar
    rows = bar_store().read_latest(session, symbol_id, base, fetch_n, to=to, frm=frm)
    truncated = len(rows) == fetch_n
    if not len(rows):
        empty = np.array([], dtype=float)
        return Bars(empty.astype(np.int64), empty, empty, empty, empty, empty, False)

    cols = rows.T
    market = symbol_market(session, symbol_id) if tf.intraday else IST_MARKET
    t, o, h, l, c, v = resample(tf, cols[0].astype(np.int64), *cols[1:], market=market)  # noqa: E741
    if truncated and per_bar > 1:
        # oldest bucket may be missing base bars that fell past the fetch limit
        t, o, h, l, c, v = (a[1:] for a in (t, o, h, l, c, v))  # noqa: E741
    has_more = truncated or len(t) > limit
    t, o, h, l, c, v = (a[-limit:] for a in (t, o, h, l, c, v))  # noqa: E741
    return Bars(t, o, h, l, c, v, has_more)


def get_bars_after(session: Session, symbol_id: int, tf: Timeframe, *, frm: int, limit: int) -> Bars:
    """The first `limit` tf bars with open time >= frm (a bucket boundary), ascending.

    Used for indicators that look ahead (e.g. Ichimoku's lagging span) when a page ends at `to`.
    """
    base = pick_base(session, symbol_id, tf)
    per_bar = tf.per_bar(base)
    fetch_n = (limit + 1) * per_bar
    rows = bar_store().read_after(session, symbol_id, base, frm, fetch_n)
    if not len(rows):
        empty = np.array([], dtype=float)
        return Bars(empty.astype(np.int64), empty, empty, empty, empty, empty, False)
    cols = rows.T
    market = symbol_market(session, symbol_id) if tf.intraday else IST_MARKET
    arrs = resample(tf, cols[0].astype(np.int64), *cols[1:], market=market)
    if len(rows) == fetch_n and per_bar > 1:
        arrs = tuple(a[:-1] for a in arrs)  # newest bucket may be incomplete
    t, o, h, l, c, v = (a[:limit] for a in arrs)  # noqa: E741
    return Bars(t, o, h, l, c, v, False)


def concat_bars(a: Bars, b: Bars) -> Bars:
    return Bars(*(np.concatenate([getattr(a, k), getattr(b, k)]) for k in "tohlcv"), a.has_more)
