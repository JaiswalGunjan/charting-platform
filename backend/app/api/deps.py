from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.marketdata.loader import resolve_symbol
from app.marketdata.timeframes import Timeframe, get_timeframe
from app.models import Symbol

SessionDep = Annotated[Session, Depends(get_session)]


def symbol_or_404(session: Session, symbol: str) -> Symbol:
    s = resolve_symbol(session, symbol)
    if s is None:
        raise HTTPException(404, f"unknown symbol {symbol}")
    return s


def timeframe_or_400(tf: str) -> Timeframe:
    try:
        return get_timeframe(tf)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
