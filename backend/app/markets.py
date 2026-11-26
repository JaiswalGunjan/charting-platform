"""The market registry: every exchange's time zone, session, currency and display facts, from app/markets.toml
(MARKETS_FILE overrides the file). Product code asks here instead of naming exchanges.

    from app.markets import market, markets, default_exchange
    market("NYSE").currency  -> "USD"
"""
import tomllib
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_FILE = Path(__file__).with_name("markets.toml")


@dataclass(frozen=True)
class MarketInfo:
    code: str              # NSE, NYSE, ... (the prefix of a symbol: NSE:RELIANCE)
    title: str
    country: str
    timezone: str          # IANA zone
    tz_label: str
    open: str              # "09:15" local
    close: str
    currency: str          # ISO 4217
    screen: bool           # listed in the Pattern Screener
    order: int             # position in the file: the first is the default market

    @property
    def open_minute(self) -> int:
        h, m = self.open.split(":")
        return int(h) * 60 + int(m)

    def as_dict(self) -> dict:
        return asdict(self) | {"open_minute": self.open_minute}


def _file() -> Path:
    from app.config import get_settings

    f = getattr(get_settings(), "markets_file", "")
    return Path(f) if f else DEFAULT_FILE


@lru_cache(maxsize=4)
def _load(path: str) -> dict[str, MarketInfo]:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for i, (code, m) in enumerate(raw.items()):
        out[code.upper()] = MarketInfo(code=code.upper(), title=m.get("title", code), country=m.get("country", ""),
                                       timezone=m["timezone"], tz_label=m.get("tz_label", m["timezone"]),
                                       open=m.get("open", "00:00"), close=m.get("close", "24:00"),
                                       currency=m["currency"], screen=bool(m.get("screen", True)), order=i)
    if not out:
        raise ValueError(f"no markets in {path}")
    return out


def markets() -> dict[str, MarketInfo]:
    """Every market, in the file's order."""
    return _load(str(_file()))


def market(code: str) -> MarketInfo:
    """A market by code; an unknown code gets the default market's facts (a symbol of an exchange not listed)."""
    ms = markets()
    return ms.get(code.upper()) or next(iter(ms.values()))


def default_exchange() -> str:
    return next(iter(markets()))


def rank(code: str) -> int:
    """Sort key of an exchange (the file's order; unknown exchanges last)."""
    m = markets().get(code.upper())
    return m.order if m else len(markets())
