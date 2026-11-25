"""'Patterns formed today': every symbol of an exchange, the rulebook patterns that fire on its latest bar.

For each exchange and timeframe (daily, or weekly built from the daily bars) the bars are read in batches of
symbols (one query per batch instead of one per symbol), the pattern rules run on the last bar only, and the
result is saved as JSON under backend/data/screens/ so the dashboard opens instantly. Symbols whose last bar is
older than the exchange's latest session (delisted, suspended) are skipped. Support/resistance levels are not a
signal, so they are not screened.
"""
import calendar
import json
import re
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
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
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


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


IST = 19800


def session_date(ts: int) -> str:
    """ISO trading date of a daily bar (daily bars are stamped at IST midnight of their date, every exchange)."""
    return time.strftime("%Y-%m-%d", time.gmtime(int(ts) + IST))


def session_ts(day: str) -> int:
    """The daily-bar timestamp of an ISO date."""
    return int(calendar.timegm(time.strptime(day, "%Y-%m-%d"))) - IST


def screen_path(exchange: str, tf: str, root: Path | None = None, day: str | None = None) -> Path:
    """The newest screen (EX_TF.json), or the screen of one session (EX_TF_YYYY-MM-DD.json)."""
    return (root or screens_dir()) / (f"{exchange.upper()}_{tf}.json" if not day else f"{exchange.upper()}_{tf}_{day}.json")


def _read(p: Path) -> dict | None:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _exact(exchange: str, tf: str, root: Path | None, day: str) -> dict | None:
    res = _read(screen_path(exchange, tf, root, day))
    if res is None:                           # the newest screen may be that session (saved before dated files)
        res = _read(screen_path(exchange, tf, root))
        if not res or not res.get("last_session") or session_date(res["last_session"]) != day:
            return None
    return res


def load_screen(exchange: str, tf: str, root: Path | None = None, day: str | None = None) -> dict | None:
    """The saved screen of a date, or the newest one. A date without its own screen (a weekend or holiday, or a
    mid-week day for weekly) gets the nearest saved session before it: the same week for weekly, within 4 days for
    daily."""
    if not day:
        return _read(screen_path(exchange, tf, root))
    res = _exact(exchange, tf, root, day)
    if res is not None:
        return res
    asked = date.fromisoformat(day)
    for d in screen_dates(exchange, tf, root):            # newest first
        got = date.fromisoformat(d)
        if got > asked:
            continue
        near = got.isocalendar()[:2] == asked.isocalendar()[:2] if tf == "1W" else (asked - got).days <= 4
        return _exact(exchange, tf, root, d) if near else None
    return None


def screen_dates(exchange: str, tf: str, root: Path | None = None) -> list[str]:
    """Session dates with a saved screen, newest first."""
    d = root or screens_dir()
    pre = f"{exchange.upper()}_{tf}_"
    out = {f.stem[len(pre):] for f in d.glob(f"{pre}*.json") if DATE_RE.fullmatch(f.stem[len(pre):])}
    latest = _read(screen_path(exchange, tf, root))
    if latest and latest.get("last_session"):
        out.add(session_date(latest["last_session"]))
    return sorted(out, reverse=True)


def sessions(session_factory: sessionmaker, exchange: str, since: str) -> list[str]:
    """Trading dates of an exchange on or after `since` (from its daily bars), newest first."""
    with session_factory() as s:
        ts = s.execute(select(Candle.ts).distinct().where(
            Candle.tf == "1D", Candle.ts >= session_ts(since),
            Candle.symbol_id.in_(select(Symbol.id).where(Symbol.exchange == exchange.upper())))).scalars().all()
    return sorted({session_date(t) for t in ts}, reverse=True)


def backfill_days(session_factory: sessionmaker, exchange: str, tf: str, days: int, today: str | None = None) -> list[str]:
    """Sessions of the last `days` calendar days to screen: every session for daily; the last session of each week for
    weekly (the newest week as it stands)."""
    today = today or time.strftime("%Y-%m-%d")
    since = time.strftime("%Y-%m-%d", time.gmtime(calendar.timegm(time.strptime(today, "%Y-%m-%d")) - days * DAY))
    found = sessions(session_factory, exchange, since)
    if tf == "1D":
        return found
    weeks: dict[tuple[int, int], str] = {}
    for d in found:                                       # newest first: the first seen is the week's last session
        weeks.setdefault(date.fromisoformat(d).isocalendar()[:2], d)
    return sorted(weeks.values(), reverse=True)


def run_screen(session_factory: sessionmaker, exchange: str, tf: str, root: Path | None = None,
               progress: Progress | None = None, on_step: Callable[[Progress], None] | None = None,
               day: str | None = None) -> dict:
    """Screen every symbol of `exchange` on its latest `tf` bar, or on the bar of session `day` (the last session on
    or before it); saves and returns the result."""
    exchange, t0 = exchange.upper(), time.perf_counter()
    if tf not in SCREEN_TFS:
        raise ValueError(f"timeframe must be one of {SCREEN_TFS}")
    pr = progress or Progress()
    pr.exchange, pr.tf, pr.done, pr.errors = exchange, tf, 0, []
    market = market_for(exchange)
    with session_factory() as s:
        syms = s.execute(select(Symbol.id, Symbol.ticker, Symbol.name, Symbol.type)
                         .where(Symbol.exchange == exchange).order_by(Symbol.ticker)).all()
        cond = [Candle.tf == "1D", Candle.symbol_id.in_(select(Symbol.id).where(Symbol.exchange == exchange))]
        if day:
            cond.append(Candle.ts <= session_ts(day))
        last_day = s.scalar(select(func.max(Candle.ts)).where(*cond))
        newest = s.scalar(select(func.max(Candle.ts)).where(*cond[:2])) if day else last_day
    pr.total = len(syms)
    rows: list[dict] = []
    scanned = 0
    if last_day is None:
        return _save(dict(exchange=exchange, tf=tf, as_of=None, rows=[], scanned=0), exchange, tf, root, True)
    latest_bar = int(last_day) if tf == "1D" else int(bucket_starts(TIMEFRAMES[tf], np.array([last_day]))[0])
    since = int(last_day) - HISTORY_DAYS[tf] * DAY
    info = {sid: (tk, name, typ) for sid, tk, name, typ in syms}
    ids = [sid for sid, *_ in syms]
    for k in range(0, len(ids), BATCH):
        chunk = ids[k:k + BATCH]
        with session_factory() as s:
            data = s.execute(select(Candle.symbol_id, Candle.ts, Candle.o, Candle.h, Candle.l, Candle.c, Candle.v)
                             .where(Candle.tf == "1D", Candle.symbol_id.in_(chunk), Candle.ts >= since,
                                    Candle.ts <= last_day)
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
               session=session_date(last_day), generated_at=time.time(),
               seconds=round(time.perf_counter() - t0, 1))
    return _save(res, exchange, tf, root, last_day == newest)


def _save(res: dict, exchange: str, tf: str, root: Path | None, newest: bool) -> dict:
    """Saved under its session date; the newest session is also the dashboard's default screen."""
    paths = ([screen_path(exchange, tf, root, res["session"])] if res.get("session") else []) +         ([screen_path(exchange, tf, root)] if newest else [])
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(res), encoding="utf-8")
        tmp.replace(p)
    log.info("screen %s %s: %d symbols with patterns of %d scanned", exchange, tf, len(res["rows"]), res["scanned"])
    return res


def exchanges(session: Session) -> list[str]:
    return [e for (e,) in session.execute(select(Symbol.exchange).distinct().order_by(Symbol.exchange)).all()]
