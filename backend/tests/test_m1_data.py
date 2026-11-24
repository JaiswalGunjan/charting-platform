from datetime import date, datetime

from sqlalchemy import func, select

from app.marketdata.base import IST, MINUTES_PER_SESSION, parse_symbol
from app.marketdata.loader import load_history, resolve_symbol
from app.marketdata.synthetic import SyntheticSource
from app.models import Candle
from tests.conftest import END, MINUTE_START

SRC = SyntheticSource()


def _sym(ticker="RELIANCE"):
    return next(s for s in SRC.symbols() if s.ticker == ticker)


def test_parse_symbol():
    assert parse_symbol("nse:reliance") == ("NSE", "RELIANCE")
    assert parse_symbol("TCS") == ("NSE", "TCS")
    assert parse_symbol("NSE:NIFTY 50") == ("NSE", "NIFTY 50")


def test_synthetic_is_deterministic():
    a = SRC.candles(_sym(), "1m", date(2026, 11, 18), date(2026, 11, 18))
    b = SRC.candles(_sym(), "1m", date(2026, 11, 18), date(2026, 11, 18))
    assert a == b and len(a) == MINUTES_PER_SESSION


def test_minute_bars_inside_session_and_valid():
    bars = SRC.candles(_sym(), "1m", date(2026, 11, 16), date(2026, 11, 20))
    assert len(bars) == 5 * MINUTES_PER_SESSION
    for b in bars:
        t = datetime.fromtimestamp(b.ts, IST)
        assert (9, 15) <= (t.hour, t.minute) <= (15, 29)
        assert t.weekday() < 5
        assert b.l <= min(b.o, b.c) <= max(b.o, b.c) <= b.h
    assert [b.ts for b in bars] == sorted(b.ts for b in bars)


def test_daily_agrees_with_minutes():
    d = date(2026, 11, 19)
    mins = SRC.candles(_sym(), "1m", d, d)
    (day,) = SRC.candles(_sym(), "1D", d, d)
    assert day.o == mins[0].o and day.c == mins[-1].c
    assert day.h == max(b.h for b in mins) and day.l == min(b.l for b in mins)
    assert datetime.fromtimestamp(day.ts, IST).date() == d


def test_no_future_bars_mid_session():
    d = date(2026, 11, 19)
    now = datetime(2026, 11, 19, 10, 0, 30, tzinfo=IST).timestamp()  # 45 min into session
    mins = SRC.candles(_sym(), "1m", d, d, now=now)
    assert len(mins) == 46 and mins[-1].ts <= now  # 09:15 .. 10:00 inclusive
    (day,) = SRC.candles(_sym(), "1D", d, d, now=now)
    assert day.c == mins[-1].c and day.h == max(b.h for b in mins)
    before_open = datetime(2026, 11, 19, 9, 0, tzinfo=IST).timestamp()
    assert SRC.candles(_sym(), "1m", d, d, now=before_open) == []


def test_weekends_skipped():
    assert SRC.candles(_sym(), "1D", date(2026, 11, 21), date(2026, 11, 22)) == []


def test_load_is_idempotent(session_factory):
    with session_factory() as s:
        sym = resolve_symbol(s, "NSE:RELIANCE")
        count = lambda: s.scalar(select(func.count()).select_from(Candle)  # noqa: E731
                                 .where(Candle.symbol_id == sym.id, Candle.tf == "1m"))
        before = count()
        load_history(s, SRC, sym, "1m", MINUTE_START, END)
        assert count() == before == 10 * MINUTES_PER_SESSION


def test_symbols_api(client):
    r = client.get("/symbols", params={"q": "REL"})
    assert r.status_code == 200
    assert [x["symbol"] for x in r.json()] == ["NSE:RELIANCE"]
    assert client.get("/symbols", params={"q": "bank"}).json()  # name search
    assert client.get("/symbols/NSE:TCS").json()["name"] == "Tata Consultancy Services"
    assert client.get("/symbols/NSE:NOPE").status_code == 404
    assert client.get("/health").json()["status"] == "ok"
