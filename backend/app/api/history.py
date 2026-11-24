import numpy as np
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import SessionDep, symbol_or_404, timeframe_or_400
from app.marketdata.history import get_bars
from app.marketdata.timeframes import TIMEFRAMES

router = APIRouter(tags=["history"])


class HistoryOut(BaseModel):
    symbol: str
    tf: str
    t: list[int] = Field(description="bar open times, epoch seconds UTC, ascending")
    o: list[float]
    h: list[float]
    l: list[float]  # noqa: E741
    c: list[float]
    v: list[float]
    next_to: int | None = Field(description="pass as `to` to fetch the previous page; null = no more")


@router.get("/timeframes")
def list_timeframes() -> list[str]:
    return list(TIMEFRAMES)


@router.get("/history", response_model=HistoryOut)
def history(
    session: SessionDep,
    symbol: str = Query(..., examples=["NSE:RELIANCE"]),
    tf: str = Query("1D", examples=["5m"]),
    to: int | None = Query(None, description="exclusive upper bound (epoch s); use previous next_to"),
    from_: int | None = Query(None, alias="from", description="inclusive lower bound (epoch s)"),
    limit: int = Query(500, ge=1, le=5000),
) -> HistoryOut:
    sym = symbol_or_404(session, symbol)
    timeframe = timeframe_or_400(tf)
    bars = get_bars(session, sym.id, timeframe, limit=limit, to=to, frm=from_)
    px = lambda a: np.round(a, 4).tolist()  # noqa: E731  strip float noise (221.70000000000002)
    return HistoryOut(
        symbol=sym.full, tf=timeframe.name,
        t=bars.t.tolist(), o=px(bars.o), h=px(bars.h),
        l=px(bars.l), c=px(bars.c), v=bars.v.tolist(),
        next_to=int(bars.t[0]) if bars.has_more and len(bars) else None,
    )
