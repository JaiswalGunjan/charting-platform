"""Minute bars in PostgreSQL + TimescaleDB, the last 2 years (BAR_STORES=1m=timescale).

Needs a PostgreSQL server with TimescaleDB: TEST_PG_URL (e.g. postgresql+psycopg://charting@127.0.0.1:5433/postgres;
start the local one with scripts/pg_local.ps1 start). Skipped without it. Uses its own database, charting_minute_test,
dropped and made again for every run; the main test database (symbols, daily bars) stays where it is."""
import os
import time

import numpy as np
import pytest
from sqlalchemy import create_engine, text

from app import providers
from app.marketdata.base import Bar

PG = os.environ.get("TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG, reason="needs TEST_PG_URL (PostgreSQL + TimescaleDB)")
DAY = 86400


@pytest.fixture(scope="module")
def minute_url():
    admin = create_engine(PG, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS charting_minute_test WITH (FORCE)"))
        c.execute(text("CREATE DATABASE charting_minute_test"))
    admin.dispose()
    return PG.rsplit("/", 1)[0] + "/charting_minute_test"


@pytest.fixture()
def store(minute_url):
    from app.marketdata.minute_store import TimescaleMinuteStore

    st = TimescaleMinuteStore(minute_url, retention_days=730, compress_after_days=30)
    st.ensure_schema()
    with st.engine.begin() as c:
        c.execute(text("TRUNCATE candles_1m"))
    yield st
    st.engine.dispose()


def bars(t0, n, price=100.0):
    return [Bar(t0 + 60 * i, price + i, price + i + 1, price + i - 1, price + i + 0.5, 1000 + i) for i in range(n)]


def test_hypertable_with_compression_and_two_year_retention(store):
    with store.engine.connect() as c:
        ht = c.execute(text("SELECT count(*) FROM timescaledb_information.hypertables "
                            "WHERE hypertable_name = 'candles_1m'")).scalar()
        jobs = dict(c.execute(text("SELECT proc_name, config->>'drop_after' FROM timescaledb_information.jobs "
                                   "WHERE hypertable_name = 'candles_1m' AND proc_name = 'policy_retention'")).all())
        comp = c.execute(text("SELECT count(*) FROM timescaledb_information.jobs WHERE hypertable_name = 'candles_1m' "
                              "AND proc_name = 'policy_compression'")).scalar()
    assert ht == 1 and comp == 1 and int(jobs["policy_retention"]) == 730 * DAY
    store.ensure_schema()                                       # idempotent
    store._ready = False
    store.ensure_schema()


def test_reads_writes_and_the_window(store, session_factory):
    now = int(time.time()) // 60 * 60
    with session_factory() as s:
        from app.marketdata.loader import resolve_symbol

        tcs, rel = resolve_symbol(s, "NSE:TCS"), resolve_symbol(s, "NSE:RELIANCE")
        old = now - 3 * 365 * DAY                                # 3 years ago: outside the 2-year window
        assert store.upsert(s, tcs.id, "1m", bars(old, 5) + bars(now - 300, 5)) == 5   # old bars are not written
        assert store.upsert(s, rel.id, "1m", bars(now - 300, 5, 2000.0)) == 5
        assert store.upsert(s, tcs.id, "1m", [Bar(now - 300, 1, 2, 0.5, 1.5, 7)]) == 1  # same bar again: updated
        got = store.read_latest(s, tcs.id, "1m", 3)
        assert got[:, 0].tolist() == [now - 180, now - 120, now - 60] and got.shape == (3, 6)
        assert store.read_after(s, tcs.id, "1m", now - 300, 1)[0, 1:].tolist() == [1, 2, 0.5, 1.5, 7]
        many = store.read_many(s, [rel.id, tcs.id], "1m", now - 300, now, cols=("ts", "c"))
        assert many.shape == (10, 3) and many[0, 0] == min(rel.id, tcs.id)
        assert store.last_time(s, "NSE", "1m") == now - 60 and store.last_time(s, "NYSE", "1m") is None
        assert store.times(s, "NSE", "1m", now - 120) == [now - 120, now - 60]
        assert store.has(s, tcs.id, "1m")
        with pytest.raises(ValueError, match="1m bars only"):
            store.read_latest(s, tcs.id, "1D", 5)
        # re-import a range: delete it, append it again (older rows in the append are skipped)
        store.delete_bars(s, "NSE", ["1m", "1D"], now - 180, now)
        assert store.read_latest(s, tcs.id, "1m", 10)[:, 0].tolist() == [now - 300, now - 240]
        ts = np.array([old, now - 180, now - 120], dtype=np.int64)
        n = store.append(s, "1m", np.array([tcs.id] * 3), {"ts": ts, "o": ts * 0 + 1.0, "h": ts * 0 + 2.0,
                                                          "l": ts * 0 + 0.5, "c": ts * 0 + 1.5, "v": ts * 0 + 9.0})
        assert n == 2 and len(store.read_latest(s, tcs.id, "1m", 10)) == 4
        st = store.stats()
        assert st["bars"] == 6 and st["retention_days"] == 730             # the range delete was exchange-wide


def test_compressed_chunks_still_read_and_old_chunks_are_dropped(store, session_factory):
    from sqlalchemy import insert

    from app.marketdata.minute_store import candles_1m

    now = int(time.time()) // 60 * 60
    with session_factory() as s:
        from app.marketdata.loader import resolve_symbol

        tcs = resolve_symbol(s, "NSE:TCS")
        store.upsert(s, tcs.id, "1m", bars(now - 90 * DAY, 30) + bars(now - 600, 10))
        with store.engine.begin() as c:                          # a stray old chunk, written past the filter
            c.execute(insert(candles_1m), [dict(symbol_id=tcs.id, ts=now - 800 * DAY, o=1, h=1, l=1, c=1, v=1)])
        assert store.compress_now() >= 1
        assert store.stats()["compressed_chunks"] >= 1
        old = store.read_after(s, tcs.id, "1m", now - 91 * DAY, 30)  # from a compressed chunk
        assert len(old) == 30 and old[0, 0] == now - 90 * DAY
        assert store.apply_retention() >= 1
        assert store.read_after(s, tcs.id, "1m", 0, 1)[0, 0] == now - 90 * DAY   # the 800-day-old bar is gone


def test_charts_read_minute_bars_from_timescale(client, session_factory, minute_url, monkeypatch):
    """BAR_STORES=1m=timescale: 15m charts come from TimescaleDB, daily charts from the main database."""
    from app.config import get_settings
    from app.marketdata.loader import load_history, resolve_symbol
    from app.marketdata.synthetic import SyntheticSource
    from tests.conftest import END, MINUTE_START

    want = {tf: client.get("/history", params=dict(symbol="NSE:TCS", tf=tf, limit=200)).json() for tf in ("15m", "1D")}
    s = get_settings()
    monkeypatch.setattr(s, "bar_stores", "1m=timescale")
    monkeypatch.setattr(s, "minute_database_url", minute_url)
    providers.reset()
    try:
        routed = providers.bar_store()
        ts_store = routed.store_for("1m")
        with ts_store.engine.begin() as c:
            c.execute(text("TRUNCATE candles_1m"))
        with session_factory() as ses:
            load_history(ses, SyntheticSource(), resolve_symbol(ses, "NSE:TCS"), "1m", MINUTE_START, END)
        assert ts_store.stats()["bars"] > 1000
        for tf, w in want.items():
            got = client.get("/history", params=dict(symbol="NSE:TCS", tf=tf, limit=200)).json()
            assert got["t"] == w["t"] and got["c"] == w["c"], tf
        ts_store.engine.dispose()
    finally:
        providers.reset()


def test_needs_postgresql():
    from app.marketdata.minute_store import TimescaleMinuteStore

    with pytest.raises(ValueError, match="MINUTE_DATABASE_URL"):
        TimescaleMinuteStore("sqlite:///x.db")
