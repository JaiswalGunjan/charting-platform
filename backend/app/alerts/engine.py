"""Price-alert engine: a tick listener on the live service.

Alerts are evaluated edge-triggered: an alert fires when its condition goes
false -> true. A one-shot alert (once=True) is then marked triggered; a repeating
alert re-arms and fires again on the next false -> true transition.

Per-symbol linear scan is fine for the prototype; the blueprint's price-bucket
index is the upgrade path once a symbol carries thousands of alerts.
"""
import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.live.bars import FormingBars
from app.live.service import LiveService
from app.live.ticks import Tick
from app.models import Alert, AlertEvent

log = logging.getLogger(__name__)
OPS = ("crosses_above", "crosses_below", "above", "below")


def validate_condition(cond: dict) -> dict:
    op = cond.get("op")
    if op not in OPS:
        raise ValueError(f"condition.op must be one of {OPS}")
    try:
        price = float(cond["price"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("condition.price must be a number") from None
    if price <= 0:
        raise ValueError("condition.price must be positive")
    return {"op": op, "price": price}


def describe(symbol: str, cond: dict) -> str:
    return f"{symbol} {cond['op'].replace('_', ' ')} {cond['price']:g}"


@dataclass
class Rule:
    id: int
    symbol: str
    op: str
    price: float
    once: bool
    message: str
    prev: float | None  # last price seen by this rule
    was_true: bool = False

    def check(self, cur: float) -> bool:
        """Advance with a new price; True if the rule fires now."""
        prev, x = self.prev, self.price
        if self.op == "above":
            cond = cur >= x
        elif self.op == "below":
            cond = cur <= x
        elif self.op == "crosses_above":
            cond = prev is not None and prev < x <= cur
        else:
            cond = prev is not None and prev > x >= cur
        fired = cond and not self.was_true
        self.was_true = cond
        self.prev = cur
        return fired


class AlertEngine:
    def __init__(self, live: LiveService, session_factory: sessionmaker):
        self.live = live
        self.session_factory = session_factory
        self.by_symbol: dict[str, dict[int, Rule]] = {}
        live.add_listener(self.on_tick)

    async def start(self) -> None:
        def load():
            with self.session_factory() as s:
                return list(s.scalars(select(Alert).where(Alert.status == "active")))

        for a in await asyncio.to_thread(load):
            try:
                await self.arm(a)
            except Exception:
                log.exception("could not arm alert %s", a.id)
        log.info("alert engine: %d active alerts", sum(len(v) for v in self.by_symbol.values()))

    async def arm(self, a: Alert) -> None:
        full = await self.live.pin(a.symbol.full)
        cond = a.condition_json
        quote = self.live.quote(full) or {}
        prev = a.ref_price if a.ref_price is not None else quote.get("ltp")
        self.by_symbol.setdefault(full, {})[a.id] = Rule(
            a.id, full, cond["op"], float(cond["price"]), a.once, a.message or describe(full, cond), prev)

    async def disarm(self, alert_id: int) -> None:
        for full, rules in list(self.by_symbol.items()):
            if rules.pop(alert_id, None) is not None and not rules:
                del self.by_symbol[full]
                await self.live.unpin(full)

    def on_tick(self, tick: Tick, _fb: FormingBars) -> None:
        rules = self.by_symbol.get(tick.symbol)
        if not rules:
            return
        for rule in list(rules.values()):
            if rule.check(tick.price):
                self._fire(rule, tick)

    def _fire(self, rule: Rule, tick: Tick) -> None:
        log.info("alert %s fired: %s @ %s", rule.id, rule.message, tick.price)
        self.live.broadcast({
            "type": "alert", "alert_id": rule.id, "symbol": rule.symbol, "message": rule.message,
            "price": tick.price, "ts": tick.ts, "condition": {"op": rule.op, "price": rule.price},
        })
        if rule.once:
            self.by_symbol[rule.symbol].pop(rule.id, None)
            if not self.by_symbol[rule.symbol]:
                del self.by_symbol[rule.symbol]
                self.live._spawn(self.live.unpin(rule.symbol))
        self.live._spawn(asyncio.to_thread(self._record, rule, tick))

    def _record(self, rule: Rule, tick: Tick) -> None:
        with self.session_factory() as s:
            a = s.get(Alert, rule.id)
            if a is None:
                return
            s.add(AlertEvent(alert_id=a.id, ts=tick.ts, price=tick.price, message=rule.message))
            a.triggered_at = tick.ts
            a.ref_price = tick.price
            if rule.once:
                a.status = "triggered"
            s.commit()
