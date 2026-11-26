from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select

from app.api.deps import SessionDep, symbol_or_404
from app.models import Symbol
from app.markets import markets

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


def exchange_rank():
    """Exchanges in the market registry's order (app/markets.toml), unknown ones last."""
    ms = markets()
    return case({code: m.order for code, m in ms.items()}, value=Symbol.exchange, else_=len(ms))


@router.get("/markets")
def list_markets() -> list[dict]:
    """Every market Charting Lab knows (app/markets.toml): time zone, session, currency, ... in display order; the
    first is the default."""
    return [m.as_dict() for m in markets().values()]


@router.get("/exchanges")
def list_exchanges(session: SessionDep) -> list[dict]:
    rows = session.execute(select(Symbol.exchange, func.count()).group_by(Symbol.exchange)
                           .order_by(exchange_rank())).all()
    return [{"exchange": e, "symbols": n} for e, n in rows]


@router.get("/symbols", response_model=list[SymbolOut])
def search_symbols(
    session: SessionDep,
    q: str = Query("", description="prefix of ticker or substring of name"),
    exchange: str | None = Query(None, description="an exchange code (GET /markets)"),
    limit: int = Query(20, ge=1, le=100),
) -> list[SymbolOut]:
    """Exact ticker first, then ticker prefixes, then name matches; exchanges in the market registry's order."""
    q = q.strip()
    stmt = select(Symbol)
    if exchange:
        stmt = stmt.where(Symbol.exchange == exchange.upper())
    if q:
        esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(or_(Symbol.ticker.ilike(f"{esc}%", escape="\\"), Symbol.name.ilike(f"%{esc}%", escape="\\")))
        rank = case((func.upper(Symbol.ticker) == q.upper(), 0),
                    (Symbol.ticker.ilike(f"{esc}%", escape="\\"), 1),
                    (Symbol.name.ilike(f"{esc}%", escape="\\"), 2), else_=3)
        stmt = stmt.order_by(rank, exchange_rank(), func.length(Symbol.ticker), Symbol.ticker)
    else:
        stmt = stmt.order_by(exchange_rank(), Symbol.ticker)
    return [SymbolOut.of(s) for s in session.scalars(stmt.limit(limit))]


@router.get("/symbols/{symbol}", response_model=SymbolOut)
def get_symbol(symbol: str, session: SessionDep) -> SymbolOut:
    return SymbolOut.of(symbol_or_404(session, symbol))
