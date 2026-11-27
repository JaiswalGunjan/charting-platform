"""Admins only: who uses Charting Lab, and how.

    GET   /admin/users            every user with their stats (sign-ins, active time, requests, last seen, where from)
    GET   /admin/users.csv        the same as a CSV file, for a spreadsheet
    GET   /admin/users/{id}       one user: recent sign-ins, daily activity, features used, stocks opened
    PATCH /admin/users/{id}       make or unmake an admin; disable or enable an account (ends its sessions)
"""
import csv
import io
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.auth.activity import recorder
from app.auth.deps import AdminDep, _factory
from app.models import LoginEvent, User, UserDay, UserFeatureDay, UserSession, UserSymbol

router = APIRouter(prefix="/admin", tags=["admin"])
COLUMNS = ["id", "name", "email", "email_verified", "phone", "provider", "is_admin", "disabled", "created_at",
           "first_login_at", "last_login_at", "last_seen_at", "login_count", "request_count", "active_minutes",
           "days_active", "last_ip", "last_location", "last_user_agent", "locale", "hosted_domain", "picture"]


def _iso(t: float | None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if t else ""


def _rows(db) -> list[dict]:
    days = dict(db.execute(select(UserDay.user_id, func.count()).group_by(UserDay.user_id)).all())
    out = []
    for u in db.scalars(select(User).order_by(User.last_seen_at.desc().nulls_last(), User.id)):
        out.append(dict(id=u.id, name=u.name, email=u.email, email_verified=u.email_verified, phone=u.phone,
                        provider=u.provider, is_admin=u.is_admin, disabled=u.disabled, created_at=_iso(u.created_at),
                        first_login_at=_iso(u.first_login_at), last_login_at=_iso(u.last_login_at),
                        last_seen_at=_iso(u.last_seen_at), login_count=u.login_count, request_count=u.request_count,
                        active_minutes=round((u.active_seconds or 0) / 60, 1), days_active=days.get(u.id, 0),
                        last_ip=u.last_ip, last_location=u.last_location, last_user_agent=u.last_user_agent,
                        locale=u.locale, hosted_domain=u.hosted_domain, picture=u.picture))
    return out


@router.get("/users")
def users(admin: AdminDep, request: Request) -> dict:
    recorder.flush(_factory(request.app))                     # the counts up to this moment
    with _factory(request.app)() as db:
        rows = _rows(db)
        signed_in_now = db.scalar(select(func.count(func.distinct(UserSession.user_id))).where(
            UserSession.ended_at.is_(None), UserSession.last_seen_at > time.time() - 900))
    from app.auth.geoip import info as geo_info

    return dict(users=rows, total=len(rows), active_last_15_min=signed_in_now or 0,
                geoip=geo_info())                      # where locations come from (DB-IP asks to be credited)


@router.get("/users.csv")
def users_csv(admin: AdminDep, request: Request) -> Response:
    recorder.flush(_factory(request.app))
    with _factory(request.app)() as db:
        rows = _rows(db)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS)
    w.writeheader()
    w.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"content-disposition": f'attachment; filename="charting-lab-users-{time.strftime("%Y%m%d")}.csv"'})


@router.get("/users/{uid}")
def user_detail(admin: AdminDep, uid: int, request: Request, days: int = Query(90, ge=1, le=3650)) -> dict:
    recorder.flush(_factory(request.app))
    since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))
    with _factory(request.app)() as db:
        u = db.get(User, uid)
        if u is None:
            raise HTTPException(404, "no such user")
        logins = db.scalars(select(LoginEvent).where(LoginEvent.user_id == uid).order_by(LoginEvent.at.desc())
                            .limit(100)).all()
        daily = db.scalars(select(UserDay).where(UserDay.user_id == uid, UserDay.day >= since).order_by(UserDay.day)).all()
        feats = db.execute(select(UserFeatureDay.feature, func.sum(UserFeatureDay.count))
                           .where(UserFeatureDay.user_id == uid, UserFeatureDay.day >= since)
                           .group_by(UserFeatureDay.feature).order_by(func.sum(UserFeatureDay.count).desc())).all()
        syms = db.scalars(select(UserSymbol).where(UserSymbol.user_id == uid).order_by(UserSymbol.count.desc())
                          .limit(50)).all()
        sess = db.scalars(select(UserSession).where(UserSession.user_id == uid).order_by(UserSession.created_at.desc())
                          .limit(20)).all()
        user = next(r for r in _rows(db) if r["id"] == uid)
    return dict(
        user=user,
        logins=[dict(at=_iso(e.at), ok=e.ok, reason=e.reason, ip=e.ip, country=e.country, region=e.region, city=e.city,
                     user_agent=e.user_agent) for e in logins],
        days=[dict(day=d.day, requests=d.requests, active_minutes=round(d.active_seconds / 60, 1)) for d in daily],
        features={f: int(n) for f, n in feats},
        symbols=[dict(symbol=s.symbol, count=s.count, first=_iso(s.first_at), last=_iso(s.last_at)) for s in syms],
        sessions=[dict(started=_iso(s.created_at), last_seen=_iso(s.last_seen_at), ended=_iso(s.ended_at),
                       requests=s.requests, active_minutes=round(s.active_seconds / 60, 1), ip=s.ip,
                       user_agent=s.user_agent) for s in sess])


class UserPatch(BaseModel):
    is_admin: bool | None = None
    disabled: bool | None = None


@router.patch("/users/{uid}")
def update_user(admin: AdminDep, uid: int, body: UserPatch, request: Request) -> dict:
    if uid == admin.id and (body.disabled or body.is_admin is False):
        raise HTTPException(400, "you cannot disable yourself or remove your own admin rights")
    with _factory(request.app)() as db:
        u = db.get(User, uid)
        if u is None:
            raise HTTPException(404, "no such user")
        if body.is_admin is not None:
            u.is_admin = body.is_admin
        if body.disabled is not None:
            u.disabled = body.disabled
            if body.disabled:                                  # signed out everywhere
                for s in db.scalars(select(UserSession).where(UserSession.user_id == uid, UserSession.ended_at.is_(None))):
                    s.ended_at = time.time()
        db.commit()
    return dict(ok=True)


def prune(session_factory, days: int) -> dict:
    """Delete sign-in records, sessions and daily activity older than `days` (ACTIVITY_RETENTION_DAYS)."""
    from sqlalchemy import delete

    cut = time.time() - days * 86400
    day = time.strftime("%Y-%m-%d", time.gmtime(cut))
    with session_factory() as db:
        n = dict(logins=db.execute(delete(LoginEvent).where(LoginEvent.at < cut)).rowcount,
                 sessions=db.execute(delete(UserSession).where(UserSession.last_seen_at < cut)).rowcount,
                 days=db.execute(delete(UserDay).where(UserDay.day < day)).rowcount,
                 features=db.execute(delete(UserFeatureDay).where(UserFeatureDay.day < day)).rowcount)
        db.commit()
    return n


# ---------------------------------------------------------------- the dashboard: data status and jobs
class JobIn(BaseModel):
    kind: str                                   # download | setup_scan | pattern_screen | full
    market: str                                 # a market of the daily job (daily_update.toml): NSE, US
    date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")   # the session; default: the latest


def _data_status(request: Request) -> dict:
    """What is stored and screened: per exchange its latest daily (and minute) bar, newest setup scan, newest screens."""
    from app.markets import markets as registry
    from app.patterns.screener import screen_dates
    from app.patterns.store import session_date
    from app.providers import bar_store, setup_scanners

    store = bar_store()
    out = []
    scans = {}
    for sc in setup_scanners().values():
        try:
            for s in sc.scans():
                scans.setdefault(s["market"], s["date"])          # newest first
        except Exception:  # noqa: BLE001  a scanner that is not set up
            pass
    from app.models import Symbol

    with _factory(request.app)() as db:

        symbols = dict(db.execute(select(Symbol.exchange, func.count()).group_by(Symbol.exchange)).all())
        for code, m in registry().items():
            daily = store.last_time(db, code, "1D")
            try:
                minute = store.last_time(db, code, "1m")
            except Exception:  # noqa: BLE001  the minute store is not running
                minute = None
            out.append(dict(exchange=code, title=m.title, symbols=symbols.get(code, 0),
                            last_daily=session_date(daily) if daily else "",
                            last_minute=_iso(minute) if minute else "",
                            last_setup_scan=scans.get(code, ""),
                            last_screen_1d=(screen_dates(code, "1D") or [""])[0],
                            last_screen_1w=(screen_dates(code, "1W") or [""])[0]))
    return dict(exchanges=out)


@router.get("/status")
def status(admin: AdminDep, request: Request) -> dict:
    """The dashboard: data per exchange, the jobs an admin can run, the running job and the recent ones."""
    from app.admin_jobs import KINDS, markets, runner

    r = runner()
    return dict(_data_status(request), markets=markets(),
                kinds=[dict(kind=k, title=t) for k, (_, t) in KINDS.items()],
                running=r.current.summary() if r.current and r.current.state == "running" else None,
                jobs=[j.summary() for j in r.jobs])


@router.post("/jobs")
def start_job(admin: AdminDep, body: JobIn) -> dict:
    from app.admin_jobs import Busy, runner

    try:
        return runner().start(body.kind, body.market, body.date, by=admin.email).summary()
    except Busy as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/jobs/{job_id}")
def job_log(admin: AdminDep, job_id: int, since: int = Query(0, ge=0)) -> dict:
    """A job and its output lines from `since` on (the dashboard follows a running job with this)."""
    from app.admin_jobs import runner

    j = runner().get(job_id)
    if j is None:
        raise HTTPException(404, "no such job")
    return dict(j.summary(), lines=j.log[since:], next=len(j.log))
