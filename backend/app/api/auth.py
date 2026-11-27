"""Sign-in with Google (OpenID Connect, authorization-code flow; Authlib), sign-out, and who is signed in.

    GET  /auth/me                      the signed-in user (401 when nobody is)
    GET  /auth/google/login?next=/...  to Google's sign-in; back to `next` afterwards
    GET  /auth/google/callback         Google's answer: verify, record the sign-in, start a session, go to `next`
    POST /auth/logout                  end the session
    PUT  /auth/me                      the user's own details (phone)

Google is asked only for the basic scopes (openid email profile): no Google review and no user cap once the app is
published. The ID token's signature, audience, issuer, expiry and nonce are checked by Authlib; the email must be
verified. The browser gets a session cookie (HttpOnly, SameSite=Lax, Secure with COOKIE_SECURE=true)."""
import logging
import time
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth import sessions
from app.auth.client import client_ip, location, location_text, user_agent
from app.auth.deps import UserDep, _factory, resolve
from app.config import get_settings
from app.models import LoginEvent, User

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
SCOPES = "openid email profile"
_oauth = {}


def google_client():
    """Authlib's Google client (made once per client id). Tests replace this function."""
    s = get_settings()
    if not (s.google_client_id and s.google_client_secret):
        raise HTTPException(503, "Google sign-in is not set up: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env")
    if s.google_client_id not in _oauth:
        from authlib.integrations.starlette_client import OAuth

        oauth = OAuth()
        oauth.register("google", client_id=s.google_client_id, client_secret=s.google_client_secret,
                       server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
                       client_kwargs={"scope": SCOPES})
        _oauth[s.google_client_id] = oauth.google
    return _oauth[s.google_client_id]


def safe_next(target: str | None) -> str:
    """Only a path on this site: no other host, no scheme (an open redirect would help phishing)."""
    t = (target or "/").strip()
    if not t.startswith("/") or t.startswith("//") or "\\" in t or "://" in t.split("?")[0]:
        return "/"
    return t


def user_out(u: User) -> dict:
    return dict(id=u.id, email=u.email, name=u.name or u.email, given_name=u.given_name, picture=u.picture,
                phone=u.phone, is_admin=u.is_admin, provider=u.provider, auth_mode=get_settings().auth_mode)


@router.get("/me")
def me(request: Request) -> dict:
    got = resolve(request.app, request.cookies, request.client.host if request.client else None)
    if got is None:
        raise HTTPException(401, "not signed in")
    return user_out(got[0])


class MeIn(BaseModel):
    phone: str = Field("", max_length=32, pattern=r"^[0-9+()\- ]*$")


@router.put("/me")
def update_me(body: MeIn, user: UserDep, request: Request) -> dict:
    with _factory(request.app)() as db:
        u = db.get(User, user.id)
        u.phone = body.phone.strip()
        db.commit()
        return user_out(u)


@router.get("/google/login")
async def google_login(request: Request, next: str = "/") -> RedirectResponse:  # noqa: A002
    s = get_settings()
    if s.auth_mode != "google":
        return RedirectResponse(safe_next(next), status_code=302)
    request.session["next"] = safe_next(next)
    redirect_uri = s.public_url.rstrip("/") + s.api_prefix + "/auth/google/callback"
    return await google_client().authorize_redirect(request, redirect_uri)


def _refuse(request: Request, reason: str, email: str = "") -> RedirectResponse:
    _record(request, None, ok=False, reason=reason, email=email)
    return RedirectResponse("/?signin_error=" + quote(reason), status_code=302)


def _record(request: Request, user: User | None, ok: bool, reason: str = "", email: str = "") -> dict:
    ip = client_ip(request.headers, request.client.host if request.client else None)
    loc = location(ip)
    with _factory(request.app)() as db:
        db.add(LoginEvent(user_id=user.id if user else None, ok=ok, reason=reason[:200], email=email[:320], ip=ip,
                          user_agent=user_agent(request.headers), **loc))
        db.commit()
    return dict(ip=ip, location=location_text(loc))


@router.get("/google/callback")
async def google_callback(request: Request) -> RedirectResponse:
    from authlib.integrations.base_client import OAuthError

    try:
        token = await google_client().authorize_access_token(request)
    except OAuthError as e:
        return _refuse(request, f"Google sign-in failed: {e.error}")
    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower()
    if not info.get("sub") or not email:
        return _refuse(request, "Google gave no account id or email", email)
    if not info.get("email_verified"):
        return _refuse(request, "this Google account's email is not verified", email)
    s = get_settings()
    admins = {x.strip().lower() for x in s.admin_emails.split(",") if x.strip()}
    now = time.time()
    with _factory(request.app)() as db:
        u = db.scalar(select(User).where(User.provider == "google", User.subject == info["sub"]))
        if u is None:
            u = User(provider="google", subject=info["sub"], created_at=now, first_login_at=now)
            db.add(u)
        if u.disabled:
            db.rollback()
            return _refuse(request, "this account is disabled", email)
        u.email, u.email_verified = email, True
        u.name, u.given_name, u.family_name = info.get("name", ""), info.get("given_name", ""), info.get("family_name", "")
        u.picture, u.locale, u.hosted_domain = info.get("picture", ""), info.get("locale", ""), info.get("hd", "")
        u.is_admin = u.is_admin or email in admins
        u.login_count = (u.login_count or 0) + 1
        u.last_login_at = now
        db.commit()
        db.refresh(u)
    seen = _record(request, u, ok=True, email=email)
    with _factory(request.app)() as db:
        row = db.get(User, u.id)
        row.last_ip, row.last_location, row.last_user_agent = seen["ip"], seen["location"], user_agent(request.headers)
        db.commit()
        token_value = sessions.new_session(db, row, seen["ip"], user_agent(request.headers))
    resp = RedirectResponse(safe_next(request.session.pop("next", "/")), status_code=302)
    resp.set_cookie(sessions.COOKIE, token_value, max_age=s.session_days * 86400, httponly=True,
                    secure=s.cookie_secure, samesite="lax", path="/")
    log.info("signed in: %s (%s)", email, seen["ip"])
    return resp


@router.post("/logout")
def logout(request: Request) -> dict:
    with _factory(request.app)() as db:
        sessions.end_session(db, request.cookies.get(sessions.COOKIE))
    from fastapi.responses import JSONResponse

    resp = JSONResponse(dict(ok=True))
    resp.delete_cookie(sessions.COOKIE, path="/")
    return resp
