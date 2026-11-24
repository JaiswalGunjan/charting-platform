"""Regression guards for behaviour the UI relies on: API contracts for every timeframe, the admin CLI import
commands end to end, the public name lists, US live bars and request validation."""
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app import cli
from app.db import init_db, make_engine
from app.live.bars import FormingBars
from app.marketdata import names
from app.marketdata.timeframes import TIMEFRAMES
from app.models import Candle, Symbol

ALL_TFS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1D", "1W", "1M", "1Y"]


# ---- API contracts --------------------------------------------------------------------
def test_health_and_timeframes(client):
    h = client.get("/health").json()
    assert {"status", "data_source", "live", "simulated_ticks", "intraday_history"} <= set(h)
    assert h["intraday_history"] in ("1m", "1h")
    assert client.get("/timeframes").json() == ALL_TFS
    assert list(TIMEFRAMES) == ALL_TFS  # the frontend's timeframe menu lists exactly these


@pytest.mark.parametrize("tf", ALL_TFS)
def test_history_every_timeframe_is_well_formed(client, tf):
    r = client.get("/history", params=dict(symbol="NSE:RELIANCE", tf=tf, limit=50)).json()
    t = r["t"]
    assert t == sorted(set(t)), "bar times must be strictly ascending (the chart rejects anything else)"
    n = len(t)
    assert n and all(len(r[k]) == n for k in "ohlcv")
    o, h, l, c = (np.array(r[k]) for k in "ohlc")  # noqa: E741
    assert (h >= np.maximum(o, c) - 1e-9).all() and (l <= np.minimum(o, c) + 1e-9).all()


@pytest.mark.parametrize("tf", ["5m", "1h", "1D", "1W", "1M"])
def test_history_paging_has_no_gaps_or_overlap(client, tf):
    q = dict(symbol="NSE:RELIANCE", tf=tf)
    whole = client.get("/history", params=dict(q, limit=60)).json()
    p1 = client.get("/history", params=dict(q, limit=30)).json()
    if p1["next_to"] is None:
        pytest.skip("not enough history for two pages")
    p2 = client.get("/history", params=dict(q, limit=30, to=p1["next_to"])).json()
    assert p2["t"] + p1["t"] == whole["t"][-len(p2["t"] + p1["t"]):]


def test_exchanges_and_symbol_lookup(client):
    ex = {e["exchange"]: e["symbols"] for e in client.get("/exchanges").json()}
    assert ex.get("NSE", 0) > 0
    s = client.get("/symbols/RELIANCE").json()          # bare ticker = NSE
    assert s["symbol"] == "NSE:RELIANCE" and {"name", "type", "tick_size"} <= set(s)
    assert client.get("/symbols/NSE:NOPE").status_code == 404


def test_indicator_list_contract(client):
    meta = client.get("/indicators").json()
    assert len([m for m in meta if m["category"] != "Custom"]) == 50
    for m in meta:
        assert {"id", "title", "category", "overlay", "outputs", "plots", "params", "levels"} <= set(m)
        assert [p["name"] for p in m["plots"]] == m["outputs"]


def test_drawings_validation_limits(client):
    q = {"symbol": "NSE:TCS"}
    item = {"id": "a", "kind": "trend", "pts": [{"t": 1, "p": 1}, {"t": 2, "p": 2}]}
    assert client.put("/drawings", params=q, json={"items": [item] * 501}).status_code == 422   # max 500
    assert client.put("/drawings", params=q, json={"items": [dict(item, color="red")]}).status_code == 422
    assert client.put("/drawings", params=q, json={"items": [dict(item, width=9)]}).status_code == 422
    assert client.put("/drawings", params={"symbol": "NSE:NOPE"}, json={"items": []}).status_code == 404
    assert client.put("/drawings", params=q, json={"items": []}).status_code == 200


def test_alert_created_like_the_alert_dialog(client):
    """The top-bar Alert dialog posts {symbol, condition{op, price}, once, message}."""
    r = client.post("/alerts", json={"symbol": "NSE:TCS", "condition": {"op": "crosses_above", "price": 99999},
                                     "once": True, "message": "NSE:TCS crosses above 99,999.00"})
    assert r.status_code in (200, 201)
    a = r.json()
    assert a["status"] == "active" and a["condition"]["op"] == "crosses_above"
    assert client.delete(f"/alerts/{a['id']}").status_code in (200, 204)


# ---- live bars for US symbols --------------------------------------------------------------
def test_forming_bars_use_new_york_session_for_us_symbols():
    fb = FormingBars("NASDAQ:AAPL", {}, prev_close=100.0, tfs=("1h", "1D"))
    open_ny = int(datetime(2026, 7, 1, 13, 30, tzinfo=timezone.utc).timestamp())   # 09:30 EDT
    res = fb.apply(open_ny + 600, 101.0, 10)
    assert res.updated["1h"].t == open_ny
    late = fb.apply(int(datetime(2026, 7, 1, 19, 45, tzinfo=timezone.utc).timestamp()), 102.0, 5)  # 01:15 IST next day
    assert late.updated["1D"].t == int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()) - 19800


# ---- public name lists ----------------------------------------------------------------------
class _Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def test_names_fetch_uses_cache_and_survives_failures(tmp_path, monkeypatch):
    calls = []

    def fake(req, timeout=0):
        calls.append(req.full_url)
        if "SME" in req.full_url:
            raise OSError("network down")
        return _Resp(b"x")

    monkeypatch.setattr(names.urllib.request, "urlopen", fake)
    got = names.fetch(tmp_path)
    assert len(calls) == len(names.SOURCES) and "nse_sme.csv" not in got and len(got) == len(names.SOURCES) - 1
    calls.clear()
    names.fetch(tmp_path)                      # cached files are not downloaded again
    assert calls == [names.SOURCES["nse_sme.csv"]]
    names.fetch(tmp_path, force=True)
    assert len(calls) == 1 + len(names.SOURCES)


def test_nse_name_lists_parse(tmp_path):
    (tmp_path / "nse_equity.csv").write_text(
        "SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
        "RELIANCE,Reliance Industries Limited,EQ,29-NOV-1995,10,1,INE002A01018,10\n")
    (tmp_path / "nse_sme.csv").write_text(
        "SYMBOL,NAME_OF_COMPANY,SERIES,DATE_OF_LISTING,PAID_UP_VALUE,ISIN_NUMBER,FACE_VALUE,\n"
        "ABC,Abc Sme Limited,SM,01-Jan-24,10,INE000A01011,10,\n")
    (tmp_path / "nse_etf.csv").write_text(
        "Symbol,Underlying Asset,SecurityName,DateofListing,MarketLot,ISINNumber,FaceValue,ETF Underlying,Key\n"
        "NIFTYBEES,Nifty 50,NIPPON ETF NIFTY BEES,08-Jan-02,1,INF204KB14I2,1,EQUITY,Nifty 50\n")
    n = names.load("NSE", tmp_path, None)
    assert n["RELIANCE"].name == "Reliance Industries Limited" and n["RELIANCE"].isin == "INE002A01018"
    assert n["ABC"].name == "Abc Sme Limited"
    assert n["NIFTYBEES"].type == "ETF" and "Nifty 50" in n["NIFTYBEES"].name
    assert names.load("NSE", None, None) == {}


# ---- admin CLI ---------------------------------------------------------------------------------
@pytest.fixture()
def cli_db(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{(tmp_path / 'cli.db').as_posix()}")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(cli, "SessionLocal", factory)
    monkeypatch.setattr(cli, "init_db", lambda: init_db(engine))
    monkeypatch.setattr(cli, "NAMES_CACHE", tmp_path / "names")
    monkeypatch.setattr(names, "fetch", lambda cache, force=False: [])   # never touch the network in tests
    (tmp_path / "names").mkdir()
    (tmp_path / "names" / "nse_equity.csv").write_text(
        "SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
        "RELIANCE,Reliance Industries Limited,EQ,29-NOV-1995,10,1,INE002A01018,10\n")
    return factory


def _daily(root: Path, ex: str, rows: dict[str, list[str]]):
    d = root / ex / "bhavcopy_adjusted"
    d.mkdir(parents=True)
    for day, rs in rows.items():
        (d / f"{ex}_{day}.csv").write_text("<TICKER>,<PER>,<DTYYYYMMDD>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>\n"
                                           + "\n".join(rs) + "\n")


def test_cli_import_eod_daily_hourly_and_names(tmp_path, cli_db, capsys):
    daily, hourly = tmp_path / "daily", tmp_path / "hourly"
    _daily(daily, "NSE", {"20261120": ["RELIANCE,D,20261120,1400,1410,1390,1405,1000"],
                          "20261123": ["RELIANCE,D,20261123,1405,1420,1400,1415,1100"]})
    _daily(daily, "BSE", {"20261120": ["RELIANCE,D,20261120,1401,1411,1391,1406,500"]})
    (daily / "tickers.csv").write_text("Symbol,Name,Exchange\nRELIANCE,RELIANCE INDUSTRIES LTD. (500325),BSE\n")
    (hourly / "NSE").mkdir(parents=True)
    (hourly / "NSE" / "NSE_20261120_0915.csv").write_text(
        "Symbol,Date,Time,Open,High,Low,Close,Volume\nNSE.RELIANCE,20261120,091500,1400,1405,1395,1402,0\n")
    (hourly / "BSE").mkdir()  # folder without hourly files: skipped, not an error

    cli.main(["import-eod", "--dir", str(daily), "--hourly-dir", str(hourly), "--exchanges", "NSE,BSE"])
    out = capsys.readouterr().out
    assert "NSE: 2 daily bars" in out and "NSE: 1 hourly bars" in out and "BSE: no hourly files" in out
    with cli_db() as s:
        rel = s.scalar(select(Symbol).where(Symbol.exchange == "NSE", Symbol.ticker == "RELIANCE"))
        assert rel.name == "Reliance Industries Limited" and rel.isin == "INE002A01018"
        bse = s.scalar(select(Symbol).where(Symbol.exchange == "BSE", Symbol.ticker == "RELIANCE"))
        assert bse.name.startswith("RELIANCE INDUSTRIES")
        assert s.scalar(select(func.count()).select_from(Candle).where(Candle.tf == "1h")) == 1

    # --only hourly leaves the daily bars alone; update-names rewrites names without touching candles
    cli.main(["import-eod", "--dir", str(daily), "--hourly-dir", str(hourly), "--exchanges", "NSE",
              "--only", "hourly"])
    with cli_db() as s:
        s.execute(Symbol.__table__.update().values(name="x"))
        s.commit()
    from app.config import get_settings
    monkey = pytest.MonkeyPatch()
    monkey.setattr(get_settings(), "eod_dir", str(daily))
    try:
        cli.main(["update-names", "--exchanges", "NSE"])
    finally:
        monkey.undo()
    with cli_db() as s:
        assert s.scalar(select(Symbol.name).where(Symbol.exchange == "NSE")) == "Reliance Industries Limited"
        assert s.scalar(select(func.count()).select_from(Candle).where(Candle.tf == "1D")) == 3


def test_cli_import_eod_requires_folders(cli_db):
    with pytest.raises(SystemExit):
        cli.main(["import-eod", "--dir", "Z:/does/not/exist", "--exchanges", "NSE"])
