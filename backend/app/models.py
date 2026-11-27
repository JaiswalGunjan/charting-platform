"""Product + market-data tables.

Candles live in the relational DB for the prototype (TimescaleDB hypertable in
Postgres); the blueprint moves them to ClickHouse later.
"""
import time

from sqlalchemy import JSON, BigInteger, Boolean, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

LOCAL_USER_ID = 1  # single-user prototype; real auth comes later


def _now() -> float:
    return time.time()


class Symbol(Base):
    __tablename__ = "symbols"
    __table_args__ = (UniqueConstraint("exchange", "ticker", name="uq_symbol_exchange_ticker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exchange: Mapped[str] = mapped_column(String(16))          # NSE, BSE
    ticker: Mapped[str] = mapped_column(String(64))            # RELIANCE, NIFTY 50
    name: Mapped[str] = mapped_column(String(256), default="")
    type: Mapped[str] = mapped_column(String(16), default="EQ")  # EQ, INDEX
    isin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    lot_size: Mapped[int] = mapped_column(Integer, default=1)
    tick_size: Mapped[float] = mapped_column(Float, default=0.05)
    instrument_token: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)

    @property
    def full(self) -> str:
        return f"{self.exchange}:{self.ticker}"


class Candle(Base):
    """OHLCV bar. ts = bar open time, epoch seconds UTC. tf in {"1m", "1h", "1D"}."""

    __tablename__ = "candles"
    __table_args__ = (Index("ix_candles_sym_tf_ts", "symbol_id", "tf", "ts"),)

    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"), primary_key=True)
    tf: Mapped[str] = mapped_column(String(4), primary_key=True)
    ts: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    o: Mapped[float] = mapped_column(Float)
    h: Mapped[float] = mapped_column(Float)
    l: Mapped[float] = mapped_column(Float)  # noqa: E741
    c: Mapped[float] = mapped_column(Float)
    v: Mapped[float] = mapped_column(Float, default=0)
    oi: Mapped[float | None] = mapped_column(Float, nullable=True)


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, default=LOCAL_USER_ID, index=True)
    name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[float] = mapped_column(Float, default=_now)
    items: Mapped[list["WatchlistItem"]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan", order_by="WatchlistItem.position")


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "symbol_id", name="uq_watchlist_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), index=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    watchlist: Mapped[Watchlist] = relationship(back_populates="items")
    symbol: Mapped[Symbol] = relationship(lazy="joined")


class Alert(Base):
    """condition_json: {"op": "crosses_above"|"crosses_below"|"above"|"below", "price": float}"""
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, default=LOCAL_USER_ID, index=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"), index=True)
    condition_json: Mapped[dict] = mapped_column(JSON)
    message: Mapped[str] = mapped_column(String(512), default="")
    channels: Mapped[list] = mapped_column(JSON, default=lambda: ["ws"])
    once: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)  # active|triggered|disabled
    ref_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # price when (re)armed
    created_at: Mapped[float] = mapped_column(Float, default=_now)
    triggered_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    symbol: Mapped[Symbol] = relationship(lazy="joined")


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    ts: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    message: Mapped[str] = mapped_column(String(512), default="")


class CustomIndicator(Base):
    """A user's formula indicator (see app/indicators/formula.py).

    inputs_json: [{"name", "default", "min", "max"}]; plots_json: [{"name", "expr", "style", "color"}]
    """
    __tablename__ = "custom_indicators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, default=LOCAL_USER_ID, index=True)
    name: Mapped[str] = mapped_column(String(80))
    overlay: Mapped[bool] = mapped_column(Boolean, default=False)
    inputs_json: Mapped[list] = mapped_column(JSON, default=list)
    plots_json: Mapped[list] = mapped_column(JSON, default=list)
    levels_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[float] = mapped_column(Float, default=_now)
    updated_at: Mapped[float] = mapped_column(Float, default=_now)


class Drawing(Base):
    """A user's chart drawings for one symbol (shared by all timeframes).

    items_json: [{"id", "kind", "pts": [{"t": epoch s, "p": price}], "color", "width", "text"?, ...}]
    """
    __tablename__ = "drawings"
    __table_args__ = (UniqueConstraint("user_id", "symbol_id", name="uq_drawings_user_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, default=LOCAL_USER_ID, index=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"), index=True)
    items_json: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[float] = mapped_column(Float, default=_now)


class AiLog(Base):
    """Every AI request/response, with the exact context the model saw (audit + evals)."""
    __tablename__ = "ai_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[float] = mapped_column(Float, default=_now, index=True)
    user_id: Mapped[int] = mapped_column(Integer, default=LOCAL_USER_ID)
    feature: Mapped[str] = mapped_column(String(32))            # "explain_chart"
    symbol: Mapped[str] = mapped_column(String(80))
    tf: Mapped[str] = mapped_column(String(4))
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_json: Mapped[dict] = mapped_column(JSON)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)


# ---------------------------------------------------------------- users, sign-in and activity (app/auth)
class User(Base):
    """A person who signs in. Google gives the profile (basic scopes: openid email profile); the rest is ours.
    id 1 is the built-in local user (AUTH_MODE=local, and the owner of the data from before sign-in existed)."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), default="google")       # google | local
    subject: Mapped[str] = mapped_column(String(64))                          # Google's permanent user id ("sub")
    email: Mapped[str] = mapped_column(String(320), index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    name: Mapped[str] = mapped_column(String(200), default="")
    given_name: Mapped[str] = mapped_column(String(100), default="")
    family_name: Mapped[str] = mapped_column(String(100), default="")
    picture: Mapped[str] = mapped_column(String(500), default="")
    locale: Mapped[str] = mapped_column(String(16), default="")
    hosted_domain: Mapped[str] = mapped_column(String(100), default="")       # Google Workspace domain ("hd")
    phone: Mapped[str] = mapped_column(String(32), default="")               # not from Google: entered by the user
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float, default=_now)
    first_login_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_login_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_seen_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    login_count: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int] = mapped_column(BigInteger, default=0)
    active_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    last_ip: Mapped[str] = mapped_column(String(64), default="")
    last_location: Mapped[str] = mapped_column(String(200), default="")
    last_user_agent: Mapped[str] = mapped_column(String(400), default="")

    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_users_provider_subject"),)


class UserSession(Base):
    """A signed-in browser. The cookie holds a random token; only its SHA-256 is stored, so a leaked table cannot be
    used to sign in."""
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[float] = mapped_column(Float, default=_now)
    expires_at: Mapped[float] = mapped_column(Float)
    last_seen_at: Mapped[float] = mapped_column(Float, default=_now)
    active_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(400), default="")
    ended_at: Mapped[float | None] = mapped_column(Float, nullable=True)       # sign-out


class LoginEvent(Base):
    """One sign-in (or a refused one): when, from where, with what."""
    __tablename__ = "login_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    at: Mapped[float] = mapped_column(Float, default=_now, index=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str] = mapped_column(String(200), default="")             # why a sign-in was refused
    email: Mapped[str] = mapped_column(String(320), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    country: Mapped[str] = mapped_column(String(64), default="")
    region: Mapped[str] = mapped_column(String(100), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    user_agent: Mapped[str] = mapped_column(String(400), default="")


class UserDay(Base):
    """A user's activity on one day (UTC): requests and active time (gaps under 5 minutes between requests)."""
    __tablename__ = "user_days"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)            # YYYY-MM-DD
    requests: Mapped[int] = mapped_column(Integer, default=0)
    active_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    first_seen_at: Mapped[float] = mapped_column(Float, default=_now)
    last_seen_at: Mapped[float] = mapped_column(Float, default=_now)


class UserFeatureDay(Base):
    """Requests per feature (chart, screener, scanner, ai, ...) per user and day."""
    __tablename__ = "user_feature_days"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    feature: Mapped[str] = mapped_column(String(32), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class UserSymbol(Base):
    """The stocks a user opened: how often, first and last time."""
    __tablename__ = "user_symbols"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(80), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    first_at: Mapped[float] = mapped_column(Float, default=_now)
    last_at: Mapped[float] = mapped_column(Float, default=_now)
