"""Indicator math. Inputs/outputs are float numpy arrays of equal length;
values that are not yet defined (warm-up) are NaN.

Conventions: RSI/ATR/Supertrend use Wilder smoothing (RMA), the common
convention on Indian and US charting platforms.
"""
import numpy as np

from app.marketdata.timeframes import DAY, IST_OFFSET

NAN = np.nan


def _nan(n: int) -> np.ndarray:
    return np.full(n, NAN)


def sma(x: np.ndarray, n: int) -> np.ndarray:
    out = _nan(len(x))
    if len(x) >= n:
        cs = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def wma(x: np.ndarray, n: int) -> np.ndarray:
    out = _nan(len(x))
    if len(x) >= n:
        w = np.arange(1, n + 1, dtype=float)
        out[n - 1:] = np.convolve(x, w[::-1], mode="valid") / w.sum()
    return out


def _recursive(x: np.ndarray, n: int, alpha: float) -> np.ndarray:
    """EMA-family smoother seeded with the SMA of the first n valid values."""
    out = _nan(len(x))
    valid = np.flatnonzero(~np.isnan(x))
    if len(valid) < n:
        return out
    start = valid[0]
    seed_end = start + n - 1
    if np.isnan(x[start:seed_end + 1]).any():
        return out
    prev = x[start:seed_end + 1].mean()
    out[seed_end] = prev
    for i in range(seed_end + 1, len(x)):
        prev = prev + alpha * (x[i] - prev)
        out[i] = prev
    return out


def ema(x: np.ndarray, n: int) -> np.ndarray:
    return _recursive(x, n, 2.0 / (n + 1))


def rma(x: np.ndarray, n: int) -> np.ndarray:
    """Wilder's moving average."""
    return _recursive(x, n, 1.0 / n)


def rsi(c: np.ndarray, n: int = 14) -> np.ndarray:
    out = _nan(len(c))
    if len(c) <= n:
        return out
    d = np.diff(c)
    gain = rma(np.maximum(d, 0), n)
    loss = rma(np.maximum(-d, 0), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = 100 - 100 / (1 + gain / loss)
    r = np.where(loss == 0, np.where(gain == 0, 50.0, 100.0), r)
    r[np.isnan(gain)] = NAN
    out[1:] = r
    return out


def macd(c: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(c, fast) - ema(c, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def bollinger(c: np.ndarray, n: int = 20, k: float = 2.0):
    mid = sma(c, n)
    sd = _nan(len(c))
    if len(c) >= n:
        win = np.lib.stride_tricks.sliding_window_view(c, n)
        sd[n - 1:] = win.std(axis=1)  # population std, the usual BB convention
    return mid, mid + k * sd, mid - k * sd


def true_range(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:  # noqa: E741
    prev_c = np.r_[NAN, c[:-1]]
    tr = np.fmax(h - l, np.fmax(np.abs(h - prev_c), np.abs(l - prev_c)))
    return tr


def atr(h, l, c, n: int = 14) -> np.ndarray:  # noqa: E741
    return rma(true_range(h, l, c), n)


def supertrend(h, l, c, n: int = 10, mult: float = 3.0):  # noqa: E741
    """Returns (line, direction) where direction is +1 (up/bullish) or -1."""
    size = len(c)
    line, direction = _nan(size), _nan(size)
    a = atr(h, l, c, n)
    hl2 = (h + l) / 2
    up_basic, dn_basic = hl2 + mult * a, hl2 - mult * a
    fu = fl = NAN
    d = 1.0
    for i in range(size):
        if np.isnan(a[i]):
            continue
        if np.isnan(fu):  # first defined bar
            fu, fl = up_basic[i], dn_basic[i]
            d = 1.0 if c[i] > hl2[i] else -1.0
        else:
            fu = up_basic[i] if (up_basic[i] < fu or c[i - 1] > fu) else fu
            fl = dn_basic[i] if (dn_basic[i] > fl or c[i - 1] < fl) else fl
            if d < 0 and c[i] > fu:
                d = 1.0
            elif d > 0 and c[i] < fl:
                d = -1.0
        line[i] = fl if d > 0 else fu
        direction[i] = d
    return line, direction


def stochastic(h, l, c, k: int = 14, smooth_k: int = 3, d: int = 3):  # noqa: E741
    size = len(c)
    raw = _nan(size)
    if size >= k:
        hh = np.lib.stride_tricks.sliding_window_view(h, k).max(axis=1)
        ll = np.lib.stride_tricks.sliding_window_view(l, k).min(axis=1)
        rng = hh - ll
        with np.errstate(divide="ignore", invalid="ignore"):
            raw[k - 1:] = np.where(rng == 0, 50.0, 100 * (c[k - 1:] - ll) / rng)
    k_line = _sma_nan(raw, smooth_k)
    return k_line, _sma_nan(k_line, d)


def _sma_nan(x: np.ndarray, n: int) -> np.ndarray:
    """SMA over a series with leading NaNs."""
    out = _nan(len(x))
    valid = np.flatnonzero(~np.isnan(x))
    if len(valid):
        s = valid[0]
        out[s:] = sma(x[s:], n)
    return out


def obv(c: np.ndarray, v: np.ndarray) -> np.ndarray:
    if len(c) == 0:
        return _nan(0)
    sign = np.sign(np.diff(c))
    return np.r_[0.0, np.cumsum(sign * v[1:])]


def vwap(t: np.ndarray, h, l, c, v) -> np.ndarray:  # noqa: E741
    """Session VWAP, anchored at each IST trading day. NaN where volume is 0 (indices)."""
    tp = (h + l + c) / 3
    day = (np.asarray(t, dtype=np.int64) + IST_OFFSET) // DAY
    out = _nan(len(c))
    if len(c) == 0:
        return out
    starts = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    ends = np.r_[starts[1:], len(c)]
    for s, e in zip(starts, ends):
        cv = np.cumsum(v[s:e])
        with np.errstate(divide="ignore", invalid="ignore"):
            out[s:e] = np.where(cv > 0, np.cumsum(tp[s:e] * v[s:e]) / cv, NAN)
    return out
