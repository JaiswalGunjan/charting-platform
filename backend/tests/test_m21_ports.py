"""The replaceable parts (app/ports.py, app/providers.py): the product works with any adapter that fits the port."""
import pytest

from app import providers
from app.adapters.null import NoSetupScanner
from app.adapters.swingscanner import SwingScanner
from app.config import get_settings
from app.ports import ScannerOffline, ScanRefused, SetupScanner


def row(ticker, setup, rank, score, **kw):
    return dict(symbol=f"NSE:{ticker}", ticker=ticker, setup=setup, setups=[setup], setup_name="Sell-side squeeze",
                pattern="", valid=True, buy=True, status="would buy", close=100.0, entry=100.0, stop=95.0, risk=5.0,
                stop_pct=5.0, score=score, size_mult=1.0, rank=rank, shares=10, value=1000.0, notes="Rule passed S4-R033: ok",
                stop_note="", reject="", weak="", soft="", chart="", chart_href="", date="2026-11-26") | kw


class FakeScanner:
    """Another scanner, in memory: what a replacement for the SwingScanner has to provide."""

    name, title = "fake", "Fake scanner"

    def __init__(self):
        self.runs = []

    def status(self):
        return dict(name=self.name, title=self.title, configured=True, online=True,
                    markets=[dict(market="NSE", ok=True, last="2026-11-26", dates=["2026-11-26"])])

    def scans(self):
        return [dict(id="day-1", market="NSE", date="2026-11-26", valid=2, near=0, regime="bull", symbols=2)]

    def scan(self, scan_id, near=True):
        if scan_id != "day-1":
            return None
        return dict(id="day-1", market="NSE", date="2026-11-26", regime="bull", risk_mult=1.0, rules="x", symbols=2,
                    capital=1e6, risk_pct=1.0, max_alloc_pct=45.0, signals=[row("TCS", "SQZ", 2, 5), row("INFY", "SQZ", 1, 9)],
                    near_misses=[], setups={"SQZ": dict(name="Squeeze", what="Sell into strength", why="")},
                    market_note=None, score_note="Score: the buy score (S7-R001)")

    def setups(self):
        return {"SQZ": dict(name="Squeeze", what="", why="")}

    def explain(self, scan_id, ticker, setup, near=False, equity=None, risk_pct=None):
        return dict(title=f"{ticker} {setup}", sections=[dict(title="Why", lines=["Would buy (S4-R033)"])]) \
            if (scan_id, ticker) == ("day-1", "TCS") else None

    def portfolio(self):
        return dict(source="fake", watchlist=[], trades=[])

    def run(self, market, day=None):
        if day == "2026-11-26":
            raise ScanRefused("already scanned")
        if market == "NYSE":
            raise ScannerOffline("down")
        self.runs.append((market, day))
        return dict(ok=True)

    def job(self, since=0):
        return dict(state="done", log=[])

    def slim(self):
        return 0, 0

    def routers(self):
        return []


@pytest.fixture()
def fake():
    f = FakeScanner()
    providers.use("setup_scanner", f)
    yield f
    providers.use("setup_scanner", None)


def test_built_in_adapters_fit_the_port():
    assert isinstance(SwingScanner(), SetupScanner) and isinstance(NoSetupScanner(), SetupScanner)
    assert isinstance(FakeScanner(), SetupScanner)


def test_another_scanner_plugs_in_without_product_changes(client, fake):
    st = client.get("/scanner").json()
    assert st["title"] == "Fake scanner" and [s["id"] for s in st["scans"]] == ["day-1"]
    d = client.get("/scanner/scans/day-1").json()
    assert [r["ticker"] for r in d["signals"]] == ["INFY", "TCS"]                  # ranked by the product
    assert d["signals"][0]["name"] == "Infosys"                                    # company names from our symbols
    t = d["signals"][0]
    assert t["status"] == "breakout" and t["notes"] == "Rule passed: ok"           # the product's on-screen wording
    assert "sell" not in t["setup_name"].lower()
    assert d["setups"]["SQZ"]["what"] == "Exit into strength" and d["score_note"] == "Score: the entry score"
    assert client.get("/scanner/scans/nope").status_code == 404
    e = client.get("/scanner/scans/day-1/explain", params=dict(symbol="NSE:TCS", setup="SQZ")).json()
    assert e["sections"][0]["lines"] == ["Breakout"]
    assert client.get("/scanner/scans/day-1/explain", params=dict(symbol="X", setup="SQZ")).status_code == 404
    assert client.post("/scanner/run", json={"market": "nse", "date": "2026-11-25"}).json() == {"ok": True}
    assert fake.runs == [("NSE", "2026-11-25")]
    assert client.post("/scanner/run", json={"market": "NSE", "date": "2026-11-26"}).status_code == 409
    assert client.post("/scanner/run", json={"market": "NYSE"}).status_code == 503
    assert client.get("/scanner/portfolio").json()["source"] == "fake"


def test_no_scanner_keeps_the_product_running(client):
    providers.use("setup_scanner", NoSetupScanner())
    try:
        st = client.get("/scanner").json()
        assert st["configured"] is False and st["scans"] == [] and "SETUP_SCANNER" in st["msg"]
        assert client.get("/scanner/scans/x").status_code == 404
        assert client.post("/scanner/run", json={}).status_code == 503
    finally:
        providers.use("setup_scanner", None)


def test_a_setting_chooses_the_adapter_by_name_or_import_path(monkeypatch):
    providers.reset()
    monkeypatch.setattr(get_settings(), "setup_scanner", "none")
    assert isinstance(providers.setup_scanner(), NoSetupScanner)
    monkeypatch.setattr(get_settings(), "setup_scanner", "tests.test_m21_ports:FakeScanner")   # any class by path
    assert providers.setup_scanner().title == "Fake scanner"
    assert providers.setup_scanner() is providers.setup_scanner()                    # made once per setting
    monkeypatch.setattr(get_settings(), "setup_scanner", "nonsense")
    with pytest.raises(providers.ProviderError, match="swingscanner"):
        providers.setup_scanner()
    monkeypatch.setattr(get_settings(), "setup_scanner", "no.such.module:X")
    with pytest.raises(providers.ProviderError, match="cannot be loaded"):
        providers.setup_scanner()
    providers.reset()


# ------------------------------------------------------------------------------- pattern engine and screen store
class FakePatterns:
    """Another pattern engine: marks every bar that closes above the one before (an "up day")."""

    name, warmup = "fake", 1

    def catalog(self):
        return [dict(id="up", title="Up day", group="Test", short="U", color="#0f0", rule="", about="Buy the up day",
                     summary="")]

    def ids(self):
        return {"up"}

    def signal_ids(self):
        return {"up"}

    def scan(self, t, o, h, l, c, v, ids, first=0):  # noqa: E741
        markers = [dict(pattern="up", t=int(t[i]), text="U", notes=["closed higher"], rules=[], price=float(c[i]))
                   for i in range(max(1, first), len(t)) if "up" in ids and c[i] > c[i - 1]]
        return dict(markers=markers, shapes=[], levels=[])


class MemoryScreens:
    """Another screen store: in memory."""

    name = "memory"

    def __init__(self):
        self.saved, self.newest = {}, {}

    def read(self, exchange, tf, day=None):
        return self.newest.get((exchange.upper(), tf)) if not day else self.saved.get((exchange.upper(), tf, day))

    def dates(self, exchange, tf):
        return sorted((d for (e, t, d) in self.saved if (e, t) == (exchange.upper(), tf)), reverse=True)

    def write(self, res, newest):
        self.saved[(res["exchange"], res["tf"], res["session"])] = res
        if newest:
            self.newest[(res["exchange"], res["tf"])] = res
        return res


@pytest.fixture()
def fake_patterns():
    providers.use("pattern_engine", FakePatterns())
    providers.use("screen_store", store := MemoryScreens())
    yield store
    providers.use("pattern_engine", None)
    providers.use("screen_store", None)


def test_built_in_pattern_parts_fit_their_ports():
    from app.patterns.engine import RulebookPatterns
    from app.patterns.store import JsonScreenStore
    from app.ports import PatternEngine, ScreenStore

    assert isinstance(RulebookPatterns(), PatternEngine) and isinstance(FakePatterns(), PatternEngine)
    assert isinstance(JsonScreenStore(), ScreenStore) and isinstance(MemoryScreens(), ScreenStore)


def test_another_pattern_engine_and_screen_store_plug_in(client, fake_patterns, session_factory, monkeypatch):
    from app.patterns import screener as sc

    menu = client.get("/patterns").json()
    assert [p["id"] for p in menu] == ["up"] and menu[0]["about"] == "Entry the up day"     # product wording applies
    r = client.get("/patterns/scan", params=dict(symbol="NSE:TCS", tf="1D", ids="up", limit=50)).json()
    assert r["markers"] and {m["pattern"] for m in r["markers"]} == {"up"}
    assert client.get("/patterns/scan", params=dict(symbol="NSE:TCS", ids="pp")).status_code == 400   # not its pattern
    assert client.get("/patterns/counts", params=dict(symbol="NSE:TCS")).json()["counts"]["up"] > 0
    # the Pattern Screener: screened with the fake engine, kept in the memory store, read back through the API
    monkeypatch.setattr(sc, "MIN_BARS", 30)
    res = sc.run_screen(session_factory, "NSE", "1D")
    assert res["rows"] and all(r["patterns"] == ["up"] for r in res["rows"])
    assert fake_patterns.dates("NSE", "1D") == [res["session"]]
    got = client.get("/screener/patterns-today", params=dict(exchange="NSE", tf="1D")).json()
    assert got["missing"] is False and got["session"] == res["session"] and got["dates"] == [res["session"]]
    assert client.post("/screener/patterns-today/run", json=dict(exchange="NSE", tf="1D")).status_code == 409


# ------------------------------------------------------------------------------------------------- bar store
class MemoryBarStore:
    """Another bar store: plain dicts, no database. Exchange lookups use the symbol list it is given."""

    name = "memory"
    OHLCV = ("ts", "o", "h", "l", "c", "v")

    def __init__(self, exchange_of: dict[int, str]):
        self.bars: dict[tuple[int, str], dict[int, tuple]] = {}
        self.exchange_of = exchange_of

    def _rows(self, sid, tf, cols, lo=-2**62, hi=2**62):
        import numpy as np

        got = sorted((t, b) for t, b in self.bars.get((sid, tf), {}).items() if lo <= t <= hi)
        pick = {"ts": 0, "o": 1, "h": 2, "l": 3, "c": 4, "v": 5}
        return np.array([[(t, *b)[pick[k]] for k in cols] for t, b in got], dtype=float).reshape(-1, len(cols))

    def has(self, session, symbol_id, tf):
        return bool(self.bars.get((symbol_id, tf)))

    def read_latest(self, session, symbol_id, tf, limit, to=None, frm=None, cols=OHLCV):
        r = self._rows(symbol_id, tf, cols, frm if frm is not None else -2**62, (to - 1) if to is not None else 2**62)
        return r[-limit:]

    def read_after(self, session, symbol_id, tf, frm, limit, cols=OHLCV):
        return self._rows(symbol_id, tf, cols, frm)[:limit]

    def upsert(self, session, symbol_id, tf, bars):
        d = self.bars.setdefault((symbol_id, tf), {})
        for b in bars:
            d[b.ts] = (b.o, b.h, b.l, b.c, b.v)
        return len(bars)

    def read_many(self, session, symbol_ids, tf, since, until, cols=OHLCV):
        import numpy as np

        parts = [np.c_[np.full(len(r), sid), r] for sid in sorted(symbol_ids)
                 if len(r := self._rows(sid, tf, cols, since, until))]
        return np.vstack(parts) if parts else np.empty((0, len(cols) + 1))

    def _times(self, exchange, tf):
        return {t for (sid, f), d in self.bars.items() if f == tf and self.exchange_of.get(sid) == exchange.upper()
                for t in d}

    def last_time(self, session, exchange, tf, upto=None):
        ts = [t for t in self._times(exchange, tf) if upto is None or t <= upto]
        return max(ts) if ts else None

    def times(self, session, exchange, tf, since):
        return sorted(t for t in self._times(exchange, tf) if t >= since)

    def delete_bars(self, session, exchange, tfs, since=None, until=None):
        lo, hi = since if since is not None else -2**62, until if until is not None else 2**62
        for (sid, tf), d in self.bars.items():
            if tf in tfs and self.exchange_of.get(sid) == exchange.upper():
                for t in [t for t in d if lo <= t <= hi]:
                    del d[t]

    def append(self, session, tf, symbol_ids, data):
        for i, sid in enumerate(symbol_ids):
            self.bars.setdefault((int(sid), tf), {})[int(data["ts"][i])] = tuple(float(data[k][i]) for k in "ohlcv")
        return len(symbol_ids)

    def replace_exchange(self, session, exchange, drop_tfs, tf, symbol_ids, data):
        self.delete_bars(session, exchange, drop_tfs)
        return self.append(session, tf, symbol_ids, data)


def test_another_bar_store_serves_the_same_charts_and_screens(client, session_factory, monkeypatch):
    from sqlalchemy import select

    from app.marketdata.loader import load_history, resolve_symbol
    from app.marketdata.synthetic import SyntheticSource
    from app.models import Symbol
    from app.patterns import screener as sc
    from app.ports import BarStore
    from tests.conftest import DAILY_START, END, MINUTE_START

    sql = {tf: client.get("/history", params=dict(symbol="NSE:TCS", tf=tf, limit=300)).json() for tf in ("1D", "1W", "15m")}
    monkeypatch.setattr(sc, "MIN_BARS", 30)
    sql_screen = sc.run_screen(session_factory, "NSE", "1D")
    with session_factory() as s:
        mem = MemoryBarStore(dict(s.execute(select(Symbol.id, Symbol.exchange)).all()))
        assert isinstance(mem, BarStore)
        providers.use("bar_store", mem)
        try:
            src = SyntheticSource()
            for name in ("NSE:RELIANCE", "NSE:TCS"):          # the same bars, loaded into the other store
                sym = resolve_symbol(s, name)
                load_history(s, src, sym, "1m", MINUTE_START, END)
                load_history(s, src, sym, "1D", DAILY_START, END)
            for tf, want in sql.items():                       # the chart's history is the same, from either store
                got = client.get("/history", params=dict(symbol="NSE:TCS", tf=tf, limit=300)).json()
                assert got["t"] == want["t"] and got["c"] == want["c"], tf
            mem_screen = sc.run_screen(session_factory, "NSE", "1D")
            assert [(r["ticker"], r["patterns"]) for r in mem_screen["rows"]] == \
                [(r["ticker"], r["patterns"]) for r in sql_screen["rows"]]
            assert sc.resolve_session(session_factory, "NSE") == sql_screen["session"]
        finally:
            providers.use("bar_store", None)


def test_sql_bar_store_fits_the_port():
    from app.marketdata.barstore import SqlBarStore
    from app.ports import BarStore

    assert isinstance(SqlBarStore(), BarStore)


def test_several_setup_scanners_side_by_side(client):
    """Two scanners at once: each with its own scans; every endpoint picks one by name, the first is the default."""
    a, b = FakeScanner(), FakeScanner()
    b.name, b.title = "other", "Other scanner"
    b.scans = lambda: [dict(id="o-1", market="NYSE", date="2026-11-25", valid=0, near=0, regime=None, symbols=1)]
    providers.use("setup_scanners", {a.name: a, b.name: b})
    try:
        st = client.get("/scanner").json()
        assert st["title"] == "Fake scanner" and [s["id"] for s in st["scans"]] == ["day-1"]
        assert st["scanners"] == [dict(name="fake", title="Fake scanner"), dict(name="other", title="Other scanner")]
        assert [s["id"] for s in client.get("/scanner", params=dict(scanner="other")).json()["scans"]] == ["o-1"]
        assert client.get("/scanner/scans/day-1", params=dict(scanner="fake")).json()["scanner"] == "fake"
        assert client.get("/scanner", params=dict(scanner="nope")).status_code == 404
        assert client.post("/scanner/run", json=dict(market="NSE", date="2026-11-20", scanner="other")).json()["ok"]
        assert b.runs == [("NSE", "2026-11-20")] and a.runs == []
    finally:
        providers.use("setup_scanners", None)


def test_setup_scanners_setting_lists_several(monkeypatch):
    providers.reset()
    monkeypatch.setattr(get_settings(), "setup_scanners", "swingscanner, none")
    got = providers.setup_scanners()
    assert list(got) == ["swingscanner", "none"] and providers.setup_scanner() is got["swingscanner"]
    assert providers.setup_scanner("none").title == "No setup scanner"
    monkeypatch.setattr(get_settings(), "setup_scanners", "none,none")
    with pytest.raises(providers.ProviderError, match="two setup scanners"):
        providers.setup_scanners()
    providers.reset()


def test_several_pattern_engines_as_one(client, monkeypatch):
    """PATTERN_ENGINES=rulebook,<another>: one menu, marks from both, the screener looks for both."""
    from app.patterns.combined import CombinedPatterns, PatternIdClash
    from app.patterns.engine import RulebookPatterns
    from app.ports import PatternEngine

    providers.reset()
    monkeypatch.setattr(get_settings(), "pattern_engines", "rulebook, tests.test_m21_ports:FakePatterns")
    try:
        eng = providers.pattern_engine()
        assert isinstance(eng, CombinedPatterns) and isinstance(eng, PatternEngine)
        assert eng.warmup == RulebookPatterns.warmup and {"up", "pp", "sr"} <= eng.ids()
        assert "up" in eng.signal_ids() and "sr" not in eng.signal_ids()
        menu = {p["id"]: p for p in client.get("/patterns").json()}
        assert menu["up"]["engine"] == "fake" and menu["pp"]["engine"] == "rulebook"
        r = client.get("/patterns/scan", params=dict(symbol="NSE:TCS", ids="up,pp,bbr", limit=400)).json()
        got = {m["pattern"] for m in r["markers"]}
        assert "up" in got and got & {"pp", "bbr"}                                  # marks from both engines
        assert [m["t"] for m in r["markers"]] == sorted(m["t"] for m in r["markers"])
        counts = client.get("/patterns/counts", params=dict(symbol="NSE:TCS")).json()["counts"]
        assert counts["up"] > 0 and "pp" in counts
    finally:
        providers.reset()
    with pytest.raises(PatternIdClash, match="'up'"):
        CombinedPatterns([FakePatterns(), FakePatterns()])                          # an id means one pattern


# ------------------------------------------------------------------------------------------------ market registry
def test_a_new_market_is_one_entry_in_the_registry(client, tmp_path, monkeypatch):
    """A market added to the registry file: its own session anchor, currency and place in lists, no code change."""
    from app import markets as reg
    from app.marketdata.base import parse_symbol
    from app.marketdata.timeframes import TIMEFRAMES, Market, bucket_starts, market_for

    f = tmp_path / "markets.toml"
    f.write_text(reg.DEFAULT_FILE.read_text(encoding="utf-8") + '''
[LSE]
title = "London Stock Exchange"
country = "GB"
timezone = "Europe/London"
tz_label = "London"
open = "08:00"
close = "16:30"
currency = "GBP"
''')
    monkeypatch.setattr(get_settings(), "markets_file", str(f))
    got = {m["code"]: m for m in client.get("/markets").json()}
    assert list(got)[:4] == ["NSE", "BSE", "NYSE", "NASDAQ"] and got["LSE"]["currency"] == "GBP"
    assert got["LSE"]["open_minute"] == 480 and got["NSE"]["open_minute"] == 555
    assert market_for("LSE") == Market("Europe/London", 480)
    # 1h bars anchored at 08:00 London: 07:00 UTC in summer (BST), 08:00 UTC in winter
    import datetime as dt
    summer = int(dt.datetime(2026, 7, 1, 7, 30, tzinfo=dt.timezone.utc).timestamp())
    winter = int(dt.datetime(2026, 1, 5, 8, 30, tzinfo=dt.timezone.utc).timestamp())
    starts = bucket_starts(TIMEFRAMES["1h"], [summer, winter], market_for("LSE"))
    assert [dt.datetime.fromtimestamp(int(s), dt.timezone.utc).hour for s in starts] == [7, 8]
    assert parse_symbol("RELIANCE") == ("NSE", "RELIANCE")                     # the first market is the default
    assert reg.rank("LSE") == 4 and reg.rank("XYZ") == 5


def test_minute_bars_in_their_own_store(client, session_factory, monkeypatch):
    """BAR_STORES=1m=<another store>: minute bars (years of them, many markets) live in a store of their own, daily
    bars stay in SQL; charts of every timeframe read from the right one, and a range can be re-imported."""
    import numpy as np
    from sqlalchemy import select

    from app.marketdata.barstore import RoutedBarStore, SqlBarStore
    from app.marketdata.loader import load_history, resolve_symbol
    from app.marketdata.synthetic import SyntheticSource
    from app.models import Symbol
    from app.ports import BarStore
    from tests.conftest import END, MINUTE_START

    want = {tf: client.get("/history", params=dict(symbol="NSE:TCS", tf=tf, limit=200)).json() for tf in ("15m", "1D")}
    with session_factory() as s:
        mem = MemoryBarStore(dict(s.execute(select(Symbol.id, Symbol.exchange)).all()))
        routed = RoutedBarStore(SqlBarStore(), {"1m": mem})
        assert isinstance(routed, BarStore)
        providers.use("bar_store", routed)
        try:
            tcs = resolve_symbol(s, "NSE:TCS")
            load_history(s, SyntheticSource(), tcs, "1m", MINUTE_START, END)   # minute bars: into the memory store
            assert mem.has(s, tcs.id, "1m") and not mem.has(s, tcs.id, "1D")
            for tf, w in want.items():                                          # 15m from memory, 1D from SQL
                got = client.get("/history", params=dict(symbol="NSE:TCS", tf=tf, limit=200)).json()
                assert got["t"] == w["t"] and got["c"] == w["c"], tf
            # re-import one day: drop its range, append it again (the chunked import path)
            day = mem.read_latest(s, tcs.id, "1m", 375)
            lo, hi = int(day[0, 0]), int(day[-1, 0])
            routed.delete_bars(s, "NSE", ["1m"], lo, hi)
            assert len(mem.read_latest(s, tcs.id, "1m", 10_000, frm=lo)) == 0
            cols = dict(zip(("ts", "o", "h", "l", "c", "v"), day.T))
            routed.append(s, "1m", np.full(len(day), tcs.id), cols)
            got = client.get("/history", params=dict(symbol="NSE:TCS", tf="15m", limit=200)).json()
            assert got["t"] == want["15m"]["t"] and got["c"] == want["15m"]["c"]
        finally:
            providers.use("bar_store", None)


def test_bar_stores_setting_routes_timeframes(monkeypatch):
    from app.marketdata.barstore import RoutedBarStore, SqlBarStore

    providers.reset()
    monkeypatch.setattr(get_settings(), "bar_stores", "1m=sql")
    st = providers.bar_store()
    assert isinstance(st, RoutedBarStore) and isinstance(st.store_for("1m"), SqlBarStore)
    assert st.store_for("1D") is st.default
    monkeypatch.setattr(get_settings(), "bar_stores", "1m")
    with pytest.raises(providers.ProviderError, match="timeframe=store"):
        providers.bar_store()
    providers.reset()
