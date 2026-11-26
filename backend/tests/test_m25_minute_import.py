"""Importing Alpaca 1-minute Parquet files (app/marketdata/alpaca_minute.py): file names -> keys, the regular session,
the price factor (exact from the daily file, carried after it, a sustained jump = a split) and an end-to-end import
into a minute store (an in-memory one here; the TimescaleDB one is tested in test_m24)."""
import datetime as dt
import pickle

import numpy as np
import pandas as pd
import pytest

from app import providers
from app.marketdata import alpaca_minute as am

D = [dt.date(2026, 11, d) for d in (16, 17, 18, 19, 20)]


def test_file_names_to_keys():
    assert am.key_of("AAPL") == "AAPL"
    assert am.key_of("BC~PA") == "BC/PA"
    assert am.key_of("CON_") == "CON" and am.key_of("NUL@2024-05-01_") == "NUL@2024-05-01"
    assert am.key_of("AB_") == "AB_"                                     # not a reserved name: kept


def test_regular_session_is_new_york_09_30_to_16_00_across_dst():
    ts = pd.to_datetime(["2026-07-01 13:29", "2026-07-01 13:30", "2026-07-01 19:59", "2026-07-01 20:00",   # EDT
                         "2026-12-01 14:29", "2026-12-01 14:30", "2026-12-01 20:59", "2026-12-01 21:00"], utc=True)
    df = pd.DataFrame(dict(ts=ts, close=range(8)))
    got = am.regular_session(df)
    assert list(got.close) == [1, 2, 5, 6] and got.day.iloc[0] == dt.date(2026, 7, 1)
    assert am.regular_session(df.iloc[:0]).empty


def test_factor_is_exact_from_the_daily_file_then_carried():
    ours = pd.Series([10.0, 10.0, 11.0, 12.0, 12.0], index=D)
    official = pd.Series([20.0, 20.0, 22.0], index=D[:3])          # the daily file ends on the 18th
    minute = pd.Series([20.1, 19.9, 22.2, 23.6, 24.3], index=D)     # last trades: a little off the official close
    f = am.day_factors(D, official, ours, minute)
    assert f.tolist() == [2.0, 2.0, 2.0, 2.0, 2.0]                   # noise after the file's end: the factor carries


def test_a_split_after_the_daily_file_is_found():
    days = [dt.date(2026, 11, 1) + dt.timedelta(d) for d in range(8)]
    ours = pd.Series(10.0, index=days)
    official = pd.Series(10.0, index=days[:2])                      # factor 1 while the file lasts
    # a 1:4 reverse split on day 4: raw prices x4 from then on; day 3 has one stray print (not a split)
    minute = pd.Series([10, 10, 13, 40, 40.2, 39.8, 40, 40], index=days, dtype=float)
    f = am.day_factors(days, official, ours, minute)
    assert f.tolist()[:3] == [1, 1, 1] and f.tolist()[3:] == pytest.approx([4.0] * 5, rel=0.01)


def test_days_before_the_first_factor_take_the_first():
    ours = pd.Series([5.0, 5.0], index=D[1:3])
    f = am.day_factors(D[:3], pd.Series([10.0, 10.0], index=D[1:3]), ours, pd.Series(dtype=float))
    assert f.tolist() == [2.0, 2.0, 2.0]


def test_import_end_to_end_and_resume(session_factory, tmp_path):
    from sqlalchemy import select

    from app.marketdata.barstore import RoutedBarStore, SqlBarStore
    from app.models import Symbol
    from tests.test_m21_ports import MemoryBarStore

    with session_factory() as s:
        exchange_of = dict(s.execute(select(Symbol.id, Symbol.exchange)).all())
        tcs = s.scalar(select(Symbol.id).where(Symbol.exchange == "NSE", Symbol.ticker == "TCS"))
        daily = SqlBarStore().read_latest(s, tcs, "1D", 3, cols=("ts", "c"))
    days = [pd.Timestamp(int(t) + 19800, unit="s").date() for t in daily[:, 0]]
    ours = dict(zip(days, daily[:, 1]))
    # raw prices twice ours (a 2:1 split after these days, in our adjusted basis), one pre-market bar a day
    rows = []
    for d in days:
        for hhmm, k in (("08:00", 0), ("10:00", 1), ("15:59", 2)):
            raw = 2 * ours[d] + k * 0.02
            rows.append(dict(ts=pd.Timestamp(f"{d} {hhmm}", tz="America/New_York").tz_convert("UTC"),
                             open=raw, high=raw + 0.5, low=raw - 0.5, close=raw, volume=100 * (k + 1), trades=1,
                             vwap=raw))
    folder = tmp_path / "market_data_minute" / "NSE"
    folder.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(folder / "TCS.parquet")
    pd.DataFrame(rows[:3]).to_parquet(folder / "NOTOURS.parquet")
    daily_dir = tmp_path / "daily"
    (daily_dir / "NSE").mkdir(parents=True)
    k = pd.DataFrame(dict(Close=[2 * ours[d] + 0.04 for d in days]), index=pd.to_datetime(days))
    with open(daily_dir / "NSE" / "TCS.pkl", "wb") as fh:
        pickle.dump(k, fh)

    mem = MemoryBarStore(exchange_of)
    providers.use("bar_store", RoutedBarStore(SqlBarStore(), {"1m": mem}))
    try:
        r = am.import_exchange(session_factory, folder, "NSE", daily_dir)
        assert (r.imported, r.files, r.not_ours, r.no_factor) == (1, 2, ["NOTOURS"], [])
        assert r.bars == 2 * len(days)                                  # pre-market bars dropped
        with session_factory() as s:
            got = mem.read_latest(s, tcs, "1m", 100)
        f = np.array([(2 * ours[d] + 0.04) / ours[d] for d in days]).repeat(2)
        raw_c = np.array([2 * ours[d] + k * 0.02 for d in days for k in (1, 2)])
        assert got[:, 4] == pytest.approx(raw_c / f) and got[:, 5] == pytest.approx(np.array([200, 300] * len(days)) * f)
        assert got[-1, 4] == pytest.approx(ours[days[-1]], rel=1e-9)   # the last minute = our daily close
        again = am.import_exchange(session_factory, folder, "NSE", daily_dir)
        assert again.imported == 0 and again.skipped_unchanged == 2     # unchanged files are skipped
        assert "TCS.parquet" in (folder / "_imported.json").read_text()
    finally:
        providers.use("bar_store", None)


def test_both_file_layouts_read_as_dollars(tmp_path):
    """The downloader's two layouts: float dollars, and int64 micro-dollars with metadata price_scale."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    ts = pd.to_datetime(["2026-11-25 15:00", "2026-11-25 15:01"], utc=True)
    prices = [123.456789, 0.000123]
    pd.DataFrame(dict(ts=ts, open=prices, high=prices, low=prices, close=prices, vwap=prices, volume=[10, 20],
                      trades=[1, 2])).to_parquet(tmp_path / "F.parquet")
    micro = pa.table(dict(ts=ts, open=[123456789, 123], high=[123456789, 123], low=[123456789, 123],
                          close=[123456789, 123], vwap=[123456789, 123], volume=[10, 20], trades=[1, 2]))
    pq.write_table(micro.replace_schema_metadata({b"price_scale": b"1000000"}), tmp_path / "I.parquet")
    a, b = am.read_minute(tmp_path / "F.parquet"), am.read_minute(tmp_path / "I.parquet")
    assert list(a.columns) == ["ts", "open", "high", "low", "close", "volume"]
    assert b.close.tolist() == pytest.approx(prices, abs=1e-9) and a.close.tolist() == b.close.tolist()
    assert b.volume.tolist() == [10, 20] and b.close.dtype == "float64"
