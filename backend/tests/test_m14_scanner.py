"""Connection to the owner's SwingScanner: reading its saved scans and portfolio, and driving a running scanner.
Uses a fake scanner folder and a stubbed scanner server; the real scanner is never contacted."""
import json

import pytest

from app.adapters.swingscanner import core as scanner
from app.config import get_settings

HEADER = ("date,symbol,setup,valid,close,stop,stop_pct,stop_note,score,size_mult,stage,phase,ext,base_len,ipo,in_zone,"
          "rs60,dist_10d_high_pct,atr_state,rules_ok,reject,weak,notes,soft,res_touches,stop_rule,stop_bar,stop_raw,"
          "also,rule_stop,rule_stop_pct,skip,rank,status,shares,value,chart,geom,snap\n")


def row(sym, setup, rank, score, status="would buy", valid="True", reject=""):
    return (f'2026-11-23,{sym},{setup},{valid},919.5,891.91,3.0,below the low,{score},1.0,2,base,1,6,False,True,14.0,'
            f'0.87,none,"S4-R033",{reject},,"Bad break recovery: reclaimed the SMA50",,3,SL_MACDH,2026-11-23,905.1,'
            f'PP,904.0,1.68,,{rank},{status},181,166430,charts/{sym}_{setup}_2026-11-23.html,"{{}}","{{}}"\n')


@pytest.fixture()
def scan_root(tmp_path, monkeypatch):
    root = tmp_path / "SwingScanner"
    scans = root / "my_scans"
    day = scans / "NSE_daily_2026-11-23"
    day.mkdir(parents=True)
    (root / "swingbt_config.ini").write_text("[app]\nscans = .\\my_scans\nport = 8765\n")
    (day / "signals.csv").write_text(HEADER + row("DCBBANK", "BBR", 3, 8.3) + row("MARICO", "BBR", 1, 9.7)
                                     + row("ABC", "WEIRD", "", 5.0, status="skipped"))
    (day / "near_misses.csv").write_text(HEADER + row("PRESTIGE", "VCP", "", 9.6, "", "False", "S8-R003: no ATR"))
    (day / "market.json").write_text(json.dumps({"valid_today": 3, "near_today": 1, "symbols": 3105, "rules": "optimized",
                                                 "market_row": {"regime": "weak_bear", "risk_mult": 0.5}}))
    (scans / "NYSE_daily_2026-11-17").mkdir()
    (scans / "NYSE_daily_2026-11-17" / "signals.csv").write_text(HEADER)
    (scans / "_lib").mkdir()                                   # not a scan
    (scans / "portfolio.json").write_text(json.dumps({"watchlist": [{"symbol": "MARICO"}], "trades": []}))
    s = get_settings()
    monkeypatch.setattr(s, "scanner_dir", str(root))
    monkeypatch.setattr(s, "scanner_url", "http://127.0.0.1:9")
    calls = []
    monkeypatch.setattr(scanner, "_server", lambda path, body=None, timeout=2.0: calls.append((path, body)) or None)
    return root, calls


def test_not_configured(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "scanner_dir", "")
    r = client.get("/scanner").json()
    assert r["configured"] is False and r["scans"] == [] and "SCANNER_DIR" in r["msg"]


def test_saved_scans_listed_newest_first(client, scan_root):
    r = client.get("/scanner").json()
    assert r["configured"] and r["online"] is False
    assert [s["id"] for s in r["scans"]] == ["NSE_daily_2026-11-23", "NYSE_daily_2026-11-17"]
    assert r["scans"][0]["regime"] == "weak_bear" and r["scans"][0]["valid"] == 3


def test_scan_detail_ranks_signals_and_maps_setups_to_patterns(client, scan_root):
    d = client.get("/scanner/scans/NSE_daily_2026-11-23").json()
    assert d["regime"] == "weak_bear" and d["risk_mult"] == 0.5
    assert [r["ticker"] for r in d["signals"]] == ["MARICO", "DCBBANK", "ABC"]     # by rank, unranked last
    top = d["signals"][0]
    assert top["symbol"] == "NSE:MARICO" and top["pattern"] == "bbr" and top["valid"] is True
    assert top["stop"] == 891.91 and top["stop_pct"] == 3 and top["status"] == "breakout" and top["rank"] == 1   # "would buy" on screen as "breakout"
    assert top["chart_href"].endswith("/NSE_daily_2026-11-23/charts/MARICO_BBR_2026-11-23.html")
    assert d["signals"][2]["pattern"] == ""                                           # unknown setup: no pattern
    assert top["entry"] == 919.5 and top["risk"] == pytest.approx(27.59) and top["buy"] is True
    assert top["setup_name"] == "Bad break recovery" and d["signals"][2]["buy"] is False   # status "skipped"
    assert set(d["setups"]) == {"BBR", "WEIRD", "VCP"} and d["setups"]["VCP"]["name"] == "Volatility contraction pattern"
    nm = d["near_misses"][0]
    assert nm["valid"] is False and nm["pattern"] == "vcp" and nm["reject"] == "no ATR"   # no rulebook code
    assert client.get("/scanner/scans/NSE_daily_2026-11-23", params={"near": False}).json()["near_misses"] == []


@pytest.mark.parametrize("bad", ["../../etc", "NSE_daily_2026-13-99x", "_lib", "NSE_daily_2026-01-01"])
def test_scan_ids_are_validated(client, scan_root, bad):
    assert client.get(f"/scanner/scans/{bad}").status_code == 404


def test_portfolio_falls_back_to_file(client, scan_root):
    p = client.get("/scanner/portfolio").json()
    assert p["source"] == "file" and p["watchlist"] == [{"symbol": "MARICO"}]


def test_run_needs_a_running_scanner(client, scan_root):
    assert client.post("/scanner/run", json={"market": "NSE"}).status_code == 503
    assert client.get("/scanner/job").status_code == 503


def test_run_and_job_go_to_the_running_scanner(client, scan_root, monkeypatch):
    _, calls = scan_root
    settings = {"markets": [{"market": "NSE", "ok": True, "last": "2026-11-23", "dates": ["2026-11-23"]},
                            {"market": "NYSE", "ok": False}]}

    def fake(path, body=None, timeout=2.0):
        calls.append((path, body))
        if path == "/api/launcher/settings":
            return settings
        if path == "/api/launcher/scan":
            return {"ok": True, "msg": "scan started"}
        if path.startswith("/api/launcher/job"):
            return {"state": "running", "log": ["scan NSE: 10/116 chunks"], "next": 1}
        if path == "/api/portfolio":
            return {"watchlist": [], "trades": [{"id": "t1"}]}
        return None

    monkeypatch.setattr(scanner, "_server", fake)
    st = client.get("/scanner").json()
    assert st["online"] and st["markets"][0] == {"market": "NSE", "ok": True, "last": "2026-11-23",
                                                  "dates": ["2026-11-23"], "warning": None}
    # the latest date (23 Nov) is already scanned: refused, the scanner is not asked
    r = client.post("/scanner/run", json={"market": "nse"})
    assert r.status_code == 409 and "already scanned for 2026-11-23" in r.json()["detail"]
    assert ("/api/launcher/scan", {"market": "NSE", "date": "2026-11-23"}) not in calls
    assert client.post("/scanner/run", json={"market": "NSE", "date": "2026-11-20"}).json()["ok"] is True
    assert ("/api/launcher/scan", {"market": "NSE", "date": "2026-11-20"}) in calls
    assert client.post("/scanner/run", json={"market": "NYSE"}).status_code == 409        # no NYSE folder set
    assert client.get("/scanner/job", params={"since": 4}).json()["state"] == "running"
    assert ("/api/launcher/job?since=4", None) in calls
    assert client.get("/scanner/portfolio").json() == {"source": "scanner", "watchlist": [], "trades": [{"id": "t1"}]}


def test_setup_explanations_come_from_the_scanner_source(client, scan_root, tmp_path, monkeypatch):
    src = tmp_path / "TranscriptExtract"
    (src / "swingbt" / "scan").mkdir(parents=True)
    (src / "swingbt" / "scan" / "explain.py").write_text(
        "import numpy  # never executed: read as data\n"
        "SETUP_NAME = {'BBR': 'Bad break recovery', 'NEW': 'Brand new setup'}\n"
        "SETUP_INTRO = {'BBR': ('What it is.', 'Why it works.', 'More why.'), 'NEW': 'Only what.'}\n")
    monkeypatch.setattr(get_settings(), "scanner_src", str(src))
    s = client.get("/scanner/setups").json()
    assert s["BBR"] == {"name": "Bad break recovery", "what": "What it is.", "why": "Why it works. More why."}
    assert s["NEW"] == {"name": "Brand new setup", "what": "Only what.", "why": ""}
    assert s["VCP"]["name"] == "Volatility contraction pattern"     # built-in names fill the rest
    d = client.get("/scanner/scans/NSE_daily_2026-11-23").json()
    assert d["setups"]["BBR"]["what"] == "What it is."


def test_scan_rows_carry_company_names(client, scan_root):
    """The scan files hold tickers only; names come from our symbol list ('' for a stock we do not know)."""
    root, _ = scan_root
    f = root / "my_scans" / "NSE_daily_2026-11-23" / "signals.csv"
    f.write_text(f.read_text() + row("TCS", "PP", 4, 6.0))
    name = client.get("/symbols/NSE:TCS").json().get("name") or client.get("/symbols", params={"q": "TCS"}).json()[0]["name"]
    assert name
    by = {r["ticker"]: r for r in client.get("/scanner/scans/NSE_daily_2026-11-23").json()["signals"]}
    assert by["TCS"]["name"] == name
    assert by["MARICO"]["name"] == ""                       # not in the test universe


def test_chart_pages_are_dropped_after_a_scan(client, scan_root, monkeypatch):
    """A scan's charts/ folder (the scanner's chart pages) is removed; its data stays."""
    root, _ = scan_root
    day = root / "my_scans" / "NSE_daily_2026-11-23"
    (day / "charts").mkdir()
    (day / "charts" / "MARICO_BBR_2026-11-23.html").write_text("x" * 5000)
    (root / "my_scans" / "_lib" / "keep.js").write_text("lib")                # not a scan: never touched
    monkeypatch.setattr(scanner, "_server", lambda p, b=None, timeout=2.0:
                        {"state": "done", "folder": "NSE_daily_2026-11-23", "log": ["done"], "next": 1})
    assert client.get("/scanner/job").json()["state"] == "done"
    assert not (day / "charts").exists() and (day / "signals.csv").is_file() and (day / "market.json").is_file()
    assert (root / "my_scans" / "_lib" / "keep.js").is_file()
    d = client.get("/scanner/scans/NSE_daily_2026-11-23").json()                # the scan still reads
    assert d["signals"] and d["report_href"]


def test_slim_all_scans_and_keep_charts_setting(scan_root, monkeypatch):
    root, _ = scan_root
    for name in ("NSE_daily_2026-11-23", "NYSE_daily_2026-11-17"):
        (root / "my_scans" / name / "charts").mkdir()
        (root / "my_scans" / name / "charts" / "a.html").write_text("x" * 1000)
    monkeypatch.setattr(get_settings(), "scanner_keep_charts", True)
    assert scanner.slim_scans(root) == (0, 0)                                  # kept when asked to
    monkeypatch.setattr(get_settings(), "scanner_keep_charts", False)
    assert scanner.slim_scans(root) == (2, 2000)
    assert not any((root / "my_scans").glob("*/charts"))


def test_rows_list_every_setup_of_the_day(client, scan_root):
    """A row's setups: its own first, then the others the scanner lists (the Setup Screener filters on all of them)."""
    root, _ = scan_root
    day = root / "my_scans" / "NSE_daily_2026-11-23"
    (day / "near_misses.csv").write_text(
        "symbol,setup,valid,close,stop,score,reject,other_setups\n"
        'XYZ,BBR,False,100,95,8,S8-R003: no ATR,"PP (S8-R003), MINICOIL (S8-R003)"\n')
    d = client.get("/scanner/scans/NSE_daily_2026-11-23").json()
    by = {r["ticker"]: r for r in d["signals"]}
    assert by["MARICO"]["setups"] == ["BBR", "PP"]                           # "also" = PP in the fixture
    assert d["near_misses"][0]["setups"] == ["BBR", "PP", "MINICOIL"]        # rule ids in brackets dropped


def test_offline_scanner_is_detected_quickly(monkeypatch):
    """A closed local port is refused only after ~2 s on Windows: the 0.3 s check answers sooner, and an offline answer
    is remembered for a few seconds (so the Setup Screener opens without a 2-second wait)."""
    import socket
    import time

    monkeypatch.setattr(scanner, "_OFFLINE_UNTIL", [0.0])
    with socket.socket() as s:                                   # a free port that nothing listens on
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(get_settings(), "scanner_url", f"http://127.0.0.1:{port}")
    t = time.perf_counter()
    assert scanner._server("/api/launcher/settings") is None
    assert time.perf_counter() - t < 1.0
    t = time.perf_counter()
    assert scanner._reachable() is False and time.perf_counter() - t < 0.05     # remembered: no new check
    with socket.socket() as srv:                                 # something listening: reachable
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        monkeypatch.setattr(scanner, "_OFFLINE_UNTIL", [0.0])
        monkeypatch.setattr(get_settings(), "scanner_url", f"http://127.0.0.1:{srv.getsockname()[1]}")
        assert scanner._reachable() is True
