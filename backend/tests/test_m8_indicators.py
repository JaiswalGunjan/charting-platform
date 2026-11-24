"""The 50-indicator set: reference checks against independent implementations,
invariants, and API-level warm-up / paging consistency for every indicator."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.indicators import core, extra
from app.indicators.registry import CATEGORIES, INDICATORS, compute, price_source

RNG = np.random.default_rng(11)
N = 800
C = 100 * np.exp(np.cumsum(RNG.normal(0, 0.01, N)))
O = np.r_[C[0], C[:-1]] * (1 + RNG.normal(0, 0.002, N))
H = np.maximum(C, O) * (1 + np.abs(RNG.normal(0, 0.004, N)))
L = np.minimum(C, O) * (1 - np.abs(RNG.normal(0, 0.004, N)))
V = RNG.integers(1_000, 10_000, N).astype(float)
T = np.arange(N, dtype=np.int64) * 86400
BARS = SimpleNamespace(t=T, o=O, h=H, l=L, c=C, v=V)
S, Hs, Ls, Vs = pd.Series(C), pd.Series(H), pd.Series(L), pd.Series(V)
TAIL = slice(400, None)


def close(a, b, **kw):
    np.testing.assert_allclose(np.asarray(a, float), np.asarray(b, float), **{"rtol": 1e-9, "atol": 1e-9, **kw})


def test_registry_shape():
    assert len(INDICATORS) == 50
    for ind in INDICATORS.values():
        assert ind.category in CATEGORIES
        assert len(set(ind.outputs)) == len(ind.outputs)
        params = ind.resolve_params({})
        out = compute(ind, BARS, params)
        assert set(out) == set(ind.outputs), ind.id
        for k, v in out.items():
            assert v.shape == (N,), (ind.id, k)
            tail = v[-200:-30] if (ind.id, k) == ("ichimoku", "lagging") else v[-200:]
            assert np.isfinite(tail).all(), (ind.id, k)  # defined once warmed up
        assert int(ind.warmup(params)) >= 0


def test_sources():
    close(price_source(BARS, "hlc3"), (H + L + C) / 3)
    close(price_source(BARS, "ohlc4"), (O + H + L + C) / 4)
    ema = INDICATORS["ema"]
    p = ema.resolve_params({"length": "10", "source": "hl2"})
    close(compute(ema, BARS, p)["ema"], core.ema((H + L) / 2, 10))
    with pytest.raises(ValueError):
        ema.resolve_params({"source": "volume"})
    with pytest.raises(ValueError):
        ema.resolve_params({"length": "2.5"})


def test_moving_averages():
    e1 = core.ema(C, 10)
    close(extra.dema(C, 10)[TAIL], (2 * e1 - core.ema(e1, 10))[TAIL])
    ref_hma = pd.Series(2 * core.wma(C, 8) - core.wma(C, 16))
    w = np.arange(1, 5, dtype=float)
    close(extra.hma(C, 16)[TAIL], ref_hma.rolling(4).apply(lambda x: (x * w).sum() / w.sum(), raw=True)[TAIL])
    close(extra.vwma(C, V, 20)[TAIL], ((S * Vs).rolling(20).sum() / Vs.rolling(20).sum())[TAIL])
    # linear regression end point == np.polyfit on the window
    i = 500
    slope, icpt = np.polyfit(np.arange(25), C[i - 24:i + 1], 1)
    close(extra.linreg(C, 25)[i], icpt + slope * 24)
    # ALMA with sigma -> inf is the SMA
    close(extra.alma(C, 9, 0.85, 1e-9)[TAIL], core.sma(C, 9)[TAIL])
    # KAMA stays inside the range of prices
    k = extra.kama(C, 10, 2, 30)
    assert np.nanmin(k) >= C.min() - 1e-9 and np.nanmax(k) <= C.max() + 1e-9


def test_oscillators_vs_pandas():
    tp = (Hs + Ls + S) / 3
    md = tp.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    close(extra.cci(H, L, C, 20)[TAIL], ((tp - tp.rolling(20).mean()) / (0.015 * md))[TAIL])
    hh, ll = Hs.rolling(14).max(), Ls.rolling(14).min()
    close(extra.williams_r(H, L, C, 14)[TAIL], (-100 * (hh - S) / (hh - ll))[TAIL])
    close(extra.roc(C, 9)[TAIL], (100 * S.pct_change(9))[TAIL])
    close(extra.momentum(C, 10)[TAIL], S.diff(10)[TAIL])
    mid, up, lo = extra.donchian(H, L, 20)
    close(up[TAIL], Hs.rolling(20).max()[TAIL])
    close(lo[TAIL], Ls.rolling(20).min()[TAIL])
    # MFI by hand
    tpa = tp.to_numpy()
    flow = tpa * V
    i = 600
    pos = sum(flow[j] for j in range(i - 13, i + 1) if tpa[j] > tpa[j - 1])
    neg = sum(flow[j] for j in range(i - 13, i + 1) if tpa[j] < tpa[j - 1])
    close(extra.mfi(H, L, C, V, 14)[i], 100 - 100 / (1 + pos / neg))
    mfm = ((S - Ls) - (Hs - S)) / (Hs - Ls)
    close(extra.cmf(H, L, C, V, 20)[TAIL], ((mfm * Vs).rolling(20).sum() / Vs.rolling(20).sum())[TAIL])
    close(extra.adl(H, L, C, V), (mfm * Vs).cumsum())
    cmo_d = S.diff()
    su, sd = cmo_d.clip(lower=0).rolling(9).sum(), (-cmo_d).clip(lower=0).rolling(9).sum()
    close(extra.cmo(C, 9)[TAIL], (100 * (su - sd) / (su + sd))[TAIL])
    close(extra.hist_vol(C, 20, 252)[TAIL],
          (100 * np.sqrt(252) * np.log(S / S.shift()).rolling(20).std())[TAIL])
    pp, sig, hist = extra.ppo(C, 12, 26, 9)
    close(hist, pp - sig)


def test_bounded_oscillators():
    for name, arr, lo, hi in [
        ("stochrsi", extra.stoch_rsi(C)[0], 0, 100), ("uo", extra.ultimate(H, L, C), 0, 100),
        ("mfi", extra.mfi(H, L, C, V), 0, 100), ("aroon", extra.aroon(H, L)[0], 0, 100),
        ("adx", extra.dmi(H, L, C)[2], 0, 100), ("willr", extra.williams_r(H, L, C), -100, 0),
        ("cmo", extra.cmo(C), -100, 100), ("cmf", extra.cmf(H, L, C, V), -1, 1),
    ]:
        a = arr[~np.isnan(arr)]
        assert len(a) > 500 and a.min() >= lo - 1e-9 and a.max() <= hi + 1e-9, name


def test_trend_shapes():
    rising = np.linspace(100, 200, 120)
    up, dn = extra.aroon(rising + 1, rising - 1, 14)
    assert (up[14:] == 100).all() and (dn[14:] == 0).all()
    sar = extra.psar(rising + 1, rising - 1)
    assert (sar[2:] < rising[2:] - 1 + 1e-9).all()          # SAR trails below lows in an uptrend
    plus, minus, adx = extra.dmi(rising + 1, rising - 1, rising)
    assert plus[-1] > minus[-1] and adx[-1] > 50
    conv, base, span_a, span_b, lagging = extra.ichimoku(H, L, C)
    close(span_a[100], (conv[75] + base[75]) / 2)          # leading span drawn 25 bars ahead
    close(lagging[100], C[125])
    assert np.isnan(lagging[-25:]).all()


@pytest.mark.parametrize("ind_id", sorted(set(INDICATORS) - {"obv", "adl", "vwap"}))
def test_every_indicator_consistent_across_pages(client, ind_id):
    """Warm-up is sufficient: a page fetched on its own equals the same bars of a longer fetch."""
    base = dict(symbol="NSE:TCS", tf="1D")
    whole = client.get(f"/indicators/{ind_id}", params=dict(base, limit=300)).json()
    p1 = client.get(f"/indicators/{ind_id}", params=dict(base, limit=150)).json()
    p2 = client.get(f"/indicators/{ind_id}", params=dict(base, limit=150, to=p1["next_to"])).json()
    assert p2["t"] + p1["t"] == whole["t"]
    for out in INDICATORS[ind_id].outputs:
        a = np.array(p2["outputs"][out] + p1["outputs"][out], dtype=float)
        b = np.array(whole["outputs"][out], dtype=float)
        np.testing.assert_allclose(a, b, rtol=1e-4, atol=1e-6, err_msg=f"{ind_id}.{out}")


def test_indicator_meta(client):
    meta = {m["id"]: m for m in client.get("/indicators").json()}
    assert len(meta) == 50
    assert meta["psar"]["plots"][0] == {"name": "sar", "style": "dots", "color": "#2962ff"}
    src = next(p for p in meta["ema"]["params"] if p["name"] == "source")
    assert src["kind"] == "source" and "hlc3" in src["options"] and src["default"] == "close"
    r = client.get("/indicators/ema", params=dict(symbol="NSE:TCS", tf="1D", limit=50, source="ohlc4"))
    assert r.status_code == 200 and r.json()["params"]["source"] == "ohlc4"
