"""Formula-based custom indicators: language semantics, safety, warm-up and the API."""
from types import SimpleNamespace

import numpy as np
import pytest

from app.indicators import core
from app.indicators.formula import FormulaError, InputDef, PlotDef, Program

RNG = np.random.default_rng(3)
N = 400
C = 100 * np.exp(np.cumsum(RNG.normal(0, 0.01, N)))
H, L = C * 1.01, C * 0.99
BARS = SimpleNamespace(t=np.arange(N), o=C, h=H, l=L, c=C, v=np.full(N, 1000.0))


def run(*plots, inputs=(), params=None):
    prog = Program(list(inputs), [PlotDef(n, e) for n, e in plots])
    return prog.run(BARS, params or {i.name: i.default for i in inputs}), prog


def test_macd_from_formulas_matches_builtin():
    out, prog = run(("macd", "ema(close, fast) - ema(close, slow)"), ("sig", "ema(macd, 9)"),
                    ("hist", "macd - sig"), inputs=[InputDef("fast", 12), InputDef("slow", 26)])
    line, sig, hist = core.macd(C, 12, 26, 9)
    np.testing.assert_allclose(out["macd"], line, equal_nan=True)
    np.testing.assert_allclose(out["sig"][100:], sig[100:])
    np.testing.assert_allclose(out["hist"][100:], hist[100:])
    assert prog.warmup({"fast": 12, "slow": 26}) >= 260 + 90


def test_operators_history_and_functions():
    out, _ = run(("a", "close[1]"), ("b", "(close > close[1]) and not (close > 1e9)"),
                 ("c", "where(close > sma(close, 5), 1, -1)"), ("d", "crossover(close, sma(close, 10))"),
                 ("e", "nz(close[3], 0) + 2 ** 2 % 3"), ("f", "50"), ("g", "max(high - low, abs(change(close)))"),
                 ("h", "highest(high, 3) - lowest(low, 3)"))
    np.testing.assert_allclose(out["a"][1:], C[:-1])
    assert np.isnan(out["a"][0])
    np.testing.assert_array_equal(out["b"][1:], (C[1:] > C[:-1]).astype(float))
    assert set(np.unique(out["c"][10:])) <= {-1.0, 1.0}
    assert set(np.unique(out["d"][11:])) <= {0.0, 1.0} and out["d"].sum() > 0
    assert out["e"][0] == 1.0 and out["e"][5] == C[2] + 1
    assert (out["f"] == 50).all()
    np.testing.assert_allclose(out["h"][2:], (np.maximum.reduce([H[2:], H[1:-1], H[:-2]])
                                              - np.minimum.reduce([L[2:], L[1:-1], L[:-2]])))


def test_division_by_zero_is_missing_not_error():
    out, _ = run(("x", "close / (close - close)"))
    assert np.isnan(out["x"]).all()


@pytest.mark.parametrize("expr,msg", [
    ("__import__('os').system('echo hi')", "unknown function"),
    ("close.__class__", "not allowed"),
    ("open('x')", "unknown function 'open'"),  # a series name, not Python's open()
    ("'abc'", "only numbers"),
    ("[c for c in close]", "not allowed"),
    ("lambda: 1", "not allowed"),
    ("sma(close, -1)", "length must be"),
    ("sma(close, 2.5)", "length must be"),
    ("sma(close, close)", "length must be"),
    ("sma(close)", "takes"),
    ("close[1:3]", "history offset"),
    ("clsoe + 1", "unknown name 'clsoe'"),
    ("later", "plots defined above"),
    ("ema(close, length=3)", "named arguments"),
    ("1 +", "syntax error"),
    ("x := 3", "syntax error"),
    ("(" * 300 + "1" + ")" * 300, ""),
])
def test_rejected(expr, msg):
    with pytest.raises(FormulaError) as e:
        Program([], [PlotDef("p", expr), PlotDef("later", "1")])
    assert msg in str(e.value)


def test_names_and_limits():
    with pytest.raises(FormulaError, match="cannot be used"):
        Program([], [PlotDef("close", "1")])
    with pytest.raises(FormulaError, match="duplicate"):
        Program([InputDef("n", 3)], [PlotDef("n", "1")])
    with pytest.raises(FormulaError, match="at most"):
        Program([], [PlotDef(f"p{i}", "1") for i in range(9)])
    with pytest.raises(FormulaError, match="style"):
        Program([], [PlotDef("p", "1", style="area")])


DEF = {"name": "My MACD", "overlay": False,
       "inputs": [{"name": "fast", "default": 12, "min": 1, "max": 200}, {"name": "slow", "default": 26}],
       "plots": [{"name": "macd", "expr": "ema(close, fast) - ema(close, slow)", "color": "#2962ff"},
                 {"name": "sig", "expr": "ema(macd, 9)"},
                 {"name": "hist", "expr": "macd - sig", "style": "histogram"}],
       "levels": [0]}


def test_custom_api_roundtrip(client):
    assert client.post("/custom-indicators/check", json=DEF).json()["ok"] is True
    bad = client.post("/custom-indicators/check", json={**DEF, "plots": [{"name": "x", "expr": "ema(close)"}]})
    assert bad.status_code == 400 and bad.json()["detail"]["plot"] == "x"

    r = client.post("/custom-indicators", json=DEF)
    assert r.status_code == 201
    cid = r.json()["id"]
    assert cid.startswith("custom-") and r.json()["warmup"] > 300

    meta = {m["id"]: m for m in client.get("/indicators").json()}
    assert meta[cid]["category"] == "Custom" and meta[cid]["outputs"] == ["macd", "sig", "hist"]
    assert meta[cid]["plots"][2]["style"] == "histogram" and meta[cid]["levels"] == [0]

    q = dict(symbol="NSE:TCS", tf="1D", limit=100)
    mine = client.get(f"/indicators/{cid}", params=dict(q, fast=12, slow=26)).json()
    builtin = client.get("/indicators/macd", params=q).json()
    assert mine["t"] == builtin["t"]
    np.testing.assert_allclose(np.array(mine["outputs"]["macd"], float), np.array(builtin["outputs"]["macd"], float))
    np.testing.assert_allclose(np.array(mine["outputs"]["hist"], float), np.array(builtin["outputs"]["hist"], float),
                               rtol=1e-6)
    assert client.get(f"/indicators/{cid}", params=dict(q, fast=500)).status_code == 400   # above max
    assert client.get(f"/indicators/{cid}", params=dict(q, fast=2.5)).status_code == 400   # not a whole length

    upd = client.put(f"/custom-indicators/{cid}", json={**DEF, "name": "Renamed", "overlay": True})
    assert upd.json()["name"] == "Renamed" and upd.json()["overlay"] is True
    assert client.delete(f"/custom-indicators/{cid}").status_code == 204
    assert client.get(f"/indicators/{cid}", params=q).status_code == 404
    assert client.delete("/custom-indicators/custom-abc").status_code == 404
