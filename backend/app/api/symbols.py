from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import or_, select

from app.api.deps import SessionDep, symbol_or_404
from app.models import Symbol

router = APIRouter(tags=["symbols"])


class SymbolOut(BaseModel):
    symbol: str
    exchange: str
    ticker: str
    name: str
    type: str
    tick_size: float
    lot_size: int

    @classmethod
    def of(cls, s: Symbol) -> "SymbolOut":
        return cls(symbol=s.full, exchange=s.exchange, ticker=s.ticker, name=s.name,
                   type=s.type, tick_size=s.tick_size, lot_size=s.lot_size)


@router.get("/symbols", response_model=list[SymbolOut])
def search_symbols(
    session: SessionDep,
    q: str = Query("", description="prefix of ticker or substring of name"),
    limit: int = Query(20, ge=1, le=100),
) -> list[SymbolOut]:
    stmt = select(Symbol)
    if q:
        stmt = stmt.where(or_(Symbol.ticker.ilike(f"{q}%"), Symbol.name.ilike(f"%{q}%")))
    stmt = stmt.order_by(Symbol.ticker).limit(limit)
    return [SymbolOut.of(s) for s in session.scalars(stmt)]


@router.get("/symbols/{symbol}", response_model=SymbolOut)
def get_symbol(symbol: str, session: SessionDep) -> SymbolOut:
    return SymbolOut.of(symbol_or_404(session, symbol))
