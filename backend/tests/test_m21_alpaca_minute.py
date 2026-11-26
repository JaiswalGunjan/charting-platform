"""The 1-minute Alpaca downloader (scripts/alpaca_minute.py): which keys fall in the window, file names, New York day
bounds, shards, bar frames and resuming. Nothing is downloaded: the Alpaca request is stubbed."""
import datetime as dt
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "alpaca_minute.py"


@pytest.fixture(scope="module")
def m():
    spec = importlib.util.spec_from_file_location("alpaca_minute", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def bar(t, c=1.0, v=100):
    return dict(t=t, o=c, h=c, l=c, c=c, v=v, n=3, vw=c)


def test_key_file_names_like_the_alpaca_store(m, tmp_path):
    assert m.key_file(tmp_path, "AAPL").name == "AAPL.parquet"
    assert m.key_file(tmp_path, "BC/PA").name == "BC~PA.parquet"
    assert m.key_file(tmp_path, "CON").name == "CON_.parquet"
    assert m.key_file(tmp_path, "NUL@2024-05-01").name == "NUL@2024-05-01_.parquet"


def test_ny_bounds_cover_whole_new_york_days_across_dst(m):
    assert m.ny_bounds(dt.date(2026, 7, 1), dt.date(2026, 7, 1)) == ("2026-07-01T04:00:00Z", "2026-07-02T03:59:59Z")
    assert m.ny_bounds(dt.date(2026, 11, 2), dt.date(2026, 11, 25)) == ("2026-11-02T05:00:00Z",
                                                                        "2026-11-26T04:59:59Z")


def test_shards_split_the_keys_without_overlap(m):
    keys = [f"K{i}" for i in range(200)]
    a = {k for k in keys if m.in_shard(k, (0, 2))}
    b = {k for k in keys if m.in_shard(k, (1, 2))}
    assert a and b and not a & b and a | b == set(keys)
    assert all(m.in_shard(k, None) for k in keys)


def test_frame_columns_types_order_and_duplicates(m):
    df = m.frame([bar("2026-11-25T14:31:00Z", 2.0), bar("2026-11-25T14:30:00Z", 1.0), bar("2026-11-25T14:31:00Z")])
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume", "trades", "vwap"]
    assert list(df.close) == [1.0, 2.0] and str(df.ts.dt.tz) == "UTC"
    assert df.volume.dtype == "int64" and df.trades.dtype == "int64"
    assert m.frame([]).empty and list(m.frame([]).columns) == list(df.columns)


def test_combine_joins_pages_in_time_order(m):
    p2, p1 = m.frame([bar("2026-11-25T15:00:00Z", 3.0)]), m.frame([bar("2026-11-25T14:30:00Z", 1.0)])
    assert list(m.combine([p2, p1]).close) == [1.0, 3.0]
    assert m.combine([]).empty


def test_window_keys(m):
    u = pd.DataFrame([
        dict(key="OLD", symbol="OLD", status="av_delisted", asof="2023-03-01", delisted="2023-03-02"),
        dict(key="GONE", symbol="GONE", status="av_delisted", asof="2025-06-01", delisted="2025-06-02"),
        dict(key="LIVE", symbol="LIVE", status="active", asof="", delisted=""),
        dict(key="NEW", symbol="NEW", status="active", asof="", delisted=""),          # no daily file yet
        dict(key="DEAD", symbol="DEAD", status="inactive", asof="", delisted=""),     # last bar before the window
        dict(key="NOFILE", symbol="NOFILE", status="inactive", asof="", delisted=""),
    ])
    spans = {"OLD": ("2016-01-04", "2023-03-01"), "GONE": ("2018-01-02", "2025-05-30"),
             "LIVE": ("2016-01-04", "2026-10-23"), "DEAD": ("2016-01-04", "2024-01-05")}
    keys = m.window_keys(u, spans, dt.date(2024, 11, 26))
    assert list(keys.key) == ["GONE", "LIVE", "NEW"]
    gone = next(keys.itertuples())
    assert m.key_end(gone, dt.date(2026, 11, 25)) == dt.date(2025, 6, 2)
    live = list(keys.itertuples())[1]
    assert m.key_end(live, dt.date(2026, 11, 25)) == dt.date(2026, 11, 25)


def test_main_fetches_saves_and_resumes(m, tmp_path, monkeypatch):
    out = tmp_path / "market_data_minute" / "NASDAQ"
    out.mkdir(parents=True)
    pd.DataFrame([dict(key="AAA", symbol="AAA", asof="", first="", last="", delisted=""),
                  dict(key="BAD", symbol="BAD", asof="", first="", last="", delisted="")]
                 ).to_csv(out / "_universe_20241126_20261125.csv", index=False)
    calls = []

    def fake_fetch(api, url, symbols, s, e, asof, stats):
        calls.append(symbols)
        return {"AAA": [m.frame([bar("2026-11-25T14:30:00Z")])]}, ["BAD"]

    monkeypatch.setattr(m, "load_alpaca", lambda eod: type("A", (), {"DATA_URL": "x"}))
    monkeypatch.setattr(m, "working_clients", lambda al: [("test", object())])
    monkeypatch.setattr(m, "fetch", fake_fetch)
    args = ["--exchange", "NASDAQ", "--start", "2024-11-26", "--end", "2026-11-25", "--eod-dir", str(tmp_path)]
    assert m.main(args) == 0
    assert len(pd.read_parquet(out / "AAA.parquet")) == 1
    assert pd.read_parquet(out / "BAD.parquet").empty                # a key Alpaca does not know: empty, not refetched
    assert m.main(args) == 0 and len(calls) == 1                     # second run: everything is there
