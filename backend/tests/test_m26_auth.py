"""Sign-in with Google (a fake Google here: no network), the gate on every route, per-user data, admins, and the
recorded user data and activity."""
import time

import pytest
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import auth as auth_api
from app.auth.activity import IDLE_S, Recorder, feature_of
from app.config import get_settings
from app.models import LoginEvent, User, UserSession, UserSymbol

GATED = ["/history?symbol=NSE:TCS&tf=1D", "/symbols?q=TC", "/markets", "/indicators", "/patterns", "/watchlists",
         "/drawings?symbol=NSE:TCS", "/custom-indicators", "/alerts", "/scanner", "/screener/patterns-today",
         "/quotes?symbols=NSE:TCS", "/admin/users"]


class FakeGoogle:
    """Stands in for Authlib's Google client: the next sign-in returns `who`."""

    def __init__(self):
        self.who = None
        self.redirects = []

    async def authorize_redirect(self, request, redirect_uri):
        self.redirects.append(redirect_uri)
        return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?fake=1", status_code=302)

    async def authorize_access_token(self, request):
        if self.who is None:
            from authlib.integrations.base_client import OAuthError

            raise OAuthError(error="access_denied")
        return {"userinfo": self.who}


def person(sub, email, verified=True, **kw):
    name = kw.pop("name", email.split("@")[0].title())
    return dict(sub=sub, email=email, email_verified=verified, name=name, given_name="Given", family_name="Family",
                picture="https://lh3.example/p.jpg", locale="en-IN", **kw)


@pytest.fixture()
def google(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "auth_mode", "google")
    monkeypatch.setattr(s, "admin_emails", "owner@example.com")
    fake = FakeGoogle()
    monkeypatch.setattr(auth_api, "google_client", lambda: fake)
    client.cookies.clear()
    yield fake
    client.cookies.clear()


def sign_in(c: TestClient, fake: FakeGoogle, who: dict, next_: str = "/") -> object:
    r = c.get("/auth/google/login", params={"next": next_}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("https://accounts.google.com/")
    fake.who = who
    return c.get("/auth/google/callback", follow_redirects=False)


def test_every_route_needs_a_signed_in_user(client, google):
    for path in GATED:
        assert client.get(path).status_code == 401, path
    assert client.post("/screener/patterns-today/run", json={}).status_code == 401
    assert client.get("/health").status_code == 200                       # monitoring stays open
    assert client.get("/auth/me").status_code == 401
    # a page opened by its link (the scanner's report) goes to sign-in, then back to it
    r = client.get("/scanner/report/NSE_daily_2026-11-23/index.html?x=1", headers={"accept": "text/html"},
                   follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == \
        "/?next=%2Fapi%2Fscanner%2Freport%2FNSE_daily_2026-11-23%2Findex.html%3Fx%3D1"


def test_the_websocket_needs_a_signed_in_user(client, google):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
    assert e.value.code == 4401


def test_google_sign_in_records_the_user_and_returns_to_the_link(client, google, session_factory):
    r = sign_in(client, google, person("g-1", "Asha@Example.com", hd="example.com"), next_="/?page=setups&scan=x")
    assert r.status_code == 302 and r.headers["location"] == "/?page=setups&scan=x"
    assert google.redirects == ["http://localhost:5173/api/auth/google/callback"]
    cookie = r.headers["set-cookie"].lower()
    assert "cl_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    me = client.get("/auth/me").json()
    assert me["email"] == "asha@example.com" and me["is_admin"] is False and me["auth_mode"] == "google"
    for path in GATED[:-1]:
        assert client.get(path).status_code == 200, path                   # signed in: everything opens
    assert client.get("/admin/users").status_code == 403                    # but admin pages are for admins
    with session_factory() as db:
        u = db.scalar(select(User).where(User.subject == "g-1"))
        assert (u.name, u.given_name, u.family_name, u.locale, u.hosted_domain, u.login_count) == \
            ("Asha", "Given", "Family", "en-IN", "example.com", 1)
        assert u.email_verified and u.first_login_at and u.last_ip == "testclient"
        ev = db.scalars(select(LoginEvent).where(LoginEvent.user_id == u.id)).all()
        assert len(ev) == 1 and ev[0].ok and ev[0].ip == "testclient"
        token_rows = db.scalars(select(UserSession).where(UserSession.user_id == u.id)).all()
        assert len(token_rows) == 1 and len(token_rows[0].token_hash) == 64   # only the hash is stored
    client.cookies.clear()
    sign_in(client, google, person("g-1", "asha@example.com", name="Asha K"))
    with session_factory() as db:
        u = db.scalar(select(User).where(User.subject == "g-1"))
        assert u.login_count == 2 and u.name == "Asha K"                    # the same user, updated


@pytest.mark.parametrize("bad", ["https://evil.example/", "//evil.example", "/\\evil.example", "javascript:alert(1)"])
def test_no_redirect_to_another_site_after_sign_in(client, google, bad):
    r = sign_in(client, google, person("g-2", "b@example.com"), next_=bad)
    assert r.headers["location"] == "/"


def test_refused_sign_ins_are_recorded(client, google, session_factory):
    r = sign_in(client, google, person("g-3", "c@example.com", verified=False))
    assert r.status_code == 302 and "signin_error" in r.headers["location"] and "cl_session" not in r.headers.get("set-cookie", "")
    google.who = None
    r = client.get("/auth/google/callback", follow_redirects=False)            # the user cancelled at Google
    assert "signin_error" in r.headers["location"]
    with session_factory() as db:
        reasons = [e.reason for e in db.scalars(select(LoginEvent).where(LoginEvent.ok.is_(False)))]
    assert any("not verified" in x for x in reasons) and any("access_denied" in x for x in reasons)
    assert client.get("/auth/me").status_code == 401


def test_each_user_has_their_own_data(client, google):
    a = client
    b = TestClient(client.app)
    sign_in(a, google, person("g-a", "a1@example.com"))
    sign_in(b, google, person("g-b", "b1@example.com"))
    wl = a.post("/watchlists", json={"name": "A's list"}).json()
    a.put("/drawings", params={"symbol": "NSE:TCS"}, json={"items": [{"id": "x", "kind": "hline", "pts": [{"t": 1, "p": 3500}]}]})
    assert "A's list" in [w["name"] for w in a.get("/watchlists").json()]
    assert "A's list" not in [w["name"] for w in b.get("/watchlists").json()]    # B gets their own starter list
    assert b.get("/drawings", params={"symbol": "NSE:TCS"}).json()["items"] == []
    assert b.delete(f"/watchlists/{wl['id']}").status_code == 404                # nor can B touch A's
    assert a.get("/drawings", params={"symbol": "NSE:TCS"}).json()["items"][0]["id"] == "x"


def test_alerts_go_to_their_owner_only():
    from app.live.service import Connection, LiveService

    got = {1: [], 2: []}
    live = LiveService.__new__(LiveService)
    live.all_conns = set()
    for uid in (1, 2):
        c = Connection(lambda m: None, 0.1, user_id=uid)
        c.push_event = got[uid].append
        live.all_conns.add(c)
    live.send_to_user(2, {"type": "alert", "alert_id": 7})
    assert got == {1: [], 2: [{"type": "alert", "alert_id": 7}]}


def test_admins_see_user_stats_and_run_scans(client, google, session_factory):
    other = TestClient(client.app)
    sign_in(other, google, person("g-u", "user@example.com"))
    assert other.post("/screener/patterns-today/run", json={"exchange": "NSE", "tf": "1D"}).status_code == 403
    assert other.post("/scanner/run", json={"market": "NSE"}).status_code == 403
    other.get("/history", params={"symbol": "NSE:TCS", "tf": "1D"})            # opens a stock
    other.get("/history", params={"symbol": "NSE:TCS", "tf": "1D", "to": 1})   # paging back: not a new opening
    sign_in(client, google, person("g-o", "owner@example.com"))                # ADMIN_EMAILS
    assert client.get("/auth/me").json()["is_admin"] is True
    data = client.get("/admin/users").json()
    u = next(x for x in data["users"] if x["email"] == "user@example.com")
    assert u["login_count"] == 1 and u["request_count"] >= 4 and u["last_ip"] == "testclient" and u["last_seen_at"]
    detail = client.get(f"/admin/users/{u['id']}").json()
    assert detail["symbols"][0]["symbol"] == "NSE:TCS" and detail["symbols"][0]["count"] == 1
    assert {"chart", "pattern_screener", "setup_screener"} <= set(detail["features"])
    assert detail["logins"][0]["ok"] and detail["days"][0]["requests"] >= 4
    csv_text = client.get("/admin/users.csv").text
    assert csv_text.splitlines()[0].startswith("id,name,email") and "user@example.com" in csv_text
    # disabling an account signs it out everywhere
    assert client.patch(f"/admin/users/{u['id']}", json={"disabled": True}).json()["ok"]
    assert other.get("/watchlists").status_code == 401
    me = client.get("/auth/me").json()["id"]
    assert client.patch(f"/admin/users/{me}", json={"disabled": True}).status_code == 400


def test_sign_out_ends_the_session(client, google):
    sign_in(client, google, person("g-s", "s@example.com"))
    assert client.get("/watchlists").status_code == 200
    kept = dict(client.cookies)
    assert client.post("/auth/logout").json()["ok"]
    client.cookies.update(kept)                                                # even a copied cookie is dead now
    assert client.get("/watchlists").status_code == 401


def test_google_not_set_up(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_mode", "google")
    monkeypatch.setattr(get_settings(), "google_client_id", "")
    r = client.get("/auth/google/login", follow_redirects=False)
    assert r.status_code == 503 and "GOOGLE_CLIENT_ID" in r.json()["detail"]


def test_local_mode_serves_this_computer_only(client):
    from fastapi import HTTPException

    from app.auth.deps import resolve

    assert client.get("/auth/me").json()["provider"] == "local"
    with pytest.raises(HTTPException) as e:
        resolve(client.app, {}, "203.0.113.9")
    assert e.value.status_code == 403


def test_active_time_counts_short_gaps_only():
    r = Recorder()
    t0 = 1_800_000_000.0
    for dt in (0, 30, 90, 90 + IDLE_S + 1, 90 + IDLE_S + 61):               # 30 s, 60 s, idle, 60 s
        r.record(9, None, "/history", now=t0 + dt)
    (n, active, first, last), = r.days.values()
    assert n == 5 and active == 150 and first == t0
    assert feature_of("/scanner/scans/x") == "setup_screener" and feature_of("/history") == "chart"


def test_old_activity_is_pruned(session_factory):
    from app.api.admin import prune

    with session_factory() as db:
        db.add(LoginEvent(user_id=None, at=time.time() - 400 * 86400, email="old@example.com"))
        db.add(LoginEvent(user_id=None, at=time.time(), email="new@example.com"))
        db.commit()
    assert prune(session_factory, 365)["logins"] >= 1
    with session_factory() as db:
        left = {e.email for e in db.scalars(select(LoginEvent))}
    assert "old@example.com" not in left and "new@example.com" in left


def test_the_built_in_users_id_is_never_given_to_a_google_user(client, google, session_factory):
    """Id 1 (the built-in user and the data from before sign-in) is reserved when the app starts."""
    sign_in(client, google, person("g-first", "first@example.com"))
    me = client.get("/auth/me").json()
    assert me["id"] != 1 and me["provider"] == "google"
    with session_factory() as db:
        assert db.get(User, 1).provider == "local"
