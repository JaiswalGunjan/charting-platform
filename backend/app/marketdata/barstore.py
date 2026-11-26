"""Stored price bars in the SQL database (BAR_STORE=sql): app.ports.BarStore.

The only module that reads or writes the candles table. SQLite and PostgreSQL/TimescaleDB both work (DATABASE_URL);
another store (ClickHouse, Parquet files, a market-data service) is a new class with these methods.

Bars are base-timeframe bars (1m, 1h, 1D; other timeframes are resampled on read by app.marketdata.history).
Reads return numpy arrays: one row per bar, columns as named by `cols` (default ts, o, h, l, c, v), ascending time.
`session` is the caller's unit of work (a SQLAlchemy Session here); a store that has none ignores it.
"""
from collections.abc import Sequence

import numpy as np
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.marketdata.base import BASE_TFS, Bar
from app.models import Candle, Symbol

DAY = 86400
_BATCH = 1000          # rows per multi-row upsert; x9 columns stays under SQLite/Postgres parameter limits
_BULK = 20_000         # rows per executemany chunk of a bulk insert
_COL = {"sid": Candle.symbol_id, "ts": Candle.ts, "o": Candle.o, "h": Candle.h, "l": Candle.l, "c": Candle.c,
        "v": Candle.v}
OHLCV = ("ts", "o", "h", "l", "c", "v")


def _upsert_stmt(session: Session):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as ins
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as ins
    else:
        raise NotImplementedError(f"upsert not implemented for {dialect}")
    return ins(Candle)


def _array(rows, ncols: int) -> np.ndarray:
    return np.array(rows, dtype=float).reshape(-1, ncols) if rows else np.empty((0, ncols))


def _of_exchange(exchange: str):
    return Candle.symbol_id.in_(select(Symbol.id).where(Symbol.exchange == exchange.upper()))


class SqlBarStore:
    name = "sql"

    # ---------------------------------------------------------------- one symbol
    def has(self, session: Session, symbol_id: int, tf: str) -> bool:
        """Does the symbol have any bars of `tf`?"""
        return session.execute(select(Candle.ts).where(Candle.symbol_id == symbol_id, Candle.tf == tf)
                               .limit(1)).first() is not None

    def read_latest(self, session: Session, symbol_id: int, tf: str, limit: int, to: int | None = None,
                    frm: int | None = None, cols: Sequence[str] = OHLCV) -> np.ndarray:
        """The newest `limit` bars with time in [frm, to), ascending."""
        stmt = select(*(_COL[k] for k in cols)).where(Candle.symbol_id == symbol_id, Candle.tf == tf)
        if to is not None:
            stmt = stmt.where(Candle.ts < to)
        if frm is not None:
            stmt = stmt.where(Candle.ts >= frm)
        rows = session.execute(stmt.order_by(Candle.ts.desc()).limit(limit)).all()
        return _array(rows[::-1], len(cols))

    def read_after(self, session: Session, symbol_id: int, tf: str, frm: int, limit: int,
                   cols: Sequence[str] = OHLCV) -> np.ndarray:
        """The first `limit` bars with time >= frm, ascending."""
        rows = session.execute(select(*(_COL[k] for k in cols))
                               .where(Candle.symbol_id == symbol_id, Candle.tf == tf, Candle.ts >= frm)
                               .order_by(Candle.ts).limit(limit)).all()
        return _array(rows, len(cols))

    def upsert(self, session: Session, symbol_id: int, tf: str, bars: Sequence[Bar]) -> int:
        """Insert or update bars (same symbol, tf and time = the same bar); commits."""
        if tf not in BASE_TFS:
            raise ValueError(f"only base timeframes {BASE_TFS} are stored, got {tf!r}")
        for i in range(0, len(bars), _BATCH):
            rows = [dict(symbol_id=symbol_id, tf=tf, ts=b.ts, o=b.o, h=b.h, l=b.l, c=b.c, v=b.v, oi=b.oi)
                    for b in bars[i:i + _BATCH]]
            stmt = _upsert_stmt(session).values(rows)
            stmt = stmt.on_conflict_do_update(index_elements=["symbol_id", "tf", "ts"],
                                              set_={k: stmt.excluded[k] for k in ("o", "h", "l", "c", "v", "oi")})
            session.execute(stmt)
        session.commit()
        return len(bars)

    # ---------------------------------------------------------------- many symbols
    def read_many(self, session: Session, symbol_ids: Sequence[int], tf: str, since: int, until: int,
                  cols: Sequence[str] = OHLCV) -> np.ndarray:
        """Bars of many symbols with time in [since, until]: rows (symbol id, *cols), by symbol then time."""
        if not symbol_ids:
            return np.empty((0, len(cols) + 1))
        rows = session.execute(select(Candle.symbol_id, *(_COL[k] for k in cols))
                               .where(Candle.tf == tf, Candle.symbol_id.in_(list(symbol_ids)), Candle.ts >= since,
                                      Candle.ts <= until)
                               .order_by(Candle.symbol_id, Candle.ts)).all()
        return _array(rows, len(cols) + 1)

    def last_time(self, session: Session, exchange: str, tf: str, upto: int | None = None) -> int | None:
        """The newest bar time of any symbol of `exchange` (at or before `upto`)."""
        cond = [Candle.tf == tf, _of_exchange(exchange)]
        if upto is not None:
            cond.append(Candle.ts <= upto)
        top = upto if upto is not None else 2 ** 31
        # the last 40 days first: a bounded range reads only the newest chunks (TimescaleDB) / index pages;
        # the whole history only when nothing is that recent
        ts = session.scalar(select(func.max(Candle.ts)).where(*cond, Candle.ts >= top - 40 * DAY)) \
            if upto is not None else None
        if ts is None:
            ts = session.scalar(select(func.max(Candle.ts)).where(*cond))
        return int(ts) if ts is not None else None

    def times(self, session: Session, exchange: str, tf: str, since: int) -> list[int]:
        """Distinct bar times of an exchange from `since`, ascending."""
        ts = session.execute(select(Candle.ts).distinct().where(Candle.tf == tf, Candle.ts >= since,
                                                                _of_exchange(exchange))).scalars().all()
        return sorted(int(t) for t in ts)

    def delete_bars(self, session: Session, exchange: str, tfs: Sequence[str], since: int | None = None,
                    until: int | None = None, symbol_ids: Sequence[int] | None = None) -> None:
        """Delete the exchange's bars of `tfs` with time in [since, until] (None = open-ended), or only those of
        `symbol_ids`; commits."""
        cond = [Candle.symbol_id.in_(list(symbol_ids)) if symbol_ids is not None else _of_exchange(exchange),
                Candle.tf.in_(tuple(tfs))]
        if since is not None:
            cond.append(Candle.ts >= since)
        if until is not None:
            cond.append(Candle.ts <= until)
        session.execute(delete(Candle).where(*cond))
        session.commit()

    def replace_exchange(self, session: Session, exchange: str, drop_tfs: Sequence[str], tf: str,
                         symbol_ids: np.ndarray, data: dict[str, np.ndarray]) -> int:
        """Delete the exchange's bars of `drop_tfs`, then insert `data` (ts, o, h, l, c, v arrays, one per bar, with
        `symbol_ids` alongside) as `tf`; commits. A bulk load: no per-row conflict check."""
        session.execute(delete(Candle).where(_of_exchange(exchange), Candle.tf.in_(tuple(drop_tfs))))
        return self.append(session, tf, symbol_ids, data)

    def append(self, session: Session, tf: str, symbol_ids: np.ndarray, data: dict[str, np.ndarray]) -> int:
        """Insert bars that are not stored yet (after delete_bars of their range), in chunks; commits. The bulk path
        for large imports: one call per exchange and month of minute bars keeps memory flat."""
        stmt = insert(Candle)
        n = len(symbol_ids)
        for i in range(0, n, _BULK):
            sl = slice(i, i + _BULK)
            rows = [{"symbol_id": int(s), "tf": tf, "ts": int(ts), "o": float(o), "h": float(h), "l": float(l),
                     "c": float(c), "v": float(v), "oi": None}
                    for s, ts, o, h, l, c, v in zip(symbol_ids[sl], data["ts"][sl], data["o"][sl],  # noqa: E741
                                                   data["h"][sl], data["l"][sl], data["c"][sl], data["v"][sl])]
            session.execute(stmt, rows)
        session.commit()
        return n


class RoutedBarStore:
    """Several bar stores as one (BAR_STORES): each stored timeframe goes to its own store, the rest to the default.
    Reads and writes name a timeframe, so each call goes to exactly one store; an exchange-wide delete goes to every
    store that holds one of the timeframes."""

    name = "routed"

    def __init__(self, default, routes: dict):
        self.default, self.routes = default, dict(routes)

    def store_for(self, tf: str):
        return self.routes.get(tf, self.default)

    def has(self, session, symbol_id, tf):
        return self.store_for(tf).has(session, symbol_id, tf)

    def read_latest(self, session, symbol_id, tf, limit, to=None, frm=None, cols=OHLCV):
        return self.store_for(tf).read_latest(session, symbol_id, tf, limit, to=to, frm=frm, cols=cols)

    def read_after(self, session, symbol_id, tf, frm, limit, cols=OHLCV):
        return self.store_for(tf).read_after(session, symbol_id, tf, frm, limit, cols=cols)

    def upsert(self, session, symbol_id, tf, bars):
        return self.store_for(tf).upsert(session, symbol_id, tf, bars)

    def read_many(self, session, symbol_ids, tf, since, until, cols=OHLCV):
        return self.store_for(tf).read_many(session, symbol_ids, tf, since, until, cols=cols)

    def last_time(self, session, exchange, tf, upto=None):
        return self.store_for(tf).last_time(session, exchange, tf, upto)

    def times(self, session, exchange, tf, since):
        return self.store_for(tf).times(session, exchange, tf, since)

    def _by_store(self, tfs):
        groups: dict[int, tuple] = {}
        for tf in tfs:
            st = self.store_for(tf)
            groups.setdefault(id(st), (st, []))[1].append(tf)
        return groups.values()

    def delete_bars(self, session, exchange, tfs, since=None, until=None, symbol_ids=None):
        for st, mine in self._by_store(tfs):
            st.delete_bars(session, exchange, mine, since, until, symbol_ids=symbol_ids)

    def append(self, session, tf, symbol_ids, data):
        return self.store_for(tf).append(session, tf, symbol_ids, data)

    def replace_exchange(self, session, exchange, drop_tfs, tf, symbol_ids, data):
        self.delete_bars(session, exchange, drop_tfs)
        return self.append(session, tf, symbol_ids, data)
