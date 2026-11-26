"""Minute bars in PostgreSQL + TimescaleDB, the last 2 years (owner's choice, 26 Nov 2026): app.ports.BarStore for 1m.

    BAR_STORES=1m=timescale
    MINUTE_DATABASE_URL=postgresql+psycopg://charting@127.0.0.1:5433/charting   (empty: DATABASE_URL)
    MINUTE_RETENTION_DAYS=730   MINUTE_COMPRESS_AFTER_DAYS=30

Its own hypertable, `candles_1m` (symbol_id, ts, o, h, l, c, v, oi), in 7-day chunks:
- chunks older than MINUTE_COMPRESS_AFTER_DAYS are compressed (by symbol, ordered by time), by a TimescaleDB policy;
- chunks older than MINUTE_RETENTION_DAYS are dropped whole by a retention policy (cheap: no row deletes);
- bars older than the retention window are not written at all (an import of older files skips them).
Daily and hourly bars, symbols and everything else stay in the main database (SQLite or PostgreSQL); the store looks up
which symbols belong to an exchange through the caller's session, so the two databases need not be the same.
"""
import logging
import time
from collections.abc import Sequence

import numpy as np
from sqlalchemy import (BigInteger, Column, Float, Integer, MetaData, Table, create_engine, delete, func, select,
                        text)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.marketdata.base import Bar
from app.models import Symbol

log = logging.getLogger(__name__)
DAY = 86400
CHUNK_SECONDS = 7 * DAY
_BATCH = 2000
OHLCV = ("ts", "o", "h", "l", "c", "v")

meta = MetaData()
candles_1m = Table(
    "candles_1m", meta,
    Column("symbol_id", Integer, primary_key=True),
    Column("ts", BigInteger, primary_key=True),          # epoch seconds (the bar's open)
    Column("o", Float, nullable=False), Column("h", Float, nullable=False), Column("l", Float, nullable=False),
    Column("c", Float, nullable=False), Column("v", Float, nullable=False), Column("oi", Float),
)
_COL = {"sid": candles_1m.c.symbol_id, **{k: candles_1m.c[k] for k in OHLCV}}


def _array(rows, ncols: int) -> np.ndarray:
    return np.array(rows, dtype=float).reshape(-1, ncols) if rows else np.empty((0, ncols))


class TimescaleMinuteStore:
    """1-minute bars only (route other timeframes elsewhere: BAR_STORES=1m=timescale)."""

    name = "timescale"

    def __init__(self, url: str | None = None, retention_days: int | None = None,
                 compress_after_days: int | None = None):
        from app.config import get_settings

        s = get_settings()
        self.url = url or s.minute_database_url or s.database_url
        if not self.url.startswith("postgresql"):
            raise ValueError("the minute store needs PostgreSQL + TimescaleDB: set MINUTE_DATABASE_URL "
                             f"(got {self.url.split(':', 1)[0]})")
        self.retention_days = retention_days or s.minute_retention_days
        self.compress_after_days = compress_after_days or s.minute_compress_after_days
        self.engine = create_engine(self.url, pool_pre_ping=True)
        self._ready = False

    # ---------------------------------------------------------------- schema and policies
    def ensure_schema(self) -> None:
        """Create the hypertable and its compression and retention policies (idempotent)."""
        if self._ready:
            return
        with self.engine.begin() as c:
            c.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
            meta.create_all(c, tables=[candles_1m])
            c.execute(text(f"SELECT create_hypertable('candles_1m', by_range('ts', {CHUNK_SECONDS}), "
                           "if_not_exists => true)"))
            # integer time: TimescaleDB's policies need "now" in the same unit (epoch seconds)
            c.execute(text("CREATE OR REPLACE FUNCTION candles_1m_now() RETURNS BIGINT LANGUAGE SQL STABLE AS "
                           "$$ SELECT extract(epoch FROM now())::BIGINT $$"))
            c.execute(text("SELECT set_integer_now_func('candles_1m', 'candles_1m_now', replace_if_exists => true)"))
            c.execute(text("ALTER TABLE candles_1m SET (timescaledb.compress, "
                           "timescaledb.compress_segmentby = 'symbol_id', timescaledb.compress_orderby = 'ts')"))
            c.execute(text("SELECT remove_compression_policy('candles_1m', if_exists => true)"))
            c.execute(text(f"SELECT add_compression_policy('candles_1m', compress_after => "
                           f"{self.compress_after_days * DAY}::BIGINT)"))
            c.execute(text("SELECT remove_retention_policy('candles_1m', if_exists => true)"))
            c.execute(text(f"SELECT add_retention_policy('candles_1m', drop_after => {self.retention_days * DAY}::BIGINT)"))
        self._ready = True

    def oldest_kept(self, now: float | None = None) -> int:
        """The first bar time inside the retention window."""
        return int((now or time.time()) - self.retention_days * DAY)

    def apply_retention(self, now: float | None = None) -> int:
        """Drop the chunks past the window now (the policy does it daily on its own); returns chunks dropped."""
        self.ensure_schema()
        with self.engine.begin() as c:
            return len(c.execute(text("SELECT drop_chunks('candles_1m', older_than => :t)"),
                                 dict(t=self.oldest_kept(now))).all())

    def compress_now(self, now: float | None = None) -> int:
        """Compress the chunks past MINUTE_COMPRESS_AFTER_DAYS now (the policy does it on its own)."""
        self.ensure_schema()
        cutoff = int((now or time.time()) - self.compress_after_days * DAY)
        with self.engine.begin() as c:
            return len(c.execute(text("SELECT compress_chunk(ch, if_not_compressed => true) FROM "
                                      "show_chunks('candles_1m', older_than => :t) ch"), dict(t=cutoff)).all())

    def stats(self) -> dict:
        self.ensure_schema()
        with self.engine.connect() as c:
            n, lo, hi = c.execute(text("SELECT count(*), min(ts), max(ts) FROM candles_1m")).one()
            size = c.execute(text("SELECT hypertable_size('candles_1m')")).scalar()
            chunks = c.execute(text("SELECT count(*), count(*) FILTER (WHERE is_compressed) FROM "
                                    "timescaledb_information.chunks WHERE hypertable_name = 'candles_1m'")).one()
        return dict(bars=n, first=lo, last=hi, bytes=size, chunks=chunks[0], compressed_chunks=chunks[1],
                    retention_days=self.retention_days, compress_after_days=self.compress_after_days)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _check(tf: str) -> None:
        if tf != "1m":
            raise ValueError(f"the TimescaleDB minute store keeps 1m bars only, not {tf!r} (BAR_STORES=1m=timescale)")

    @staticmethod
    def _ids(session, exchange: str) -> list[int]:
        """Symbols of an exchange, from the main database (the caller's session)."""
        return list(session.execute(select(Symbol.id).where(Symbol.exchange == exchange.upper())).scalars())

    def _keep(self, symbol_ids, data: dict) -> tuple:
        """Drop bars older than the retention window."""
        ts = np.asarray(data["ts"], dtype=np.int64)
        mask = ts >= self.oldest_kept()
        if mask.all():
            return np.asarray(symbol_ids), data
        return np.asarray(symbol_ids)[mask], {k: np.asarray(v)[mask] for k, v in data.items()}

    # ---------------------------------------------------------------- BarStore
    def has(self, session, symbol_id: int, tf: str) -> bool:
        self._check(tf)
        self.ensure_schema()
        with self.engine.connect() as c:
            return c.execute(select(candles_1m.c.ts).where(candles_1m.c.symbol_id == symbol_id).limit(1)).first() \
                is not None

    def read_latest(self, session, symbol_id: int, tf: str, limit: int, to: int | None = None,
                    frm: int | None = None, cols: Sequence[str] = OHLCV) -> np.ndarray:
        self._check(tf)
        self.ensure_schema()
        stmt = select(*(_COL[k] for k in cols)).where(candles_1m.c.symbol_id == symbol_id)
        if to is not None:
            stmt = stmt.where(candles_1m.c.ts < to)
        if frm is not None:
            stmt = stmt.where(candles_1m.c.ts >= frm)
        with self.engine.connect() as c:
            rows = c.execute(stmt.order_by(candles_1m.c.ts.desc()).limit(limit)).all()
        return _array(rows[::-1], len(cols))

    def read_after(self, session, symbol_id: int, tf: str, frm: int, limit: int,
                   cols: Sequence[str] = OHLCV) -> np.ndarray:
        self._check(tf)
        self.ensure_schema()
        with self.engine.connect() as c:
            rows = c.execute(select(*(_COL[k] for k in cols))
                             .where(candles_1m.c.symbol_id == symbol_id, candles_1m.c.ts >= frm)
                             .order_by(candles_1m.c.ts).limit(limit)).all()
        return _array(rows, len(cols))

    def upsert(self, session, symbol_id: int, tf: str, bars: Sequence[Bar]) -> int:
        self._check(tf)
        self.ensure_schema()
        floor = self.oldest_kept()
        rows = [dict(symbol_id=symbol_id, ts=b.ts, o=b.o, h=b.h, l=b.l, c=b.c, v=b.v, oi=b.oi)
                for b in bars if b.ts >= floor]
        with self.engine.begin() as c:
            for i in range(0, len(rows), _BATCH):
                stmt = pg_insert(candles_1m).values(rows[i:i + _BATCH])
                c.execute(stmt.on_conflict_do_update(index_elements=["symbol_id", "ts"],
                                                     set_={k: stmt.excluded[k] for k in ("o", "h", "l", "c", "v", "oi")}))
        return len(rows)

    def read_many(self, session, symbol_ids: Sequence[int], tf: str, since: int, until: int,
                  cols: Sequence[str] = OHLCV) -> np.ndarray:
        self._check(tf)
        if not symbol_ids:
            return np.empty((0, len(cols) + 1))
        self.ensure_schema()
        with self.engine.connect() as c:
            rows = c.execute(select(candles_1m.c.symbol_id, *(_COL[k] for k in cols))
                             .where(candles_1m.c.symbol_id.in_(list(symbol_ids)), candles_1m.c.ts >= since,
                                    candles_1m.c.ts <= until)
                             .order_by(candles_1m.c.symbol_id, candles_1m.c.ts)).all()
        return _array(rows, len(cols) + 1)

    def last_time(self, session, exchange: str, tf: str, upto: int | None = None) -> int | None:
        self._check(tf)
        ids = self._ids(session, exchange)
        if not ids:
            return None
        self.ensure_schema()
        stmt = select(func.max(candles_1m.c.ts)).where(candles_1m.c.symbol_id.in_(ids))
        if upto is not None:
            stmt = stmt.where(candles_1m.c.ts <= upto)
        with self.engine.connect() as c:
            ts = c.execute(stmt).scalar()
        return int(ts) if ts is not None else None

    def times(self, session, exchange: str, tf: str, since: int) -> list[int]:
        self._check(tf)
        ids = self._ids(session, exchange)
        if not ids:
            return []
        self.ensure_schema()
        with self.engine.connect() as c:
            ts = c.execute(select(candles_1m.c.ts).distinct()
                           .where(candles_1m.c.symbol_id.in_(ids), candles_1m.c.ts >= since)).scalars().all()
        return sorted(int(t) for t in ts)

    def delete_bars(self, session, exchange: str, tfs: Sequence[str], since: int | None = None,
                    until: int | None = None, symbol_ids: Sequence[int] | None = None) -> None:
        if "1m" not in tfs:
            return
        ids = list(symbol_ids) if symbol_ids is not None else self._ids(session, exchange)
        if not ids:
            return
        self.ensure_schema()
        cond = [candles_1m.c.symbol_id.in_(ids)]
        if since is not None:
            cond.append(candles_1m.c.ts >= since)
        if until is not None:
            cond.append(candles_1m.c.ts <= until)
        with self.engine.begin() as c:
            c.execute(delete(candles_1m).where(*cond))

    def append(self, session, tf: str, symbol_ids, data: dict) -> int:
        """Bulk insert (after delete_bars of the range); bars past the retention window are skipped."""
        self._check(tf)
        self.ensure_schema()
        sid, data = self._keep(symbol_ids, data)
        n = len(sid)
        if not n:
            return 0
        cols = [np.asarray(sid, np.int64), np.asarray(data["ts"], np.int64)] + \
            [np.asarray(data[k], float) for k in ("o", "h", "l", "c", "v")]
        raw = self.engine.raw_connection()                     # COPY: the fast path for millions of bars
        try:
            cur = raw.cursor()
            with cur.copy("COPY candles_1m (symbol_id, ts, o, h, l, c, v) FROM STDIN") as cp:
                for row in zip(*(a.tolist() for a in cols)):
                    cp.write_row(row)
            raw.commit()
        finally:
            raw.close()
        return n

    def replace_exchange(self, session, exchange: str, drop_tfs: Sequence[str], tf: str, symbol_ids, data: dict) -> int:
        self.delete_bars(session, exchange, drop_tfs)
        return self.append(session, tf, symbol_ids, data) if tf == "1m" else 0
