from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.ai.analyst import ChartAnalyst
from app.db import init_db, make_engine
from app.live.service import LiveService
from app.live.store import MemoryStore
from app.live.ticks import ManualTickSource
from app.main import create_app
from app.marketdata.base import IST
from app.marketdata.loader import load_history, resolve_symbol, upsert_symbols
from app.marketdata.synthetic import SyntheticSource

# Fixed window so tests are reproducible regardless of today's date.
END = date(2026, 11, 20)  # Friday
MINUTE_START = date(2026, 11, 9)
DAILY_START = date(2025, 11, 20)


@pytest.fixture(scope="session")
def session_factory(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "test.db"
    engine = make_engine(f"sqlite:///{db.as_posix()}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    src = SyntheticSource()
    with factory() as s:
        upsert_symbols(s, src.symbols())
        for name in ("NSE:RELIANCE", "NSE:TCS"):
            sym = resolve_symbol(s, name)
            load_history(s, src, sym, "1m", MINUTE_START, END)
            load_history(s, src, sym, "1D", DAILY_START, END)
    return factory


# "now" for live tests: Monday 2026-11-23 10:00:00 IST
LIVE_NOW = datetime(2026, 11, 23, 10, 0, 0, tzinfo=IST).timestamp()


@pytest.fixture()
def ticks():
    return ManualTickSource()


class FakeLLM:
    """Stands in for anthropic.AsyncAnthropic: client.beta.messages.create(**kw)."""

    def __init__(self):
        self.calls: list[dict] = []
        self.reply: object = None  # a response object, or an exception to raise
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        self.calls.append(kw)
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply


@pytest.fixture()
def llm():
    return FakeLLM()


@pytest.fixture()
def client(session_factory, ticks, llm):
    app = create_app(lambda sf: LiveService(ticks, MemoryStore(), sf, throttle_s=0.02, clock=lambda: LIVE_NOW),
                     session_factory=session_factory, analyst=ChartAnalyst(client=llm))
    with TestClient(app) as c:
        yield c
