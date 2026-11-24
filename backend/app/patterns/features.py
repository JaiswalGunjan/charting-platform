"""Feature columns the chart-pattern rules read.

Ported from the owner's backtester, TranscriptExtract/swingbt/indicators.py (`add_all`), keeping its definitions
(WMA = linearly weighted, EMA alpha 2/(n+1) seeded with the first value, MACD 12/26/9 histogram, slow stochastic
5-3-3, pocket-pivot volume, change-in-character bars, 2-bar fractal swings, AVWAPs). Every column at bar t uses
bars <= t only. Only the columns the pattern rules use are built.
"""
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view


def wma(x, n):
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    w = np.arange(1, n + 1, dtype=float)
    out[n - 1:] = sliding_window_view(x, n) @ w / w.sum()
    return out


def sma(x, n):
    return pd.Series(x).rolling(n, min_periods=n).mean().to_numpy()


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def slope(x, n):
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) > n:
        with np.errstate(invalid="ignore", divide="ignore"):
            out[n:] = x[n:] / x[:-n] - 1
    return out


def rolling_max(x, n):
    return pd.Series(x).rolling(n, min_periods=1).max().to_numpy()


def rolling_min(x, n):
    return pd.Series(x).rolling(n, min_periods=1).min().to_numpy()


def rolling_argmax(x, n):
    """Index of the highest value in the trailing n-bar window (latest on ties)."""
    x = np.asarray(x, dtype=float)
    out = np.zeros(len(x), dtype=np.int64)
    m = min(n, len(x))
    for i in range(m - 1):
        seg = x[:i + 1]
        out[i] = len(seg) - 1 - int(np.nanargmax(seg[::-1]))
    if len(x) >= n:
        win = sliding_window_view(x, n)[:, ::-1]
        out[n - 1:] = np.arange(n - 1, len(x)) - np.nanargmax(np.nan_to_num(win, nan=-np.inf), axis=1)
    return out


def avwap_from(anchor, tp, v):
    pv, cv = np.cumsum(tp * v), np.cumsum(v)
    a = np.asarray(anchor)
    pv0 = np.where(a > 0, pv[np.maximum(a - 1, 0)], 0.0)
    cv0 = np.where(a > 0, cv[np.maximum(a - 1, 0)], 0.0)
    den = cv - cv0
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, (pv - pv0) / den, np.nan)


def stoch_slow(h, l, c, k=5, ks=3, kd=3):  # noqa: E741
    hh = pd.Series(h).rolling(k, min_periods=k).max()
    ll = pd.Series(l).rolling(k, min_periods=k).min()
    with np.errstate(invalid="ignore", divide="ignore"):
        raw = np.where(hh > ll, 100 * (c - ll) / (hh - ll), 50.0)
    sk = pd.Series(raw).rolling(ks, min_periods=ks).mean()
    return sk.to_numpy(), sk.rolling(kd, min_periods=kd).mean().to_numpy()


def fractal_flags(x, k=2, kind="low"):
    """Bar j is a swing low (high) if below (above) the k bars on each side; known only at j + k."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    flag = np.zeros(n, dtype=bool)
    if n < 2 * k + 1:
        return flag
    win = sliding_window_view(x, 2 * k + 1)
    mid = win[:, k]
    others = np.delete(win, k, axis=1)
    ok = (mid[:, None] < others).all(axis=1) if kind == "low" else (mid[:, None] > others).all(axis=1)
    flag[k:n - k] = ok
    return flag


def build(t, o, h, l, c, v, cfg=None) -> dict[str, np.ndarray]:  # noqa: E741
    cfg = cfg or {}
    o, h, l, c, v = (np.asarray(a, dtype=float) for a in (o, h, l, c, v))
    n = len(c)
    f: dict[str, np.ndarray] = {"t": np.asarray(t, dtype=np.int64), "o": o, "h": h, "l": l, "c": c, "v": v}
    for p in (10, 20, 50, 100, 200):
        f[f"wma{p}"] = wma(c, p)
    for p in (21, 50, 200):
        f[f"sma{p}"] = sma(c, p)
    for p in (10, 20):
        f[f"ema{p}"] = ema(c, p)
    f["wma200_slope"] = slope(f["wma200"], cfg.get("slope_bars", 20))
    for p in (10, 20):
        w = f[f"wma{p}"]
        f[f"wma{p}_up"] = np.concatenate([[False], w[1:] > w[:-1]])
        f[f"wma{p}_slope5"] = slope(w, 5)

    line = ema(c, 12) - ema(c, 26)
    f["macdh"] = line - ema(line, 9)
    f["stoch_k"], f["stoch_d"] = stoch_slow(h, l, c, *cfg.get("stoch", (5, 3, 3)))

    with np.errstate(invalid="ignore", divide="ignore"):
        f["range_pct"] = 100 * (h - l) / np.where(c > 0, c, np.nan)
        rng = h - l
        f["close_pos"] = np.where(rng > 0, (c - l) / rng, 0.5)
    f["vol50"] = sma(v, 50)
    pc = np.concatenate([[c[0]], c[:-1]]) if n else c
    f["fi"] = ema((c - pc) * v, 5)
    up, dn = c > pc, c < pc
    if n:
        up[0] = dn[0] = False
    f["up_day"], f["down_day"] = up, dn

    w = cfg.get("pp_window", 10)
    dv = np.where(dn, v, np.nan)
    maxdown = pd.Series(dv).rolling(w, min_periods=1).max().shift(1).to_numpy()
    f["pp_maxdown"] = maxdown
    f["pp"] = up & ~np.isnan(maxdown) & (v > np.nan_to_num(maxdown, nan=np.inf))
    for kk in cfg.get("cic_windows", (250, 66, 22)):
        f[f"cic{kk}"] = up & (v >= rolling_max(v, kk)) & (np.arange(n) >= min(kk, 22) - 1)

    f["high_52w"], f["low_52w"] = rolling_max(h, 250), rolling_min(l, 250)
    for p in (10, 20, 22):
        f[f"high_{p}"] = pd.Series(h).rolling(p, min_periods=1).max().shift(1).to_numpy()
    tp = (h + l + c) / 3
    f["avwap_52wh"] = avwap_from(rolling_argmax(h, 250), tp, v)
    f["avwap_swing"] = avwap_from(rolling_argmax(h, 40), tp, v)
    f["swing_low"], f["swing_high"] = fractal_flags(l, 2, "low"), fractal_flags(h, 2, "high")
    return f


class Bars:
    """Attribute access to the feature arrays (b.c, b.wma10, ...), like swingbt.rules.common.Bars."""

    def __init__(self, feats: dict[str, np.ndarray], cfg: dict | None = None):
        self.__dict__.update(feats)
        self.cfg = cfg or {}
        self.n = len(feats["c"])

    def date(self, i) -> str:
        return pd.Timestamp(int(self.t[i]) + 19800, unit="s").strftime("%Y-%m-%d")
