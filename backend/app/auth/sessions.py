"""Browser sessions: a random token in an HttpOnly cookie; the database keeps only its SHA-256."""
import hashlib
import secrets
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import LOCAL_USER_ID, User, UserSession

COOKIE = "cl_session"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(db: Session, user: User, ip: str, user_agent: str) -> str:
    """Start a session for `user`; returns the token for the cookie."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    db.add(UserSession(token_hash=_hash(token), user_id=user.id, created_at=now, last_seen_at=now,
                       expires_at=now + get_settings().session_days * 86400, ip=ip[:64], user_agent=user_agent[:400]))
    db.commit()
    return token


def lookup(db: Session, token: str | None) -> tuple[User, UserSession] | None:
    """The user and session behind a cookie token, if the session is live and the user may sign in."""
    if not token:
        return None
    s = db.scalar(select(UserSession).where(UserSession.token_hash == _hash(token)))
    if s is None or s.ended_at is not None or s.expires_at < time.time():
        return None
    u = db.get(User, s.user_id)
    if u is None or u.disabled:
        return None
    return u, s


def end_session(db: Session, token: str | None) -> None:
    if not token:
        return
    s = db.scalar(select(UserSession).where(UserSession.token_hash == _hash(token)))
    if s is not None and s.ended_at is None:
        s.ended_at = time.time()
        db.commit()


def local_user(db: Session) -> User:
    """The built-in local user (id 1): AUTH_MODE=local, and the owner of the data from before sign-in existed."""
    u = db.get(User, LOCAL_USER_ID)
    if u is None:
        u = User(id=LOCAL_USER_ID, provider="local", subject="local", email="local@localhost", email_verified=True,
                 name="Local user", is_admin=True, first_login_at=time.time())
        db.add(u)
        db.commit()
        if db.get_bind().dialect.name == "postgresql":
            # an id given by hand does not move PostgreSQL's counter: without this the first Google user would
            # also be given id 1 (and fail)
            from sqlalchemy import text

            db.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), "
                            "GREATEST((SELECT MAX(id) FROM users), 1))"))
            db.commit()
    return u
