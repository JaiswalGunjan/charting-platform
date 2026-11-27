"""Chart drawings (trend lines, fibs, ...) per user and symbol. The client owns the geometry;
the server validates shape and size and stores the list as a whole."""
import time
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import SessionDep, symbol_or_404
from app.models import Drawing
from app.auth.deps import UserDep

router = APIRouter(prefix="/drawings", tags=["drawings"])

Kind = Literal["trend", "ray", "extended", "arrow", "hline", "hray", "vline", "rect", "channel", "fib", "brush", "text"]


class Point(BaseModel):
    t: float  # bar-time domain, epoch seconds
    p: float  # price


class Item(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    kind: Kind
    pts: list[Point] = Field(min_length=1, max_length=2000)  # brush strokes have many points
    color: str = Field("#2962ff", pattern=r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
    width: int = Field(2, ge=1, le=6)
    text: str | None = Field(None, max_length=500)
    locked: bool = False
    hidden: bool = False


class DrawingsIn(BaseModel):
    items: list[Item] = Field(max_length=500)


class DrawingsOut(DrawingsIn):
    symbol: str
    updated_at: float | None


def _row(session, uid: int, symbol_id: int) -> Drawing | None:
    return session.scalar(select(Drawing).where(Drawing.user_id == uid, Drawing.symbol_id == symbol_id))


@router.get("", response_model=DrawingsOut)
def get_drawings(user: UserDep, session: SessionDep, symbol: str = Query(...)) -> DrawingsOut:
    sym = symbol_or_404(session, symbol)
    row = _row(session, user.id, sym.id)
    return DrawingsOut(symbol=sym.full, items=row.items_json if row else [], updated_at=row.updated_at if row else None)


@router.put("", response_model=DrawingsOut)
def put_drawings(user: UserDep, body: DrawingsIn, session: SessionDep, symbol: str = Query(...)) -> DrawingsOut:
    sym = symbol_or_404(session, symbol)
    row = _row(session, user.id, sym.id)
    if row is None:
        row = Drawing(user_id=user.id, symbol_id=sym.id)
        session.add(row)
    row.items_json = [i.model_dump(exclude_none=True) for i in body.items]
    row.updated_at = time.time()
    session.commit()
    return DrawingsOut(symbol=sym.full, items=row.items_json, updated_at=row.updated_at)
