from datetime import datetime

import pytest

from app.marketdata.base import IST, MINUTES_PER_SESSION

TRADING_DAYS_1M = 10  # conftest loads 2026-11-09..2026-11-20


def _get(client, **params):
    r = client.get("/history", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _page_all(client, symbol, tf, limit):
    pages, to = [], None
    while True:
        params = dict(symbol=symbol, tf=tf, limit=limit)
        if to is not None:
            params["to"] = to
        p = _get(client, **params)
        pages.append(p)
        if p["next_to"] is None:
            break
        to = p["next_to"]
        assert len(pages) < 1000
    merged = {k: [] for k in "tohlcv"}
    for p in reversed(pages):
        for k in merged:
            merged[k] += p[k]
    return merged


def _ist(ts):
    return datetime.fromtimestamp(ts, IST)


def test_latest_page_and_shape(client):
    p = _get(client, symbol="NSE:RELIANCE", tf="1m", limit=100)
    assert len(p["t"]) == 100 and p["next_to"] == p["t"][0]
    assert p["t"] == sorted(p["t"])
    assert _ist(p["t"][-1]).strftime("%Y-%m-%d %H:%M") == "2026-11-20 15:29"


@pytest.mark.parametrize("tf,limit", [("1m", 1000), ("5m", 37), ("15m", 7), ("1h", 5), ("4h", 3),
                                      ("1D", 50), ("1W", 4), ("1M", 2)])
def test_paging_equals_single_request(client, tf, limit):
    paged = _page_all(client, "NSE:RELIANCE", tf, limit)
    whole = _get(client, symbol="NSE:RELIANCE", tf=tf, limit=5000)
    assert whole["next_to"] is None
    assert paged == {k: whole[k] for k in "tohlcv"}
    assert len(set(paged["t"])) == len(paged["t"])


def test_intraday_alignment_and_aggregation(client):
    m1 = _get(client, symbol="NSE:TCS", tf="1m", limit=5000)
    m5 = _get(client, symbol="NSE:TCS", tf="5m", limit=5000)
    h1 = _get(client, symbol="NSE:TCS", tf="1h", limit=5000)
    assert len(m1["t"]) == TRADING_DAYS_1M * MINUTES_PER_SESSION
    assert len(m5["t"]) == TRADING_DAYS_1M * 75
    assert len(h1["t"]) == TRADING_DAYS_1M * 7  # 09:15 ... 15:15 (last bar is 15 min)
    assert {_ist(t).strftime("%H:%M") for t in h1["t"]} == {
        "09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"}
    # first 5m bar == aggregate of first five 1m bars
    i = 0
    assert m5["o"][i] == m1["o"][0] and m5["c"][i] == m1["c"][4]
    assert m5["h"][i] == max(m1["h"][:5]) and m5["l"][i] == min(m1["l"][:5])
    assert m5["v"][i] == pytest.approx(sum(m1["v"][:5]))


def test_weekly_monthly_alignment(client):
    d1 = _get(client, symbol="NSE:RELIANCE", tf="1D", limit=5000)
    w = _get(client, symbol="NSE:RELIANCE", tf="1W", limit=5000)
    mo = _get(client, symbol="NSE:RELIANCE", tf="1M", limit=5000)
    for t in w["t"]:
        d = _ist(t)
        assert d.weekday() == 0 and (d.hour, d.minute) == (0, 0)
    for t in mo["t"]:
        assert _ist(t).day == 1
    assert sum(w["v"]) == pytest.approx(sum(d1["v"]))
    assert w["c"][-1] == d1["c"][-1] and max(w["h"]) == max(d1["h"])


def test_from_bound(client):
    full = _get(client, symbol="NSE:RELIANCE", tf="1D", limit=5000)
    frm = full["t"][-10]
    p = _get(client, symbol="NSE:RELIANCE", tf="1D", limit=5000, **{"from": frm})
    assert p["t"] == full["t"][-10:]


def test_errors(client):
    assert client.get("/history", params={"symbol": "NSE:NOPE"}).status_code == 404
    assert client.get("/history", params={"symbol": "NSE:TCS", "tf": "7m"}).status_code == 400
    empty = _get(client, symbol="NSE:INFY", tf="1D")  # symbol with no candles loaded
    assert empty["t"] == [] and empty["next_to"] is None
    assert "1h" in client.get("/timeframes").json()
