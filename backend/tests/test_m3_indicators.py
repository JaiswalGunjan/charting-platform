import numpy as np
import pandas as pd
import pytest

from app.indicators import core

RNG = np.random.default_rng(7)
N = 600
C = 100 * np.exp(np.cumsum(RNG.normal(0, 0.01, N)))
H = C * (1 + np.abs(RNG.normal(0, 0.004, N)))
L = C * (1 - np.abs(RNG.normal(0, 0.004, N)))
V = RNG.integers(1_000, 10_000, N).astype(float)
TAIL = slice(300, None)  # compare after recursive seeds have converged


def test_sma_wma_ema_by_hand():
    x = np.array([1, 2, 3, 4, 5], dtype=float)
    np.testing.assert_allclose(core.sma(x, 3), [np.nan, np.nan, 2, 3, 4])
    np.testing.assert_allclose(core.wma(x, 3), [np.nan, np.nan, 14 / 6, 20 / 6, 26 / 6])
    np.testing.assert_allclose(core.ema(x, 3), [np.nan, np.nan, 2, 3, 4])  # SMA seed, alpha .5
    assert np.isnan(core.sma(x[:2], 3)).all()


def test_ema_matches_pandas():
    ref = pd.Series(C).ewm(span=20, adjust=False).mean().to_numpy()
    np.testing.assert_allclose(core.ema(C, 20)[TAIL], ref[TAIL], rtol=1e-9)


def test_rsi_matches_pandas_wilder():
    d = pd.Series(C).diff()
    g = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    lo = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    ref = (100 - 100 / (1 + g / lo)).to_numpy()
    np.testing.assert_allclose(core.rsi(C, 14)[TAIL], ref[TAIL], rtol=1e-7)
    assert core.rsi(np.arange(1, 50, dtype=float), 14)[-1] == 100
    assert core.rsi(np.arange(50, 1, -1, dtype=float), 14)[-1] == 0
    assert np.isnan(core.rsi(C, 14)[:14]).all() and not np.isnan(core.rsi(C, 14)[14])


def test_macd_matches_pandas():
    s = pd.Series(C)
    line = s.ewm(span=12, adjust=False).mean() - s.ewm(span=26, adjust=False).mean()
    sig = line.ewm(span=9, adjust=False).mean()
    m, sg, hist = core.macd(C)
    np.testing.assert_allclose(m[TAIL], line.to_numpy()[TAIL], rtol=1e-7, atol=1e-9)
    np.testing.assert_allclose(sg[TAIL], sig.to_numpy()[TAIL], rtol=1e-6, atol=1e-9)
    np.testing.assert_allclose(hist, m - sg)


def test_bollinger_matches_pandas():
    s = pd.Series(C)
    mid, up, lo = core.bollinger(C, 20, 2)
    np.testing.assert_allclose(mid[19:], s.rolling(20).mean().to_numpy()[19:])
    np.testing.assert_allclose(up[19:], (s.rolling(20).mean() + 2 * s.rolling(20).std(ddof=0)).to_numpy()[19:])
    assert (up[19:] >= mid[19:]).all() and (lo[19:] <= mid[19:]).all()


def test_atr_and_supertrend_invariants():
    a = core.atr(H, L, C, 14)
    assert np.isnan(a[:13]).all() and (a[13:] > 0).all()  # TR[0] = H-L
    line, d = core.supertrend(H, L, C, 10, 3)
    ok = ~np.isnan(line)
    assert ok.sum() > N - 20
    assert set(np.unique(d[ok])) == {-1.0, 1.0}  # flips both ways on a random walk
    assert (C[ok & (d > 0)] >= line[ok & (d > 0)]).all()   # bullish: price above line
    assert (C[ok & (d < 0)] <= line[ok & (d < 0)]).all()   # bearish: price below line


def test_stochastic_bounds_and_obv():
    k, d = core.stochastic(H, L, C)
    valid = ~np.isnan(d)
    assert valid.sum() > N - 20 and ((k[valid] >= 0) & (k[valid] <= 100)).all()
    np.testing.assert_allclose(core.obv(np.array([1, 2, 2, 1.]), np.array([5, 10, 20, 7.])), [0, 10, 10, 3])


def test_vwap_resets_each_ist_day():
    day0 = 1795000000 - (1795000000 + 19800) % 86400 - 19800 + 33300  # some 09:15 IST
    t = np.r_[day0 + 60 * np.arange(3), day0 + 86400 + 60 * np.arange(3)]
    h = np.array([11, 12, 13, 21, 22, 23.]); l = h - 2; c = h - 1  # noqa: E702,E741
    v = np.array([1, 1, 2, 1, 3, 0.])
    w = core.vwap(t, h, l, c, v)
    tp = (h + l + c) / 3
    assert w[0] == tp[0] and w[3] == tp[3]  # first bar of each session
    assert w[2] == pytest.approx((tp[0] + tp[1] + 2 * tp[2]) / 4)
    assert w[5] == w[4]  # zero volume bar leaves VWAP unchanged
    assert np.isnan(core.vwap(t[:1], h[:1], l[:1], c[:1], np.zeros(1))).all()


# ---- API -----------------------------------------------------------------

def test_indicator_list(client):
    meta = {m["id"]: m for m in client.get("/indicators").json()}
    assert len(meta) >= 10
    assert meta["rsi"]["overlay"] is False and meta["rsi"]["levels"] == [30, 70]
    assert meta["macd"]["outputs"] == ["macd", "signal", "hist"]


def test_indicator_aligned_with_history(client):
    hist = client.get("/history", params=dict(symbol="NSE:RELIANCE", tf="5m", limit=200)).json()
    r = client.get("/indicators/ema", params=dict(symbol="NSE:RELIANCE", tf="5m", limit=200, length=50))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["t"] == hist["t"] and body["params"] == {"length": 50, "source": "close"}
    assert all(x is not None for x in body["outputs"]["ema"])  # warm-up came from earlier bars
    assert body["next_to"] == hist["next_to"]


@pytest.mark.parametrize("ind,params,out", [("ema", {"length": 20}, "ema"), ("rsi", {}, "rsi"),
                                            ("macd", {}, "signal"), ("supertrend", {}, "line")])
def test_indicator_consistent_across_pages(client, ind, params, out):
    base = dict(symbol="NSE:TCS", tf="15m", **params)
    p1 = client.get(f"/indicators/{ind}", params=dict(base, limit=100)).json()
    p2 = client.get(f"/indicators/{ind}", params=dict(base, limit=100, to=p1["next_to"])).json()
    whole = client.get(f"/indicators/{ind}", params=dict(base, limit=200)).json()
    assert p2["t"] + p1["t"] == whole["t"]
    a = np.array(p2["outputs"][out] + p1["outputs"][out], dtype=float)
    np.testing.assert_allclose(a, np.array(whole["outputs"][out], dtype=float), rtol=1e-6)


def test_indicator_errors(client):
    q = dict(symbol="NSE:TCS", tf="1D")
    assert client.get("/indicators/nope", params=q).status_code == 400
    assert client.get("/indicators/ema", params=dict(q, length=0)).status_code == 400
    assert client.get("/indicators/ema", params=dict(q, length="x")).status_code == 400
    assert client.get("/indicators/ema", params=dict(q, symbol="NSE:NOPE")).status_code == 404
