"""Indicator registry: metadata for the UI + a uniform compute interface.

Each indicator declares its inputs (params), its outputs and how each output is
drawn (Plot). A `source` param picks the price series (close, hl2, ...); compute()
resolves it to an array before calling the indicator function.
"""
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from app.indicators import core, extra

SOURCES = ("close", "open", "high", "low", "hl2", "hlc3", "ohlc4")
CATEGORIES = ("Moving averages", "Trend & bands", "Momentum", "Volatility", "Volume")


def price_source(bars, name: str) -> np.ndarray:
    if name == "hl2":
        return (bars.h + bars.l) / 2
    if name == "hlc3":
        return (bars.h + bars.l + bars.c) / 3
    if name == "ohlc4":
        return (bars.o + bars.h + bars.l + bars.c) / 4
    return {"close": bars.c, "open": bars.o, "high": bars.h, "low": bars.l}[name]


@dataclass(frozen=True)
class Param:
    name: str
    default: float | str
    min: float = 0
    max: float = 0
    kind: str = "int"  # "int" | "float" | "source"
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class Plot:
    name: str
    style: str = "line"          # line | histogram | dots | hidden
    color: str | None = None     # None: the UI picks one (cycled per instance for MAs)


@dataclass(frozen=True)
class Indicator:
    id: str
    title: str
    category: str
    overlay: bool                       # True: draw on price pane; False: own pane
    plots: tuple[Plot, ...]
    params: tuple[Param, ...]
    fn: Callable[..., dict[str, np.ndarray]] = field(repr=False)
    warmup: Callable[[dict], int] = field(repr=False)
    levels: tuple[float, ...] = ()      # reference lines for oscillators (e.g. RSI 30/70)
    lookahead: Callable[[dict], int] = field(default=lambda p: 0, repr=False)  # future bars read

    @property
    def outputs(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.plots)

    def resolve_params(self, raw: dict[str, str]) -> dict[str, float | str]:
        out: dict[str, float | str] = {}
        for p in self.params:
            val = raw.get(p.name, p.default)
            if p.kind == "source":
                if val not in p.options:
                    raise ValueError(f"{self.id}.{p.name} must be one of {list(p.options)}")
                out[p.name] = val
                continue
            try:
                num = float(val)
                if p.kind == "int":
                    if not num.is_integer():
                        raise ValueError
                    num = int(num)
            except (TypeError, ValueError):
                raise ValueError(f"{self.id}.{p.name} must be {p.kind}, got {val!r}") from None
            if not p.min <= num <= p.max:
                raise ValueError(f"{self.id}.{p.name} must be within [{p.min}, {p.max}]")
            out[p.name] = num
        return out


# ---- declaration helpers ---------------------------------------------------------
def _p(name, default, lo, hi, kind="int"):
    return Param(name, default, lo, hi, kind)


def LEN(d, name="length", hi=500):  # noqa: N802
    return _p(name, d, 1, hi)


def MULT(d, name="mult", lo=0.1, hi=20):  # noqa: N802
    return _p(name, d, lo, hi, "float")


SRC = Param("source", "close", kind="source", options=SOURCES)
L = Plot  # short alias for declarations


def _lines(*names, colors=()):
    cs = list(colors) + [None] * len(names)
    return tuple(Plot(n, "line", c) for n, c in zip(names, cs))


def _zip(names, values):
    return dict(zip(names, values))


BLUE, ORANGE, PURPLE, TEAL, RED, GREEN, YELLOW, GREY = (
    "#2962ff", "#ff9800", "#9c27b0", "#00acc1", "#e53935", "#43a047", "#fbc02d", "#78909c")
BANDS = (L("mid", color=ORANGE), L("upper", color=BLUE), L("lower", color=BLUE))
MA = "Moving averages"
TREND = "Trend & bands"
MOM = "Momentum"
VOLA = "Volatility"
VOL = "Volume"


def _ma(id_, title, fn, warm, extra_params=()):
    return Indicator(id_, title, MA, True, (L(id_),), (LEN(20), SRC, *extra_params),
                     lambda b, length, source, **kw: {id_: fn(source, length, **kw)}, warm)


INDICATORS: dict[str, Indicator] = {i.id: i for i in [
    # -- moving averages
    _ma("sma", "Simple Moving Average", core.sma, lambda p: p["length"]),
    _ma("ema", "Exponential Moving Average", core.ema, lambda p: p["length"] * 10),
    _ma("wma", "Weighted Moving Average", core.wma, lambda p: p["length"]),
    _ma("dema", "Double EMA", extra.dema, lambda p: p["length"] * 20),
    _ma("tema", "Triple EMA", extra.tema, lambda p: p["length"] * 30),
    _ma("hma", "Hull Moving Average", extra.hma, lambda p: p["length"] * 2),
    _ma("smma", "Smoothed MA (RMA)", core.rma, lambda p: p["length"] * 20),
    _ma("alma", "Arnaud Legoux MA", extra.alma, lambda p: p["length"],
        (MULT(0.85, "offset", 0, 1), MULT(6.0, "sigma", 0.1, 50))),
    _ma("kama", "Kaufman Adaptive MA", extra.kama, lambda p: p["length"] + 300,
        (LEN(2, "fast", 100), LEN(30, "slow", 400))),
    _ma("linreg", "Linear Regression", extra.linreg, lambda p: p["length"]),
    Indicator("vwma", "Volume-Weighted MA", MA, True, (L("vwma"),), (LEN(20),),
              lambda b, length: {"vwma": extra.vwma(b.c, b.v, length)}, lambda p: p["length"]),
    Indicator("vwap", "VWAP (session)", MA, True, (L("vwap", color=PURPLE),), (),
              lambda b: {"vwap": core.vwap(b.t, b.h, b.l, b.c, b.v)}, lambda p: 0),

    # -- trend & bands
    Indicator("bb", "Bollinger Bands", TREND, True, BANDS, (LEN(20), MULT(2.0, hi=10), SRC),
              lambda b, length, mult, source: _zip(("mid", "upper", "lower"), core.bollinger(source, length, mult)),
              lambda p: p["length"]),
    Indicator("keltner", "Keltner Channels", TREND, True, BANDS, (LEN(20), MULT(2.0), LEN(10, "atr_length")),
              lambda b, length, mult, atr_length: _zip(("mid", "upper", "lower"),
                                                       extra.keltner(b.h, b.l, b.c, length, mult, atr_length)),
              lambda p: max(p["length"] * 10, p["atr_length"] * 20)),
    Indicator("donchian", "Donchian Channels", TREND, True, BANDS, (LEN(20),),
              lambda b, length: _zip(("mid", "upper", "lower"), extra.donchian(b.h, b.l, length)),
              lambda p: p["length"]),
    Indicator("envelopes", "Envelopes", TREND, True, BANDS, (LEN(20), MULT(2.5, "percent", 0.1, 50), SRC),
              lambda b, length, percent, source: _zip(("mid", "upper", "lower"),
                                                      extra.envelopes(source, length, percent)),
              lambda p: p["length"]),
    Indicator("supertrend", "Supertrend", TREND, True, (L("line"), Plot("direction", "hidden")),
              (LEN(10), MULT(3.0)),
              lambda b, length, mult: _zip(("line", "direction"), core.supertrend(b.h, b.l, b.c, length, mult)),
              lambda p: p["length"] * 20),  # RMA (alpha=1/n) needs ~20n bars to converge to e^-20
    Indicator("psar", "Parabolic SAR", TREND, True, (Plot("sar", "dots", BLUE),),
              (MULT(0.02, "start", 0.001, 1), MULT(0.02, "increment", 0.001, 1), MULT(0.2, "maximum", 0.01, 1)),
              lambda b, start, increment, maximum: {"sar": extra.psar(b.h, b.l, start, increment, maximum)},
              lambda p: 200),
    Indicator("ichimoku", "Ichimoku Cloud", TREND, True,
              _lines("conversion", "base", "span_a", "span_b", "lagging",
                     colors=(BLUE, RED, GREEN, RED, PURPLE)),
              (LEN(9, "conversion"), LEN(26, "base"), LEN(52, "span_b"), LEN(26, "displacement")),
              lambda b, conversion, base, span_b, displacement: _zip(
                  ("conversion", "base", "span_a", "span_b", "lagging"),
                  extra.ichimoku(b.h, b.l, b.c, conversion, base, span_b, displacement)),
              lambda p: p["span_b"] + p["displacement"], lookahead=lambda p: p["displacement"]),
    Indicator("dmi", "ADX / DMI", TREND, False,
              _lines("plus_di", "minus_di", "adx", colors=(GREEN, RED, BLUE)), (LEN(14), LEN(14, "adx_smoothing")),
              lambda b, length, adx_smoothing: _zip(("plus_di", "minus_di", "adx"),
                                                    extra.dmi(b.h, b.l, b.c, length, adx_smoothing)),
              lambda p: (p["length"] + p["adx_smoothing"]) * 20, levels=(20,)),
    Indicator("aroon", "Aroon", TREND, False, _lines("up", "down", colors=(ORANGE, BLUE)), (LEN(14),),
              lambda b, length: _zip(("up", "down"), extra.aroon(b.h, b.l, length)),
              lambda p: p["length"] + 1, levels=(30, 70)),
    Indicator("vortex", "Vortex Indicator", TREND, False, _lines("plus", "minus", colors=(BLUE, RED)), (LEN(14),),
              lambda b, length: _zip(("plus", "minus"), extra.vortex(b.h, b.l, b.c, length)),
              lambda p: p["length"] + 1, levels=(1,)),

    # -- momentum
    Indicator("rsi", "Relative Strength Index", MOM, False, (L("rsi", color=PURPLE),), (LEN(14), SRC),
              lambda b, length, source: {"rsi": core.rsi(source, length)},
              lambda p: p["length"] * 20, levels=(30, 70)),
    Indicator("macd", "MACD", MOM, False,
              (L("macd", color=BLUE), L("signal", color=ORANGE), Plot("hist", "histogram")),
              (LEN(12, "fast", 200), LEN(26, "slow", 400), LEN(9, "signal", 200), SRC),
              lambda b, fast, slow, signal, source: _zip(("macd", "signal", "hist"),
                                                         core.macd(source, fast, slow, signal)),
              lambda p: (max(p["fast"], p["slow"]) + p["signal"]) * 10, levels=(0,)),
    Indicator("stoch", "Stochastic", MOM, False, _lines("k", "d", colors=(BLUE, ORANGE)),
              (LEN(14, "k", 200), LEN(3, "smooth_k", 50), LEN(3, "d", 50)),
              lambda b, k, smooth_k, d: _zip(("k", "d"), core.stochastic(b.h, b.l, b.c, k, smooth_k, d)),
              lambda p: p["k"] + p["smooth_k"] + p["d"], levels=(20, 80)),
    Indicator("stochrsi", "Stochastic RSI", MOM, False, _lines("k", "d", colors=(BLUE, ORANGE)),
              (LEN(14, "rsi_length", 200), LEN(14, "stoch_length", 200), LEN(3, "k", 50), LEN(3, "d", 50), SRC),
              lambda b, rsi_length, stoch_length, k, d, source: _zip(
                  ("k", "d"), extra.stoch_rsi(source, rsi_length, stoch_length, k, d)),
              lambda p: p["rsi_length"] * 20 + p["stoch_length"] + p["k"] + p["d"], levels=(20, 80)),
    Indicator("cci", "Commodity Channel Index", MOM, False, (L("cci", color=TEAL),), (LEN(20),),
              lambda b, length: {"cci": extra.cci(b.h, b.l, b.c, length)},
              lambda p: p["length"], levels=(-100, 100)),
    Indicator("willr", "Williams %R", MOM, False, (L("willr", color=PURPLE),), (LEN(14),),
              lambda b, length: {"willr": extra.williams_r(b.h, b.l, b.c, length)},
              lambda p: p["length"], levels=(-80, -20)),
    Indicator("roc", "Rate of Change", MOM, False, (L("roc", color=BLUE),), (LEN(9), SRC),
              lambda b, length, source: {"roc": extra.roc(source, length)},
              lambda p: p["length"], levels=(0,)),
    Indicator("mom", "Momentum", MOM, False, (L("mom", color=BLUE),), (LEN(10), SRC),
              lambda b, length, source: {"mom": extra.momentum(source, length)},
              lambda p: p["length"], levels=(0,)),
    Indicator("ao", "Awesome Oscillator", MOM, False, (Plot("ao", "histogram"),), (),
              lambda b: {"ao": extra.awesome(b.h, b.l)}, lambda p: 34, levels=(0,)),
    Indicator("uo", "Ultimate Oscillator", MOM, False, (L("uo", color=RED),),
              (LEN(7, "fast"), LEN(14, "middle"), LEN(28, "slow")),
              lambda b, fast, middle, slow: {"uo": extra.ultimate(b.h, b.l, b.c, fast, middle, slow)},
              lambda p: max(p["fast"], p["middle"], p["slow"]) + 1, levels=(30, 70)),
    Indicator("trix", "TRIX", MOM, False, _lines("trix", "signal", colors=(RED, BLUE)),
              (LEN(18), LEN(9, "signal"), SRC),
              lambda b, length, signal, source: _zip(("trix", "signal"), extra.trix(source, length, signal)),
              lambda p: p["length"] * 30 + p["signal"] * 10, levels=(0,)),
    Indicator("tsi", "True Strength Index", MOM, False, _lines("tsi", "signal", colors=(BLUE, RED)),
              (LEN(25, "long"), LEN(13, "short"), LEN(13, "signal"), SRC),
              lambda b, long, short, signal, source: _zip(("tsi", "signal"), extra.tsi(source, long, short, signal)),
              lambda p: (p["long"] + p["short"] + p["signal"]) * 10, levels=(0,)),
    Indicator("cmo", "Chande Momentum Oscillator", MOM, False, (L("cmo", color=BLUE),), (LEN(9), SRC),
              lambda b, length, source: {"cmo": extra.cmo(source, length)},
              lambda p: p["length"] + 1, levels=(-50, 50)),
    Indicator("dpo", "Detrended Price Oscillator", MOM, False, (L("dpo", color=GREEN),), (LEN(21), SRC),
              lambda b, length, source: {"dpo": extra.dpo(source, length)},
              lambda p: p["length"] + p["length"] // 2 + 1, levels=(0,)),
    Indicator("ppo", "Percentage Price Oscillator", MOM, False,
              (L("ppo", color=BLUE), L("signal", color=ORANGE), Plot("hist", "histogram")),
              (LEN(12, "fast", 200), LEN(26, "slow", 400), LEN(9, "signal", 200), SRC),
              lambda b, fast, slow, signal, source: _zip(("ppo", "signal", "hist"),
                                                         extra.ppo(source, fast, slow, signal)),
              lambda p: (max(p["fast"], p["slow"]) + p["signal"]) * 10, levels=(0,)),
    Indicator("bbpower", "Bull Bear Power (Elder Ray)", MOM, False,
              (Plot("bull", "histogram", GREEN), Plot("bear", "histogram", RED)), (LEN(13),),
              lambda b, length: _zip(("bull", "bear"), extra.elder_ray(b.h, b.l, b.c, length)),
              lambda p: p["length"] * 10, levels=(0,)),
    Indicator("coppock", "Coppock Curve", MOM, False, (L("coppock", color=BLUE),),
              (LEN(10, "wma_length"), LEN(14, "long_roc"), LEN(11, "short_roc"), SRC),
              lambda b, wma_length, long_roc, short_roc, source: {
                  "coppock": extra.coppock(source, wma_length, long_roc, short_roc)},
              lambda p: max(p["long_roc"], p["short_roc"]) + p["wma_length"], levels=(0,)),

    # -- volatility
    Indicator("atr", "Average True Range", VOLA, False, (L("atr", color=RED),), (LEN(14),),
              lambda b, length: {"atr": core.atr(b.h, b.l, b.c, length)},
              lambda p: p["length"] * 20),
    Indicator("hv", "Historical Volatility", VOLA, False, (L("hv", color=BLUE),),
              (LEN(20), LEN(252, "periods_per_year", 100_000)),
              lambda b, length, periods_per_year: {"hv": extra.hist_vol(b.c, length, periods_per_year)},
              lambda p: p["length"] + 1),
    Indicator("bbpct", "Bollinger %B", VOLA, False, (L("percent_b", color=TEAL),), (LEN(20), MULT(2.0, hi=10), SRC),
              lambda b, length, mult, source: {"percent_b": extra.bb_percent_b(source, length, mult)},
              lambda p: p["length"], levels=(0, 1)),
    Indicator("bbw", "Bollinger BandWidth", VOLA, False, (L("width", color=BLUE),), (LEN(20), MULT(2.0, hi=10), SRC),
              lambda b, length, mult, source: {"width": extra.bb_width(source, length, mult)},
              lambda p: p["length"]),

    # -- volume
    Indicator("obv", "On-Balance Volume", VOL, False, (L("obv", color=TEAL),), (),
              lambda b: {"obv": core.obv(b.c, b.v)}, lambda p: 0),
    Indicator("mfi", "Money Flow Index", VOL, False, (L("mfi", color=PURPLE),), (LEN(14),),
              lambda b, length: {"mfi": extra.mfi(b.h, b.l, b.c, b.v, length)},
              lambda p: p["length"] + 1, levels=(20, 80)),
    Indicator("cmf", "Chaikin Money Flow", VOL, False, (L("cmf", color=GREEN),), (LEN(20),),
              lambda b, length: {"cmf": extra.cmf(b.h, b.l, b.c, b.v, length)},
              lambda p: p["length"], levels=(0,)),
    Indicator("adl", "Accumulation/Distribution", VOL, False, (L("adl", color=BLUE),), (),
              lambda b: {"adl": extra.adl(b.h, b.l, b.c, b.v)}, lambda p: 0),
    Indicator("chaikin", "Chaikin Oscillator", VOL, False, (L("osc", color=RED),),
              (LEN(3, "fast"), LEN(10, "slow")),
              lambda b, fast, slow: {"osc": extra.chaikin_osc(b.h, b.l, b.c, b.v, fast, slow)},
              lambda p: max(p["fast"], p["slow"]) * 10, levels=(0,)),
    Indicator("efi", "Elder Force Index", VOL, False, (L("efi", color=RED),), (LEN(13),),
              lambda b, length: {"efi": extra.force_index(b.c, b.v, length)},
              lambda p: p["length"] * 10, levels=(0,)),
    Indicator("eom", "Ease of Movement", VOL, False, (L("eom", color=GREEN),),
              (LEN(14), _p("divisor", 10_000, 1, 1e12, "float")),
              lambda b, length, divisor: {"eom": extra.ease_of_movement(b.h, b.l, b.v, length, divisor)},
              lambda p: p["length"] + 1, levels=(0,)),
]}


def get_indicator(ind_id: str) -> Indicator:
    try:
        return INDICATORS[ind_id]
    except KeyError:
        raise ValueError(f"unknown indicator {ind_id!r}; one of {list(INDICATORS)}") from None


def compute(ind: Indicator, bars, params: dict) -> dict[str, np.ndarray]:
    args = {k: (price_source(bars, v) if k == "source" else v) for k, v in params.items()}
    return ind.fn(bars, **args)
