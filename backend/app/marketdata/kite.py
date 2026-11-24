"""Zerodha Kite Connect source.

PRIVATE PROTOTYPING ONLY: Zerodha's terms forbid displaying or redistributing
this data on external platforms. Production needs an NSE/BSE-authorised vendor.
"""
import time as _time
from datetime import date, datetime, timedelta

from app.config import Settings
from app.marketdata.base import Bar, SymbolInfo, day_ts

# Kite historical API: max span per request by interval
_MAX_SPAN = {"1m": timedelta(days=60), "1D": timedelta(days=2000)}
_INTERVAL = {"1m": "minute", "1D": "day"}
_RATE_SLEEP = 0.35  # historical API allows ~3 req/s


class KiteSource:
    name = "kite"

    def __init__(self, settings: Settings, exchanges: tuple[str, ...] = ("NSE",)):
        from kiteconnect import KiteConnect

        if not settings.kite_api_key or not settings.kite_access_token:
            raise RuntimeError(
                "KITE_API_KEY and KITE_ACCESS_TOKEN must be set in .env "
                "(run `python -m app.cli kite-login` to get a fresh access token)"
            )
        self.kite = KiteConnect(api_key=settings.kite_api_key)
        self.kite.set_access_token(settings.kite_access_token)
        self.exchanges = exchanges

    def symbols(self) -> list[SymbolInfo]:
        out: list[SymbolInfo] = []
        for ex in self.exchanges:
            for ins in self.kite.instruments(ex):
                seg, itype = ins.get("segment"), ins.get("instrument_type")
                if seg == "INDICES":
                    typ = "INDEX"
                elif seg == ex and itype == "EQ":
                    typ = "EQ"
                else:
                    continue  # skip F&O, bonds, etc. for now
                out.append(SymbolInfo(
                    exchange=ex,
                    ticker=ins["tradingsymbol"],
                    name=ins.get("name") or "",
                    type=typ,
                    lot_size=int(ins.get("lot_size") or 1),
                    tick_size=float(ins.get("tick_size") or 0.05),
                    instrument_token=int(ins["instrument_token"]),
                ))
        return out

    def candles(self, sym: SymbolInfo, tf: str, start: date, end: date) -> list[Bar]:
        if sym.instrument_token is None:
            raise ValueError(f"{sym.full} has no instrument_token; load symbols from kite first")
        span = _MAX_SPAN[tf]
        out: list[Bar] = []
        cur = datetime.combine(start, datetime.min.time())
        stop = datetime.combine(end, datetime.max.time().replace(microsecond=0))
        while cur <= stop:
            chunk_end = min(cur + span - timedelta(seconds=1), stop)
            rows = self.kite.historical_data(sym.instrument_token, cur, chunk_end, _INTERVAL[tf], oi=False)
            for r in rows:
                dt: datetime = r["date"]
                ts = day_ts(dt.date()) if tf == "1D" else int(dt.timestamp())
                out.append(Bar(ts, float(r["open"]), float(r["high"]), float(r["low"]),
                               float(r["close"]), float(r.get("volume") or 0), r.get("oi")))
            cur = chunk_end + timedelta(seconds=1)
            _time.sleep(_RATE_SLEEP)
        return out


def login_url(settings: Settings) -> str:
    from kiteconnect import KiteConnect

    return KiteConnect(api_key=settings.kite_api_key).login_url()


def exchange_request_token(settings: Settings, request_token: str) -> str:
    from kiteconnect import KiteConnect

    kite = KiteConnect(api_key=settings.kite_api_key)
    data = kite.generate_session(request_token, api_secret=settings.kite_api_secret)
    return data["access_token"]
