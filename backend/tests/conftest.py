import os

# Before the app reads its settings: the owner's .env routes minute bars to the real PostgreSQL
# (BAR_STORES=1m=timescale). Tests never write there; environment variables win over .env.
os.environ["BAR_STORES"] = ""
os.environ["MINUTE_DATABASE_URL"] = ""

from datetime import date, datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402

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


def _test_engine(tmp_path_factory):
    """SQLite in a temp folder; or, with TEST_PG_URL (e.g. postgresql+psycopg://charting@127.0.0.1:5433/postgres), a
    fresh PostgreSQL database `charting_test` on that server (dropped and created again for every run)."""
    import os

    pg = os.environ.get("TEST_PG_URL")
    if not pg:
        return make_engine(f"sqlite:///{(tmp_path_factory.mktemp('db') / 'test.db').as_posix()}")
    from sqlalchemy import create_engine, text

    admin = create_engine(pg, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS charting_test WITH (FORCE)"))
        c.execute(text("CREATE DATABASE charting_test"))
    admin.dispose()
    return make_engine(pg.rsplit("/", 1)[0] + "/charting_test")


@pytest.fixture(scope="session")
def session_factory(tmp_path_factory):
    engine = _test_engine(tmp_path_factory)
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


@pytest.fixture(autouse=True)
def _no_real_screens(tmp_path_factory, monkeypatch):
    """No test reads or writes the real saved screens (backend/data/screens): every test gets its own screens folder,
    and the default folder points to a scratch one (a test that clears SCREENS_DIR still cannot reach the real one).
    A screen job a test started is waited for before the folders are restored."""
    from app.config import get_settings
    from app.patterns import store

    monkeypatch.setattr(get_settings(), "screens_dir", str(tmp_path_factory.mktemp("screens")))
    monkeypatch.setattr(store, "SCREEN_DIR", tmp_path_factory.mktemp("default-screens"))
    yield
    # a screen started through the API runs in a thread: let it finish here, while the folders above still apply
    from app.api import screener as api_sc

    if api_sc._LOCK.acquire(timeout=120):
        api_sc._LOCK.release()


@pytest.fixture(autouse=True)
def _no_real_minute_store(monkeypatch):
    """The owner's .env routes minute bars to the real PostgreSQL (BAR_STORES=1m=timescale): tests never use it; a
    test that wants a minute store sets its own (test_m24 uses a database of its own)."""
    from app import providers
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "bar_stores", "")
    monkeypatch.setattr(get_settings(), "minute_database_url", "")
    providers.reset()
    yield
    providers.reset()
