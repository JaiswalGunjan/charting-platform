"""Drawings persistence, exchange-aware sessions and symbol search ranking."""
from datetime import datetime, timezone

import numpy as np

from app.live.bars import live_bucket
from app.marketdata.timeframes import IST_MARKET, TIMEFRAMES, US_MARKET, bucket_starts, market_for


def utc(*a):
    return int(datetime(*a, tzinfo=timezone.utc).timestamp())


def test_drawings_roundtrip(client):
    q = {"symbol": "NSE:TCS"}
    assert client.get("/drawings", params=q).json()["items"] == []
    items = [{"id": "a", "kind": "trend", "pts": [{"t": 1, "p": 10}, {"t": 2, "p": 11}], "color": "#ff0000"},
             {"id": "b", "kind": "text", "pts": [{"t": 3, "p": 12}], "text": "breakout", "width": 1}]
    r = client.put("/drawings", params=q, json={"items": items})
    assert r.status_code == 200
    got = client.get("/drawings", params=q).json()["items"]
    assert [i["id"] for i in got] == ["a", "b"] and got[1]["text"] == "breakout" and got[0]["width"] == 2
    assert client.get("/drawings", params={"symbol": "NSE:INFY"}).json()["items"] == []  # per symbol
    bad = client.put("/drawings", params=q, json={"items": [{"id": "x", "kind": "laser", "pts": [{"t": 1, "p": 1}]}]})
    assert bad.status_code == 422
    assert client.put("/drawings", params=q, json={"items": []}).json()["items"] == []


def test_us_sessions_are_new_york_time_with_dst():
    assert market_for("NASDAQ") is US_MARKET and market_for("NSE") is IST_MARKET
    h1 = TIMEFRAMES["1h"]
    # 09:30 New York = 13:30 UTC in summer (EDT), 14:30 UTC in winter (EST)
    summer, winter = utc(2026, 7, 1, 13, 30), utc(2026, 12, 1, 14, 30)
    assert bucket_starts(h1, np.array([summer + 1800, winter + 1800]), US_MARKET).tolist() == [summer, winter]
    assert bucket_starts(TIMEFRAMES["4h"], np.array([summer + 5 * 3600]), US_MARKET).tolist() == [summer + 4 * 3600]
    # a US bar at 15:30 NY on 1 Jul is 01:00 IST on 2 Jul, but belongs to the 1 Jul daily bar
    day = live_bucket(TIMEFRAMES["1D"], utc(2026, 7, 1, 19, 30), US_MARKET)
    assert day == utc(2026, 7, 1) - 19800
    assert live_bucket(h1, summer + 2000, US_MARKET) == summer


def test_symbol_search_ranking(client):
    r = client.get("/symbols", params={"q": "TCS"}).json()
    assert r[0]["symbol"] == "NSE:TCS"
    ex = client.get("/exchanges").json()
    assert ex and ex[0]["exchange"] == "NSE"
    assert all(s["exchange"] == "NSE" for s in client.get("/symbols", params={"q": "", "exchange": "nse"}).json())
    assert client.get("/symbols", params={"q": "100%_"}).status_code == 200  # LIKE wildcards are escaped


def test_us_hourly_import_converts_new_york_time(tmp_path):
    from app.marketdata.eod import read_exchange_hourly

    d = tmp_path / "NASDAQ"
    d.mkdir()
    hdr = "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
    (d / "NASDAQ_20260701_0930.csv").write_text(hdr + "NASDAQ.AAPL,20260701,093000,1,2,0.5,1.5,10\n,20260701,093000,1,1,1,1,1\n")
    (d / "NASDAQ_20261201_0930.csv").write_text(hdr + "NASDAQ.AAPL,20261201,093000,1,2,0.5,1.5,10\n")
    df, n = read_exchange_hourly(tmp_path, "NASDAQ")
    assert n == 2 and df["ticker"].tolist() == ["AAPL", "AAPL"]            # blank ticker dropped
    assert df["ts"].tolist() == [utc(2026, 7, 1, 13, 30), utc(2026, 12, 1, 14, 30)]  # EDT / EST


def test_names_lookup_variants(tmp_path):
    from app.marketdata import names

    (tmp_path / "otherlisted.txt").write_text(
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
        "BFH$A|Bread Financial Pref A|N|BFH-A|N|100|N|BFH-A\nBRK.B|Berkshire Hathaway Inc. Common Stock|N|BRK.B|N|100|N|BRK.B\n"
        "SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY\nZZZT|Test|N|ZZZT|N|100|Y|ZZZT\n")
    n = names.load("NYSE", tmp_path, None)
    assert names.lookup(n, "BFH.PRA", "NYSE").name == "Bread Financial Pref A"
    assert names.lookup(n, "BRK.B", "NYSE").name == "Berkshire Hathaway Inc."
    assert names.lookup(n, "SPY", "NYSE").type == "ETF"
    assert names.lookup(n, "ZZZT", "NYSE") is None  # test issues are skipped
