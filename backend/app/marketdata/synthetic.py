"""Deterministic synthetic NSE data, for development without a data licence.

Daily closes are a seeded random walk per ticker. Each day's 1m bars are a
Brownian bridge from that day's open to its close, so 1m and 1D always agree,
and the same request always returns the same bars.
"""
import time
import zlib
from datetime import date, timedelta
from functools import lru_cache

import numpy as np

from app.marketdata.base import MINUTES_PER_SESSION, Bar, SymbolInfo, day_ts, session_open_ts

EPOCH = date(2015, 1, 1)
DAILY_VOL = 0.016
_U_SHAPE = 1.0 + 2.0 * (np.linspace(-1, 1, MINUTES_PER_SESSION) ** 2)  # volume smile

UNIVERSE: list[tuple[str, str, str, float]] = [
    # ticker, name, type, start price (synthetic)
    ("NIFTY 50", "Nifty 50 Index", "INDEX", 8300.0),
    ("NIFTY BANK", "Nifty Bank Index", "INDEX", 18500.0),
    ("RELIANCE", "Reliance Industries", "EQ", 450.0),
    ("TCS", "Tata Consultancy Services", "EQ", 1250.0),
    ("HDFCBANK", "HDFC Bank", "EQ", 480.0),
    ("INFY", "Infosys", "EQ", 990.0),
    ("ICICIBANK", "ICICI Bank", "EQ", 320.0),
    ("SBIN", "State Bank of India", "EQ", 310.0),
    ("BHARTIARTL", "Bharti Airtel", "EQ", 360.0),
    ("ITC", "ITC", "EQ", 330.0),
    ("LT", "Larsen & Toubro", "EQ", 1650.0),
    ("HINDUNILVR", "Hindustan Unilever", "EQ", 750.0),
    ("KOTAKBANK", "Kotak Mahindra Bank", "EQ", 640.0),
    ("AXISBANK", "Axis Bank", "EQ", 490.0),
    ("BAJFINANCE", "Bajaj Finance", "EQ", 3300.0),
    ("MARUTI", "Maruti Suzuki", "EQ", 3400.0),
    ("TATAMOTORS", "Tata Motors", "EQ", 500.0),
    ("SUNPHARMA", "Sun Pharmaceutical", "EQ", 820.0),
    ("WIPRO", "Wipro", "EQ", 280.0),
    ("ASIANPAINT", "Asian Paints", "EQ", 720.0),
]
_START_PRICE = {t: p for t, _, _, p in UNIVERSE}


def _seed(*parts: object) -> int:
    return zlib.crc32("|".join(map(str, parts)).encode())


def _is_trading_day(d: date) -> bool:
    return d.weekday() < 5  # synthetic: ignore exchange holidays


def _round_tick(x: np.ndarray, tick: float) -> np.ndarray:
    return np.round(np.asarray(x) / tick) * tick


@lru_cache(maxsize=64)
def _daily_path(ticker: str, until: date) -> tuple[tuple[date, ...], np.ndarray, np.ndarray]:
    """Trading days from EPOCH..until with (open, close) per day."""
    days = []
    d = EPOCH
    while d <= until:
        if _is_trading_day(d):
            days.append(d)
        d += timedelta(days=1)
    rng = np.random.default_rng(_seed("daily", ticker))
    n = len(days)
    drift = 0.0004
    rets = rng.normal(drift, DAILY_VOL, n)
    gaps = rng.normal(0, DAILY_VOL * 0.3, n)
    closes = np.empty(n)
    opens = np.empty(n)
    prev = _START_PRICE.get(ticker, 100.0 + _seed(ticker) % 900)
    for i in range(n):
        opens[i] = prev * np.exp(gaps[i])
        closes[i] = opens[i] * np.exp(rets[i])
        prev = closes[i]
    return tuple(days), opens, closes


class SyntheticSource:
    name = "synthetic"

    def symbols(self) -> list[SymbolInfo]:
        return [
            SymbolInfo(exchange="NSE", ticker=t, name=n, type=ty, tick_size=0.05)
            for t, n, ty, _ in UNIVERSE
        ]

    def _minutes(self, sym: SymbolInfo, d: date, o: float, c: float) -> tuple[np.ndarray, ...]:
        """(ts, o, h, l, c, v) arrays for one full session."""
        n = MINUTES_PER_SESSION
        rng = np.random.default_rng(_seed("1m", sym.ticker, d.isoformat()))
        sigma = DAILY_VOL / np.sqrt(n)
        w = np.concatenate([[0.0], np.cumsum(rng.normal(0, sigma, n))])
        t = np.arange(n + 1) / n
        bridge = w - t * w[-1] + t * np.log(c / o)
        path = o * np.exp(bridge)
        opens, closes = path[:-1], path[1:]
        wick = np.abs(rng.normal(0, sigma * 0.6, (2, n)))
        highs = np.maximum(opens, closes) * (1 + wick[0])
        lows = np.minimum(opens, closes) * (1 - wick[1])
        tick = sym.tick_size
        opens, highs, lows, closes = (_round_tick(a, tick) for a in (opens, highs, lows, closes))
        highs = np.maximum.reduce([highs, opens, closes])
        lows = np.minimum.reduce([lows, opens, closes])
        base_vol = 0 if sym.type == "INDEX" else 2_000_000 / max(o, 1) * 50
        vols = np.round(base_vol * _U_SHAPE * rng.lognormal(0, 0.4, n))
        ts = session_open_ts(d) + 60 * np.arange(n)
        return ts, opens, highs, lows, closes, vols

    def candles(self, sym: SymbolInfo, tf: str, start: date, end: date,
                now: float | None = None) -> list[Bar]:
        """`now` (epoch s) caps output: no bar that opens in the future is returned."""
        if tf not in ("1m", "1D"):
            raise ValueError(f"unsupported base timeframe {tf!r}")
        now = time.time() if now is None else now
        days, opens, closes = _daily_path(sym.ticker, max(end, EPOCH))
        out: list[Bar] = []
        for i, d in enumerate(days):
            if d < start or d > end or session_open_ts(d) > now:
                continue
            ts, o, h, l, c, v = self._minutes(sym, d, float(opens[i]), float(closes[i]))  # noqa: E741
            k = int(np.searchsorted(ts, now, side="right"))  # bars opened at or before now
            if tf == "1m":
                out.extend(Bar(int(ts[j]), float(o[j]), float(h[j]), float(l[j]), float(c[j]), float(v[j]))
                           for j in range(k))
            else:
                out.append(Bar(day_ts(d), float(o[0]), float(h[:k].max()), float(l[:k].min()),
                               float(c[k - 1]), float(v[:k].sum())))
        return out
