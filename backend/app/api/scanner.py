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
import re
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.config import get_settings

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
            # the scanner's trade plan: entry = the signal-day close, stop tested from the next session
            row["entry"] = row["close"]
            row["risk"] = round(row["close"] - row["stop"], 4) if row["close"] is not None and row["stop"] is not None                 else None
            row["buy"] = row["valid"] and row["status"].strip().lower() == "would buy"
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
    markets = [dict(market=m.get("market"), ok=bool(m.get("ok")), last=m.get("last"), dates=(m.get("dates") or [])[:60])
               for m in (st or {}).get("markets", [])]
    return dict(configured=True, dir=str(root), url=get_settings().scanner_url, online=st is not None,
                markets=markets, scans=_list(scans_dir(root)))


@router.get("/scans/{scan_id}")
def get_scan(scan_id: str, near: bool = Query(True)) -> dict:
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
    url = get_settings().scanner_url.rstrip("/")
    info = setup_info(root)
    for r in signals + misses:
        r["chart_href"] = f"{url}/{scan_id}/{r['chart']}" if r["chart"] else ""
        r["setup_name"] = info.get(r["setup"], {}).get("name", r["setup"])
    present = sorted({r["setup"] for r in signals + misses})
    setups = {c: info.get(c, dict(name=c, what="", why="")) for c in present}
    mr = meta.get("market_row") or {}
    return dict(id=scan_id, market=market, date=m.group(2), regime=mr.get("regime"), risk_mult=mr.get("risk_mult"),
                rules=meta.get("rules"), symbols=meta.get("symbols"), report_href=f"{url}/{scan_id}/index.html",
                signals=signals, near_misses=misses, setups=setups)


@router.get("/setups")
def setups() -> dict:
    """Every buy setup the scanner knows, with its name and explanation."""
    return setup_info(scanner_dir())


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
    return r
