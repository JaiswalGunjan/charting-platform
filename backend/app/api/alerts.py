"""Price alerts. Async handlers (DB work in threads) so the engine is only
mutated on the event-loop thread, where ticks are processed."""
import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.alerts.engine import AlertEngine, describe, validate_condition
from app.db import SessionLocal
from app.marketdata.loader import resolve_symbol
from app.models import Alert, AlertEvent
from app.auth.deps import UserDep

router = APIRouter(prefix="/alerts", tags=["alerts"])


class Condition(BaseModel):
    op: Literal["crosses_above", "crosses_below", "above", "below"]
    price: float = Field(gt=0)


class AlertIn(BaseModel):
    symbol: str
    condition: Condition
    message: str = Field("", max_length=512)
    once: bool = True


class AlertPatch(BaseModel):
    status: Literal["active", "disabled"] | None = None
    message: str | None = Field(None, max_length=512)


class AlertOut(BaseModel):
    id: int
    symbol: str
    condition: Condition
    message: str
    once: bool
    status: str
    created_at: float
    triggered_at: float | None

    @classmethod
    def of(cls, a: Alert) -> "AlertOut":
        return cls(id=a.id, symbol=a.symbol.full, condition=Condition(**a.condition_json),
                   message=a.message or describe(a.symbol.full, a.condition_json), once=a.once,
                   status=a.status, created_at=a.created_at, triggered_at=a.triggered_at)


class EventOut(BaseModel):
    id: int
    alert_id: int
    ts: float
    price: float
    message: str


def _engine(request: Request) -> AlertEngine | None:
    return getattr(request.app.state, "alerts", None)


def _sf(request: Request):
    return getattr(request.app.state, "session_factory", SessionLocal)


@router.get("", response_model=list[AlertOut])
async def list_alerts(user: UserDep, request: Request, status: str | None = None) -> list[AlertOut]:
    def q():
        with _sf(request)() as s:
            stmt = select(Alert).where(Alert.user_id == user.id)
            if status:
                stmt = stmt.where(Alert.status == status)
            return [AlertOut.of(a) for a in s.scalars(stmt.order_by(Alert.id.desc()))]
    return await asyncio.to_thread(q)


@router.post("", response_model=AlertOut, status_code=201)
async def create_alert(user: UserDep, body: AlertIn, request: Request) -> AlertOut:
    cond = validate_condition(body.condition.model_dump())
    engine = _engine(request)
    live = getattr(request.app.state, "live", None)

    def create():
        with _sf(request)() as s:
            sym = resolve_symbol(s, body.symbol)
            if sym is None:
                return None
            quote = live.quote(sym.full) if live else None
            a = Alert(user_id=user.id, symbol_id=sym.id, condition_json=cond, message=body.message, once=body.once,
                      ref_price=(quote or {}).get("ltp"))
            s.add(a)
            s.commit()
            s.refresh(a)
            return a

    a = await asyncio.to_thread(create)
    if a is None:
        raise HTTPException(404, f"unknown symbol {body.symbol}")
    if engine:
        await engine.arm(a)
    return AlertOut.of(a)


@router.patch("/{alert_id}", response_model=AlertOut)
async def update_alert(user: UserDep, alert_id: int, body: AlertPatch, request: Request) -> AlertOut:
    engine = _engine(request)

    def upd():
        with _sf(request)() as s:
            a = s.get(Alert, alert_id)
            if a is None or a.user_id != user.id:
                return None
            if body.message is not None:
                a.message = body.message
            if body.status is not None:
                a.status = body.status
                if body.status == "active":
                    a.ref_price = None  # re-arm from the current price
            s.commit()
            s.refresh(a)
            return a

    a = await asyncio.to_thread(upd)
    if a is None:
        raise HTTPException(404, f"alert {alert_id} not found")
    if engine:
        await engine.disarm(alert_id)
        if a.status == "active":
            await engine.arm(a)
    return AlertOut.of(a)


@router.delete("/{alert_id}", status_code=204)
async def delete_alert(user: UserDep, alert_id: int, request: Request) -> None:
    def rm():
        with _sf(request)() as s:
            a = s.get(Alert, alert_id)
            if a is None or a.user_id != user.id:
                return False
            s.delete(a)
            s.commit()
            return True

    if not await asyncio.to_thread(rm):
        raise HTTPException(404, f"alert {alert_id} not found")
    if engine := _engine(request):
        await engine.disarm(alert_id)


@router.get("/events", response_model=list[EventOut])
async def list_events(user: UserDep, request: Request, limit: int = Query(50, ge=1, le=500)) -> list[EventOut]:
    def q():
        with _sf(request)() as s:
            stmt = (select(AlertEvent).join(Alert).where(Alert.user_id == user.id)
                    .order_by(AlertEvent.id.desc()).limit(limit))
            return [EventOut(id=e.id, alert_id=e.alert_id, ts=e.ts, price=e.price, message=e.message)
                    for e in s.scalars(stmt)]
    return await asyncio.to_thread(q)
