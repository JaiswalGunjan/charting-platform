"""Patterns-today screener edge cases: stale and short histories, a failing symbol, the row figures, the background
job's error path and the one-screen-at-a-time rule."""
import time

import numpy as np
import pytest
from sqlalchemy.orm import sessionmaker

from app.api import screener as api_sc
from app.db import init_db, make_engine
from app.marketdata.base import Bar, SymbolInfo
from app.marketdata.loader import resolve_symbol, upsert_candles, upsert_symbols
from app.patterns import screener as sc

DAY = 86400
LAST = 1_795_000_000 - (1_795_000_000 % DAY) - 19800   # an IST-midnight daily bar time


def bars(n, end, start_price=100.0, seed=1):
    rng = np.random.default_rng(seed)
    c = start_price * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    v = rng.integers(1_000, 5_000, n).astype(float)
    t = end - DAY * np.arange(n)[::-1]
    return [Bar(int(t[i]), float(c[i]), float(c[i] * 1.01), float(c[i] * 0.99), float(c[i]), float(v[i]))
            for i in range(n)]


@pytest.fixture()
def db(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{(tmp_path / 'scr.db').as_posix()}")
    init_db(engine)
    f = sessionmaker(bind=engine, expire_on_commit=False)
    with f() as s:
        upsert_symbols(s, [SymbolInfo("NSE", t, name=f"{t} Ltd") for t in ("FRESH", "STALE", "SHORT", "BROKEN")])
        upsert_candles(s, resolve_symbol(s, "NSE:FRESH").id, "1D", bars(300, LAST, seed=1))
        upsert_candles(s, resolve_symbol(s, "NSE:STALE").id, "1D", bars(300, LAST - 3 * DAY, seed=2))  # stopped trading
        upsert_candles(s, resolve_symbol(s, "NSE:SHORT").id, "1D", bars(20, LAST, seed=3))             # new listing
        upsert_candles(s, resolve_symbol(s, "NSE:BROKEN").id, "1D", bars(300, LAST, seed=4))
    monkeypatch.setattr(sc, "SCREEN_DIR", tmp_path / "screens")
    return f


def fake_hits(t, o, h, l, c, v):  # noqa: E741  every screened symbol "forms" a pattern, so each gets a row
    return [dict(pattern="pp", t=int(t[-1]), text="PP", notes=["n1", "n2", "n3"], rules=[])]


def test_stale_and_short_histories_are_skipped(db, monkeypatch):
    monkeypatch.setattr(sc, "latest_hits", fake_hits)
    r = sc.run_screen(db, "NSE", "1D")
    assert r["symbols"] == 4 and r["last_session"] == LAST
    assert sorted(x["ticker"] for x in r["rows"]) == ["BROKEN", "FRESH"]          # STALE: old last bar; SHORT: < MIN_BARS
    assert r["scanned"] == 2


def test_row_figures(db, monkeypatch):
    monkeypatch.setattr(sc, "latest_hits", fake_hits)
    row = next(x for x in sc.run_screen(db, "NSE", "1D")["rows"] if x["ticker"] == "FRESH")
    b = bars(300, LAST, seed=1)
    c = np.array([x.c for x in b])
    v = np.array([x.v for x in b])
    assert row["close"] == round(c[-1], 4) and row["volume"] == v[-1]
    assert row["change_pct"] == round((c[-1] / c[-2] - 1) * 100, 2)
    assert row["turnover"] == round(float(np.median(c[-50:] * v[-50:])), 0)
    assert row["symbol"] == "NSE:FRESH" and row["name"] == "FRESH Ltd" and row["patterns"] == ["pp"]
    assert row["hits"][0]["notes"] == ["n1", "n2"]                                   # notes trimmed to two


def test_one_failing_symbol_does_not_stop_the_screen(db, monkeypatch):
    def boom(t, o, h, l, c, v):  # noqa: E741
        if abs(c[-1] - bars(300, LAST, seed=4)[-1].c) < 1e-9:
            raise ValueError("bad series")
        return fake_hits(t, o, h, l, c, v)

    monkeypatch.setattr(sc, "latest_hits", boom)
    r = sc.run_screen(db, "NSE", "1D")
    assert [x["ticker"] for x in r["rows"]] == ["FRESH"]
    assert len(r["errors"]) == 1 and r["errors"][0].startswith("BROKEN:") and "bad series" in r["errors"][0]


def test_weekly_rows_sit_on_the_week_of_the_last_session(db, monkeypatch):
    monkeypatch.setattr(sc, "latest_hits", fake_hits)
    assert sc.run_screen(db, "NSE", "1W")["rows"] == []       # 300 days = ~43 weeks < MIN_BARS: not enough history
    monkeypatch.setattr(sc, "MIN_BARS", 30)
    r = sc.run_screen(db, "NSE", "1W")
    days = (LAST + 19800) // DAY
    monday = (days - (days + 3) % 7) * DAY - 19800
    assert r["as_of"] == monday and r["last_session"] == LAST and r["rows"]


def test_progress_is_reported(db, monkeypatch):
    monkeypatch.setattr(sc, "latest_hits", fake_hits)
    seen = []
    sc.run_screen(db, "NSE", "1D", on_step=lambda p: seen.append((p.done, p.total, p.msg)))
    assert seen and seen[-1][0] == seen[-1][1] == 4 and "with patterns" in seen[-1][2]


def wait_job(client):
    for _ in range(200):
        j = client.get("/screener/patterns-today/job").json()
        if j["state"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_job_error_is_reported(client, monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "SCREEN_DIR", tmp_path / "screens")

    def fail(*a, **kw):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(sc, "run_screen", fail)
    assert client.post("/screener/patterns-today/run", json=dict(exchange="NSE", tf="1D")).status_code == 200
    j = wait_job(client)
    assert j["state"] == "error" and "RuntimeError: database is locked" in j["msg"] and j["finished"]
    assert client.get("/screener/patterns-today", params=dict(exchange="NSE", tf="1D")).json()["missing"] is True


def test_only_one_screen_at_a_time(client):
    assert api_sc._LOCK.acquire(blocking=False)
    try:
        r = client.post("/screener/patterns-today/run", json=dict(exchange="NSE", tf="1W"))
        assert r.status_code == 409 and "already running" in r.json()["detail"]
    finally:
        api_sc._LOCK.release()
    assert client.post("/screener/patterns-today/run", json=dict(exchange="NSE", tf="5m")).status_code == 400
