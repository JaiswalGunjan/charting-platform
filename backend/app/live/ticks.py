"""Tick sources. Each calls `on_tick` on the asyncio loop thread."""
import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from app.config import Settings
from app.marketdata.base import SymbolInfo

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tick:
    symbol: str   # "NSE:RELIANCE"
    ts: float     # epoch seconds
    price: float
    qty: float


OnTick = Callable[[Tick], None]


class TickSource(Protocol):
    """A live price feed. `feed` says what it delivers: "live" (real trades, saved as bars), "simulated" (made up,
    never saved over real history) or "none" (no ticks: quotes stay at the last close)."""
    name: str
    feed: str

    async def start(self, on_tick: OnTick) -> None: ...
    async def stop(self) -> None: ...
    async def subscribe(self, sym: SymbolInfo, last_price: float | None) -> None: ...
    async def unsubscribe(self, sym: SymbolInfo) -> None: ...


class SyntheticTickSource:
    """Random-walk ticks for subscribed symbols, continuing from the last stored price.

    Runs 24x7 so you can see live updates in dev outside market hours.
    """
    name = "synthetic"
    feed = "simulated"

    def __init__(self, interval_s: float = 0.5, tick_vol: float = 0.0004, seed: int | None = None):
        self.interval_s = interval_s
        self.tick_vol = tick_vol
        self.rng = np.random.default_rng(seed)
        self.prices: dict[str, tuple[float, float]] = {}  # symbol -> (price, tick_size)
        self._task: asyncio.Task | None = None
        self._on_tick: OnTick | None = None

    async def start(self, on_tick: OnTick) -> None:
        self._on_tick = on_tick
        self._task = asyncio.create_task(self._run(), name="synthetic-ticks")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def subscribe(self, sym: SymbolInfo, last_price: float | None) -> None:
        self.prices.setdefault(sym.full, (last_price or 100.0, sym.tick_size))

    async def unsubscribe(self, sym: SymbolInfo) -> None:
        self.prices.pop(sym.full, None)

    def step(self, now: float | None = None) -> list[Tick]:
        now = time.time() if now is None else now
        out = []
        for symbol, (p, tick) in list(self.prices.items()):
            p = max(tick, round(p * float(np.exp(self.rng.normal(0, self.tick_vol))) / tick) * tick)
            self.prices[symbol] = (p, tick)
            qty = 0.0 if "NIFTY" in symbol else float(self.rng.integers(1, 500))
            out.append(Tick(symbol, now, round(p, 4), qty))
        return out

    async def _run(self) -> None:
        while True:
            for t in self.step():
                self._on_tick(t)
            await asyncio.sleep(self.interval_s * float(self.rng.uniform(0.5, 1.5)))


class KiteTickSource:
    """Zerodha KiteTicker (WebSocket) bridged into asyncio. Private prototyping only."""
    name = "kite"
    feed = "live"

    def __init__(self, settings: Settings):
        from kiteconnect import KiteTicker

        self.ticker = KiteTicker(settings.kite_api_key, settings.kite_access_token)
        self.by_token: dict[int, str] = {}
        self.cum_volume: dict[int, float] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._on_tick: OnTick | None = None

    async def start(self, on_tick: OnTick) -> None:
        self._loop = asyncio.get_running_loop()
        self._on_tick = on_tick
        self.ticker.on_ticks = self._handle_ticks
        self.ticker.on_connect = lambda ws, _resp: self._resubscribe()
        self.ticker.on_error = lambda ws, code, reason: log.warning("kite ws error %s %s", code, reason)
        self.ticker.connect(threaded=True)

    async def stop(self) -> None:
        self.ticker.close()

    def _resubscribe(self) -> None:
        tokens = list(self.by_token)
        if tokens:
            self.ticker.subscribe(tokens)
            self.ticker.set_mode(self.ticker.MODE_FULL, tokens)

    async def subscribe(self, sym: SymbolInfo, last_price: float | None) -> None:
        if sym.instrument_token is None:
            raise ValueError(f"{sym.full} has no instrument_token")
        self.by_token[sym.instrument_token] = sym.full
        if self.ticker.is_connected():
            self.ticker.subscribe([sym.instrument_token])
            self.ticker.set_mode(self.ticker.MODE_FULL, [sym.instrument_token])

    async def unsubscribe(self, sym: SymbolInfo) -> None:
        if sym.instrument_token in self.by_token:
            del self.by_token[sym.instrument_token]
            if self.ticker.is_connected():
                self.ticker.unsubscribe([sym.instrument_token])

    def _handle_ticks(self, _ws, ticks: list[dict]) -> None:  # runs on KiteTicker's thread
        for t in ticks:
            token = t["instrument_token"]
            symbol = self.by_token.get(token)
            if symbol is None:
                continue
            ts_dt = t.get("exchange_timestamp") or t.get("last_trade_time")
            ts = ts_dt.timestamp() if ts_dt else time.time()
            cum = float(t.get("volume_traded") or 0)
            prev = self.cum_volume.get(token)
            qty = max(0.0, cum - prev) if prev is not None else 0.0
            self.cum_volume[token] = cum
            tick = Tick(symbol, ts, float(t["last_price"]), qty)
            self._loop.call_soon_threadsafe(self._on_tick, tick)


class StaticTickSource:
    """No ticks at all: quotes stay at the last real close (end-of-day data without a live feed)."""
    name = "static"
    feed = "none"

    async def start(self, on_tick: OnTick) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def subscribe(self, sym: SymbolInfo, last_price: float | None) -> None:
        pass

    async def unsubscribe(self, sym: SymbolInfo) -> None:
        pass


class ManualTickSource:
    """For tests: ticks are pushed explicitly with `emit`."""
    name = "manual"
    feed = "live"

    def __init__(self):
        self.subscribed: dict[str, float | None] = {}
        self._on_tick: OnTick | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self, on_tick: OnTick) -> None:
        self._on_tick = on_tick
        self._loop = asyncio.get_running_loop()

    def emit_threadsafe(self, tick: Tick) -> None:
        """Emit from another thread (e.g. a TestClient test body)."""
        self._loop.call_soon_threadsafe(self._on_tick, tick)

    async def stop(self) -> None:
        pass

    async def subscribe(self, sym: SymbolInfo, last_price: float | None) -> None:
        self.subscribed[sym.full] = last_price

    async def unsubscribe(self, sym: SymbolInfo) -> None:
        self.subscribed.pop(sym.full, None)

    def emit(self, tick: Tick) -> None:
        self._on_tick(tick)


class RoutedTickSource:
    """A tick source per exchange (TICK_SOURCES): e.g. Kite for NSE/BSE, a US vendor for NYSE/NASDAQ, a crypto
    exchange's WebSocket for crypto. Exchanges not named use the default source. Every source feeds the same
    callback; the live service, the WebSocket and the UI do not know which one a tick came from."""

    name = "routed"

    def __init__(self, default: TickSource, routes: dict[str, TickSource]):
        self.default = default
        self.routes = {k.upper(): v for k, v in routes.items()}

    @property
    def feed(self) -> str:
        return self.default.feed

    def source_for(self, exchange: str) -> TickSource:
        return self.routes.get(exchange.upper(), self.default)

    def feed_for(self, exchange: str) -> str:
        return self.source_for(exchange).feed

    def _all(self) -> list[TickSource]:
        out: list[TickSource] = []
        for s in [self.default, *self.routes.values()]:
            if all(s is not x for x in out):
                out.append(s)
        return out

    async def start(self, on_tick: OnTick) -> None:
        for s in self._all():
            await s.start(on_tick)

    async def stop(self) -> None:
        for s in self._all():
            await s.stop()

    async def subscribe(self, sym: SymbolInfo, last_price: float | None) -> None:
        await self.source_for(sym.exchange).subscribe(sym, last_price)

    async def unsubscribe(self, sym: SymbolInfo) -> None:
        await self.source_for(sym.exchange).unsubscribe(sym)


def feed_of(source: TickSource, exchange: str) -> str:
    """What `source` delivers for `exchange`: live, simulated or none."""
    fn = getattr(source, "feed_for", None)
    return fn(exchange) if fn else getattr(source, "feed", "live")


def _one_source(choice: str, settings: Settings) -> TickSource:
    built_in = {"kite": lambda: KiteTickSource(settings),
                "synthetic": lambda: SyntheticTickSource(interval_s=settings.synthetic_tick_interval_ms / 1000),
                "static": StaticTickSource}
    if choice in built_in:
        return built_in[choice]()
    from app.providers import load

    return load("tick_source", choice)              # "package.module:Class", made with no arguments


def make_tick_source(settings: Settings) -> TickSource:
    """The feed: TICK_SOURCES routes exchanges to sources ("NSE=kite,NYSE=mypkg.vendor:Ticks"); the rest (or every
    exchange, when it is empty) get the default below."""
    default = _default_source(settings)
    routes = {}
    for part in [x.strip() for x in settings.tick_sources.split(",") if x.strip()]:
        ex, _, choice = part.partition("=")
        if not choice:
            raise ValueError(f"TICK_SOURCES entry '{part}': use EXCHANGE=source, e.g. NSE=kite")
        routes[ex.strip().upper()] = choice.strip()
    if not routes:
        return default
    made: dict[str, TickSource] = {}
    return RoutedTickSource(default, {ex: made.setdefault(c, _one_source(c, settings)) for ex, c in routes.items()})


def _default_source(settings: Settings) -> TickSource:
    if settings.data_source == "kite":
        return KiteTickSource(settings)
    if settings.simulate_ticks:
        return SyntheticTickSource(interval_s=settings.synthetic_tick_interval_ms / 1000)
    return StaticTickSource()
