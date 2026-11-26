from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import NamedTuple, Protocol

IST = timezone(timedelta(hours=5, minutes=30))
NSE_OPEN = time(9, 15)
NSE_CLOSE = time(15, 30)
MINUTES_PER_SESSION = 375  # 09:15 -> 15:30

BASE_TFS = ("1m", "1D")  # what we store; everything else is resampled


@dataclass(frozen=True)
class SymbolInfo:
    exchange: str
    ticker: str
    name: str = ""
    type: str = "EQ"
    isin: str | None = None
    lot_size: int = 1
    tick_size: float = 0.05
    instrument_token: int | None = None

    @property
    def full(self) -> str:
        return f"{self.exchange}:{self.ticker}"


class Bar(NamedTuple):
    ts: int  # bar open, epoch seconds UTC
    o: float
    h: float
    l: float  # noqa: E741
    c: float
    v: float
    oi: float | None = None


class MarketDataSource(Protocol):
    name: str

    def symbols(self) -> list[SymbolInfo]: ...

    def candles(self, sym: SymbolInfo, tf: str, start: date, end: date) -> list[Bar]:
        """Bars for tf in BASE_TFS with bar dates in [start, end] (IST calendar days)."""
        ...


def session_open_ts(d: date) -> int:
    return int(datetime.combine(d, NSE_OPEN, IST).timestamp())


def day_ts(d: date) -> int:
    """Daily bar timestamp: IST midnight (matches Kite's daily candles)."""
    return int(datetime.combine(d, time(0, 0), IST).timestamp())


def parse_symbol(s: str) -> tuple[str, str]:
    """'NSE:RELIANCE' -> ('NSE', 'RELIANCE'); a bare 'RELIANCE' is on the default market (the registry's first)."""
    if ":" in s:
        ex, t = s.split(":", 1)
        return ex.strip().upper(), t.strip().upper()
    from app.markets import default_exchange

    return default_exchange(), s.strip().upper()
