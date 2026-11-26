"""The Setup Screener's API. It talks only to app.ports.SetupScanner. Several scanners can run side by side
(SETUP_SCANNERS, see app/providers.py): every endpoint takes `scanner` (a scanner's name; default: the first), and
adds what is the product's own: company names, ranking, and on-screen wording (no buy / sell
words, no rulebook codes)."""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import SessionDep
from app.models import Symbol
from app.ports import ScannerOffline, ScanRefused
from app.providers import ProviderError, setup_scanner, setup_scanners
from app.wording import for_screen, for_screen_all

router = APIRouter(prefix="/scanner", tags=["scanner"])
ROW_TEXT = ("status", "notes", "stop_note", "reject", "weak", "soft", "setup_name")   # a row's text shown on screen


Which = Query(None, description="the setup scanner's name (GET /scanner lists them); default: the first")


def _sc(name: str | None):
    try:
        return setup_scanner(name)
    except ProviderError as e:
        raise HTTPException(404, str(e)) from e


def _for_screen_row(r: dict) -> dict:
    for k in ROW_TEXT:
        if k in r:
            r[k] = for_screen(r[k])
    return r


@router.get("")
def status(scanner: str | None = Which) -> dict:
    """One scanner: is it set up and running, its markets and their sessions, and its saved scans (newest first);
    `scanners` lists every scanner in use (name, title), the default first."""
    sc = _sc(scanner)
    st = sc.status()
    return dict(st, scans=sc.scans() if st.get("configured") else [],
                scanners=[dict(name=k, title=v.title) for k, v in setup_scanners().items()])


@router.get("/scans/{scan_id}")
def get_scan(scan_id: str, session: SessionDep, near: bool = Query(True), scanner: str | None = Which) -> dict:
    sc = _sc(scanner)
    d = sc.scan(scan_id, near)
    if d is None:
        raise HTTPException(404, "no such scan")
    signals, misses = d.get("signals") or [], d.get("near_misses") or []
    signals.sort(key=lambda r: (r.get("rank") is None, r.get("rank") or 0, -(r.get("score") or 0)))
    misses.sort(key=lambda r: -(r.get("score") or 0))
    # company names from our symbol list (scanners give tickers)
    tickers = {r["ticker"] for r in signals + misses}
    names = dict(session.execute(select(Symbol.ticker, Symbol.name).where(
        Symbol.exchange == d["market"], Symbol.ticker.in_(tickers))).all()) if tickers else {}
    for r in signals + misses:
        r["name"] = names.get(r["ticker"]) or ""
        _for_screen_row(r)
    return dict(d, scanner=sc.name, signals=signals, near_misses=misses, setups=for_screen_all(d.get("setups") or {}),
                market_note=for_screen_all(d.get("market_note")), score_note=for_screen(d.get("score_note") or ""))


@router.get("/setups")
def setups(scanner: str | None = Which) -> dict:
    """Every setup the scanner knows, with its name and explanation."""
    return for_screen_all(_sc(scanner).setups())


@router.get("/portfolio")
def portfolio(scanner: str | None = Which) -> dict:
    """The scanner's watchlist and trades."""
    return _sc(scanner).portfolio()


class RunIn(BaseModel):
    market: str = "NSE"
    date: str | None = None
    scanner: str | None = None             # default: the first scanner


@router.post("/run")
def run_scan(body: RunIn) -> dict:
    """Start a scan (a scan already saved is not run again: 409)."""
    try:
        return _sc(body.scanner).run(body.market.upper(), body.date)
    except ScannerOffline as e:
        raise HTTPException(503, str(e)) from e
    except ScanRefused as e:
        raise HTTPException(409, str(e)) from e


@router.get("/job")
def job(since: int = 0, scanner: str | None = Which) -> dict:
    try:
        return _sc(scanner).job(since)
    except ScannerOffline as e:
        raise HTTPException(503, str(e)) from e


@router.get("/scans/{scan_id}/explain")
def explain_signal(scan_id: str, symbol: str = Query(..., description="ticker, e.g. MARICO (or NSE:MARICO)"),
                   setup: str = Query(...), near: bool = Query(False),
                   equity: float | None = Query(None, gt=0, description="your portfolio size; default: the scan's capital"),
                   risk_pct: float | None = Query(None, gt=0, le=100,
                                                  description="risk per trade, % of the portfolio; default: the scan's"),
                   scanner: str | None = Which) -> dict:
    """A brief 'why this trade' for one signal (or near miss) of a saved scan."""
    ticker = symbol.split(":")[-1].upper()
    d = _sc(scanner).explain(scan_id, ticker, setup, near, equity, risk_pct)
    if d is None:
        raise HTTPException(404, f"{ticker} {setup} is not in {scan_id}")
    return for_screen_all(d)
