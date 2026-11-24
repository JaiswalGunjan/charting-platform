import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import sessionmaker

from app.ai.analyst import ChartAnalyst
from app.alerts.engine import AlertEngine
from app.api import ai, alerts, history, indicators, symbols, watchlists, ws
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.live.service import LiveService

log = logging.getLogger(__name__)
LiveFactory = Callable[[sessionmaker], LiveService | None]


def default_live(session_factory: sessionmaker) -> LiveService | None:
    settings = get_settings()
    if not settings.live_enabled:
        return None
    from app.live.store import make_store
    from app.live.ticks import make_tick_source

    return LiveService(make_tick_source(settings), make_store(settings.redis_url), session_factory,
                       throttle_s=settings.ws_throttle_ms / 1000)


def default_analyst() -> ChartAnalyst:
    s = get_settings()
    return ChartAnalyst(api_key=s.anthropic_api_key, model=s.ai_model, effort=s.ai_effort, fallbacks=s.ai_fallbacks)


def create_app(live_factory: LiveFactory = default_live,
               session_factory: sessionmaker = SessionLocal,
               analyst: ChartAnalyst | None = None) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(session_factory.kw["bind"])
        app.state.session_factory = session_factory
        app.state.analyst = analyst or default_analyst()
        live = live_factory(session_factory)
        app.state.live = live
        app.state.alerts = None
        if live is not None:
            await live.start()
            app.state.alerts = AlertEngine(live, session_factory)
            await app.state.alerts.start()
        try:
            yield
        finally:
            if live is not None:
                await live.stop()

    app = FastAPI(title="Charting Platform API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for r in (symbols, history, indicators, ws, watchlists, alerts, ai):
        app.include_router(r.router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "data_source": settings.data_source, "live": app.state.live is not None}

    return app


app = create_app()
