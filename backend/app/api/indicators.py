import math

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.api.deps import SessionDep, symbol_or_404, timeframe_or_400
from app.auth.deps import UserDep
from app.api.custom_indicators import PREFIX, get_custom, to_indicator, user_customs
from app.indicators.registry import INDICATORS, Indicator, compute, get_indicator
from app.marketdata.history import concat_bars, get_bars, get_bars_after

router = APIRouter(tags=["indicators"])
_RESERVED = {"symbol", "tf", "to", "from", "limit"}


class ParamOut(BaseModel):
    name: str
    default: float | str
    min: float
    max: float
    kind: str
    options: list[str]


class PlotOut(BaseModel):
    name: str
    style: str
    color: str | None


class IndicatorMeta(BaseModel):
    id: str
    title: str
    category: str
    overlay: bool
    outputs: list[str]
    plots: list[PlotOut]
    params: list[ParamOut]
    levels: list[float]


class IndicatorOut(BaseModel):
    id: str
    symbol: str
    tf: str
    params: dict[str, float | str]
    t: list[int]
    outputs: dict[str, list[float | None]]
    next_to: int | None


def _clean(a: np.ndarray) -> list[float | None]:
    return [round(x, 6) if math.isfinite(x) else None for x in a.tolist()]


def _meta(i: Indicator) -> IndicatorMeta:
    return IndicatorMeta(id=i.id, title=i.title, category=i.category, overlay=i.overlay, outputs=list(i.outputs),
                         plots=[PlotOut(**p.__dict__) for p in i.plots],
                         params=[ParamOut(**{**p.__dict__, "options": list(p.options)}) for p in i.params],
                         levels=list(i.levels))


@router.get("/indicators", response_model=list[IndicatorMeta])
def list_indicators(user: UserDep, session: SessionDep) -> list[IndicatorMeta]:
    """Built-in indicators, then the user's custom (formula) indicators."""
    return [_meta(i) for i in INDICATORS.values()] + [_meta(to_indicator(r)) for r in user_customs(session, user.id)]


def _lookup(session, ind_id: str, uid: int) -> Indicator:
    if ind_id.startswith(PREFIX):
        return to_indicator(get_custom(session, ind_id, uid))
    return get_indicator(ind_id)


@router.get("/indicators/{ind_id}", response_model=IndicatorOut)
def indicator_values(
    user: UserDep,
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
        ind = _lookup(session, ind_id, user.id)
        params = ind.resolve_params({k: v for k, v in request.query_params.items() if k not in _RESERVED})
        warm = int(ind.warmup(params))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    sym = symbol_or_404(session, symbol)
    timeframe = timeframe_or_400(tf)

    bars = get_bars(session, sym.id, timeframe, limit=limit + warm, to=to)
    page_t, n_page = bars.t, len(bars)
    ahead = int(ind.lookahead(params))
    if ahead and to is not None:  # e.g. Ichimoku's lagging span reads bars after the page
        bars = concat_bars(bars, get_bars_after(session, sym.id, timeframe, frm=to, limit=ahead))
    try:
        values = {k: v[:n_page] for k, v in compute(ind, bars, params).items()}
    except ValueError as e:  # e.g. a formula input used as a window length set to 2.5
        raise HTTPException(400, str(e)) from None

    keep = np.ones(n_page, dtype=bool)
    if n_page > limit:
        keep[: n_page - limit] = False
    if from_ is not None:
        keep &= page_t >= from_
    t = page_t[keep]
    more = bars.has_more or (len(t) > 0 and bool((page_t < t[0]).any()))
    return IndicatorOut(
        id=ind.id, symbol=sym.full, tf=timeframe.name, params=params,
        t=t.tolist(),
        outputs={k: _clean(v[keep]) for k, v in values.items()},
        next_to=int(t[0]) if more and len(t) else None,
    )
