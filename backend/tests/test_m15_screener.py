"""'Patterns formed today' screener: correctness against the chart's own pattern scan, stale symbols, weekly
bars, the background job API and the CLI."""
import time

import numpy as np
import pytest

from app.marketdata.timeframes import TIMEFRAMES, bucket_starts
from app.patterns import screener as sc


@pytest.fixture()
def screens(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "screens_dir", str(tmp_path / "screens"))
    monkeypatch.setattr(sc, "MIN_BARS", 30)        # the test universe has ~1 year of daily bars
    return tmp_path / "screens"


def last_bar_patterns(client, symbol, tf):
    """What the chart itself marks on the last bar, with the rules run on this timeframe's own bars."""
    ids = ",".join(sorted(sc.screen_ids()))
    hist = client.get("/history", params=dict(symbol=symbol, tf=tf, limit=1)).json()
    r = client.get("/patterns/scan", params=dict(symbol=symbol, tf=tf, ids=ids, limit=600, basis="chart")).json()
    return sorted({m["pattern"] for m in r["markers"] if m["t"] == hist["t"][-1]})


@pytest.mark.parametrize("tf", ["1D", "1W"])
def test_screen_matches_the_chart_scan(client, session_factory, screens, tf):
    res = sc.run_screen(session_factory, "NSE", tf)
    # only RELIANCE and TCS have daily history in the test data; the rest are skipped (no bars / stale)
    assert res["scanned"] == 2 and res["symbols"] > 2
    by_sym = {r["symbol"]: r for r in res["rows"]}
    for sym in ("NSE:RELIANCE", "NSE:TCS"):
        expect = last_bar_patterns(client, sym, tf)
        got = by_sym[sym]["patterns"] if sym in by_sym else []
        assert got == expect, (sym, tf)
    for r in res["rows"]:
        assert r["patterns"] and set(r["patterns"]) <= sc.screen_ids() and "sr" not in r["patterns"]
        assert r["close"] > 0 and r["turnover"] >= 0 and {"pattern", "text", "notes"} <= set(r["hits"][0])
    hist = client.get("/history", params=dict(symbol="NSE:RELIANCE", tf=tf, limit=1)).json()
    assert res["as_of"] == hist["t"][-1]
    if tf == "1W":
        assert res["as_of"] == int(bucket_starts(TIMEFRAMES["1W"], np.array([res["last_session"]]))[0])
    assert sc.load_screen("NSE", tf) == res                                  # saved for the dashboard


def test_latest_bar_hits_equal_the_full_scan_at_every_end_date():
    """Screening a series that ends on bar i finds exactly the patterns the full chart scan marks on bar i."""
    from app.patterns.engine import scan

    rng = np.random.default_rng(21)
    n = 700
    c = 100 * np.exp(np.cumsum(rng.normal(0.0006, 0.018, n)))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.004, n))
    h, l = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.01, n))), np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.01, n)))  # noqa: E741
    v = rng.integers(10_000, 90_000, n).astype(float)
    t = np.arange(n, dtype=np.int64) * 86400
    full = scan(t, o, h, l, c, v, sc.screen_ids())
    by_bar: dict[int, set] = {}
    for m in full["markers"]:
        by_bar.setdefault(m["t"], set()).add(m["pattern"])
    compared = 0
    for i in range(500, n):
        got = {m["pattern"] for m in sc.latest_hits(t[:i + 1], o[:i + 1], h[:i + 1], l[:i + 1], c[:i + 1], v[:i + 1])}
        assert got == by_bar.get(int(t[i]), set()), i
        compared += len(got)
    assert compared >= 30                      # the comparison covered plenty of real hits (50 with this seed)


def test_rows_sorted_by_number_of_patterns(session_factory, screens):
    rows = sc.run_screen(session_factory, "NSE", "1D")["rows"]
    counts = [len(r["patterns"]) for r in rows]
    assert counts == sorted(counts, reverse=True)


def test_screens_dir_setting(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "screens_dir", str(tmp_path / "elsewhere"))
    assert sc.screen_path("nse", "1D") == tmp_path / "elsewhere" / "NSE_1D.json"
    monkeypatch.setattr(get_settings(), "screens_dir", "")
    from app.patterns import store

    assert sc.screen_path("NSE", "1W") == store.SCREEN_DIR / "NSE_1W.json"


def test_unknown_timeframe_and_empty_exchange(session_factory, screens):
    with pytest.raises(ValueError):
        sc.run_screen(session_factory, "NSE", "1h")
    r = sc.run_screen(session_factory, "NYSE", "1D")                        # no symbols / bars
    assert r["rows"] == [] and r["as_of"] is None


def test_api_run_job_and_result(client, screens):
    first = client.get("/screener/patterns-today", params=dict(exchange="NSE", tf="1D")).json()
    assert first["missing"] is True and first["rows"] == []
    assert client.get("/screener/patterns-today", params=dict(tf="5m")).status_code == 400
    r = client.post("/screener/patterns-today/run", json=dict(exchange="nse", tf="1D"))
    assert r.status_code == 200 and r.json()["job"]["state"] == "running"
    for _ in range(200):
        j = client.get("/screener/patterns-today/job").json()
        if j["state"] != "running":
            break
        time.sleep(0.05)
    assert j["state"] == "done" and j["done"] == j["total"] > 0
    res = client.get("/screener/patterns-today", params=dict(exchange="NSE", tf="1D")).json()
    assert res["missing"] is False and res["scanned"] == 2 and res["as_of"]


def test_cli_screen(session_factory, screens, monkeypatch, capsys):
    from app import cli

    monkeypatch.setattr(cli, "SessionLocal", session_factory)
    monkeypatch.setattr(cli, "init_db", lambda: None)
    cli.main(["screen", "--exchanges", "NSE", "--tf", "1D,1W"])
    out = capsys.readouterr().out
    assert "NSE 1D 20" in out and "NSE 1W 20" in out                         # each line names its session
    assert sc.load_screen("NSE", "1D") and sc.load_screen("NSE", "1W")
    latest = sc.load_screen("NSE", "1D")["session"]
    # one past session, then a backfill that skips sessions already saved
    past = sc.sessions(session_factory, "NSE", "2000-01-01")[3]
    cli.main(["screen", "--exchanges", "NSE", "--tf", "1D", "--date", past])
    assert sc.load_screen("NSE", "1D", day=past)["session"] == past
    assert sc.load_screen("NSE", "1D")["session"] == latest                   # the default screen is still the newest
    capsys.readouterr()
    cli.main(["screen", "--exchanges", "NSE", "--tf", "1D", "--days", "8"])
    out = capsys.readouterr().out
    assert past not in out.split("sessions to screen")[1] and latest not in out.split("sessions to screen")[1]
    assert set(sc.backfill_days(session_factory, "NSE", "1D", 8)) <= set(sc.screen_dates("NSE", "1D"))  # all saved
