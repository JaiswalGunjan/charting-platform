from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import SessionDep, symbol_or_404
from app.marketdata.loader import resolve_symbol
from app.models import Watchlist, WatchlistItem
from app.auth.deps import UserDep

router = APIRouter(prefix="/watchlists", tags=["watchlists"])

DEFAULT_SYMBOLS = ["NSE:NIFTY 50", "NSE:NIFTY BANK", "NSE:RELIANCE", "NSE:TCS", "NSE:HDFCBANK", "NSE:INFY"]


class WatchlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class ItemIn(BaseModel):
    symbol: str


class WatchlistOut(BaseModel):
    id: int
    name: str
    symbols: list[str]

    @classmethod
    def of(cls, w: Watchlist) -> "WatchlistOut":
        return cls(id=w.id, name=w.name, symbols=[i.symbol.full for i in w.items])


def _get(session: Session, wid: int, uid: int) -> Watchlist:
    w = session.get(Watchlist, wid)
    if w is None or w.user_id != uid:
        raise HTTPException(404, f"watchlist {wid} not found")
    return w


def ensure_default_watchlist(session: Session, uid: int) -> None:
    """A user's first visit: a starter watchlist of well-known symbols."""
    if session.scalar(select(func.count()).select_from(Watchlist).where(Watchlist.user_id == uid)):
        return
    w = Watchlist(name="My Watchlist", user_id=uid)
    session.add(w)
    session.flush()
    for pos, name in enumerate(DEFAULT_SYMBOLS):
        sym = resolve_symbol(session, name)
        if sym is not None:
            session.add(WatchlistItem(watchlist_id=w.id, symbol_id=sym.id, position=pos))
    session.commit()


@router.get("", response_model=list[WatchlistOut])
def list_watchlists(user: UserDep, session: SessionDep) -> list[WatchlistOut]:
    ensure_default_watchlist(session, user.id)
    rows = session.scalars(select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.id))
    return [WatchlistOut.of(w) for w in rows.unique()]


@router.post("", response_model=WatchlistOut, status_code=201)
def create_watchlist(user: UserDep, body: WatchlistIn, session: SessionDep) -> WatchlistOut:
    w = Watchlist(name=body.name, user_id=user.id)
    session.add(w)
    session.commit()
    return WatchlistOut.of(w)


@router.patch("/{wid}", response_model=WatchlistOut)
def rename_watchlist(user: UserDep, wid: int, body: WatchlistIn, session: SessionDep) -> WatchlistOut:
    w = _get(session, wid, user.id)
    w.name = body.name
    session.commit()
    return WatchlistOut.of(w)


@router.delete("/{wid}", status_code=204)
def delete_watchlist(user: UserDep, wid: int, session: SessionDep) -> None:
    session.delete(_get(session, wid, user.id))
    session.commit()


@router.post("/{wid}/items", response_model=WatchlistOut, status_code=201)
def add_item(user: UserDep, wid: int, body: ItemIn, session: SessionDep) -> WatchlistOut:
    w = _get(session, wid, user.id)
    sym = symbol_or_404(session, body.symbol)
    full = sym.full
    if any(i.symbol_id == sym.id for i in w.items):
        raise HTTPException(409, f"{full} already in watchlist")
    pos = max((i.position for i in w.items), default=-1) + 1
    w.items.append(WatchlistItem(symbol_id=sym.id, position=pos, symbol=sym))
    try:
        session.commit()
    except IntegrityError:  # concurrent add
        session.rollback()
        raise HTTPException(409, f"{full} already in watchlist") from None
    session.refresh(w)
    return WatchlistOut.of(w)


@router.delete("/{wid}/items/{symbol}", response_model=WatchlistOut)
def remove_item(user: UserDep, wid: int, symbol: str, session: SessionDep) -> WatchlistOut:
    w = _get(session, wid, user.id)
    sym = symbol_or_404(session, symbol)
    item = next((i for i in w.items if i.symbol_id == sym.id), None)
    if item is None:
        raise HTTPException(404, f"{sym.full} not in watchlist")
    w.items.remove(item)
    session.commit()
    return WatchlistOut.of(w)
