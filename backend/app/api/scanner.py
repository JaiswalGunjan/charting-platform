"""Connection to the owner's SwingScanner (TranscriptExtract/swingbt/scan, shipped as SwingScanner.exe).

Saved scans are read straight from the scanner's `scans` folder (works whether or not the scanner is running):
    scans/<MARKET>_daily_<YYYY-MM-DD>/signals.csv      signals of the day, ranked ("would buy", ...)
    scans/<MARKET>_daily_<YYYY-MM-DD>/near_misses.csv  setups that failed a rule (reject / weak columns)
    scans/<MARKET>_daily_<YYYY-MM-DD>/market.json      market regime, counts
    scans/portfolio.json                               its watchlist and trades
Running a scan and its progress go through the scanner's local server (SCANNER_URL, default :8765), which must be
started by the owner (SwingScanner.exe). Nothing here writes into the scanner's folders.
"""
import ast
import configparser
import csv
import json
import math
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from sqlalchemy import select

from app.api.deps import SessionDep
from app.config import get_settings
from app.models import Symbol
from app.scanner_explain import market_note, rulebook, score_note
from app.wording import neutral, neutral_all

router = APIRouter(prefix="/scanner", tags=["scanner"])
SCAN_ID = re.compile(r"^(NSE|BSE|NYSE|NASDAQ)_daily_(\d{4}-\d{2}-\d{2})$")
# scanner setup code -> chart pattern id (app/patterns/engine.py), so a signal can switch its pattern on
SETUP_PATTERN = {"BBR": "bbr", "PP": "pp", "OVERSOLD": "oversold", "ONE23": "one23", "TL3": "tl3",
                 "MINICOIL": "minicoil", "NAT_REACTION": "natural", "SQUAT": "squat", "MOMENTUM": "momentum",
                 "QUIET_BO": "quiet", "VCP": "vcp", "CWH": "cwh", "FLAT": "flat", "HTF": "htf"}
NUM = ("close", "stop", "stop_pct", "score", "size_mult", "base_len", "rs60", "dist_10d_high_pct", "shares",
       "value", "rank", "stage", "res_touches")
TEXT = ("date", "setup", "status", "phase", "stop_note", "notes", "reject", "weak", "soft", "stop_rule", "chart")


# fallback names when the scanner's source (swingbt/scan/explain.py) is not on this machine
SETUP_NAME = {"PP": "Pocket pivot", "ONE23": "1-2-3 shaper", "OVERSOLD": "Oversold shaper", "BBR": "Bad break recovery",
              "TL3": "Three-touch trendline", "MINICOIL": "Mini coil", "CWH": "Cup with handle", "FLAT": "Flat base",
              "HTF": "High tight flag", "VCP": "Volatility contraction pattern", "NAT_REACTION": "Natural reaction",
              "SQUAT": "Squat", "MOMENTUM": "Momentum riding", "QUIET_BO": "Quiet-zone breakout",
              "EARLY_EOD": "Early end-of-day system", "IPO": "IPO base"}


def _explain_py(root: Path | None) -> Path | None:
    """The scanner's explain.py: SCANNER_SRC (a TranscriptExtract folder), else found from the bundle's location
    (TranscriptExtract/dist/<bundle>/SwingScanner)."""
    cands = []
    src = get_settings().scanner_src
    if src:
        cands.append(Path(src))
    if root is not None:
        cands += [root.parents[k] for k in range(1, min(4, len(root.parents)))]
    for c in cands:
        f = c / "swingbt" / "scan" / "explain.py"
        if f.is_file():
            return f
    return None


def setup_info(root: Path | None) -> dict[str, dict]:
    """{setup code: {name, what, why}} from the scanner's own explanations (read as data with ast; never imported)."""
    names, intro = dict(SETUP_NAME), {}
    f = _explain_py(root)
    if f is not None:
        try:
            for node in ast.parse(f.read_text(encoding="utf-8")).body:
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                    if node.targets[0].id == "SETUP_NAME":
                        names.update(ast.literal_eval(node.value))
                    elif node.targets[0].id == "SETUP_INTRO":
                        intro = ast.literal_eval(node.value)
        except (OSError, SyntaxError, ValueError):
            pass
    out = {}
    for code, name in names.items():
        parts = intro.get(code, ())
        parts = (parts,) if isinstance(parts, str) else tuple(parts)
        out[code] = dict(name=name, what=parts[0] if parts else "", why=" ".join(parts[1:]))
    return out


def scanner_dir() -> Path | None:
    d = get_settings().scanner_dir
    return Path(d) if d and Path(d).is_dir() else None


def scans_dir(root: Path) -> Path:
    """The scans folder named in the scanner's swingbt_config.ini ([app] scans, relative to the exe folder)."""
    ini = configparser.ConfigParser()
    ini.read(root / "swingbt_config.ini", encoding="utf-8")
    rel = ini.get("app", "scans", fallback="scans").strip() or "scans"
    p = Path(rel)
    return p if p.is_absolute() else (root / p).resolve()


STUB_BYTES = 20_000        # a per-symbol file smaller than this holds only a few bars (the scanner's own threshold)
NO_BARS_HINT = ("The scanner found no usable history. Usually the market's per-symbol folder ({folder}) holds only "
                "stubs of a few recent bars (left by the downloader's incremental update); SwingScanner.exe of "
                "18 Nov 2026 then has nothing to scan. Rebuild the scanner bundle from its current source (which "
                "falls back to the day files), or clear '{key}' in swingbt_config.ini, or re-download full history.")


def data_warnings(root: Path) -> dict[str, dict]:
    """Per market: the per-symbol folder named in the scanner's ini ([data] <market>_symbols) when every sampled file
    in it is a stub. Read only."""
    ini = configparser.ConfigParser()
    ini.read(root / "swingbt_config.ini", encoding="utf-8")
    out = {}
    for market in ("NSE", "BSE", "NYSE", "NASDAQ"):
        key = f"{market.lower()}_symbols"
        raw = ini.get("data", key, fallback="").strip()
        if not raw:
            continue
        folder = Path(raw) if Path(raw).is_absolute() else (root / raw)
        try:
            sizes = [e.stat().st_size for _, e in zip(range(300), (e for e in os.scandir(folder)
                                                                    if e.name.lower().endswith(".csv")))]
        except OSError:
            continue
        if sizes and max(sizes) < STUB_BYTES:
            out[market] = dict(folder=str(folder), key=key, msg=(
                f"{market}: the per-symbol files in {folder} hold only a few bars each (largest "
                f"{max(sizes):,} bytes of {len(sizes)} checked), so a scan of {market} fails with 'no symbol "
                f"produced bars'."))
    return out


def drop_charts(folder: Path) -> int:
    """Remove a scan's charts/ folder (the scanner's chart page per signal: most of a scan's size; Charting Lab draws
    its own charts). Returns the bytes freed. Only `<scans>/<MARKET>_daily_<date>/charts` is ever removed."""
    import shutil

    charts = folder / "charts"
    if get_settings().scanner_keep_charts or not SCAN_ID.match(folder.name) or not charts.is_dir():
        return 0
    size = sum(f.stat().st_size for f in charts.rglob("*") if f.is_file())
    shutil.rmtree(charts, ignore_errors=True)
    return size


def slim_scans(root: Path) -> tuple[int, int]:
    """drop_charts() on every saved scan: (scans slimmed, bytes freed)."""
    n = freed = 0
    for p in scans_dir(root).glob("*_daily_*"):
        if (p / "signals.csv").is_file():
            got = drop_charts(p)
            n += bool(got)
            freed += got
    return n, freed


def _num(v: str):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else (int(x) if x.is_integer() else round(x, 4))


def _rows(path: Path, market: str) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            row = {k: (r.get(k) or "") for k in TEXT}
            row.update({k: _num(r.get(k)) for k in NUM})
            row["valid"] = (r.get("valid") or "").strip().lower() == "true"
            row["ticker"] = r.get("symbol", "")
            row["symbol"] = f"{market}:{r.get('symbol', '')}"
            row["pattern"] = SETUP_PATTERN.get(row["setup"], "")
            # every setup that formed on this stock that day: its own, then the others the scanner lists
            # (breakouts: "also" = "PP, NAT_REACTION"; near misses: "other_setups" = "PP (S8-R003), MINICOIL (...)")
            others = (r.get("also") or "") + "," + (r.get("other_setups") or "")
            codes = [c.strip().split(" ")[0].split("(")[0].strip() for c in others.split(",")]
            row["setups"] = list(dict.fromkeys([row["setup"]] + [c for c in codes if c and c != row["setup"]]))
            # the scanner's trade plan: entry = the signal-day close, stop tested from the next session
            row["entry"] = row["close"]
            row["risk"] = round(row["close"] - row["stop"], 4) if row["close"] is not None and row["stop"] is not None                 else None
            row["buy"] = row["valid"] and row["status"].strip().lower() == "would buy"
            for k in ("status", "notes", "stop_note", "reject", "weak", "soft"):    # on-screen text: no buy/sell words
                row[k] = neutral(row[k])
            out.append(row)
    return out


def _list(scans: Path) -> list[dict]:
    out = []
    for p in scans.glob("*_daily_*"):
        m = SCAN_ID.match(p.name)
        if not m or not (p / "signals.csv").is_file():
            continue
        meta = {}
        try:
            meta = json.loads((p / "market.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        out.append(dict(id=p.name, market=m.group(1), date=m.group(2), valid=meta.get("valid_today"),
                        near=meta.get("near_today"), regime=(meta.get("market_row") or {}).get("regime"),
                        symbols=meta.get("symbols")))
    return sorted(out, key=lambda s: (s["date"], s["market"]), reverse=True)


def _server(path: str, body: dict | None = None, timeout: float = 2.0):
    """Call the running scanner; None when it is not running."""
    url = get_settings().scanner_url.rstrip("/") + path
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {},
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read() or b"{}") | {"ok": False, "status": e.code}
        except ValueError:
            return {"ok": False, "status": e.code}
    except (OSError, ValueError):
        return None


@router.get("")
def status() -> dict:
    root = scanner_dir()
    if root is None:
        return dict(configured=False, online=False, scans=[],
                    msg="Set SCANNER_DIR in .env to the SwingScanner folder (the one with SwingScanner.exe).")
    st = _server("/api/launcher/settings")
    warn = data_warnings(root)
    markets = [dict(market=m.get("market"), ok=bool(m.get("ok")), last=m.get("last"), dates=(m.get("dates") or [])[:60],
                    warning=warn.get(m.get("market"), {}).get("msg"))
               for m in (st or {}).get("markets", [])]
    return dict(configured=True, dir=str(root), url=get_settings().scanner_url, online=st is not None,
                markets=markets, scans=_list(scans_dir(root)))


# when a scan has no report page: the scanner's priority score in brief (swingbt/rules/priority.py)
SCORE_NOTE = ("Score = the scanner's priority score: cycle phase + setup weight + pocket pivots in the pattern + "
              "closeness to the 10-day high + tight stop + relative strength + nearness to the 52-week high + OBV high + "
              "confluence + volume contraction, minus a penalty per soft miss. Higher ranks first.")


@router.get("/scans/{scan_id}")
def get_scan(scan_id: str, session: SessionDep, near: bool = Query(True)) -> dict:
    root = scanner_dir()
    m = SCAN_ID.match(scan_id)
    if root is None or not m:
        raise HTTPException(404, "no such scan")
    folder = scans_dir(root) / scan_id
    if not (folder / "signals.csv").is_file():
        raise HTTPException(404, "no such scan")
    meta = {}
    try:
        meta = json.loads((folder / "market.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    market = m.group(1)
    signals = _rows(folder / "signals.csv", market)
    signals.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, -(r["score"] or 0)))
    misses = _rows(folder / "near_misses.csv", market) if near else []
    misses.sort(key=lambda r: -(r["score"] or 0))
    info = setup_info(root)
    # company names from our symbol list (the scan files only carry tickers)
    tickers = {r["ticker"] for r in signals + misses}
    names = dict(session.execute(select(Symbol.ticker, Symbol.name).where(
        Symbol.exchange == market, Symbol.ticker.in_(tickers))).all()) if tickers else {}
    for r in signals + misses:
        r["name"] = names.get(r["ticker"]) or ""
        r["chart_href"] = f"/scanner/report/{scan_id}/{r['chart']}" if r["chart"] else ""
        r["setup_name"] = neutral(info.get(r["setup"], {}).get("name", r["setup"]))
    present = sorted({r["setup"] for r in signals + misses})
    setups = {c: info.get(c, dict(name=c, what="", why="")) for c in present}
    mr = meta.get("market_row") or {}
    return dict(id=scan_id, market=market, date=m.group(2), regime=mr.get("regime"), risk_mult=mr.get("risk_mult"),
                rules=meta.get("rules"), symbols=meta.get("symbols"), report_href=f"/scanner/report/{scan_id}/index.html",
                capital=meta.get("capital"), risk_pct=(meta.get("config") or {}).get("risk_pct", 1.0),
                max_alloc_pct=(meta.get("config") or {}).get("max_alloc_pct", 45.0),
                signals=signals, near_misses=misses, setups=neutral_all(setups),
                market_note=neutral_all(market_note(market, mr, rulebook(root))),
                score_note=neutral(score_note(folder)) or neutral(SCORE_NOTE))


@router.get("/setups")
def setups() -> dict:
    """Every buy setup the scanner knows, with its name and explanation."""
    return neutral_all(setup_info(scanner_dir()))


@router.get("/portfolio")
def portfolio() -> dict:
    """The scanner's watchlist and trades: live from its server, else from scans/portfolio.json."""
    live = _server("/api/portfolio")
    if live is not None:
        return dict(source="scanner", **{k: live.get(k, []) for k in ("watchlist", "trades")})
    root = scanner_dir()
    f = scans_dir(root) / "portfolio.json" if root else None
    if f is None or not f.is_file():
        return dict(source="none", watchlist=[], trades=[])
    st = json.loads(f.read_text(encoding="utf-8"))
    return dict(source="file", watchlist=st.get("watchlist", []), trades=st.get("trades", []))


class RunIn(BaseModel):
    market: str = "NSE"
    date: str | None = None


@router.post("/run")
def run_scan(body: RunIn) -> dict:
    market, day = body.market.upper(), body.date
    if not day:  # default: the latest session in the scanner's data folder for that market
        st = _server("/api/launcher/settings")
        if st is None:
            raise HTTPException(503, "The scanner is not running: start SwingScanner.exe, then try again.")
        day = next((m.get("last") for m in st.get("markets", []) if m.get("market") == market and m.get("ok")), None)
        if not day:
            raise HTTPException(409, f"The scanner has no {market} data folder set.")
    # a scan that is already saved is not run again
    root = scanner_dir()
    if root is not None and (scans_dir(root) / f"{market}_daily_{day}" / "signals.csv").is_file():
        raise HTTPException(409, f"{market} is already scanned for {day}; the saved scan is shown")
    r = _server("/api/launcher/scan", dict(market=market, date=day))
    if r is None:
        raise HTTPException(503, "The scanner is not running: start SwingScanner.exe, then try again.")
    if not r.get("ok", True):
        raise HTTPException(409, r.get("msg", "the scanner refused the scan"))
    return r


@router.get("/job")
def job(since: int = 0) -> dict:
    r = _server(f"/api/launcher/job?since={since}")
    if r is None:
        raise HTTPException(503, "The scanner is not running.")
    log = r.get("log") or []
    if r.get("state") == "done" and r.get("folder"):
        root = scanner_dir()
        if root is not None:
            drop_charts(scans_dir(root) / str(r["folder"]))       # keep the scan's data, not its chart pages
    if r.get("state") == "error" and any("no symbol produced bars" in str(x) for x in log[-3:]):
        root = scanner_dir()
        w = data_warnings(root).get(str(r.get("market", "")).upper()) if root else None
        r["hint"] = NO_BARS_HINT.format(folder=w["folder"] if w else "alpaca_adjusted",
                                        key=w["key"] if w else f"{str(r.get('market', 'nyse')).lower()}_symbols")
    return r


@router.get("/scans/{scan_id}/explain")
def explain_signal(scan_id: str, symbol: str = Query(..., description="ticker, e.g. MARICO (or NSE:MARICO)"),
                   setup: str = Query(...), near: bool = Query(False),
                   equity: float | None = Query(None, gt=0, description="your portfolio size; default: the scan's capital"),
                   risk_pct: float | None = Query(None, gt=0, le=100,
                                                  description="risk per trade, % of the portfolio; default: the scan's")) -> dict:
    """A brief 'why this trade' for one signal (or near miss) of a saved scan."""
    from app.scanner_explain import explain, load_meta, rulebook

    root = scanner_dir()
    m = SCAN_ID.match(scan_id)
    if root is None or not m:
        raise HTTPException(404, "no such scan")
    folder = scans_dir(root) / scan_id
    ticker = symbol.split(":")[-1].upper()
    f = folder / ("near_misses.csv" if near else "signals.csv")
    row = None
    if f.is_file():
        with open(f, encoding="utf-8", newline="") as fh:
            row = next((r for r in csv.DictReader(fh)
                        if r.get("symbol", "").upper() == ticker and r.get("setup") == setup), None)
    if row is None:
        raise HTTPException(404, f"{ticker} {setup} is not in {scan_id}")
    info = setup_info(root).get(setup, dict(name=setup, what="", why=""))
    return neutral_all(explain(row, m.group(1), info, rulebook(root), load_meta(folder), equity, risk_pct))
