"""Live pipeline: tick source -> forming bars -> store / persistence / WebSocket fan-out."""
import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.live.bars import FormingBars, LiveBar, live_bucket
from app.live.store import LiveStore
from app.live.ticks import Tick, TickSource
from app.marketdata.base import Bar, parse_symbol
from app.marketdata.history import get_bars
from app.marketdata.loader import resolve_symbol, to_info, upsert_candles
from app.marketdata.timeframes import TIMEFRAMES, get_timeframe, market_for

log = logging.getLogger(__name__)
TickListener = Callable[[Tick, FormingBars], Awaitable[None] | None]


class Connection:
    """One WebSocket client. Updates are conflated and flushed every `throttle_s`."""

    def __init__(self, send_json: Callable[[Any], Awaitable[None]], throttle_s: float):
        self.send_json = send_json
        self.throttle_s = throttle_s
        self.subs: dict[str, set[str]] = {}     # symbol -> {tf}
        self.pending: dict[tuple, dict] = {}
        self.finals: list[dict] = []            # last state of bars that rolled over

    def push_bar(self, symbol: str, tf: str, bar: dict) -> None:
        key = ("bar", symbol, tf)
        old = self.pending.get(key)
        if old is not None and old["bar"]["t"] != bar["t"]:
            self.finals.append(old)
        self.pending[key] = {"type": "bar", "symbol": symbol, "tf": tf, "bar": bar}

    def push_quote(self, quote: dict) -> None:
        self.pending[("quote", quote["symbol"])] = {"type": "quote", **quote}

    def push_event(self, msg: dict) -> None:
        """Never conflated (e.g. alert notifications)."""
        self.finals.append(msg)

    async def flush(self) -> None:
        if not self.pending and not self.finals:
            return
        msgs = self.finals + list(self.pending.values())
        self.finals, self.pending = [], {}
        for m in msgs:
            await self.send_json(m)

    async def run_sender(self) -> None:
        while True:
            await asyncio.sleep(self.throttle_s)
            await self.flush()


class LiveService:
    def __init__(self, source: TickSource, store: LiveStore, session_factory: sessionmaker,
                 throttle_s: float = 0.25, clock: Callable[[], float] = time.time, persist: bool = True):
        self.source = source
        self.persist = persist  # False: simulated ticks must never be written over real history
        self.store = store
        self.session_factory = session_factory
        self.throttle_s = throttle_s
        self.clock = clock
        self.state: dict[str, FormingBars] = {}
        self.symbol_ids: dict[str, int] = {}
        self.infos: dict[str, Any] = {}
        self.conns: dict[str, set[Connection]] = {}
        self.listeners: list[TickListener] = []
        self.pinned: set[str] = set()              # streamed without WS clients (alerts)
        self.all_conns: set[Connection] = set()
        self._locks: dict[str, asyncio.Lock] = {}
        self._dirty: set[str] = set()
        self._bg: set[asyncio.Task] = set()
        self._flusher: asyncio.Task | None = None

    # ---- lifecycle -------------------------------------------------------
    async def start(self) -> None:
        await self.source.start(self._on_tick)
        self._flusher = asyncio.create_task(self._store_flusher(), name="live-store-flusher")

    async def stop(self) -> None:
        if self._flusher:
            self._flusher.cancel()
        await self.source.stop()
        for t in list(self._bg):
            t.cancel()
        await self.store.close()

    def add_listener(self, fn: TickListener) -> None:
        self.listeners.append(fn)

    # ---- subscriptions ---------------------------------------------------
    def new_connection(self, send_json: Callable[[Any], Awaitable[None]]) -> Connection:
        conn = Connection(send_json, self.throttle_s)
        self.all_conns.add(conn)
        return conn

    def broadcast(self, msg: dict) -> None:
        for conn in self.all_conns:
            conn.push_event(msg)

    async def subscribe(self, conn: Connection, symbol: str, tf: str) -> dict:
        get_timeframe(tf)  # raises ValueError for bad tf
        full = await self.ensure_stream(symbol)
        conn.subs.setdefault(full, set()).add(tf)
        self.conns.setdefault(full, set()).add(conn)
        fb = self.state[full]
        bar = fb.bars.get(tf)
        return {"symbol": full, "tf": tf, "bar": bar.as_dict() if bar else None, "quote": fb.quote()}

    async def unsubscribe(self, conn: Connection, symbol: str, tf: str | None = None) -> None:
        full = "{}:{}".format(*parse_symbol(symbol))
        if full not in conn.subs:
            return
        if tf is None:
            conn.subs.pop(full)
        else:
            conn.subs[full].discard(tf)
            if not conn.subs[full]:
                conn.subs.pop(full)
        if full not in conn.subs:
            await self._release(conn, full)

    async def drop(self, conn: Connection) -> None:
        self.all_conns.discard(conn)
        for full in list(conn.subs):
            conn.subs.pop(full)
            await self._release(conn, full)

    async def _release(self, conn: Connection, full: str) -> None:
        subs = self.conns.get(full)
        if subs is None:
            return
        subs.discard(conn)
        if not subs and full not in self.pinned:
            del self.conns[full]
            await self.source.unsubscribe(self.infos[full])
            self.state.pop(full, None)
            log.info("upstream unsubscribed %s", full)

    async def pin(self, symbol: str) -> str:
        """Keep a symbol streaming without any WebSocket client (e.g. for alerts)."""
        full = await self.ensure_stream(symbol)
        self.pinned.add(full)
        self.conns.setdefault(full, set())
        return full

    async def unpin(self, full: str) -> None:
        if full in self.pinned:
            self.pinned.discard(full)
            if not self.conns.get(full):
                self.conns[full] = set()
                await self._release(None, full)  # type: ignore[arg-type]

    async def ensure_stream(self, symbol: str) -> str:
        """Start the single upstream subscription for a symbol (idempotent)."""
        lock = self._locks.setdefault(symbol.upper(), asyncio.Lock())
        async with lock:
            sym_row = await asyncio.to_thread(self._resolve, symbol)
            if sym_row is None:
                raise LookupError(f"unknown symbol {symbol}")
            full = sym_row.full
            if full in self.state:
                return full
            fb, last_price = await asyncio.to_thread(self._seed, sym_row.id, full)
            self.state[full] = fb
            self.symbol_ids[full] = sym_row.id
            self.infos[full] = to_info(sym_row)
            await self.source.subscribe(self.infos[full], last_price)
            log.info("upstream subscribed %s (last %.2f)", full, last_price or float("nan"))
            return full

    def _resolve(self, symbol: str):
        with self.session_factory() as s:
            return resolve_symbol(s, symbol)

    def _seed(self, symbol_id: int, full: str) -> tuple[FormingBars, float | None]:
        now = self.clock()
        seed: dict[str, LiveBar | None] = {}
        market = market_for(full.split(":", 1)[0])
        with self.session_factory() as s:
            for name, tf in TIMEFRAMES.items():
                b = get_bars(s, symbol_id, tf, limit=1)
                if len(b) and int(b.t[-1]) == live_bucket(tf, now, market):
                    seed[name] = LiveBar(int(b.t[-1]), float(b.o[-1]), float(b.h[-1]),
                                         float(b.l[-1]), float(b.c[-1]), float(b.v[-1]))
            daily = get_bars(s, symbol_id, TIMEFRAMES["1D"], limit=2)
            last_1m = get_bars(s, symbol_id, TIMEFRAMES["1m"], limit=1)
        prev_close = None
        if len(daily):
            today = int(daily.t[-1]) == live_bucket(TIMEFRAMES["1D"], now, market)
            idx = -2 if today else -1
            if len(daily) >= abs(idx):
                prev_close = float(daily.c[idx])
        last = float(last_1m.c[-1]) if len(last_1m) else (float(daily.c[-1]) if len(daily) else None)
        fb = FormingBars(full, seed, prev_close)
        fb.last_price = last
        return fb, last

    # ---- tick path (runs on the event loop) -------------------------------
    def _on_tick(self, tick: Tick) -> None:
        fb = self.state.get(tick.symbol)
        if fb is None:
            return  # late tick after unsubscribe
        res = fb.apply(tick.ts, tick.price, tick.qty)
        if res.closed_1m is not None and self.persist:
            day = fb.bars.get("1D")
            self._spawn(asyncio.to_thread(self._persist, self.symbol_ids[tick.symbol],
                                          res.closed_1m, LiveBar(**day.as_dict()) if day else None))
        quote = fb.quote()
        for conn in self.conns.get(tick.symbol, ()):
            for tf in conn.subs.get(tick.symbol, ()):
                bar = res.updated.get(tf)
                if bar is not None:
                    conn.push_bar(tick.symbol, tf, bar.as_dict())
            conn.push_quote(quote)
        self._dirty.add(tick.symbol)
        for fn in self.listeners:
            try:
                out = fn(tick, fb)
                if inspect.isawaitable(out):
                    self._spawn(out)
            except Exception:  # a broken listener must never stop the feed
                log.exception("tick listener failed")

    def _spawn(self, aw) -> None:
        t = asyncio.ensure_future(aw)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    def _persist(self, symbol_id: int, bar_1m: LiveBar, bar_1d: LiveBar | None) -> None:
        try:
            with self.session_factory() as s:
                upsert_candles(s, symbol_id, "1m", [Bar(bar_1m.t, bar_1m.o, bar_1m.h, bar_1m.l, bar_1m.c, bar_1m.v)])
                if bar_1d is not None:
                    upsert_candles(s, symbol_id, "1D",
                                   [Bar(bar_1d.t, bar_1d.o, bar_1d.h, bar_1d.l, bar_1d.c, bar_1d.v)])
        except Exception:
            log.exception("persisting closed bar failed")

    async def _store_flusher(self) -> None:
        while True:
            await asyncio.sleep(self.throttle_s)
            dirty, self._dirty = self._dirty, set()
            for sym in dirty:
                fb = self.state.get(sym)
                if fb is None:
                    continue
                try:
                    await self.store.set_state(sym, fb.quote(), {k: b.as_dict() for k, b in fb.current().items()})
                except Exception:
                    log.exception("live store write failed")

    # ---- reads -----------------------------------------------------------
    def quote(self, symbol: str) -> dict | None:
        fb = self.state.get(symbol)
        return fb.quote() if fb else None
