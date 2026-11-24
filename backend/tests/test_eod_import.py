from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.db import init_db, make_engine
from app.marketdata.base import Bar, SymbolInfo, day_ts
from app.marketdata.eod import import_exchange
from app.marketdata.history import get_bars
from app.marketdata.loader import resolve_symbol, upsert_candles, upsert_symbols
from app.marketdata.timeframes import TIMEFRAMES
from app.models import Candle, Symbol, Watchlist, WatchlistItem

HEADER = "<TICKER>,<PER>,<DTYYYYMMDD>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>\n"
DAYS = {  # date -> rows
    "20261117": ["RELIANCE,D,20261117,1400,1410,1390,1405,1000", "M&M,D,20261117,3500,3550,3490,3540,200"],
    "20261118": ["RELIANCE,D,20261118,1405,1420,1400,1415,1100", "M&M,D,20261118,3540,3560,3500,3510,250",
                 "BAJAJ-AUTO,D,20261118,10700,10800,10650,10790,50"],
    "20261123": ["RELIANCE,D,20261123,1381,1390,1346.9,1351,15392522", "BAJAJ-AUTO,D,20261123,10775,10828,10640,10643,382079",
                 "BADROW,D,20261123,,,,,"],  # empty prices are skipped
}


@pytest.fixture()
def eod_root(tmp_path):
    d = tmp_path / "NSE" / "bhavcopy_adjusted"
    d.mkdir(parents=True)
    for day, rows in DAYS.items():
        (d / f"NSE_{day}.csv").write_text(HEADER + "\n".join(rows) + "\n")
    (tmp_path / "tickers.csv").write_text("Symbol,Name,Exchange\n500325,Reliance Industries,BSE\n")
    return tmp_path


@pytest.fixture()
def factory(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'eod.db').as_posix()}")
    init_db(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_import_replaces_synthetic_data(eod_root, factory):
    with factory() as s:
        # pre-existing synthetic state: RELIANCE with fake 1m/1D bars, an index not in the files, a watchlist
        upsert_symbols(s, [SymbolInfo("NSE", "RELIANCE"), SymbolInfo("NSE", "NIFTY 50", type="INDEX"),
                           SymbolInfo("NASDAQ", "AAPL")])
        rel, nifty = resolve_symbol(s, "NSE:RELIANCE"), resolve_symbol(s, "NSE:NIFTY 50")
        upsert_candles(s, rel.id, "1m", [Bar(day_ts(date(2026, 11, 20)) + 33300, 220, 221, 219, 220.5, 10)])
        upsert_candles(s, rel.id, "1D", [Bar(day_ts(date(2026, 11, 20)), 220, 221, 219, 220.5, 10)])
        w = Watchlist(name="W")
        s.add(w)
        s.flush()
        s.add_all([WatchlistItem(watchlist_id=w.id, symbol_id=rel.id, position=0),
                   WatchlistItem(watchlist_id=w.id, symbol_id=nifty.id, position=1)])
        s.commit()

        r = import_exchange(s, eod_root, "NSE")
        assert (r.files, r.symbols, r.bars, r.removed_symbols) == (3, 3, 7, 1)
        assert (r.first_date, r.last_date) == ("2026-11-17", "2026-11-23")

        assert resolve_symbol(s, "NSE:NIFTY 50") is None            # not in the files -> removed
        assert resolve_symbol(s, "NASDAQ:AAPL") is not None          # other exchanges untouched
        assert [i.symbol.ticker for i in s.get(Watchlist, w.id).items] == ["RELIANCE"]
        rel = resolve_symbol(s, "NSE:RELIANCE")
        assert s.scalar(select(func.count()).select_from(Candle).where(Candle.symbol_id == rel.id, Candle.tf == "1m")) == 0

        bars = get_bars(s, rel.id, TIMEFRAMES["1D"], limit=10)
        assert bars.t.tolist() == [day_ts(date(2026, 11, d)) for d in (17, 18, 23)]
        assert bars.c.tolist() == [1405, 1415, 1351] and bars.v[-1] == 15392522
        assert resolve_symbol(s, "NSE:M&M").tick_size == 0.05

        # re-import is idempotent
        r2 = import_exchange(s, eod_root, "NSE")
        assert (r2.bars, r2.removed_symbols) == (7, 0)
        assert s.scalar(select(func.count()).select_from(Candle)) == 7
        assert s.scalar(select(func.count()).select_from(Symbol).where(Symbol.exchange == "NSE")) == 3


def test_missing_folder(tmp_path, factory):
    with factory() as s, pytest.raises(FileNotFoundError):
        import_exchange(s, tmp_path, "NSE")


HOURS = ["091500", "101500", "111500", "121500", "131500", "141500", "151500"]


@pytest.fixture()
def hourly_root(tmp_path):
    d = tmp_path / "hourly" / "NSE"
    d.mkdir(parents=True)
    for i, hh in enumerate(HOURS):
        px = 1400 + i
        rows = [f"NSE.RELIANCE,20261023,{hh},{px},{px + 5},{px - 5},{px + 1},{100 * (i + 1)}",
                f"NSE.M&M,20261023,{hh},3500,3501,3499,3500,1"]
        (d / f"NSE_20261023_{hh[:4]}.csv").write_text("Symbol,Date,Time,Open,High,Low,Close,Volume\n"
                                                       + "\n".join(rows) + "\n")
    (d / "raw_1h").mkdir()  # sub-folders are ignored
    return tmp_path / "hourly"


def test_hourly_import_and_resampling(eod_root, hourly_root, factory):
    from app.marketdata.eod import import_exchange_hourly
    from app.marketdata.history import pick_base

    with factory() as s:
        import_exchange(s, eod_root, "NSE")
        rel = resolve_symbol(s, "NSE:RELIANCE")
        upsert_candles(s, rel.id, "1m", [Bar(day_ts(date(2026, 11, 24)) + 33300, 1, 1, 1, 1, 1)])

        r = import_exchange_hourly(s, hourly_root, "NSE")
        assert (r.files, r.symbols, r.bars) == (7, 2, 14)
        # daily import must not wipe the hourly bars
        import_exchange(s, eod_root, "NSE")
        assert s.scalar(select(func.count()).select_from(Candle).where(Candle.tf == "1h")) == 14

        open_ = day_ts(date(2026, 10, 23)) + 33300  # 09:15 IST
        assert pick_base(s, rel.id, TIMEFRAMES["1h"]) == "1h"
        h1 = get_bars(s, rel.id, TIMEFRAMES["1h"], limit=100)
        assert h1.t.tolist() == [open_ + 3600 * i for i in range(7)]
        h4 = get_bars(s, rel.id, TIMEFRAMES["4h"], limit=100)
        assert h4.t.tolist() == [open_, open_ + 4 * 3600]
        assert h4.o.tolist() == [1400, 1404] and h4.c.tolist() == [1404, 1407]
        assert h4.h.tolist() == [1408, 1411] and h4.v.tolist() == [1000, 1800]
        assert get_bars(s, rel.id, TIMEFRAMES["2h"], limit=100).t.tolist() == [open_ + 7200 * i for i in range(4)]
        # 15m has no hourly base: falls back to whatever 1m data exists
        assert pick_base(s, rel.id, TIMEFRAMES["15m"]) == "1m"


def test_yearly_timeframe(eod_root, factory):
    with factory() as s:
        import_exchange(s, eod_root, "NSE")
        rel = resolve_symbol(s, "NSE:RELIANCE")
        upsert_candles(s, rel.id, "1D", [Bar(day_ts(date(2025, 3, 3)), 1000, 1100, 900, 1050, 5)])
        y = get_bars(s, rel.id, TIMEFRAMES["1Y"], limit=10)
        assert y.t.tolist() == [day_ts(date(2025, 1, 1)), day_ts(date(2026, 1, 1))]
        assert y.o.tolist() == [1000, 1400] and y.c.tolist() == [1050, 1351] and y.l.tolist() == [900, 1346.9]
