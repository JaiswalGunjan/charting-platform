"""Copy Charting Lab's SQLite database into PostgreSQL + TimescaleDB (a trial copy; the SQLite file is only read).

    python scripts/sqlite_to_postgres.py --exchanges NSE --tf 1D                     # step 1: NSE daily bars
    python scripts/sqlite_to_postgres.py --exchanges NSE,BSE,NYSE,NASDAQ --tf 1D,1h  # everything

  1. creates the app's tables in PostgreSQL (the app's own models)
  2. makes `candles` a TimescaleDB hypertable on ts (90-day chunks)
  3. copies every symbol and the small tables (watchlists, drawings, alerts, custom indicators) as they are
  4. copies the bars of the chosen exchanges / timeframes with COPY (fast bulk load)
  5. compresses chunks older than 30 days (segment by symbol and timeframe, ordered by time) and reports sizes

The target is PG_URL (default postgresql+psycopg://charting@127.0.0.1:5433/charting, the local test server in
.tools/pgdata). Re-running replaces what an earlier run copied.
"""
import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from sqlalchemy import inspect, text  # noqa: E402

from app.db import Base, init_db, make_engine  # noqa: E402

SQLITE = BACKEND / "data" / "charting.db"
PG_URL = os.environ.get("PG_URL", "postgresql+psycopg://charting@127.0.0.1:5433/charting")
CHUNK_SECONDS = 90 * 86400
BATCH = 200_000


def mb(n) -> str:
    return f"{(n or 0) / 1e6:,.0f} MB"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exchanges", default="NSE")
    ap.add_argument("--tf", default="1D", help="1D, 1h, 1m or a comma list")
    a = ap.parse_args(argv)
    exchanges = [e.strip().upper() for e in a.exchanges.split(",") if e.strip()]
    tfs = [t.strip() for t in a.tf.split(",") if t.strip()]
    t0 = time.time()

    pg = make_engine(PG_URL)
    with pg.begin() as c:
        c.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
    init_db(pg)
    with pg.begin() as c:
        is_ht = c.execute(text("SELECT count(*) FROM timescaledb_information.hypertables "
                               "WHERE hypertable_name = 'candles'")).scalar()
        if not is_ht:
            c.execute(text(f"SELECT create_hypertable('candles', by_range('ts', {CHUNK_SECONDS}), migrate_data => true)"))
            print("candles is now a TimescaleDB hypertable (90-day chunks)")

    src = sqlite3.connect(f"file:{SQLITE.as_posix()}?mode=ro", uri=True)
    raw = pg.raw_connection()
    try:
        cur = raw.cursor()
        # small tables first (symbols, then the user tables), replaced as a whole
        small = [t for t in Base.metadata.sorted_tables if t.name != "candles"]
        cur.execute("TRUNCATE " + ", ".join(t.name for t in small) + " CASCADE")
        for t in small:
            cols = [col.name for col in t.columns]
            if not src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t.name,)).fetchone():
                continue
            rows = src.execute(f"SELECT {', '.join(cols)} FROM {t.name}").fetchall()
            with cur.copy(f"COPY {t.name} ({', '.join(cols)}) FROM STDIN") as cp:
                for r in rows:
                    cp.write_row(r)
            pk = [col.name for col in t.primary_key.columns]
            if len(pk) == 1 and rows:                                        # keep id sequences past the copied ids
                cur.execute(f"SELECT setval(pg_get_serial_sequence('{t.name}', '{pk[0]}'), "
                            f"(SELECT coalesce(max({pk[0]}), 1) FROM {t.name}))")
            print(f"{t.name}: {len(rows):,} rows")
        raw.commit()

        # bars of the chosen exchanges and timeframes
        ids = [r[0] for r in src.execute(
            f"SELECT id FROM symbols WHERE exchange IN ({','.join('?' * len(exchanges))})", exchanges)]
        q = (f"SELECT symbol_id, tf, ts, o, h, l, c, v, oi FROM candles WHERE tf IN ({','.join('?' * len(tfs))}) "
             f"AND symbol_id IN (SELECT id FROM symbols WHERE exchange IN ({','.join('?' * len(exchanges))}))")
        n, t1 = 0, time.time()
        cur.execute("DELETE FROM candles WHERE tf = ANY(%s) AND symbol_id = ANY(%s)", (tfs, ids))
        rows = src.execute(q, tfs + exchanges)
        with cur.copy("COPY candles (symbol_id, tf, ts, o, h, l, c, v, oi) FROM STDIN") as cp:
            while True:
                batch = rows.fetchmany(BATCH)
                if not batch:
                    break
                for r in batch:
                    cp.write_row(r)
                n += len(batch)
                print(f"  bars copied: {n:,} ({n / max(time.time() - t1, 1e-9):,.0f}/s)", flush=True)
        raw.commit()
        print(f"candles: {n:,} bars of {','.join(exchanges)} {','.join(tfs)} in {time.time() - t1:.0f}s")

        cur.execute("ANALYZE candles")
        cur.execute("SELECT hypertable_size('candles')")
        before = cur.fetchone()[0]
        # compression: chunks older than 30 days, per symbol and timeframe, ordered by time
        cur.execute("ALTER TABLE candles SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol_id, tf', "
                    "timescaledb.compress_orderby = 'ts')")
        raw.commit()
        t2 = time.time()
        cur.execute(f"SELECT count(*) FROM (SELECT compress_chunk(c, if_not_compressed => true) "
                    f"FROM show_chunks('candles', older_than => {int(time.time()) - 30 * 86400}) c) x")
        chunks = cur.fetchone()[0]
        raw.commit()
        cur.execute("SELECT hypertable_size('candles')")
        after = cur.fetchone()[0]
        print(f"compressed {chunks} chunks in {time.time() - t2:.0f}s: {mb(before)} -> {mb(after)}")
        cur.execute("SELECT pg_database_size(current_database())")
        print(f"database size: {mb(cur.fetchone()[0])}; total {time.time() - t0:.0f}s")
    finally:
        raw.close()
        src.close()
    tables = inspect(pg).get_table_names()
    print("tables:", ", ".join(sorted(tables)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
