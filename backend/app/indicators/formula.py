"""Custom indicators from one-line formulas (the seed of our own scripting language).

A definition has inputs (named numbers) and up to 8 plots, each `name = expression`:

    fast = 12, slow = 26
    macd = ema(close, fast) - ema(close, slow)
    sig  = ema(macd, 9)
    hist = macd - sig

Expressions are vectorised over the bar series:
  * series: open high low close volume hl2 hlc3 ohlc4, inputs, earlier plots
  * arithmetic + - * / % **, comparisons (1 = true, 0 = false), and / or / not
  * history: x[n] is x n bars ago (n a constant or an input)
  * functions: see FUNCTIONS below; window lengths must be constants or inputs

Safety: text is parsed with Python's `ast` module into a syntax tree that is checked
against a whitelist of node types and names, then interpreted node by node on
numpy arrays. Nothing is ever passed to eval/exec, and there is no attribute access,
no strings, no loops and no user-defined functions, so a formula can only compute.
"""
import ast
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from app.indicators import core, extra

MAX_EXPR_LEN = 500
MAX_PLOTS = 8
MAX_INPUTS = 8
MAX_NODES = 300
MAX_PERIOD = 1000
WARMUP_CAP = 5000
SERIES = ("open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4")
STYLES = ("line", "histogram", "dots", "hidden")


class FormulaError(ValueError):
    def __init__(self, msg: str, plot: str | None = None, col: int | None = None):
        where = f"plot '{plot}'" if plot else "formula"
        if col is not None:
            where += f", column {col + 1}"
        super().__init__(f"{where}: {msg}")
        self.plot, self.col, self.msg = plot, col, msg


@dataclass(frozen=True)
class Fn:
    impl: Callable
    series: int            # number of leading series arguments
    periods: int = 0       # number of trailing window-length arguments (constants/inputs)
    optional: int = 0      # how many trailing periods may be omitted
    warm: int = 1          # warm-up multiplier per period (recursive smoothers need ~10x)
    doc: str = ""


def _cross(a, b, up: bool):
    pa, pb = extra.shift(a, 1), extra.shift(b, 1)
    hit = (a > b) & (pa <= pb) if up else (a < b) & (pa >= pb)
    return hit.astype(float)


def _nz(x, v=0.0):
    return np.where(np.isnan(x), v, x)


FUNCTIONS: dict[str, Fn] = {
    "sma": Fn(core.sma, 1, 1, doc="sma(x, n) simple moving average"),
    "ema": Fn(core.ema, 1, 1, warm=10, doc="ema(x, n) exponential moving average"),
    "wma": Fn(core.wma, 1, 1, doc="wma(x, n) weighted moving average"),
    "rma": Fn(core.rma, 1, 1, warm=20, doc="rma(x, n) Wilder's smoothing"),
    "hma": Fn(extra.hma, 1, 1, warm=2, doc="hma(x, n) Hull moving average"),
    "dema": Fn(extra.dema, 1, 1, warm=20, doc="dema(x, n) double EMA"),
    "tema": Fn(extra.tema, 1, 1, warm=30, doc="tema(x, n) triple EMA"),
    "linreg": Fn(extra.linreg, 1, 1, doc="linreg(x, n) least-squares line end point"),
    "rsi": Fn(core.rsi, 1, 1, warm=20, doc="rsi(x, n) relative strength index"),
    "roc": Fn(extra.roc, 1, 1, doc="roc(x, n) rate of change, %"),
    "change": Fn(lambda x, n=1: x - extra.shift(x, n), 1, 1, optional=1, doc="change(x, n=1) x - x[n]"),
    "stdev": Fn(lambda x, n: extra.rolling(x, n, np.std), 1, 1, doc="stdev(x, n) population std dev"),
    "highest": Fn(lambda x, n: extra.rolling(x, n, np.max), 1, 1, doc="highest(x, n)"),
    "lowest": Fn(lambda x, n: extra.rolling(x, n, np.min), 1, 1, doc="lowest(x, n)"),
    "sum": Fn(extra.rsum, 1, 1, doc="sum(x, n) trailing sum"),
    "atr": Fn(None, 0, 1, warm=20, doc="atr(n) average true range"),  # needs bars, special-cased
    "vwma": Fn(None, 1, 1, doc="vwma(x, n) volume-weighted MA"),        # needs volume, special-cased
    "crossover": Fn(lambda a, b: _cross(a, b, True), 2, doc="crossover(a, b) 1 on the bar a crosses above b"),
    "crossunder": Fn(lambda a, b: _cross(a, b, False), 2, doc="crossunder(a, b) 1 on the bar a crosses below b"),
    "where": Fn(lambda c, a, b: np.where(np.isnan(c), np.nan, np.where(c != 0, a, b)), 3,
                doc="where(cond, a, b) a where cond is true, else b"),
    "nz": Fn(_nz, 2, doc="nz(x, v) x with missing values replaced by v"),
    "abs": Fn(np.abs, 1, doc="abs(x)"),
    "sqrt": Fn(np.sqrt, 1, doc="sqrt(x)"),
    "log": Fn(np.log, 1, doc="log(x) natural log"),
    "exp": Fn(np.exp, 1, doc="exp(x)"),
    "max": Fn(np.fmax, 2, doc="max(a, b) element-wise"),
    "min": Fn(np.fmin, 2, doc="min(a, b) element-wise"),
}
RESERVED = set(SERIES) | set(FUNCTIONS) | {"and", "or", "not", "true", "false"}

_BINOPS = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply, ast.Div: np.divide,
           ast.Mod: np.mod, ast.Pow: np.power}
_CMPOPS = {ast.Gt: np.greater, ast.Lt: np.less, ast.GtE: np.greater_equal, ast.LtE: np.less_equal,
           ast.Eq: np.equal, ast.NotEq: np.not_equal}


@dataclass(frozen=True)
class InputDef:
    name: str
    default: float
    min: float = -1e9
    max: float = 1e9


@dataclass(frozen=True)
class PlotDef:
    name: str
    expr: str
    style: str = "line"
    color: str | None = None


class Program:
    """A checked formula set, ready to run on bars."""

    def __init__(self, inputs: list[InputDef], plots: list[PlotDef]):
        self.inputs, self.plots = inputs, plots
        if not plots:
            raise FormulaError("define at least one plot")
        if len(plots) > MAX_PLOTS or len(inputs) > MAX_INPUTS:
            raise FormulaError(f"at most {MAX_PLOTS} plots and {MAX_INPUTS} inputs")
        names: set[str] = set()
        for d in [*inputs, *plots]:
            if not d.name.isidentifier() or d.name.lower() in RESERVED or d.name.startswith("_"):
                raise FormulaError(f"'{d.name}' cannot be used as a name")
            if d.name in names:
                raise FormulaError(f"duplicate name '{d.name}'")
            names.add(d.name)
        for i in inputs:
            if not i.min <= i.default <= i.max:
                raise FormulaError(f"input '{i.name}' default must be within [{i.min}, {i.max}]")
        self.input_names = {i.name for i in inputs}
        self.trees: list[ast.expr] = []
        known = set(self.input_names)
        for p in plots:
            if p.style not in STYLES:
                raise FormulaError(f"style must be one of {STYLES}", p.name)
            if not p.expr.strip():
                raise FormulaError("empty expression", p.name)
            if len(p.expr) > MAX_EXPR_LEN:
                raise FormulaError(f"expression longer than {MAX_EXPR_LEN} characters", p.name)
            try:
                tree = ast.parse(p.expr.strip(), mode="eval").body
            except SyntaxError as e:
                raise FormulaError(f"syntax error: {e.msg}", p.name, (e.offset or 1) - 1) from None
            except (RecursionError, MemoryError):
                raise FormulaError("expression is nested too deeply", p.name) from None
            if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
                raise FormulaError("expression is too long", p.name)
            self._check(tree, p.name, known)
            self.trees.append(tree)
            known.add(p.name)

    # ---- static checks ------------------------------------------------------------
    def _check(self, node: ast.AST, plot: str, known: set[str]) -> None:
        err = lambda msg: FormulaError(msg, plot, getattr(node, "col_offset", None))  # noqa: E731
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise err("only numbers are allowed as literals")
        elif isinstance(node, ast.Name):
            if node.id not in SERIES and node.id not in known:
                hint = " (plots can only use plots defined above them)" if node.id in {p.name for p in self.plots} else ""
                raise err(f"unknown name '{node.id}'{hint}")
        elif isinstance(node, ast.BinOp):
            if type(node.op) not in _BINOPS:
                raise err("unsupported operator")
            self._check(node.left, plot, known)
            self._check(node.right, plot, known)
        elif isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
                raise err("unsupported operator")
            self._check(node.operand, plot, known)
        elif isinstance(node, ast.BoolOp):
            for v in node.values:
                self._check(v, plot, known)
        elif isinstance(node, ast.Compare):
            if any(type(o) not in _CMPOPS for o in node.ops):
                raise err("unsupported comparison")
            for v in [node.left, *node.comparators]:
                self._check(v, plot, known)
        elif isinstance(node, ast.Subscript):
            self._check(node.value, plot, known)
            self._check_period(node.slice, plot, "history offset", allow_zero=True)
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                name = node.func.id if isinstance(node.func, ast.Name) else "?"
                raise err(f"unknown function '{name}'")
            if node.keywords:
                raise err("named arguments are not supported")
            fn = FUNCTIONS[node.func.id]
            lo, hi = fn.series + fn.periods - fn.optional, fn.series + fn.periods
            if not lo <= len(node.args) <= hi:
                usage = fn.doc.split(")")[0] + ")"
                raise err(f"{node.func.id} takes {lo if lo == hi else f'{lo}-{hi}'} arguments: {usage}")
            for a in node.args[:fn.series]:
                self._check(a, plot, known)
            for a in node.args[fn.series:]:
                self._check_period(a, plot, f"{node.func.id} length")
        else:
            raise err(f"'{ast.unparse(node)}' is not allowed")

    def _check_period(self, node: ast.AST, plot: str, what: str, allow_zero: bool = False) -> None:
        ok = (isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool)
              and (0 if allow_zero else 1) <= node.value <= MAX_PERIOD) or \
             (isinstance(node, ast.Name) and node.id in self.input_names)
        if not ok:
            raise FormulaError(f"{what} must be a whole number from {0 if allow_zero else 1} to "
                               f"{MAX_PERIOD} or an input name", plot, getattr(node, "col_offset", None))

    # ---- evaluation -------------------------------------------------------------
    def _period(self, node: ast.AST, params: dict) -> int:
        v = node.value if isinstance(node, ast.Constant) else params[node.id]
        if float(v) != int(v) or not 0 <= int(v) <= MAX_PERIOD:
            raise ValueError(f"window lengths must be whole numbers up to {MAX_PERIOD}, got {v}")
        return int(v)

    def warmup(self, params: dict) -> int:
        def w(node) -> int:
            if isinstance(node, ast.Name):
                return plot_warm.get(node.id, 0)
            if isinstance(node, ast.Subscript):
                return w(node.value) + self._period(node.slice, params)
            if isinstance(node, ast.Call):
                fn = FUNCTIONS[node.func.id]
                inner = max((w(a) for a in node.args[:fn.series]), default=0)
                return inner + sum(self._period(a, params) * fn.warm for a in node.args[fn.series:])
            return max((w(c) for c in ast.iter_child_nodes(node)), default=0)
        plot_warm: dict[str, int] = {}
        for p, tree in zip(self.plots, self.trees):
            plot_warm[p.name] = w(tree)
        return min(WARMUP_CAP, max(plot_warm.values(), default=0) + 1)

    def run(self, bars, params: dict) -> dict[str, np.ndarray]:
        n = len(bars.c)
        env: dict[str, np.ndarray | float] = {
            "open": bars.o, "high": bars.h, "low": bars.l, "close": bars.c, "volume": bars.v,
            "hl2": (bars.h + bars.l) / 2, "hlc3": (bars.h + bars.l + bars.c) / 3,
            "ohlc4": (bars.o + bars.h + bars.l + bars.c) / 4, **params,
        }
        out = {}
        with np.errstate(all="ignore"):
            for p, tree in zip(self.plots, self.trees):
                val = np.asarray(self._eval(tree, env, bars, params), dtype=float)
                val = np.full(n, float(val)) if val.ndim == 0 else val
                env[p.name] = val
                out[p.name] = np.where(np.isfinite(val), val, np.nan)
        return out

    def _eval(self, node, env, bars, params):
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            return env[node.id]
        if isinstance(node, ast.BinOp):
            return _BINOPS[type(node.op)](self._eval(node.left, env, bars, params),
                                          self._eval(node.right, env, bars, params))
        if isinstance(node, ast.UnaryOp):
            v = self._eval(node.operand, env, bars, params)
            if isinstance(node.op, ast.Not):
                return np.where(np.isnan(v), np.nan, (v == 0).astype(float))
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BoolOp):
            vals = [self._eval(v, env, bars, params) for v in node.values]
            acc = np.asarray(vals[0]) != 0
            for v in vals[1:]:
                acc = (acc & (np.asarray(v) != 0)) if isinstance(node.op, ast.And) else (acc | (np.asarray(v) != 0))
            return acc.astype(float)
        if isinstance(node, ast.Compare):
            left = self._eval(node.left, env, bars, params)
            acc = None
            for op, comp in zip(node.ops, node.comparators):
                right = self._eval(comp, env, bars, params)
                r = _CMPOPS[type(op)](left, right)
                acc = r if acc is None else acc & r
                left = right
            return np.asarray(acc).astype(float)
        if isinstance(node, ast.Subscript):
            v = self._eval(node.value, env, bars, params)
            k = self._period(node.slice, params)
            v = np.full(len(bars.c), float(v)) if np.ndim(v) == 0 else v
            return extra.shift(np.asarray(v, dtype=float), k)
        if isinstance(node, ast.Call):
            name = node.func.id
            fn = FUNCTIONS[name]
            series = [self._series(self._eval(a, env, bars, params), len(bars.c)) for a in node.args[:fn.series]]
            periods = [self._period(a, params) for a in node.args[fn.series:]]
            if fn.periods and any(p < 1 for p in periods):
                raise ValueError(f"{name} length must be at least 1")
            if name == "atr":
                return core.atr(bars.h, bars.l, bars.c, *periods)
            if name == "vwma":
                return extra.vwma(series[0], bars.v, *periods)
            if fn.series and fn.periods:  # smoothers are NaN-intolerant: start at the first value
                return extra.on_valid(fn.impl, series[0], *periods)
            return fn.impl(*series, *periods)
        raise FormulaError("unsupported expression")  # unreachable after _check

    @staticmethod
    def _series(v, n):
        return np.full(n, float(v)) if np.ndim(v) == 0 else np.asarray(v, dtype=float)
