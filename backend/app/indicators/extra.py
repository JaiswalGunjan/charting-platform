"""Indicator math, part 2: the rest of the popular-indicator set.

Same conventions as core.py: float numpy arrays in and out, NaN while warming up,
Wilder smoothing (RMA) where the classic definition uses it. Formulas follow the
original authors' definitions (Wilder, Lane, Chaikin, Appel, Ehlers, ...).
"""
import numpy as np

from app.indicators.core import _nan, atr, bollinger, ema, rma, rsi, sma, true_range, wma

NAN = np.nan


# ---- helpers ------------------------------------------------------------------
def _windows(x: np.ndarray, n: int):
    return np.lib.stride_tricks.sliding_window_view(x, n)


def rolling(x: np.ndarray, n: int, fn) -> np.ndarray:
    """fn(windows, axis=1) over trailing windows of n; NaN for the first n-1 bars."""
    out = _nan(len(x))
    if 0 < n <= len(x):
        out[n - 1:] = fn(_windows(x, n), axis=1)
    return out


def rsum(x: np.ndarray, n: int) -> np.ndarray:
    """Trailing n-bar sum; NaN where the window holds a NaN (NaN never leaks further)."""
    out = _nan(len(x))
    if 0 < n <= len(x):
        bad = np.isnan(x)
        cs = np.cumsum(np.insert(np.where(bad, 0.0, x), 0, 0.0))
        cn = np.cumsum(np.insert(bad.astype(np.int64), 0, 0))
        out[n - 1:] = np.where(cn[n:] - cn[:-n] > 0, NAN, cs[n:] - cs[:-n])
    return out


def shift(x: np.ndarray, k: int) -> np.ndarray:
    """x shifted right by k bars (k < 0 shifts left); vacated bars are NaN."""
    out = _nan(len(x))
    if k == 0:
        return x.copy()
    if abs(k) >= len(x):
        return out
    if k > 0:
        out[k:] = x[:-k]
    else:
        out[:k] = x[-k:]
    return out


def on_valid(fn, x: np.ndarray, *args) -> np.ndarray:
    """Apply a NaN-intolerant smoother to x from its first non-NaN value on."""
    out = _nan(len(x))
    valid = np.flatnonzero(~np.isnan(x))
    if len(valid):
        s = valid[0]
        out[s:] = fn(x[s:], *args)
    return out


def _div(a, b, fill=NAN):
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(b == 0, fill, a / b)


# ---- moving averages ------------------------------------------------------------
def dema(x, n):
    e1 = ema(x, n)
    return 2 * e1 - ema(e1, n)


def tema(x, n):
    e1 = ema(x, n)
    e2 = ema(e1, n)
    return 3 * e1 - 3 * e2 + ema(e2, n)


def hma(x, n):
    half, root = max(1, n // 2), max(1, int(np.sqrt(n)))
    raw = 2 * wma(x, half) - wma(x, n)
    return on_valid(wma, raw, root)


def vwma(c, v, n):
    return _div(rsum(c * v, n), rsum(v, n))


def alma(x, n, offset=0.85, sigma=6.0):
    m, s = offset * (n - 1), n / sigma
    w = np.exp(-((np.arange(n) - m) ** 2) / (2 * s * s))
    out = _nan(len(x))
    if len(x) >= n:
        out[n - 1:] = _windows(x, n) @ w / w.sum()
    return out


def kama(x, n=10, fast=2, slow=30):
    out = _nan(len(x))
    if len(x) <= n:
        return out
    change = np.abs(x[n:] - x[:-n])
    vol = rsum(np.abs(np.diff(x, prepend=x[0])), n)[n:]
    er = _div(change, vol, 0.0)
    fsc, ssc = 2 / (fast + 1), 2 / (slow + 1)
    sc = (er * (fsc - ssc) + ssc) ** 2
    prev = x[n - 1]
    out[n - 1] = prev
    for i in range(n, len(x)):
        prev = prev + sc[i - n] * (x[i] - prev)
        out[i] = prev
    return out


def linreg(x, n):
    """End point of the least-squares line over the last n bars."""
    out = _nan(len(x))
    if len(x) < n or n < 2:
        return out
    idx = np.arange(n, dtype=float)
    win = _windows(x, n)
    sx, sxx = idx.sum(), (idx ** 2).sum()
    sy, sxy = win.sum(axis=1), win @ idx
    slope = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    intercept = (sy - slope * sx) / n
    out[n - 1:] = intercept + slope * (n - 1)
    return out


# ---- bands, channels, trend ----------------------------------------------------
def keltner(h, l, c, n=20, mult=2.0, atr_len=10):  # noqa: E741
    mid = ema(c, n)
    a = atr(h, l, c, atr_len)
    return mid, mid + mult * a, mid - mult * a


def donchian(h, l, n=20):  # noqa: E741
    up, lo = rolling(h, n, np.max), rolling(l, n, np.min)
    return (up + lo) / 2, up, lo


def envelopes(x, n=20, pct=2.5):
    mid = sma(x, n)
    return mid, mid * (1 + pct / 100), mid * (1 - pct / 100)


def psar(h, l, start=0.02, inc=0.02, maximum=0.2):  # noqa: E741
    size = len(h)
    out = _nan(size)
    if size < 2:
        return out
    up = h[1] >= h[0]
    sar = l[0] if up else h[0]
    ep = h[1] if up else l[1]
    af = start
    out[1] = sar
    for i in range(2, size):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, l[i - 1], l[i - 2])
            if l[i] < sar:            # reversal to downtrend
                up, sar, ep, af = False, ep, l[i], start
            elif h[i] > ep:
                ep, af = h[i], min(af + inc, maximum)
        else:
            sar = max(sar, h[i - 1], h[i - 2])
            if h[i] > sar:            # reversal to uptrend
                up, sar, ep, af = True, ep, h[i], start
            elif l[i] < ep:
                ep, af = l[i], min(af + inc, maximum)
        out[i] = sar
    return out


def ichimoku(h, l, c, conv=9, base=26, span_b=52, disp=26):  # noqa: E741
    mid = lambda n: (rolling(h, n, np.max) + rolling(l, n, np.min)) / 2  # noqa: E731
    tenkan, kijun = mid(conv), mid(base)
    # leading spans are plotted `disp` bars ahead; bars beyond the last candle are dropped
    span_a = shift((tenkan + kijun) / 2, disp - 1)
    span_b_ = shift(mid(span_b), disp - 1)
    lagging = shift(c, -(disp - 1))
    return tenkan, kijun, span_a, span_b_, lagging


# ---- momentum / oscillators ---------------------------------------------------
def stoch_rsi(c, rsi_len=14, stoch_len=14, k=3, d=3):
    r = rsi(c, rsi_len)
    hh, ll = rolling(r, stoch_len, np.max), rolling(r, stoch_len, np.min)
    raw = _div(100 * (r - ll), hh - ll, 50.0)
    raw[np.isnan(hh)] = NAN
    k_line = on_valid(sma, raw, k)
    return k_line, on_valid(sma, k_line, d)


def cci(h, l, c, n=20):  # noqa: E741
    tp = (h + l + c) / 3
    ma = sma(tp, n)
    md = rolling(tp, n, lambda w, axis: np.abs(w - w.mean(axis=axis, keepdims=True)).mean(axis=axis))
    return _div(tp - ma, 0.015 * md, 0.0)


def williams_r(h, l, c, n=14):  # noqa: E741
    hh, ll = rolling(h, n, np.max), rolling(l, n, np.min)
    return _div(-100 * (hh - c), hh - ll, -50.0)


def roc(x, n=9):
    prev = shift(x, n)
    return _div(100 * (x - prev), prev)


def momentum(x, n=10):
    return x - shift(x, n)


def mfi(h, l, c, v, n=14):  # noqa: E741
    tp = (h + l + c) / 3
    flow = tp * v
    d = np.diff(tp, prepend=NAN)
    pos, neg = rsum(np.where(d > 0, flow, 0.0), n), rsum(np.where(d < 0, flow, 0.0), n)
    out = 100 - _div(100.0, 1 + _div(pos, neg, np.inf), 1.0)
    out = np.where((pos + neg) == 0, 50.0, out)
    out[:n] = NAN  # first diff is undefined
    return out


def dmi(h, l, c, n=14, smooth=14):  # noqa: E741
    up, dn = np.diff(h, prepend=NAN), -np.diff(l, prepend=NAN)
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    plus_dm[0] = minus_dm[0] = NAN
    tr = true_range(h, l, c)
    tr[0] = NAN
    atr_ = rma(tr, n)
    plus = _div(100 * rma(plus_dm, n), atr_)
    minus = _div(100 * rma(minus_dm, n), atr_)
    dx = _div(100 * np.abs(plus - minus), plus + minus, 0.0)
    dx[np.isnan(plus)] = NAN
    return plus, minus, rma(dx, smooth)


def aroon(h, l, n=14):  # noqa: E741
    up, dn = _nan(len(h)), _nan(len(h))
    if len(h) > n:
        wh, wl = _windows(h, n + 1), _windows(l, n + 1)
        # bars since the most recent extreme within the last n+1 bars
        since_h = np.argmax(wh[:, ::-1], axis=1)
        since_l = np.argmin(wl[:, ::-1], axis=1)
        up[n:] = 100 * (n - since_h) / n
        dn[n:] = 100 * (n - since_l) / n
    return up, dn


def awesome(h, l):  # noqa: E741
    mid = (h + l) / 2
    return sma(mid, 5) - sma(mid, 34)


def ultimate(h, l, c, s=7, m=14, lg=28):  # noqa: E741
    prev = shift(c, 1)
    low_ = np.fmin(l, prev)
    bp = c - low_
    tr = np.fmax(h, prev) - low_
    bp[0] = tr[0] = NAN  # no previous close yet
    avg = lambda n: _div(rsum(bp, n), rsum(tr, n))  # noqa: E731
    return 100 * (4 * avg(s) + 2 * avg(m) + avg(lg)) / 7


def trix(x, n=18, signal=9):
    e3 = on_valid(ema, on_valid(ema, ema(x, n), n), n)
    line = 100 * _div(e3 - shift(e3, 1), shift(e3, 1))
    return line, on_valid(ema, line, signal)


def tsi(x, long=25, short=13, signal=13):
    pc = np.diff(x, prepend=NAN)
    ds = lambda s: on_valid(ema, on_valid(ema, s, long), short)  # noqa: E731
    line = 100 * _div(ds(pc), ds(np.abs(pc)), 0.0)
    line[np.isnan(ds(pc))] = NAN
    return line, on_valid(ema, line, signal)


def cmo(x, n=9):
    d = np.diff(x, prepend=NAN)
    su, sd = rsum(np.where(d > 0, d, 0.0), n), rsum(np.where(d < 0, -d, 0.0), n)
    out = _div(100 * (su - sd), su + sd, 0.0)
    out[:n] = NAN
    return out


def dpo(x, n=21):
    return x - shift(sma(x, n), n // 2 + 1)


def ppo(x, fast=12, slow=26, signal=9):
    es = ema(x, slow)
    line = _div(100 * (ema(x, fast) - es), es)
    sig = on_valid(ema, line, signal)
    return line, sig, line - sig


def vortex(h, l, c, n=14):  # noqa: E741
    vp, vm = np.abs(h - shift(l, 1)), np.abs(l - shift(h, 1))
    tr = true_range(h, l, c)
    vp[0] = vm[0] = tr[0] = NAN
    s = rsum(tr, n)
    return _div(rsum(vp, n), s), _div(rsum(vm, n), s)


def elder_ray(h, l, c, n=13):  # noqa: E741
    e = ema(c, n)
    return h - e, l - e


def coppock(x, wma_len=10, long=14, short=11):
    return on_valid(wma, roc(x, long) + roc(x, short), wma_len)


# ---- volatility ---------------------------------------------------------------
def hist_vol(c, n=20, periods=252):
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.log(c / shift(c, 1))
    return 100 * np.sqrt(periods) * rolling(r, n, lambda w, axis: w.std(axis=axis, ddof=1))


def bb_percent_b(x, n=20, mult=2.0):
    _, up, lo = bollinger(x, n, mult)
    return _div(x - lo, up - lo, 0.5)


def bb_width(x, n=20, mult=2.0):
    mid, up, lo = bollinger(x, n, mult)
    return _div(up - lo, mid)


# ---- volume -------------------------------------------------------------------
def _mf_multiplier(h, l, c):  # noqa: E741
    return _div((c - l) - (h - c), h - l, 0.0)


def cmf(h, l, c, v, n=20):  # noqa: E741
    return _div(rsum(_mf_multiplier(h, l, c) * v, n), rsum(v, n), 0.0)


def adl(h, l, c, v):  # noqa: E741
    return np.cumsum(_mf_multiplier(h, l, c) * v)


def chaikin_osc(h, l, c, v, fast=3, slow=10):  # noqa: E741
    a = adl(h, l, c, v)
    return ema(a, fast) - ema(a, slow)


def force_index(c, v, n=13):
    return on_valid(ema, np.diff(c, prepend=NAN) * v, n)


def ease_of_movement(h, l, v, n=14, divisor=10_000):  # noqa: E741
    mid = (h + l) / 2
    raw = _div(divisor * np.diff(mid, prepend=NAN) * (h - l), v, 0.0)
    raw[0] = NAN
    return on_valid(sma, raw, n)
