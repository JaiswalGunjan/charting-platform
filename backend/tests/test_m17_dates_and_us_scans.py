"""Past sessions in both scanners, and US scans:
- Setup Scanner: a US market whose per-symbol folder holds only stub files is flagged, and the scanner's bare
  'no symbol produced bars' error gets a plain explanation; NYSE / NASDAQ scans are listed like NSE ones.
- Pattern Screener: a screen for a past session, saved per date; the newest stays the default; dates are listed."""
import json
from datetime import date, timedelta

from app.api import scanner
from app.patterns import screener as sc
from tests.test_m14_scanner import HEADER, row, scan_root  # noqa: F401  (fixture)
from tests.test_m15b_screener_edges import DAY, LAST, db, fake_hits  # noqa: F401  (fixture)

# ---------------------------------------------------------------- Setup Scanner: US data and US scans


def us_data(root, stub=True):
    """The scanner's ini naming per-symbol folders for NYSE (stubs or full files) and NASDAQ (full files)."""
    nyse, nasdaq = root / "NYSE_alpaca", root / "NASDAQ_alpaca"
    for d, small in ((nyse, stub), (nasdaq, False)):
        d.mkdir()
        for k in range(5):
            (d / f"{d.name[:-7]}.SYM{k}.csv").write_text("Date,Open,High,Low,Close,Volume\n" +
                                                        "2026-11-17,1,1,1,1,1\n" * (5 if small else 2000))
    (root / "swingbt_config.ini").write_text(
        f"[data]\nnyse_symbols = {nyse}\nnasdaq_symbols = {nasdaq}\n[app]\nscans = .\\my_scans\nport = 8765\n")
    return nyse


def online(monkeypatch, job=None):
    markets = [dict(market=m, ok=True, last="2026-11-23", dates=["2026-11-23", "2026-11-20"])
               for m in ("NSE", "NYSE", "NASDAQ")]

    def fake(path, body=None, timeout=2.0):
        if path.startswith("/api/launcher/settings"):
            return dict(markets=markets)
        if path.startswith("/api/launcher/job"):
            return job
        return {"ok": True}

    monkeypatch.setattr(scanner, "_server", fake)


def test_stub_us_data_is_flagged(client, scan_root, monkeypatch):  # noqa: F811
    root, _ = scan_root
    nyse = us_data(root)
    online(monkeypatch)
    by = {m["market"]: m for m in client.get("/scanner").json()["markets"]}
    assert by["NSE"]["warning"] is None and by["NASDAQ"]["warning"] is None      # full history: no warning
    w = by["NYSE"]["warning"]
    assert w.startswith("NYSE:") and str(nyse) in w and "no symbol produced bars" in w


def test_full_us_data_is_not_flagged(scan_root):  # noqa: F811
    root, _ = scan_root
    us_data(root, stub=False)
    assert scanner.data_warnings(root) == {}
    (root / "swingbt_config.ini").write_text("[data]\nnyse_symbols = \nnasdaq_symbols = missing\n")
    assert scanner.data_warnings(root) == {}                                     # blank or missing folder: no check


def test_no_bars_error_gets_a_plain_explanation(client, scan_root, monkeypatch):  # noqa: F811
    root, _ = scan_root
    nyse = us_data(root)
    log = ["> python --run-module swingbt.scan --market NYSE --date 2026-11-23 --offline",
           "08:47:33 [+8s] scan NYSE: 116/116 chunks | 8s | ETA 0s", "no symbol produced bars"]
    online(monkeypatch, dict(state="error", market="NYSE", date="2026-11-23", ok=False, log=log, next=3))
    j = client.get("/scanner/job").json()
    assert j["state"] == "error" and str(nyse) in j["hint"] and "nyse_symbols" in j["hint"]
    assert "Rebuild the scanner bundle" in j["hint"]
    # other errors are passed through as they are
    online(monkeypatch, dict(state="error", market="NSE", date="2026-11-23", ok=False, log=["disk full"], next=1))
    assert "hint" not in client.get("/scanner/job").json()


def test_run_passes_the_chosen_date(client, scan_root, monkeypatch):  # noqa: F811
    sent = []
    online(monkeypatch)
    real = scanner._server
    monkeypatch.setattr(scanner, "_server", lambda p, b=None, timeout=2.0: sent.append((p, b)) or real(p, b, timeout))
    assert client.post("/scanner/run", json=dict(market="NASDAQ", date="2026-11-20")).status_code == 200
    assert ("/api/launcher/scan", dict(market="NASDAQ", date="2026-11-20")) in sent
    assert client.post("/scanner/run", json=dict(market="NYSE")).status_code == 200      # default: the latest
    assert ("/api/launcher/scan", dict(market="NYSE", date="2026-11-23")) in sent


def test_us_scans_are_listed_and_read(client, scan_root):  # noqa: F811
    root, _ = scan_root
    for m in ("NYSE", "NASDAQ"):
        d = root / "my_scans" / f"{m}_daily_2026-11-20"
        d.mkdir()
        (d / "signals.csv").write_text(HEADER + row("AAPL", "PP", 1, 7.5))
        (d / "market.json").write_text(json.dumps({"valid_today": 1, "market_row": {"regime": "bull", "risk_mult": 1}}))
    scans = client.get("/scanner").json()["scans"]
    assert {"NYSE_daily_2026-11-20", "NASDAQ_daily_2026-11-20", "NYSE_daily_2026-11-17"} <= {s["id"] for s in scans}
    d = client.get("/scanner/scans/NASDAQ_daily_2026-11-20").json()
    assert d["market"] == "NASDAQ" and d["signals"][0]["symbol"] == "NASDAQ:AAPL"
    e = client.get("/scanner/scans/NASDAQ_daily_2026-11-20/explain", params=dict(symbol="AAPL", setup="PP")).json()
    assert "$" in " ".join(e["sections"][2]["lines"])                            # US prices in dollars


# ---------------------------------------------------------------- Pattern Screener: past sessions


def iso(ts):
    return sc.session_date(ts)


def test_screen_of_a_past_session(db, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(sc, "latest_hits", fake_hits)
    root = tmp_path / "screens"
    newest = sc.run_screen(db, "NSE", "1D", root=root)
    past = sc.run_screen(db, "NSE", "1D", root=root, day=iso(LAST - 2 * DAY))
    assert newest["session"] == iso(LAST) and past["session"] == iso(LAST - 2 * DAY)
    assert past["as_of"] == past["last_session"] == LAST - 2 * DAY
    # the newest file still holds the newest screen; the past one has its own file
    assert sc.load_screen("NSE", "1D", root)["session"] == iso(LAST)
    assert sc.load_screen("NSE", "1D", root, day=iso(LAST - 2 * DAY))["session"] == iso(LAST - 2 * DAY)
    assert sc.screen_dates("NSE", "1D", root) == [iso(LAST), iso(LAST - 2 * DAY)]
    assert sc.load_screen("NSE", "1D", root, day="2001-01-01") is None
    # STALE stopped 3 days before LAST: on that session it was still trading, so it is screened
    assert "STALE" in {r["ticker"] for r in sc.run_screen(db, "NSE", "1D", root=root, day=iso(LAST - 3 * DAY))["rows"]}


def test_past_screen_uses_only_bars_up_to_that_session(db, monkeypatch, tmp_path):  # noqa: F811
    seen = {}
    monkeypatch.setattr(sc, "latest_hits", lambda t, o, h, l, c, v: seen.setdefault("t", int(t[-1])) and [])  # noqa: E741
    sc.run_screen(db, "NSE", "1D", root=tmp_path, day=iso(LAST - 5 * DAY))
    assert seen["t"] == LAST - 5 * DAY


def test_a_non_trading_day_means_the_session_before(db, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(sc, "latest_hits", fake_hits)
    r = sc.run_screen(db, "NSE", "1D", root=tmp_path, day=iso(LAST + 10 * DAY))     # after the data: the latest
    assert r["session"] == iso(LAST)


def test_backfill_session_lists(db):  # noqa: F811
    today = iso(LAST + DAY)
    daily = sc.backfill_days(db, "NSE", "1D", 10, today)
    assert daily[0] == iso(LAST) and len(daily) == 10 and daily == sorted(daily, reverse=True)
    weekly = sc.backfill_days(db, "NSE", "1W", 30, today)
    weeks = [date.fromisoformat(d).isocalendar()[:2] for d in weekly]       # ISO weeks (Monday to Sunday)
    assert weekly[0] == iso(LAST) and len(set(weeks)) == len(weeks)            # one session per week
    assert all(d in sc.sessions(db, "NSE", "2000-01-01") for d in weekly)


def test_api_dates_and_past_screens(client, monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "SCREEN_DIR", tmp_path)
    for day, n in (("2026-11-23", 3), ("2026-11-20", 1)):
        res = dict(exchange="NSE", tf="1D", as_of=sc.session_ts(day), last_session=sc.session_ts(day), session=day,
                   rows=[dict(ticker=f"S{k}") for k in range(n)], scanned=10)
        (tmp_path / f"NSE_1D_{day}.json").write_text(json.dumps(res))
        if day == "2026-11-23":
            (tmp_path / "NSE_1D.json").write_text(json.dumps(res))
    r = client.get("/screener/patterns-today", params=dict(exchange="NSE", tf="1D")).json()
    assert r["session"] == "2026-11-23" and len(r["rows"]) == 3 and r["dates"] == ["2026-11-23", "2026-11-20"]
    r = client.get("/screener/patterns-today", params=dict(exchange="NSE", tf="1D", date="2026-11-20")).json()
    assert r["session"] == "2026-11-20" and len(r["rows"]) == 1 and r["missing"] is False
    r = client.get("/screener/patterns-today", params=dict(exchange="NSE", tf="1D", date="2026-11-19")).json()
    assert r["missing"] is True and r["dates"] == ["2026-11-23", "2026-11-20"]
    assert client.get("/screener/patterns-today", params=dict(date="23-11-2026")).status_code == 422
    assert client.post("/screener/patterns-today/run", json=dict(date="yesterday")).status_code == 422
    # a screen saved before dated files existed still counts as its session
    (tmp_path / "NSE_1D_2026-11-23.json").unlink()
    assert client.get("/screener/patterns-today", params=dict(date="2026-11-23")).json()["missing"] is False


def test_a_date_without_its_own_screen_gets_the_session_before(client, monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "SCREEN_DIR", tmp_path)
    for tf, day in (("1D", "2026-11-20"), ("1D", "2026-11-13"), ("1W", "2026-11-20")):  # Fridays
        (tmp_path / f"NSE_{tf}_{day}.json").write_text(json.dumps(dict(session=day, rows=[], scanned=1)))
    get = lambda tf, d: client.get("/screener/patterns-today", params=dict(tf=tf, date=d)).json()  # noqa: E731
    assert get("1D", "2026-11-22")["session"] == "2026-11-20"              # Sunday -> Friday
    assert get("1D", "2026-11-19")["missing"] is True                      # a weekday without a screen stays missing
    assert get("1D", "2026-11-12")["missing"] is True                      # nothing saved on or within 4 days before
    assert get("1W", "2026-11-18")["missing"] is True                      # Wednesday, but the week's screen is Friday's
    assert get("1W", "2026-11-22")["session"] == "2026-11-20"              # Sunday of that week
    assert get("1W", "2026-11-25")["missing"] is True                      # next week: not screened


def test_a_saved_screen_is_not_screened_again(client, monkeypatch, tmp_path):
    from app.api import screener as api_sc
    monkeypatch.setattr(sc, "SCREEN_DIR", tmp_path)
    latest = client.get("/screener/patterns-today", params=dict(exchange="NSE", tf="1D")).json()["latest_session"]
    assert latest                                                      # the newest session with data
    (tmp_path / f"NSE_1D_{latest}.json").write_text(json.dumps(dict(session=latest, rows=[], scanned=1)))
    for body in (dict(exchange="NSE", tf="1D"), dict(exchange="NSE", tf="1D", date=latest)):
        r = client.post("/screener/patterns-today/run", json=body)
        assert r.status_code == 409 and f"already screened for {latest}" in r.json()["detail"]
    assert api_sc._JOB.state != "running"                             # nothing started
    # a later date (a weekend, a holiday, no data yet) resolves to the last session: refused as well
    later = (date.fromisoformat(latest) + timedelta(days=2)).isoformat()
    assert client.post("/screener/patterns-today/run", json=dict(exchange="NSE", tf="1D", date=later)).status_code == 409


def test_a_saved_scan_is_not_run_again(client, scan_root, monkeypatch):  # noqa: F811
    sent = []
    online(monkeypatch)
    real = scanner._server
    monkeypatch.setattr(scanner, "_server", lambda p, b=None, timeout=2.0: sent.append((p, b)) or real(p, b, timeout))
    r = client.post("/scanner/run", json=dict(market="NSE", date="2026-11-23"))     # saved in the fixture
    assert r.status_code == 409 and "already scanned" in r.json()["detail"]
    assert not any(p == "/api/launcher/scan" for p, _ in sent)
    assert client.post("/scanner/run", json=dict(market="NSE", date="2026-11-20")).status_code == 200


def test_a_replaced_newest_screen_keeps_its_dated_file(db, monkeypatch, tmp_path):  # noqa: F811
    """A screen saved before dated files existed lives only in EX_TF.json; a newer screen must not wipe it."""
    monkeypatch.setattr(sc, "latest_hits", fake_hits)
    old = dict(exchange="NSE", tf="1D", as_of=LAST - 2 * DAY, last_session=LAST - 2 * DAY, rows=[], scanned=7)
    (tmp_path / "NSE_1D.json").write_text(json.dumps(old))                     # legacy: no dated file, no "session"
    sc.run_screen(db, "NSE", "1D", root=tmp_path)                              # the newest session replaces it
    assert sc.load_screen("NSE", "1D", tmp_path)["session"] == sc.session_date(LAST)
    kept = sc.saved_screen("NSE", "1D", sc.session_date(LAST - 2 * DAY), tmp_path)
    assert kept and kept["scanned"] == 7                                       # still there, under its date
    assert sc.screen_dates("NSE", "1D", tmp_path)[:2] == [sc.session_date(LAST), sc.session_date(LAST - 2 * DAY)]
