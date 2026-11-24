"""Indicator registry: metadata for the UI + a uniform compute interface."""
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from app.indicators import core


@dataclass(frozen=True)
class Param:
    name: str
    default: float
    min: float
    max: float
    kind: str = "int"  # "int" | "float"


@dataclass(frozen=True)
class Indicator:
    id: str
    title: str
    overlay: bool                       # True: draw on price pane; False: own pane
    outputs: tuple[str, ...]
    params: tuple[Param, ...]
    fn: Callable[..., dict[str, np.ndarray]] = field(repr=False)
    warmup: Callable[[dict], int] = field(repr=False)
    levels: tuple[float, ...] = ()      # reference lines for oscillators (e.g. RSI 30/70)

    def resolve_params(self, raw: dict[str, str]) -> dict[str, float]:
        out = {}
        for p in self.params:
            val = raw.get(p.name, p.default)
            try:
                num = int(val) if p.kind == "int" else float(val)
            except (TypeError, ValueError):
                raise ValueError(f"{self.id}.{p.name} must be {p.kind}, got {val!r}") from None
            if not p.min <= num <= p.max:
                raise ValueError(f"{self.id}.{p.name} must be within [{p.min}, {p.max}]")
            out[p.name] = num
        return out


def _p(name, default, lo, hi, kind="int"):
    return Param(name, default, lo, hi, kind)


LEN = lambda d: _p("length", d, 1, 500)  # noqa: E731

INDICATORS: dict[str, Indicator] = {i.id: i for i in [
    Indicator("sma", "Simple Moving Average", True, ("sma",), (LEN(20),),
              lambda b, length: {"sma": core.sma(b.c, length)},
              lambda p: p["length"]),
    Indicator("ema", "Exponential Moving Average", True, ("ema",), (LEN(20),),
              lambda b, length: {"ema": core.ema(b.c, length)},
              lambda p: p["length"] * 10),
    Indicator("wma", "Weighted Moving Average", True, ("wma",), (LEN(20),),
              lambda b, length: {"wma": core.wma(b.c, length)},
              lambda p: p["length"]),
    Indicator("bb", "Bollinger Bands", True, ("mid", "upper", "lower"),
              (LEN(20), _p("mult", 2.0, 0.1, 10, "float")),
              lambda b, length, mult: dict(zip(("mid", "upper", "lower"), core.bollinger(b.c, length, mult))),
              lambda p: p["length"]),
    Indicator("vwap", "VWAP (session)", True, ("vwap",), (),
              lambda b: {"vwap": core.vwap(b.t, b.h, b.l, b.c, b.v)},
              lambda p: 0),
    Indicator("supertrend", "Supertrend", True, ("line", "direction"),
              (LEN(10), _p("mult", 3.0, 0.1, 20, "float")),
              lambda b, length, mult: dict(zip(("line", "direction"),
                                               core.supertrend(b.h, b.l, b.c, length, mult))),
              lambda p: p["length"] * 20),  # RMA (alpha=1/n) needs ~20n bars to converge to e^-20
    Indicator("rsi", "Relative Strength Index", False, ("rsi",), (LEN(14),),
              lambda b, length: {"rsi": core.rsi(b.c, length)},
              lambda p: p["length"] * 20, levels=(30, 70)),
    Indicator("macd", "MACD", False, ("macd", "signal", "hist"),
              (_p("fast", 12, 1, 200), _p("slow", 26, 1, 400), _p("signal", 9, 1, 200)),
              lambda b, fast, slow, signal: dict(zip(("macd", "signal", "hist"),
                                                     core.macd(b.c, fast, slow, signal))),
              lambda p: (max(p["fast"], p["slow"]) + p["signal"]) * 10, levels=(0,)),
    Indicator("atr", "Average True Range", False, ("atr",), (LEN(14),),
              lambda b, length: {"atr": core.atr(b.h, b.l, b.c, length)},
              lambda p: p["length"] * 20),
    Indicator("stoch", "Stochastic", False, ("k", "d"),
              (_p("k", 14, 1, 200), _p("smooth_k", 3, 1, 50), _p("d", 3, 1, 50)),
              lambda b, k, smooth_k, d: dict(zip(("k", "d"), core.stochastic(b.h, b.l, b.c, k, smooth_k, d))),
              lambda p: p["k"] + p["smooth_k"] + p["d"], levels=(20, 80)),
    Indicator("obv", "On-Balance Volume", False, ("obv",), (),
              lambda b: {"obv": core.obv(b.c, b.v)},
              lambda p: 0),
]}


def get_indicator(ind_id: str) -> Indicator:
    try:
        return INDICATORS[ind_id]
    except KeyError:
        raise ValueError(f"unknown indicator {ind_id!r}; one of {list(INDICATORS)}") from None


def compute(ind: Indicator, bars, params: dict) -> dict[str, np.ndarray]:
    return ind.fn(bars, **params)
