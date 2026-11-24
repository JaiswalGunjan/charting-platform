"""'Patterns formed today': every symbol of an exchange, the rulebook patterns that fire on its latest bar.

For each exchange and timeframe (daily, or weekly built from the daily bars) the bars are read in batches of
symbols (one query per batch instead of one per symbol), the pattern rules run on the last bar only, and the
result is saved as JSON under backend/data/screens/ so the dashboard opens instantly. Symbols whose last bar is
older than the exchange's latest session (delisted, suspended) are skipped. Support/resistance levels are not a
signal, so they are not screened.
"""
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.marketdata.timeframes import TIMEFRAMES, bucket_starts, market_for, resample
from app.models import Candle, Symbol
from app.patterns.engine import PATTERNS, scan

log = logging.getLogger(__name__)
DAY = 86400
SCREEN_TFS = ("1D", "1W")
SCREEN_IDS = {p.id for p in PATTERNS} - {"sr"}
# daily bars read per symbol: enough warm-up for the daily rules, and ~260 weeks for the weekly ones
HISTORY_DAYS = {"1D": 600, "1W": 1900}          # calendar days
MIN_BARS = 60
BATCH = 300                                    # symbols per query
SCREEN_DIR = Path(__file__).resolve().parents[2] / "data" / "screens"


@dataclass
class Progress:
    state: str = "idle"                        # idle | running | done | error
    exchange: str = ""
    tf: str = ""
    done: int = 0
    total: int = 0
    msg: str = ""
    started: float | None = None
    finished: float | None = None
    errors: list[str] = field(default_factory=list)


def latest_hits(t, o, h, l, c, v) -> list[dict]:  # noqa: E741
    """Pattern hits on the last bar only (the rules are causal: a bar's result never depends on later bars)."""
    out = scan(t, o, h, l, c, v, SCREEN_IDS, first=len(t) - 1)
    return [m for m in out["markers"] if m["t"] == int(t[-1])]


def screens_dir() -> Path:
    """Where screens are saved: SCREENS_DIR if set (the end-to-end tests use their own), else SCREEN_DIR."""
    from app.config import get_settings

    d = get_settings().screens_dir
    return Path(d) if d else SCREEN_DIR


def screen_path(exchange: str, tf: str, root: Path | None = None) -> Path:
    return (root or screens_dir()) / f"{exchange.upper()}_{tf}.json"


def load_screen(exchange: str, tf: str, root: Path | None = None) -> dict | None:
    p = screen_path(exchange, tf, root)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_screen(session_factory: sessionmaker, exchange: str, tf: str, root: Path | None = None,
               progress: Progress | None = None, on_step: Callable[[Progress], None] | None = None) -> dict:
    """Screen every symbol of `exchange` on its latest `tf` bar; saves and returns the result."""
    exchange, t0 = exchange.upper(), time.perf_counter()
    if tf not in SCREEN_TFS:
        raise ValueError(f"timeframe must be one of {SCREEN_TFS}")
    pr = progress or Progress()
    pr.exchange, pr.tf, pr.done, pr.errors = exchange, tf, 0, []
    market = market_for(exchange)
    with session_factory() as s:
        syms = s.execute(select(Symbol.id, Symbol.ticker, Symbol.name, Symbol.type)
                         .where(Symbol.exchange == exchange).order_by(Symbol.ticker)).all()
        last_day = s.scalar(select(func.max(Candle.ts)).where(
            Candle.tf == "1D", Candle.symbol_id.in_(select(Symbol.id).where(Symbol.exchange == exchange))))
    pr.total = len(syms)
    rows: list[dict] = []
    scanned = 0
    if last_day is None:
        return _save(dict(exchange=exchange, tf=tf, as_of=None, rows=[], scanned=0), exchange, tf, root)
    latest_bar = int(last_day) if tf == "1D" else int(bucket_starts(TIMEFRAMES[tf], np.array([last_day]))[0])
    since = int(last_day) - HISTORY_DAYS[tf] * DAY
    info = {sid: (tk, name, typ) for sid, tk, name, typ in syms}
    ids = [sid for sid, *_ in syms]
    for k in range(0, len(ids), BATCH):
        chunk = ids[k:k + BATCH]
        with session_factory() as s:
            data = s.execute(select(Candle.symbol_id, Candle.ts, Candle.o, Candle.h, Candle.l, Candle.c, Candle.v)
                             .where(Candle.tf == "1D", Candle.symbol_id.in_(chunk), Candle.ts >= since)
                             .order_by(Candle.symbol_id, Candle.ts)).all()
        if data:
            arr = np.array(data, dtype=float)
            sid_col = arr[:, 0].astype(np.int64)
            cuts = np.flatnonzero(np.r_[True, sid_col[1:] != sid_col[:-1], True])
            for a, z in zip(cuts[:-1], cuts[1:]):
                sid = int(sid_col[a])
                t = arr[a:z, 1].astype(np.int64)
                o, h, l, c, v = (arr[a:z, j] for j in range(2, 7))  # noqa: E741
                if t[-1] != last_day:
                    continue                                   # stale symbol: not traded on the latest session
                if tf != "1D":
                    t, o, h, l, c, v = resample(TIMEFRAMES[tf], t, o, h, l, c, v, market=market)  # noqa: E741
                if len(t) < MIN_BARS:
                    continue
                scanned += 1
                try:
                    hits = latest_hits(t, o, h, l, c, v)
                except Exception as e:  # noqa: BLE001  one bad series must not stop the screen
                    pr.errors.append(f"{info[sid][0]}: {e!r}")
                    continue
                if not hits:
                    continue
                tk, name, typ = info[sid]
                vals = (c[-50:] * v[-50:])[np.isfinite(c[-50:] * v[-50:])]
                rows.append(dict(
                    symbol=f"{exchange}:{tk}", ticker=tk, name=name, type=typ,
                    close=round(float(c[-1]), 4),
                    change_pct=round(float((c[-1] / c[-2] - 1) * 100), 2) if len(c) > 1 and c[-2] else None,
                    volume=float(v[-1]), turnover=round(float(np.median(vals)), 0) if len(vals) else 0.0,
                    patterns=sorted({m["pattern"] for m in hits}),
                    hits=[dict(pattern=m["pattern"], text=m["text"], notes=m["notes"][:2]) for m in hits]))
        pr.done = min(pr.total, k + len(chunk))
        pr.msg = f"{pr.done:,}/{pr.total:,} symbols, {len(rows):,} with patterns"
        if on_step:
            on_step(pr)
    rows.sort(key=lambda r: (-len(r["patterns"]), -(r["turnover"] or 0)))
    res = dict(exchange=exchange, tf=tf, as_of=int(latest_bar), last_session=int(last_day), rows=rows,
               scanned=scanned, symbols=len(syms), errors=pr.errors[:20],
               generated_at=time.time(), seconds=round(time.perf_counter() - t0, 1))
    return _save(res, exchange, tf, root)


def _save(res: dict, exchange: str, tf: str, root: Path | None) -> dict:
    p = screen_path(exchange, tf, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(res), encoding="utf-8")
    tmp.replace(p)
    log.info("screen %s %s: %d symbols with patterns of %d scanned", exchange, tf, len(res["rows"]), res["scanned"])
    return res


def exchanges(session: Session) -> list[str]:
    return [e for (e,) in session.execute(select(Symbol.exchange).distinct().order_by(Symbol.exchange)).all()]
