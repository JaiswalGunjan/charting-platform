import math

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.api.deps import SessionDep, symbol_or_404, timeframe_or_400
from app.indicators.registry import INDICATORS, compute, get_indicator
from app.marketdata.history import get_bars

router = APIRouter(tags=["indicators"])
_RESERVED = {"symbol", "tf", "to", "from", "limit"}


class ParamOut(BaseModel):
    name: str
    default: float
    min: float
    max: float
    kind: str


class IndicatorMeta(BaseModel):
    id: str
    title: str
    overlay: bool
    outputs: list[str]
    params: list[ParamOut]
    levels: list[float]


class IndicatorOut(BaseModel):
    id: str
    symbol: str
    tf: str
    params: dict[str, float]
    t: list[int]
    outputs: dict[str, list[float | None]]
    next_to: int | None


def _clean(a: np.ndarray) -> list[float | None]:
    return [None if math.isnan(x) else round(x, 6) for x in a.tolist()]


@router.get("/indicators", response_model=list[IndicatorMeta])
def list_indicators() -> list[IndicatorMeta]:
    return [
        IndicatorMeta(id=i.id, title=i.title, overlay=i.overlay, outputs=list(i.outputs),
                      params=[ParamOut(**p.__dict__) for p in i.params], levels=list(i.levels))
        for i in INDICATORS.values()
    ]


@router.get("/indicators/{ind_id}", response_model=IndicatorOut)
def indicator_values(
    ind_id: str,
    request: Request,
    session: SessionDep,
    symbol: str = Query(...),
    tf: str = Query("1D"),
    to: int | None = Query(None),
    from_: int | None = Query(None, alias="from"),
    limit: int = Query(500, ge=1, le=5000),
) -> IndicatorOut:
    """Indicator values aligned to /history bars. Params as query args, e.g. ?length=50."""
    try:
        ind = get_indicator(ind_id)
        params = ind.resolve_params({k: v for k, v in request.query_params.items() if k not in _RESERVED})
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    sym = symbol_or_404(session, symbol)
    timeframe = timeframe_or_400(tf)

    warm = int(ind.warmup(params))
    bars = get_bars(session, sym.id, timeframe, limit=limit + warm, to=to)
    values = compute(ind, bars, params)

    keep = np.ones(len(bars), dtype=bool)
    if len(bars) > limit:
        keep[: len(bars) - limit] = False
    if from_ is not None:
        keep &= bars.t >= from_
    t = bars.t[keep]
    more = bars.has_more or (len(t) > 0 and bool((bars.t < t[0]).any()))
    return IndicatorOut(
        id=ind.id, symbol=sym.full, tf=timeframe.name, params=params,
        t=t.tolist(),
        outputs={k: _clean(v[keep]) for k, v in values.items()},
        next_to=int(t[0]) if more and len(t) else None,
    )
