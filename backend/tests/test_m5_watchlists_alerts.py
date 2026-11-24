import time

import pytest

from app.alerts.engine import Rule
from app.live.ticks import Tick
from tests.conftest import LIVE_NOW


# ---- rule semantics -----------------------------------------------------------

@pytest.mark.parametrize("op,prices,fires", [
    ("crosses_above", [99, 100, 101, 99, 101], [False, True, False, False, True]),
    ("crosses_above", [101, 102], [False, False]),             # already above: no cross
    ("crosses_below", [101, 100, 99, 101, 99], [False, True, False, False, True]),
    ("above", [101, 102, 99, 100], [True, False, False, True]),  # edge-triggered
    ("below", [101, 100, 99], [False, True, False]),
])
def test_rule_edges(op, prices, fires):
    r = Rule(1, "S", op, 100.0, once=False, message="", prev=None)
    assert [r.check(p) for p in prices] == fires


def test_rule_uses_ref_price_for_first_cross():
    r = Rule(1, "S", "crosses_above", 100.0, once=True, message="", prev=95.0)
    assert r.check(100.5) is True


# ---- watchlists -----------------------------------------------------------------

def test_watchlist_crud(client):
    lists = client.get("/watchlists").json()
    assert lists[0]["name"] == "My Watchlist" and "NSE:RELIANCE" in lists[0]["symbols"]

    w = client.post("/watchlists", json={"name": "Banks"}).json()
    assert w["symbols"] == []
    w = client.post(f"/watchlists/{w['id']}/items", json={"symbol": "HDFCBANK"}).json()
    w = client.post(f"/watchlists/{w['id']}/items", json={"symbol": "NSE:SBIN"}).json()
    assert w["symbols"] == ["NSE:HDFCBANK", "NSE:SBIN"]
    assert client.post(f"/watchlists/{w['id']}/items", json={"symbol": "SBIN"}).status_code == 409
    assert client.post(f"/watchlists/{w['id']}/items", json={"symbol": "NOPE"}).status_code == 404
    w = client.delete(f"/watchlists/{w['id']}/items/NSE:HDFCBANK").json()
    assert w["symbols"] == ["NSE:SBIN"]
    assert client.patch(f"/watchlists/{w['id']}", json={"name": "PSU"}).json()["name"] == "PSU"
    assert client.delete(f"/watchlists/{w['id']}").status_code == 204
    assert client.get(f"/watchlists/{w['id']}/items").status_code in (404, 405)
    assert client.delete(f"/watchlists/{w['id']}").status_code == 404


# ---- alerts end-to-end ------------------------------------------------------------

def _wait(pred, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_alert_fires_once_over_ws_and_records(client, ticks):
    a = client.post("/alerts", json={"symbol": "NSE:ITC", "condition": {"op": "crosses_above", "price": 400}}).json()
    assert a["status"] == "active" and a["message"] == "NSE:ITC crosses above 400"
    assert "NSE:ITC" in ticks.subscribed  # pinned: streams with no chart open

    with client.websocket_connect("/ws") as ws:
        for i, p in enumerate([398.0, 399.5, 400.5, 399.0, 401.0]):
            ticks.emit_threadsafe(Tick("NSE:ITC", LIVE_NOW + i, p, 1))
        msg = ws.receive_json()
        assert msg["type"] == "alert" and msg["alert_id"] == a["id"] and msg["price"] == 400.5

    assert _wait(lambda: client.get("/alerts", params={"status": "triggered"}).json() != [])
    (t,) = client.get("/alerts", params={"status": "triggered"}).json()
    assert t["id"] == a["id"] and t["triggered_at"] == LIVE_NOW + 2
    events = [e for e in client.get("/alerts/events").json() if e["alert_id"] == a["id"]]
    assert len(events) == 1 and events[0]["price"] == 400.5   # once: 2nd cross ignored
    assert _wait(lambda: "NSE:ITC" not in ticks.subscribed)    # unpinned after one-shot fired


def test_alert_disable_rearm_delete(client, ticks):
    a = client.post("/alerts", json={"symbol": "LT", "condition": {"op": "below", "price": 50},
                                      "once": False, "message": "LT cheap"}).json()
    assert "NSE:LT" in ticks.subscribed
    d = client.patch(f"/alerts/{a['id']}", json={"status": "disabled"}).json()
    assert d["status"] == "disabled"
    assert _wait(lambda: "NSE:LT" not in ticks.subscribed)
    assert client.patch(f"/alerts/{a['id']}", json={"status": "active"}).json()["status"] == "active"
    assert "NSE:LT" in ticks.subscribed
    assert client.delete(f"/alerts/{a['id']}").status_code == 204
    assert _wait(lambda: "NSE:LT" not in ticks.subscribed)
    assert client.delete(f"/alerts/{a['id']}").status_code == 404


def test_alerts_rearmed_on_restart(client, session_factory, ticks):
    a = client.post("/alerts", json={"symbol": "MARUTI", "condition": {"op": "above", "price": 1e6}}).json()
    from app.live.service import LiveService
    from app.live.store import MemoryStore
    from app.live.ticks import ManualTickSource
    from app.main import create_app
    from fastapi.testclient import TestClient

    src2 = ManualTickSource()
    app2 = create_app(lambda sf: LiveService(src2, MemoryStore(), sf, throttle_s=0.02, clock=lambda: LIVE_NOW),
                      session_factory=session_factory)
    with TestClient(app2):
        assert "NSE:MARUTI" in src2.subscribed  # loaded from DB at startup
    client.delete(f"/alerts/{a['id']}")


def test_alert_validation(client):
    bad = [
        {"symbol": "NSE:TCS", "condition": {"op": "sideways", "price": 1}},
        {"symbol": "NSE:TCS", "condition": {"op": "above", "price": -5}},
        {"symbol": "NSE:TCS"},
    ]
    for body in bad:
        assert client.post("/alerts", json=body).status_code == 422
    r = client.post("/alerts", json={"symbol": "NSE:NOPE", "condition": {"op": "above", "price": 1}})
    assert r.status_code == 404
