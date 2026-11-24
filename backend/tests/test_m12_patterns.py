"""Chart patterns: the rule port, the scan engine and the API."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.patterns.engine import PATTERNS, scan, support_resistance
from app.patterns.features import Bars, build
from app.patterns.sync_rules import DEFAULT_SRC

DAY = 86400


def series(n=400, seed=5):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0008, 0.015, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.006, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.006, n)))  # noqa: E741
    v = rng.integers(10_000, 50_000, n).astype(float)
    t = np.arange(n, dtype=np.int64) * DAY
    return t, o, h, l, c, v


def test_scan_all_patterns_runs_and_reports_only_requested():
    t, o, h, l, c, v = series()  # noqa: E741
    all_ids = {p.id for p in PATTERNS}
    out = scan(t, o, h, l, c, v, all_ids)
    assert {m["pattern"] for m in out["markers"]} <= all_ids
    assert all(m["t"] in set(t.tolist()) for m in out["markers"])        # markers sit on bar times
    for s in out["shapes"]:
        assert s["kind"] in ("segment", "rect") and len(s["pts"]) == 2
    only_pp = scan(t, o, h, l, c, v, {"pp"})
    assert {m["pattern"] for m in only_pp["markers"]} <= {"pp"}
    assert scan(t, o, h, l, c, v, set()) == dict(markers=[], shapes=[], levels=[])


def test_scan_respects_first_bar():
    t, o, h, l, c, v = series()  # noqa: E741
    out = scan(t, o, h, l, c, v, {"pp", "cic"}, first=300)
    assert out["markers"] and min(m["t"] for m in out["markers"]) >= t[300]


def test_pocket_pivot_marker_on_a_built_bar():
    t, o, h, l, c, v = series()  # noqa: E741
    i = 350
    # a strong up day near the 10 WMA on volume far above any down day of the prior 10 bars
    feats = build(t, o, h, l, c, v)
    w10 = feats["wma10"][i]
    c[i - 1] = w10 * 0.995
    o[i], l[i] = w10 * 0.999, w10 * 0.998
    c[i], h[i] = w10 * 1.03, w10 * 1.031
    v[i] = 10 * v[i - 10:i].max()
    out = scan(t, o, h, l, c, v, {"pp"}, first=i)
    hit = [m for m in out["markers"] if m["t"] == t[i]]
    if Bars(build(t, o, h, l, c, v)).wma50[i] < c[i]:
        assert hit and hit[0]["text"] == "PP" and "S3B-R001" in hit[0]["rules"]


def test_support_resistance_levels():
    n = 200
    t = np.arange(n) * DAY
    # oscillate between 100 and 120 so swing highs cluster near 120 and swing lows near 100, last close 110
    c = 110 + 10 * np.sin(np.arange(n) / 4.0)
    h, l = c + 0.5, c - 0.5  # noqa: E741
    b = Bars(build(t, c, h, l, c, np.full(n, 1000.0)))
    lv = support_resistance(b)
    kinds = {x["kind"] for x in lv}
    assert kinds == {"support", "resistance"}
    res = max(lv, key=lambda x: x["price"])
    assert 118 <= res["price"] <= 121 and res["touches"] >= 3


def test_pattern_api(client):
    meta = client.get("/patterns").json()
    ids = [m["id"] for m in meta]
    assert {"sr", "pp", "bbr", "wedge_pop", "cwh", "vcp"} <= set(ids)
    assert all(m["summary"] for m in meta)                 # every pattern has a plain-English line
    r = client.get("/patterns/scan", params=dict(symbol="NSE:RELIANCE", tf="1D", ids="pp,cic,sr,wedge_pop", limit=300))
    assert r.status_code == 200
    body = r.json()
    hist = client.get("/history", params=dict(symbol="NSE:RELIANCE", tf="1D", limit=300)).json()
    assert all(m["t"] in set(hist["t"]) for m in body["markers"])
    assert client.get("/patterns/scan", params=dict(symbol="NSE:RELIANCE", ids="nope")).status_code == 400
    assert client.get("/patterns/scan", params=dict(symbol="NSE:RELIANCE", ids="")).json()["markers"] == []
    # counts cover every pattern, selected or not, and agree with a scan of that pattern
    cnt = client.get("/patterns/counts", params=dict(symbol="NSE:RELIANCE", tf="1D", limit=300)).json()["counts"]
    assert set(cnt) == set(ids)
    pp = client.get("/patterns/scan", params=dict(symbol="NSE:RELIANCE", tf="1D", ids="pp", limit=300)).json()
    assert cnt["pp"] == len(pp["markers"])


@pytest.mark.skipif(not (DEFAULT_SRC / "bases.py").exists(), reason="owner's swingbt rules not on this machine")
def test_parity_with_swingbt():
    """rules.py must behave exactly like the backtester's rules (same hits, rule ids and rejections on every bar)."""
    sys.path.insert(0, str(DEFAULT_SRC.parents[1]))
    from swingbt import indicators as SI
    from swingbt.rules import bases, cycle, pocket_pivot, shapers
    from swingbt.rules.common import Bars as SB

    from app.patterns import rules as R

    t, o, h, l, c, v = series(500, seed=11)  # noqa: E741
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=pd.to_datetime(t, unit="s"))
    theirs, ours = SB(SI.add_all(df), {}, "X"), Bars(build(t, o, h, l, c, v))
    sig = lambda x: None if x is None else (x.setup, tuple(x.rules), tuple(x.reject))  # noqa: E731

    def run(fn, b, i):
        try:
            return sig(fn(b, i))
        except Exception as e:  # noqa: BLE001
            return type(e).__name__

    for a, z in [(bases.base_breakout, R.base_breakout), (bases.squat, R.squat), (shapers.mini_coil, R.mini_coil),
                 (shapers.bad_break_recovery, R.bad_break_recovery), (pocket_pivot.pocket_pivot, R.pocket_pivot),
                 (shapers.one_two_three, R.one_two_three), (shapers.three_touch_trendline, R.three_touch_trendline)]:
        for i in range(60, len(t)):
            assert run(a, theirs, i) == run(z, ours, i), (a.__name__, i)
    assert (cycle.phases(theirs)[0] == R.phases(ours)[0]).all()


@pytest.mark.parametrize("tf", ["1W", "1M", "1h"])
def test_daily_patterns_placed_on_other_timeframes(client, tf):
    """basis=daily: the rules run on daily bars and every marker sits on a bar of the chart's own timeframe; the
    weekly/monthly hit count equals the daily chart's count over the same dates."""
    hist = client.get("/history", params=dict(symbol="NSE:RELIANCE", tf=tf, limit=60)).json()
    if not hist["t"]:
        pytest.skip("no bars for this timeframe in the test data")
    q = dict(symbol="NSE:RELIANCE", ids="pp,cic,wedge_pop,crossback,base_break", limit=60)
    r = client.get("/patterns/scan", params=dict(q, tf=tf)).json()
    assert r["basis"] == "daily"
    times = set(hist["t"])
    assert all(m["t"] in times for m in r["markers"])
    if tf in ("1W", "1M"):
        daily = client.get("/patterns/scan", params=dict(q, tf="1D", limit=5000)).json()
        start = hist["t"][0]
        n_daily = sum(1 for m in daily["markers"] if m["t"] >= start)
        assert sum(m.get("count", 1) for m in r["markers"]) == n_daily
        counts = client.get("/patterns/counts", params=dict(symbol="NSE:RELIANCE", tf=tf, limit=60)).json()["counts"]
        assert counts["pp"] == sum(m.get("count", 1) for m in r["markers"] if m["pattern"] == "pp")
    chart_basis = client.get("/patterns/scan", params=dict(q, tf=tf, basis="chart")).json()
    assert chart_basis["basis"] == "chart" and all(m["t"] in times for m in chart_basis["markers"])
