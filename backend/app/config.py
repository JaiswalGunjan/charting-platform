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
