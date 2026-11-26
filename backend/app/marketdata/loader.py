"""Symbol-master and historical-candle loading (idempotent upserts)."""
import logging
from collections.abc import Iterable, Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.marketdata.base import Bar, MarketDataSource, SymbolInfo, parse_symbol
from app.models import Symbol
from app.providers import bar_store

log = logging.getLogger(__name__)
_BATCH = 1000  # rows per multi-row INSERT; x9 columns stays under SQLite/Postgres param limits


def get_source(settings: Settings) -> MarketDataSource:
    if settings.data_source == "kite":
        from app.marketdata.kite import KiteSource

        return KiteSource(settings)
    if settings.data_source == "synthetic":
        from app.marketdata.synthetic import SyntheticSource

        return SyntheticSource()
    if settings.data_source == "eod":
        raise ValueError("DATA_SOURCE=eod loads history with `python -m app.cli import-eod`")
    raise ValueError(f"unknown DATA_SOURCE {settings.data_source!r}")


def _insert(session: Session, model):  # noqa: ANN001
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise NotImplementedError(f"upsert not implemented for {dialect}")
    return insert(model)


def upsert_symbols(session: Session, infos: Iterable[SymbolInfo]) -> int:
    rows = [
        dict(exchange=s.exchange, ticker=s.ticker, name=s.name, type=s.type, isin=s.isin,
             lot_size=s.lot_size, tick_size=s.tick_size, instrument_token=s.instrument_token)
        for s in infos
    ]
    for i in range(0, len(rows), _BATCH):
        stmt = _insert(session, Symbol).values(rows[i:i + _BATCH])
        stmt = stmt.on_conflict_do_update(
            index_elements=["exchange", "ticker"],
            set_={k: stmt.excluded[k] for k in
                  ("name", "type", "isin", "lot_size", "tick_size", "instrument_token")},
        )
        session.execute(stmt)
    session.commit()
    return len(rows)


def upsert_candles(session: Session, symbol_id: int, tf: str, bars: Sequence[Bar]) -> int:
    """Store bars (the bar store in use; same symbol, tf and time = the same bar)."""
    return bar_store().upsert(session, symbol_id, tf, bars)


def resolve_symbol(session: Session, sym: str) -> Symbol | None:
    ex, ticker = parse_symbol(sym)
    return session.scalar(select(Symbol).where(Symbol.exchange == ex, Symbol.ticker == ticker))


def to_info(s: Symbol) -> SymbolInfo:
    return SymbolInfo(exchange=s.exchange, ticker=s.ticker, name=s.name, type=s.type, isin=s.isin,
                      lot_size=s.lot_size, tick_size=s.tick_size, instrument_token=s.instrument_token)


def load_history(session: Session, source: MarketDataSource, sym: Symbol,
                 tf: str, start: date, end: date) -> int:
    bars = source.candles(to_info(sym), tf, start, end)
    n = upsert_candles(session, sym.id, tf, bars)
    log.info("%s %s %s..%s: %d bars", sym.full, tf, start, end, n)
    return n
