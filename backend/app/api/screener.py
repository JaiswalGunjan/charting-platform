"""'Patterns formed today' dashboard API: saved screen results and a background job that refreshes them."""
import dataclasses
import threading
import time

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.patterns import screener as sc
from app.wording import neutral_all

router = APIRouter(prefix="/screener", tags=["screener"])
_JOB = sc.Progress()
_LOCK = threading.Lock()


def _job_dict() -> dict:
    return dataclasses.asdict(_JOB)


@router.get("/patterns-today")
def patterns_today(request: Request, exchange: str = Query("NSE"), tf: str = Query("1D"),
                   date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$",
                                            description="a session with a saved screen; default: the newest")) -> dict:
    """A saved screen for exchange/timeframe (rows = symbols with at least one pattern on that bar), with the
    session dates that have saved screens."""
    if tf not in sc.SCREEN_TFS:
        raise HTTPException(400, f"tf must be one of {sc.SCREEN_TFS}")
    res = sc.load_screen(exchange, tf, day=date)
    latest = sc.resolve_session(request.app.state.session_factory, exchange)   # newest session with data
    extra = dict(job=_job_dict(), dates=sc.screen_dates(exchange, tf), latest_session=latest)
    if res is None:
        return dict(exchange=exchange.upper(), tf=tf, as_of=None, rows=[], scanned=0, missing=True, **extra)
    res = sc.with_turnover(request.app.state.session_factory, res)  # turnover: 20-day average, HTQ
    return dict(neutral_all(res), missing=False, **extra)        # saved notes: no buy/sell words on screen


class RunIn(BaseModel):
    exchange: str = "NSE"
    tf: str = "1D"
    date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")   # a past session; default: the latest


@router.post("/patterns-today/run")
def run(body: RunIn, request: Request) -> dict:
    if body.tf not in sc.SCREEN_TFS:
        raise HTTPException(400, f"tf must be one of {sc.SCREEN_TFS}")
    factory = request.app.state.session_factory
    # a session that is already screened is not screened again
    session = sc.resolve_session(factory, body.exchange, body.date)
    if session and sc.saved_screen(body.exchange, body.tf, session) is not None:
        raise HTTPException(409, f"{body.exchange.upper()} {'daily' if body.tf == '1D' else 'weekly'} is already "
                                 f"screened for {session}; the saved screen is shown")
    if not _LOCK.acquire(blocking=False):
        raise HTTPException(409, f"a screen is already running ({_JOB.exchange} {_JOB.tf})")
    _JOB.__init__(state="running", exchange=body.exchange.upper(), tf=body.tf, msg="starting…", started=time.time())

    def work():
        try:
            res = sc.run_screen(factory, body.exchange, body.tf, progress=_JOB, day=body.date)
            _JOB.state, _JOB.msg = "done", f"{len(res['rows']):,} symbols with patterns of {res['scanned']:,} screened"
        except Exception as e:  # noqa: BLE001  reported to the UI
            _JOB.state, _JOB.msg = "error", f"{type(e).__name__}: {e}"
        finally:
            _JOB.finished = time.time()
            _LOCK.release()

    threading.Thread(target=work, name="pattern-screen", daemon=True).start()
    return dict(ok=True, job=_job_dict())


@router.get("/patterns-today/job")
def job() -> dict:
    return _job_dict()
