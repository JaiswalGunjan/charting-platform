"""'Patterns formed today' dashboard API: saved screen results and a background job that refreshes them."""
import dataclasses
import threading
import time

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.patterns import screener as sc

router = APIRouter(prefix="/screener", tags=["screener"])
_JOB = sc.Progress()
_LOCK = threading.Lock()


def _job_dict() -> dict:
    return dataclasses.asdict(_JOB)


@router.get("/patterns-today")
def patterns_today(exchange: str = Query("NSE"), tf: str = Query("1D")) -> dict:
    """The latest saved screen for exchange/timeframe (rows = symbols with at least one pattern on the last bar)."""
    if tf not in sc.SCREEN_TFS:
        raise HTTPException(400, f"tf must be one of {sc.SCREEN_TFS}")
    res = sc.load_screen(exchange, tf)
    job = _job_dict()
    if res is None:
        return dict(exchange=exchange.upper(), tf=tf, as_of=None, rows=[], scanned=0, missing=True, job=job)
    return dict(res, missing=False, job=job)


class RunIn(BaseModel):
    exchange: str = "NSE"
    tf: str = "1D"


@router.post("/patterns-today/run")
def run(body: RunIn, request: Request) -> dict:
    if body.tf not in sc.SCREEN_TFS:
        raise HTTPException(400, f"tf must be one of {sc.SCREEN_TFS}")
    if not _LOCK.acquire(blocking=False):
        raise HTTPException(409, f"a screen is already running ({_JOB.exchange} {_JOB.tf})")
    factory = request.app.state.session_factory
    _JOB.__init__(state="running", exchange=body.exchange.upper(), tf=body.tf, msg="starting…", started=time.time())

    def work():
        try:
            res = sc.run_screen(factory, body.exchange, body.tf, progress=_JOB)
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
