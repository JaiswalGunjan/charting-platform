"""Chart patterns, from the pattern engine in use (PATTERN_ENGINE; built in: the owner's rulebook rules).

The rules are written for daily bars (a cup is 20-130 bars, a pocket pivot compares 10 days of volume, ...).
With basis=daily (the default) they always run on daily bars and the hits are placed on the chart's own
timeframe: a weekly/monthly chart marks the week/month that contains the signal day, an intraday chart the last
bar of that day. Shapes are in (time, price), so they draw on any timeframe. basis=chart runs the rules on the
chart's bars as they are.
"""
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from app.wording import neutral_all
from app.api.deps import SessionDep, symbol_or_404, timeframe_or_400
from app.marketdata.history import get_bars
from app.marketdata.timeframes import TIMEFRAMES, Timeframe
from app.providers import pattern_engine

router = APIRouter(prefix="/patterns", tags=["patterns"])
DAY = 86400
SPAN_DAYS = {"1W": 7, "1M": 31, "1Y": 366}
Basis = Literal["daily", "chart"]


@router.get("")
def list_patterns() -> list[dict]:
    return neutral_all(pattern_engine().catalog())


def _empty() -> dict:
    return dict(markers=[], shapes=[], levels=[])


def run_patterns(session, sym_id: int, tf: Timeframe, ids: set[str], limit: int, basis: Basis) -> dict:
    """Pattern hits for the chart's last `limit` bars of `tf` (see the module docstring for `basis`)."""
    if not ids:
        return _empty()
    eng = pattern_engine()
    if basis == "chart" or tf.name == "1D":
        bars = get_bars(session, sym_id, tf, limit=limit + eng.warmup)
        if not len(bars):
            return _empty()
        return eng.scan(bars.t, bars.o, bars.h, bars.l, bars.c, bars.v, ids, max(0, len(bars) - limit))

    chart = get_bars(session, sym_id, tf, limit=limit)
    if not len(chart):
        return _empty()
    t0 = int(chart.t[0])
    # daily bars from WARMUP trading days before the chart's first bar (~1.6 calendar days per trading day)
    daily = get_bars(session, sym_id, TIMEFRAMES["1D"], limit=20_000, frm=t0 - int(eng.warmup * 1.6) * DAY)
    if not len(daily):
        return _empty()
    first = int(np.searchsorted(daily.t, t0 - DAY + 1))  # the daily bar that contains the chart's first bar
    out = eng.scan(daily.t, daily.o, daily.h, daily.l, daily.c, daily.v, ids, first)
    out["markers"] = _place(out["markers"], chart.t, tf)
    return out


def _place(markers: list[dict], chart_t: np.ndarray, tf: Timeframe) -> list[dict]:
    """Move daily-bar markers onto the chart's bars and merge hits of one pattern on one chart bar."""
    merged: dict[tuple[str, int], dict] = {}
    for m in markers:
        k = int(np.searchsorted(chart_t, m["t"] + DAY, side="left")) - 1   # last chart bar opening before day end
        if k < 0:
            continue
        ct = int(chart_t[k])
        if tf.intraday:
            if ct < m["t"]:          # no intraday bar on that day (e.g. hourly history ends earlier)
                continue
        elif m["t"] - ct >= SPAN_DAYS.get(tf.name, 1) * DAY:
            continue                 # no chart bar covers that day
        key = (m["pattern"], ct)
        if key in merged:
            g = merged[key]
            g["count"] += 1
            g["notes"] += m["notes"]
            g["rules"] = sorted(set(g["rules"]) | set(m["rules"]))
        else:
            merged[key] = dict(m, t=ct, count=1, day_t=m["t"])
    out = []
    for g in merged.values():
        if g["count"] > 1:
            g["text"] = f"{g['text']}×{g['count']}"
        out.append(g)
    return out


@router.get("/scan")
def scan_patterns(
    session: SessionDep,
    symbol: str = Query(...),
    tf: str = Query("1D"),
    ids: str = Query("", description="comma list of pattern ids; empty = none"),
    limit: int = Query(500, ge=1, le=5000),
    basis: Basis = Query("daily", description="daily: rulebook rules on daily bars, placed on this timeframe; "
                                               "chart: rules on this timeframe's bars"),
) -> dict:
    """Patterns present in the chart's last `limit` bars (the bars /history returns): markers, shapes, levels."""
    want = {x for x in ids.split(",") if x}
    bad = want - pattern_engine().ids()
    if bad:
        raise HTTPException(400, f"unknown pattern ids {sorted(bad)}")
    sym = symbol_or_404(session, symbol)
    timeframe = timeframe_or_400(tf)
    out = run_patterns(session, sym.id, timeframe, want, limit, basis)
    return dict(symbol=sym.full, tf=timeframe.name, basis=basis, **neutral_all(out))


@router.get("/counts")
def count_patterns(
    session: SessionDep,
    symbol: str = Query(...),
    tf: str = Query("1D"),
    limit: int = Query(500, ge=1, le=5000),
    basis: Basis = Query("daily"),
) -> dict:
    """How often every pattern occurs in the chart's last `limit` bars (for the pattern menu), whether shown or
    not; counts signal days, so several hits inside one weekly/monthly bar each count. sr = number of levels."""
    sym = symbol_or_404(session, symbol)
    timeframe = timeframe_or_400(tf)
    counts = {pid: 0 for pid in sorted(pattern_engine().ids())}
    out = run_patterns(session, sym.id, timeframe, set(counts), limit, basis)
    for m in out["markers"]:
        counts[m["pattern"]] += m.get("count", 1)
    counts["sr"] = len(out["levels"])
    return dict(symbol=sym.full, tf=timeframe.name, basis=basis, counts=counts)
