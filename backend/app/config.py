from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'charting.db').as_posix()}"
    data_source: str = "synthetic"  # "synthetic" | "kite" | "eod" (local CSV history)

    # the replaceable parts (app/ports.py, app/providers.py): a built-in name or "package.module:Class"
    setup_scanner: str = "swingscanner"   # "swingscanner" | "none"; the default one when several are set
    setup_scanners: str = ""              # several at once: "swingscanner,mypkg.scan:Fast" (empty: just setup_scanner)
    pattern_engines: str = ""             # several combined: "rulebook,mypkg.pat:Candles" (empty: just pattern_engine)
    pattern_engine: str = "rulebook"
    screen_store: str = "json"
    bar_store: str = "sql"
    # a store per stored timeframe, e.g. "1m=mypkg.ch:ClickHouseBars" (others use bar_store): years of minute bars
    # for many markets in a column store, daily and hourly bars where they are
    bar_stores: str = ""
    # minute bars in PostgreSQL + TimescaleDB, the last 2 years (owner's choice, 26 Nov 2026): BAR_STORES=1m=timescale
    minute_database_url: str = ""         # empty: DATABASE_URL (which must then be PostgreSQL)
    minute_retention_days: int = 730      # chunks older than this are dropped; older bars are not written
    minute_compress_after_days: int = 30
    markets_file: str = ""                # the market registry (default: app/markets.toml)

    # sign-in (app/auth, app/api/auth.py)
    auth_mode: str = "google"             # google | local (local: this computer is the built-in local user; dev/tests)
    google_client_id: str = ""            # Google Cloud Console -> Credentials -> OAuth client ID (Web application)
    google_client_secret: str = ""
    public_url: str = "http://localhost:5173"   # where the UI is served; Google's redirect URI is
    api_prefix: str = "/api"                    #   public_url + api_prefix + /auth/google/callback
    session_secret: str = ""              # signs the short-lived sign-in state cookie; empty: random at each start
    session_days: int = 30                # a sign-in lasts this long
    cookie_secure: bool = False           # True on HTTPS (the live site)
    admin_emails: str = ""                # comma list: these users are admins (run scans, see user stats)
    trust_proxy: bool = False             # behind a reverse proxy: the client IP is X-Forwarded-For's first entry
    activity_retention_days: int = 365    # sign-in records and daily activity older than this are deleted
    admin_jobs_dry_run: bool = False      # dashboard jobs only log what they would do (browser tests)
    # a live feed per exchange: "NSE=kite,BSE=kite,NYSE=mypkg.vendor:Ticks" (kite | synthetic | static | import path);
    # exchanges not named use the default feed (kite when DATA_SOURCE=kite, else simulated or none)
    tick_sources: str = ""

    # local end-of-day CSVs (python -m app.cli import-eod)
    eod_dir: str = ""                  # path to a market_data_daily folder
    scanner_dir: str = ""              # SwingScanner folder (has SwingScanner.exe, swingbt_config.ini, scans/)
    scanner_url: str = "http://127.0.0.1:8765"  # the scanner's local server, when it is running
    # the scanner writes a chart page per signal (most of a scan's size); Charting Lab draws its own charts, so a finished
    # scan's charts/ folder is removed (owner's choice, 26 Nov 2026). True keeps them.
    scanner_keep_charts: bool = False
    screens_dir: str = ""              # saved "patterns formed today" screens (default backend/data/screens)
    scanner_src: str = ""              # TranscriptExtract folder (setup explanations); found from scanner_dir if empty
    eod_hourly_dir: str = ""           # path to a market_data_hourly folder (optional)
    eod_exchanges: list[str] = ["NSE"]

    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_access_token: str = ""

    # live data
    live_enabled: bool = True
    redis_url: str = ""                 # e.g. redis://localhost:6379/0 ; empty = in-memory
    ws_throttle_ms: int = 250           # per-subscription conflation interval
    synthetic_tick_interval_ms: int = 500
    # without a real feed (Kite), prices stay at the last real close unless this is on (random-walk ticks, a demo /
    # test aid; off at the owner's request, 25 Nov 2026)
    simulate_ticks: bool = False

    # AI analyst (Anthropic). Empty key = SDK default resolution (env var / `ant auth login`).
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "medium"          # low | medium | high | xhigh | max
    ai_fallbacks: bool = True          # server-side refusal fallback

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
