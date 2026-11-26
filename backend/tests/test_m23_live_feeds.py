"""A live feed per exchange (TICK_SOURCES): ticks are routed by exchange, each feed says what it delivers, only real
feeds are saved as bars, and /health tells the UI what each market streams."""
import asyncio

import pytest

from app.config import get_settings
from app.live.service import LiveService
from app.live.store import MemoryStore
from app.live.ticks import (ManualTickSource, RoutedTickSource, StaticTickSource, SyntheticTickSource, feed_of,
                            make_tick_source)
from app.marketdata.base import SymbolInfo


def info(full):
    ex, t = full.split(":")
    return SymbolInfo(exchange=ex, ticker=t, name=t)


def test_ticks_are_routed_by_exchange():
    nse, us, rest = ManualTickSource(), ManualTickSource(), StaticTickSource()
    src = RoutedTickSource(rest, {"NSE": nse, "BSE": nse, "nyse": us})
    seen = []

    async def go():
        await src.start(seen.append)
        await src.subscribe(info("NSE:TCS"), 3500.0)
        await src.subscribe(info("NYSE:IBM"), 250.0)
        await src.subscribe(info("LSE:VOD"), 70.0)                  # not routed: the default feed
        await src.unsubscribe(info("NSE:TCS"))
        await src.stop()

    asyncio.run(go())
    assert nse.subscribed == {} and set(us.subscribed) == {"NYSE:IBM"}
    assert src._all() == [rest, nse, us]                              # each feed started once, even if routed twice
    assert [feed_of(src, x) for x in ("NSE", "NYSE", "LSE")] == ["live", "live", "none"]
    assert feed_of(SyntheticTickSource(), "NSE") == "simulated"


def test_tick_sources_setting(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "data_source", "eod")
    monkeypatch.setattr(s, "simulate_ticks", False)
    monkeypatch.setattr(s, "tick_sources", "NYSE=synthetic, NASDAQ=synthetic")
    src = make_tick_source(s)
    assert isinstance(src, RoutedTickSource) and src.source_for("NYSE") is src.source_for("NASDAQ")
    assert feed_of(src, "NSE") == "none" and feed_of(src, "NYSE") == "simulated"
    monkeypatch.setattr(s, "tick_sources", "tests.test_m23_live_feeds:make_manual")
    with pytest.raises(ValueError, match="EXCHANGE=source"):
        make_tick_source(s)
    monkeypatch.setattr(s, "tick_sources", "NSE=tests.test_m23_live_feeds:make_manual")   # any feed by import path
    assert feed_of(make_tick_source(s), "NSE") == "live"


def make_manual():
    return ManualTickSource()


def test_only_real_feeds_are_saved(session_factory):
    """EOD history with a live NSE feed and simulated US ticks: NSE bars are saved, US ones never are."""
    src = RoutedTickSource(SyntheticTickSource(), {"NSE": ManualTickSource()})
    live = LiveService(src, MemoryStore(), session_factory, persist=False)    # persist=False: real (EOD) history
    assert live._saves("NSE:TCS") is True and live._saves("NYSE:IBM") is False
    assert live.feeds(["NSE", "NYSE"]) == {"NSE": "live", "NYSE": "simulated"}
    synthetic_history = LiveService(SyntheticTickSource(), MemoryStore(), session_factory, persist=True)
    assert synthetic_history._saves("NSE:TCS") is True                       # simulated over synthetic history: as before


def test_health_reports_the_feed_of_every_market(client):
    h = client.get("/health").json()
    assert list(h["feeds"]) == ["NSE", "BSE", "NYSE", "NASDAQ"] and set(h["feeds"].values()) <= {"live", "simulated", "none"}
