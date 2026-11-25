import time
from datetime import datetime

import numpy as np

from app.live.bars import FormingBars, LiveBar, live_bucket
from app.live.service import Connection
from app.live.ticks import SyntheticTickSource, Tick
from app.marketdata.base import IST, SymbolInfo
from app.marketdata.timeframes import TIMEFRAMES, bucket_starts
from tests.conftest import LIVE_NOW


def ist(*hms, day=23):
    return datetime(2026, 11, day, *hms, tzinfo=IST).timestamp()


# ---- pure units -------------------------------------------------------------

def test_live_bucket_matches_history_buckets():
    ts = np.array([int(ist(9, 15)), int(ist(10, 14)), int(ist(10, 15)), int(ist(15, 29))])
    for name in ("1m", "5m", "15m", "1h", "4h"):
        tf = TIMEFRAMES[name]
        assert [live_bucket(tf, t + 37) for t in ts] == bucket_starts(tf, ts).tolist()
    assert live_bucket(TIMEFRAMES["1h"], ist(10, 20, 5)) == ist(10, 15)
    assert live_bucket(TIMEFRAMES["1D"], ist(13, 0)) == ist(0, 0)
    assert live_bucket(TIMEFRAMES["1W"], ist(13, 0, day=26)) == ist(0, 0, day=23)  # Thu -> Mon
    assert live_bucket(TIMEFRAMES["1M"], ist(13, 0)) == ist(0, 0, day=1)


def test_forming_bars_fold_and_roll():
    fb = FormingBars("NSE:X", {}, prev_close=100.0, tfs=("1m", "5m", "1D"))
    fb.apply(ist(10, 0, 1), 101, 10)
    fb.apply(ist(10, 0, 30), 103, 5)
    r = fb.apply(ist(10, 0, 59), 99, 1)
    assert r.closed_1m is None
    assert r.updated["1m"] == LiveBar(int(ist(10, 0)), 101, 103, 99, 99, 16)
    r = fb.apply(ist(10, 1, 0), 100, 2)
    assert r.closed_1m == LiveBar(int(ist(10, 0)), 101, 103, 99, 99, 16)
    assert r.updated["1m"].t == ist(10, 1) and r.updated["1m"].v == 2
    assert r.updated["5m"] == LiveBar(int(ist(10, 0)), 101, 103, 99, 100, 18)  # 10:00 is a 5m boundary
    q = fb.quote()
    assert q["ltp"] == 100 and q["change"] == 0 and q["high"] == 103
    r = fb.apply(ist(9, 15, day=24), 105, 1)  # next day
    assert r.day_rolled and fb.prev_close == 100 and fb.quote()["change_pct"] == 5.0


def test_seeded_bar_continues():
    seed = {"1D": LiveBar(int(ist(0, 0)), 50, 60, 45, 55, 1000)}
    fb = FormingBars("NSE:X", seed, prev_close=52, tfs=("1m", "1D"))
    r = fb.apply(ist(10, 0), 62, 10)
    assert r.updated["1D"] == LiveBar(int(ist(0, 0)), 50, 62, 45, 62, 1010)


def test_synthetic_ticks_respect_tick_size():
    src = SyntheticTickSource(seed=1)
    import asyncio
    asyncio.run(src.subscribe(SymbolInfo("NSE", "ABC", tick_size=0.05), 123.45))
    for _ in range(50):
        (t,) = src.step(now=1.0)
        assert abs(t.price / 0.05 - round(t.price / 0.05)) < 1e-6 and t.qty >= 1


def test_connection_conflation_keeps_final_state_of_rolled_bar():
    sent = []

    async def send(m):
        sent.append(m)

    c = Connection(send, 1.0)
    c.push_bar("S", "1m", {"t": 60, "c": 1})
    c.push_bar("S", "1m", {"t": 60, "c": 2})   # conflated away
    c.push_bar("S", "1m", {"t": 60, "c": 3})   # final state of bar 60
    c.push_bar("S", "1m", {"t": 120, "c": 4})
    import asyncio
    asyncio.run(c.flush())
    assert [(m["bar"]["t"], m["bar"]["c"]) for m in sent] == [(60, 3), (120, 4)]


# ---- WebSocket end-to-end ----------------------------------------------------

def _recv_until(ws, pred, limit=50):
    for _ in range(limit):
        m = ws.receive_json()
        if pred(m):
            return m
    raise AssertionError("message not received")


def test_ws_subscribe_ticks_and_persist(client, ticks):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"op": "subscribe", "symbol": "NSE:WIPRO", "tf": "5m"})
        sub = ws.receive_json()
        assert sub["type"] == "subscribed" and sub["symbol"] == "NSE:WIPRO" and sub["bar"] is None
        assert "NSE:WIPRO" in ticks.subscribed

        ticks.emit_threadsafe(Tick("NSE:WIPRO", LIVE_NOW + 5, 250.0, 10))
        ticks.emit_threadsafe(Tick("NSE:WIPRO", LIVE_NOW + 20, 252.5, 5))
        bar = _recv_until(ws, lambda m: m["type"] == "bar" and m["bar"]["c"] == 252.5)
        assert bar["tf"] == "5m" and bar["bar"]["t"] == int(LIVE_NOW) and bar["bar"]["h"] == 252.5
        assert bar["bar"]["v"] == 15
        q = _recv_until(ws, lambda m: m["type"] == "quote")
        assert q["symbol"] == "NSE:WIPRO" and q["ltp"] == 252.5

        # crossing into the next minute closes and persists the 10:00 1m bar
        ticks.emit_threadsafe(Tick("NSE:WIPRO", LIVE_NOW + 61, 251.0, 1))
        _recv_until(ws, lambda m: m["type"] == "bar" and m["bar"]["c"] == 251.0)
        hist = {}
        for _ in range(100):
            hist = client.get("/history", params={"symbol": "NSE:WIPRO", "tf": "1m"}).json()
            if hist["t"]:
                break
            time.sleep(0.02)
        assert hist["t"] == [int(LIVE_NOW)]
        assert (hist["o"][0], hist["h"][0], hist["c"][0], hist["v"][0]) == (250.0, 252.5, 252.5, 15)
        d = client.get("/history", params={"symbol": "NSE:WIPRO", "tf": "1D"}).json()
        assert d["t"] == [int(ist(0, 0))]

        ws.send_json({"op": "unsubscribe", "symbol": "NSE:WIPRO"})
        _recv_until(ws, lambda m: m["type"] == "unsubscribed")
        assert "NSE:WIPRO" not in ticks.subscribed  # last client left -> upstream released


def test_ws_one_upstream_for_many_clients(client, ticks):
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        a.send_json({"op": "subscribe", "symbol": "NSE:TCS", "tf": "1m"})
        b.send_json({"op": "subscribe", "symbol": "TCS", "tf": "1h"})
        sa, sb = a.receive_json(), b.receive_json()
        assert sa["symbol"] == sb["symbol"] == "NSE:TCS"
        assert sa["quote"]["prev_close"] is not None  # seeded from daily history
        assert list(ticks.subscribed) == ["NSE:TCS"]
        ticks.emit_threadsafe(Tick("NSE:TCS", LIVE_NOW + 1, 1000.0, 3))
        assert _recv_until(a, lambda m: m["type"] == "bar")["tf"] == "1m"
        assert _recv_until(b, lambda m: m["type"] == "bar")["tf"] == "1h"
    assert ticks.subscribed == {}  # both disconnected


def test_ws_errors(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"op": "subscribe", "symbol": "NSE:NOPE", "tf": "1m"})
        assert ws.receive_json() == {"type": "error", "message": "unknown symbol NSE:NOPE"}
        ws.send_json({"op": "subscribe", "symbol": "NSE:TCS", "tf": "7m"})
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"op": "dance"})
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"op": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_quotes_endpoint(client, ticks):
    r = client.get("/quotes", params={"symbols": "NSE:SBIN"})
    assert r.status_code == 200 and r.json()[0]["symbol"] == "NSE:SBIN"
    ticks.emit_threadsafe(Tick("NSE:SBIN", LIVE_NOW + 1, 500.0, 1))
    for _ in range(100):
        if client.get("/quotes", params={"symbols": "NSE:SBIN"}).json()[0]["ltp"] == 500.0:
            break
        time.sleep(0.02)
    else:
        raise AssertionError("quote not updated")
    assert client.get("/quotes", params={"symbols": "NSE:NOPE"}).status_code == 404


def test_no_simulated_ticks_by_default(monkeypatch):
    """Without a real feed the quote is the last real close, and nothing moves (no random-walk ticks)."""
    from app.config import Settings
    from app.live.ticks import StaticTickSource, SyntheticTickSource, make_tick_source

    assert isinstance(make_tick_source(Settings(data_source="eod")), StaticTickSource)
    assert isinstance(make_tick_source(Settings(data_source="synthetic")), StaticTickSource)
    assert isinstance(make_tick_source(Settings(data_source="eod", simulate_ticks=True)), SyntheticTickSource)


def test_static_quote_is_the_last_close_and_its_change(session_factory):
    import asyncio

    from app.live.service import LiveService
    from app.live.store import make_store
    from app.live.ticks import StaticTickSource
    from app.marketdata.loader import resolve_symbol
    from app.marketdata.timeframes import TIMEFRAMES
    from app.marketdata.history import get_bars

    async def run():
        live = LiveService(StaticTickSource(), make_store(""), session_factory, persist=False,
                           clock=lambda: 4_000_000_000.0)            # long after the data: no bar is "today"
        await live.start()
        try:
            full = await live.pin("NSE:RELIANCE")
            await asyncio.sleep(0.3)
            return live.quote(full)
        finally:
            await live.stop()

    q = asyncio.run(run())
    with session_factory() as s:
        d = get_bars(s, resolve_symbol(s, "NSE:RELIANCE").id, TIMEFRAMES["1D"], limit=2)
    assert abs(q["ltp"] - float(d.c[-1])) < 1e-6
    assert abs(q["change"] - (d.c[-1] - d.c[-2])) < 1e-3                  # against the session before, not 0
