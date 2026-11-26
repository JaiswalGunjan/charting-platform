import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import sessionmaker

from app.ai.analyst import ChartAnalyst
from app.alerts.engine import AlertEngine
from app.api import ai, alerts, custom_indicators, drawings, history, indicators, patterns, scanner, screener, symbols, watchlists, ws
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
                       throttle_s=settings.ws_throttle_ms / 1000, persist=settings.data_source != "eod")


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
    for r in (symbols, history, indicators, custom_indicators, drawings, patterns, scanner, screener, ws, watchlists, alerts, ai):
        app.include_router(r.router)
    from app.providers import setup_scanners

    for sc in setup_scanners().values():         # what each setup scanner brings (SwingScanner: its report pages)
        for r in sc.routers():
            app.include_router(r)

    @app.get("/health")
    def health() -> dict:
        from app.markets import markets

        live = app.state.live
        feeds = live.feeds(list(markets())) if live is not None else {m: "none" for m in markets()}
        return {"status": "ok", "data_source": settings.data_source, "live": app.state.live is not None,
                "feeds": feeds,                 # per exchange: live | simulated | none (last close only)
                "simulated_ticks": settings.data_source != "kite" and settings.simulate_ticks,
                # where prices come from: a live feed, simulated ticks, or the last close of the stored data
                "ticks": "live" if settings.data_source == "kite" else ("simulated" if settings.simulate_ticks else "none"),
                # finest stored intraday history: imported CSVs are hourly, Kite/synthetic are 1-minute
                "intraday_history": "1h" if settings.data_source == "eod" else "1m"}

    return app


app = create_app()
