import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth.deps import UserDep
from app.ai.analyst import DISCLAIMER, AnalystError, AnalystUnavailable, ChartAnalysis, ChartAnalyst
from app.ai.context import build_context
from app.api.deps import timeframe_or_400
from app.marketdata.history import get_bars
from app.marketdata.loader import resolve_symbol
from app.models import AiLog

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai"])
CONTEXT_BARS = 400  # enough for EMA200 to be well defined


class ExplainIn(BaseModel):
    symbol: str
    tf: str = "1D"
    to: int | None = Field(None, description="analyse the chart as of this bar time (exclusive)")
    dry_run: bool = Field(False, description="return the context only; no LLM call")


class Usage(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


class ExplainOut(BaseModel):
    symbol: str
    tf: str
    analysis: ChartAnalysis | None
    disclaimer: str
    context: dict
    usage: Usage | None
    log_id: int | None


def get_analyst(request: Request) -> ChartAnalyst:
    return request.app.state.analyst


@router.post("/explain", response_model=ExplainOut)
async def explain_chart(user: UserDep, body: ExplainIn, request: Request) -> ExplainOut:
    tf = timeframe_or_400(body.tf)
    sf = request.app.state.session_factory

    def load():
        with sf() as s:
            sym = resolve_symbol(s, body.symbol)
            if sym is None:
                return None, None
            return sym.full, get_bars(s, sym.id, tf, limit=CONTEXT_BARS, to=body.to)

    full, bars = await asyncio.to_thread(load)
    if full is None:
        raise HTTPException(404, f"unknown symbol {body.symbol}")
    try:
        ctx = build_context(full, tf.name, bars)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    if body.dry_run:
        return ExplainOut(symbol=full, tf=tf.name, analysis=None, disclaimer=DISCLAIMER,
                          context=ctx, usage=None, log_id=None)

    analyst = get_analyst(request)
    entry = AiLog(user_id=user.id, feature="explain_chart", symbol=full, tf=tf.name, model=analyst.model, context_json=ctx)
    status, err = 200, None
    try:
        res = await analyst.explain(ctx)
        entry.model, entry.request_id = res.model, res.request_id
        entry.input_tokens, entry.output_tokens, entry.latency_ms = res.input_tokens, res.output_tokens, res.latency_ms
        entry.output_json = res.analysis.model_dump()
    except AnalystUnavailable as e:
        status, err = 503, str(e)
    except AnalystError as e:
        status, err = 502, str(e)
    entry.error = err

    def save() -> int:
        with sf() as s:
            s.add(entry)
            s.commit()
            return entry.id

    log_id = await asyncio.to_thread(save)
    if err:
        raise HTTPException(status, err)
    return ExplainOut(
        symbol=full, tf=tf.name, analysis=res.analysis, disclaimer=DISCLAIMER, context=ctx,
        usage=Usage(model=res.model, input_tokens=res.input_tokens, output_tokens=res.output_tokens,
                    latency_ms=res.latency_ms),
        log_id=log_id,
    )
