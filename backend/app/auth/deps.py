"""The signed-in user, for every route (require_user) and the WebSocket (user_for_websocket)."""
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.auth import sessions
from app.auth.activity import recorder
from app.config import get_settings
from app.db import SessionLocal
from app.models import User

LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}


class NotSignedIn(HTTPException):
    def __init__(self):
        super().__init__(401, "not signed in")


def _factory(app):
    return getattr(app.state, "session_factory", SessionLocal)


def resolve(app, cookies, client_host: str | None) -> tuple[User, int | None] | None:
    """(user, session id) of a request or WebSocket; None when nobody is signed in.
    AUTH_MODE=local: every request from this computer is the local user (development and tests)."""
    s = get_settings()
    with _factory(app)() as db:
        if s.auth_mode == "local":
            if (client_host or "") not in LOOPBACK:
                raise HTTPException(403, "AUTH_MODE=local only serves this computer; use AUTH_MODE=google")
            return sessions.local_user(db), None
        got = sessions.lookup(db, cookies.get(sessions.COOKIE))
        return (got[0], got[1].id) if got else None


def require_user(request: Request) -> User:
    """The signed-in user (401 when there is none); counts the request in the user's activity."""
    got = resolve(request.app, request.cookies, request.client.host if request.client else None)
    if got is None:
        raise NotSignedIn()
    user, sid = got
    request.state.user = user
    path = request.url.path
    symbol = request.query_params.get("symbol") if path == "/history" and "to" not in request.query_params else None
    recorder.record(user.id, sid, path, symbol)
    if recorder.due():
        recorder.flush(_factory(request.app))
    return user


def require_admin(user: Annotated[User, Depends(require_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(403, "admins only")
    return user


UserDep = Annotated[User, Depends(require_user)]
AdminDep = Annotated[User, Depends(require_admin)]


def user_for_websocket(ws) -> User | None:
    try:
        got = resolve(ws.app, ws.cookies, ws.client.host if ws.client else None)
    except HTTPException:
        return None
    if got is None:
        return None
    recorder.record(got[0].id, got[1], "/ws")
    return got[0]
