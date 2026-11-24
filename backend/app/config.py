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
    data_source: str = "synthetic"  # "synthetic" | "kite"

    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_access_token: str = ""

    # live data
    live_enabled: bool = True
    redis_url: str = ""                 # e.g. redis://localhost:6379/0 ; empty = in-memory
    ws_throttle_ms: int = 250           # per-subscription conflation interval
    synthetic_tick_interval_ms: int = 500

    # AI analyst (Anthropic). Empty key = SDK default resolution (env var / `ant auth login`).
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "medium"          # low | medium | high | xhigh | max
    ai_fallbacks: bool = True          # server-side refusal fallback

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
