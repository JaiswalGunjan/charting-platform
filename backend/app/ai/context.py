"""Deterministic chart context for the AI analyst.

Every number the model may cite is computed here, so responses can be checked
against the context that produced them (no hallucinated levels or readings).
"""
import math
from datetime import datetime

import numpy as np

from app.indicators import core
from app.marketdata.base import IST
from app.marketdata.history import Bars

RECENT_BARS = 30      # raw OHLCV rows shown to the model
SWING_WINDOW = 5      # a swing high/low is the extreme of +-5 bars


def _r(x: float, nd: int = 2) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


def _last(a: np.ndarray) -> float | None:
    return _r(a[-1]) if len(a) else None


def swing_levels(h: np.ndarray, l: np.ndarray, w: int = SWING_WINDOW) -> tuple[list[float], list[float]]:  # noqa: E741
    highs, lows = [], []
    for i in range(w, len(h) - w):
        if h[i] == h[i - w:i + w + 1].max():
            highs.append(float(h[i]))
        if l[i] == l[i - w:i + w + 1].min():
            lows.append(float(l[i]))
    return highs, lows


def _cluster(levels: list[float], tol: float) -> list[float]:
    """Merge levels within `tol` of each other (keeps the average)."""
    out: list[list[float]] = []
    for x in sorted(levels):
        if out and x - out[-1][-1] <= tol:
            out[-1].append(x)
        else:
            out.append([x])
    return [sum(g) / len(g) for g in out]


def build_context(symbol: str, tf: str, bars: Bars) -> dict:
    """Bars must be ascending; ~300+ bars recommended so EMA200 is defined."""
    if len(bars) < 30:
        raise ValueError(f"not enough history for {symbol} {tf} ({len(bars)} bars, need 30+)")
    t, o, h, l, c, v = bars.t, bars.o, bars.h, bars.l, bars.c, bars.v  # noqa: E741
    price = float(c[-1])

    ema20, ema50, ema200 = core.ema(c, 20), core.ema(c, 50), core.ema(c, 200)
    rsi = core.rsi(c, 14)
    macd, sig, hist = core.macd(c)
    bb_mid, bb_up, bb_lo = core.bollinger(c, 20, 2)
    atr = core.atr(h, l, c, 14)
    st_line, st_dir = core.supertrend(h, l, c, 10, 3)

    def vs(ma: np.ndarray) -> dict | None:
        val = _last(ma)
        if val is None:
            return None
        return {"value": val, "price_vs_pct": _r(100 * (price / val - 1)),
                "slope_10_bars_pct": _r(100 * (ma[-1] / ma[-11] - 1)) if len(ma) > 11 and not math.isnan(ma[-11]) else None}

    bb_width = (bb_up[-1] - bb_lo[-1]) if not math.isnan(bb_up[-1]) else float("nan")
    atr_v = float(atr[-1]) if not math.isnan(atr[-1]) else float(np.mean(h - l))

    sw_hi, sw_lo = swing_levels(h, l)
    levels = _cluster(sw_hi + sw_lo, tol=0.5 * atr_v)
    resistance = sorted([x for x in levels if x > price])[:3]
    support = sorted([x for x in levels if x < price], reverse=True)[:3]

    vol_avg20 = float(np.mean(v[-21:-1])) if len(v) > 21 else float(np.mean(v))
    window_ret = 100 * (price / float(c[0]) - 1)
    rsi_recent = rsi[-6:]

    ctx = {
        "symbol": symbol,
        "timeframe": tf,
        "as_of": datetime.fromtimestamp(int(t[-1]), IST).strftime("%Y-%m-%d %H:%M IST"),
        "bars_analyzed": len(bars),
        "window_start": datetime.fromtimestamp(int(t[0]), IST).strftime("%Y-%m-%d %H:%M IST"),
        "price": {
            "last": _r(price),
            "window_change_pct": _r(window_ret),
            "last_bar_change_pct": _r(100 * (price / float(c[-2]) - 1)),
            "window_high": _r(h.max()), "window_low": _r(l.min()),
            "pct_from_window_high": _r(100 * (price / h.max() - 1)),
        },
        "moving_averages": {"ema20": vs(ema20), "ema50": vs(ema50), "ema200": vs(ema200)},
        "momentum": {
            "rsi14": _last(rsi),
            "rsi14_last_6": [_r(x, 1) for x in rsi_recent],
            "macd": _r(macd[-1], 3), "macd_signal": _r(sig[-1], 3), "macd_hist": _r(hist[-1], 3),
            "macd_hist_prev": _r(hist[-2], 3),
        },
        "volatility": {
            "atr14": _r(atr_v), "atr14_pct_of_price": _r(100 * atr_v / price),
            "bb_upper": _last(bb_up), "bb_lower": _last(bb_lo),
            "bb_percent_b": _r((price - bb_lo[-1]) / bb_width, 3) if bb_width and not math.isnan(bb_width) else None,
            "bb_width_pct": _r(100 * bb_width / bb_mid[-1]) if not math.isnan(bb_width) else None,
        },
        "trend_indicators": {
            "supertrend_10_3": _last(st_line),
            "supertrend_direction": None if math.isnan(st_dir[-1]) else ("up" if st_dir[-1] > 0 else "down"),
        },
        "volume": {
            "last": _r(v[-1], 0), "avg20": _r(vol_avg20, 0),
            "last_vs_avg20": _r(v[-1] / vol_avg20, 2) if vol_avg20 > 0 else None,
        },
        "levels_from_swings": {
            "resistance_above": [_r(x) for x in resistance],
            "support_below": [_r(x) for x in support],
            "method": f"swing highs/lows (+-{SWING_WINDOW} bars), clustered within 0.5*ATR",
        },
        "recent_bars": {
            "columns": ["time_ist", "open", "high", "low", "close", "volume"],
            "rows": [
                [datetime.fromtimestamp(int(t[i]), IST).strftime("%m-%d %H:%M"),
                 _r(o[i]), _r(h[i]), _r(l[i]), _r(c[i]), _r(v[i], 0)]
                for i in range(max(0, len(t) - RECENT_BARS), len(t))
            ],
        },
    }
    if tf not in ("1D", "1W", "1M"):
        ctx["volatility"]["session_vwap"] = _last(core.vwap(t, h, l, c, v))
    return ctx
