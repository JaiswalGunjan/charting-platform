"""Run the rulebook's chart-pattern rules over a chart's bars and describe each hit for drawing.

Each pattern maps to a rule function in rules.py (copied from TranscriptExtract/swingbt/rules). A hit becomes a
marker on its signal bar plus, where the rule records geometry (`hit.extra["geom"]`), shapes in (time, price): the
base and its pivot, VCP contractions, the handle, trend lines, levels, the coil box. Only hits that pass the rule's
hard checks (`hit.valid`) are returned. Support/resistance are price levels for the last bar.
"""
from dataclasses import dataclass

import numpy as np

from app.patterns import rules as R
from app.patterns.features import Bars, build

WARMUP = 300  # bars of history before the first scanned bar (52-week features, 130-bar base look-back x 2)


@dataclass(frozen=True)
class Pattern:
    id: str
    title: str
    group: str
    short: str      # marker text
    color: str
    rule: str       # where it is defined
    about: str


PATTERNS: list[Pattern] = [
    Pattern("sr", "Support & resistance", "Levels", "", "#787b86", "support_resistance.resistance_level",
            "Clusters of swing highs/lows (2% band) touched 3+ times in the last 120 bars (S1-R061); above the close = "
            "resistance, below = support."),
    Pattern("pp", "Pocket pivot", "Volume signals", "PP", "#2962ff", "pocket_pivot.pocket_pivot",
            "Up day on volume above every down-day volume of the prior 10 bars, close above the 10 and 50 WMA, low near "
            "the 10 WMA, not extended or in a V-shape (S3B-R001..R021)."),
    Pattern("cic", "Change in character", "Volume signals", "CIC", "#00897b", "indicators.cic22/66/250",
            "Up day on the highest volume of 22/66/250 bars (S2B-R017); context, not an entry by itself."),
    Pattern("wedge_pop", "Wedge pop", "Price cycle", "WP", "#ff9800", "cycle.phases",
            "After a reversal extension, an up day whose high breaches the 10 and 20 WMA while they stop falling "
            "(S2B-R005). Watch only."),
    Pattern("crossback", "MA crossback", "Price cycle", "XB", "#fb8c00", "cycle.phases",
            "First pullback to the 10 WMA after the 10/20 WMA bullish crossover (S2B-R007)."),
    Pattern("base_break", "Base and break", "Price cycle", "B&B", "#ef6c00", "cycle.phases",
            "Close above a short base that formed above the rising 10 WMA (S2B-R008)."),
    Pattern("cwh", "Cup with handle", "Bases", "CWH", "#8e24aa", "bases.base_breakout",
            "Breakout over the left top of a 20-130 bar cup (depth <= 40%, prior advance >= 30%) with a handle "
            "<= 1/3 of the cup on dry volume, on >= 1.5x volume or a pocket pivot (S3-R001..R010)."),
    Pattern("vcp", "VCP", "Bases", "VCP", "#d81b60", "bases.base_breakout",
            "Volatility contraction: >= 2 shrinking pullbacks with rising lows (first 11-50%), breakout on volume "
            "(S3-R042..R044)."),
    Pattern("flat", "Flat base", "Bases", "FLAT", "#5e35b1", "bases.base_breakout",
            "Breakout from a 25+ bar base no deeper than 30% (S3-R023..R025)."),
    Pattern("htf", "High tight flag", "Bases", "HTF", "#c2185b", "bases.base_breakout",
            "After a >= 100% advance, a 10-40 bar flag no deeper than 20% on dry volume, then a breakout "
            "(S3-R031..R034)."),
    Pattern("bbr", "Bad break recovery", "Shapers", "BBR", "#00acc1", "shapers.bad_break_recovery",
            "Shakeout close below the 50 (or 21) SMA (< 30% off the 52-week high), pocket-pivot reclaim, then a "
            "follow-up pocket pivot within 15 bars (S4-R033..R036)."),
    Pattern("one23", "1-2-3 shaper", "Shapers", "123", "#1e88e5", "shapers.one_two_three",
            "MACD-histogram waves down/up/down; close above the line through the two peaks on pocket-pivot volume "
            "(S4-R002..R017)."),
    Pattern("oversold", "Oversold shaper", "Shapers", "OS", "#3949ab", "shapers.oversold_shaper",
            "SMA50 > SMA200, slow stochastic < 20 with EMA10 > EMA20, close above the falling line from the swing high "
            "(S4-R022..R028)."),
    Pattern("tl3", "Three-touch trendline", "Shapers", "TL3", "#6d4c41", "shapers.three_touch_trendline",
            "Close above a falling line from the base high touched 3+ times (S4-R039, R040)."),
    Pattern("minicoil", "Mini coil", "Shapers", "COIL", "#546e7a", "shapers.mini_coil",
            "Two or more bars inside a pocket-pivot bar, then a close above its high on volume (S4-R044..R046)."),
    Pattern("natural", "Natural reaction", "Breakouts & pullbacks", "NR", "#43a047", "bases.natural_reaction",
            "After a breakout and a 5%+ extension, a pullback that holds the old resistance on contracting range and "
            "volume; close above the pullback highs (S3-R049)."),
    Pattern("squat", "Squat recovery", "Breakouts & pullbacks", "SQ", "#7cb342", "bases.squat",
            "Breakout, shakeout close back below, reclaim, light-volume hold, then a pocket-pivot/CIC bar "
            "(S3-R051, R052)."),
    Pattern("momentum", "Momentum pullback", "Breakouts & pullbacks", "MOM", "#00897b", "bases.momentum_riding",
            "First 4-10 bar pullback to the 10/20 WMA after a 10%+ extension from a fresh breakout (S3-R055)."),
    Pattern("quiet", "Quiet-zone breakout", "Breakouts & pullbacks", "QB", "#558b2f", "bases.quiet_breakout",
            "Close above the 20-bar high on 1.4x volume after a quiet 5 bars of smaller range and volume "
            "(S1-R011, R074)."),
]
BY_ID = {p.id: p for p in PATTERNS}
BASE_KIND = {"CWH": "cwh", "VCP": "vcp", "FLAT": "flat", "HTF": "htf"}
PER_BAR = {"pp": R.pocket_pivot, "bbr": R.bad_break_recovery, "one23": R.one_two_three,
           "oversold": R.oversold_shaper, "tl3": R.three_touch_trendline, "minicoil": R.mini_coil,
           "natural": R.natural_reaction, "squat": R.squat, "momentum": R.momentum_riding, "quiet": R.quiet_breakout}


def _safe(fn, b, i):
    try:
        return fn(b, i)
    except (IndexError, ValueError, FloatingPointError, ZeroDivisionError):
        return None  # not enough bars around i for this rule


def scan(t, o, h, l, c, v, ids: set[str], first: int = 0) -> dict:  # noqa: E741
    """Hits of the selected patterns on bars [first, n), with chart geometry in (epoch time, price)."""
    b = Bars(build(t, o, h, l, c, v))
    n = b.n
    start = max(first, 60)
    markers, shapes = [], []
    T = lambda k: int(b.t[min(max(int(k), 0), n - 1)])  # noqa: E731

    def add(pid, i, hit=None, text=None, notes=()):
        p = BY_ID[pid]
        markers.append(dict(pattern=pid, t=T(i), text=text or p.short, color=p.color,
                            notes=list(hit.notes) if hit else list(notes),
                            rules=list(hit.rules) if hit else []))
        if hit is not None and "geom" in hit.extra:
            shapes.extend(_shapes(pid, p.color, hit.extra["geom"], i, T))

    with np.errstate(all="ignore"):
        bases = ids & set(BASE_KIND.values())
        for i in range(start, n):
            if bases:
                hit = _safe(R.base_breakout, b, i)
                if hit is not None and hit.valid and BASE_KIND.get(hit.setup) in bases:
                    add(BASE_KIND[hit.setup], i, hit)
            for pid, fn in PER_BAR.items():
                if pid in ids:
                    hit = _safe(fn, b, i)
                    if hit is not None and hit.valid:
                        add(pid, i, hit)
            if "cic" in ids:
                for k in (250, 66, 22):
                    if getattr(b, f"cic{k}")[i]:
                        add("cic", i, text=f"CIC{k}", notes=[f"Up day on the highest volume of {k} bars"])
                        break
        if ids & {"wedge_pop", "crossback", "base_break"}:
            ph, base_hi, base_len = R.phases(b)
            names = {"wedge_pop": R.WEDGE_POP, "crossback": R.CROSSBACK, "base_break": R.BASE_BREAK}
            for pid, code in names.items():
                if pid not in ids:
                    continue
                for i in range(max(start, 1), n):
                    if ph[i] == code and ph[i - 1] != code:
                        note = R.PHASE_NAME[code]
                        if code == R.BASE_BREAK:
                            note += f": close above the {int(base_len[i])}-bar base high {base_hi[i]:.2f}"
                            shapes.append(dict(pattern=pid, kind="segment", color=BY_ID[pid].color, dash=True,
                                               label_at="start",
                                               pts=[dict(t=T(i - base_len[i]), p=float(base_hi[i])),
                                                    dict(t=T(i), p=float(base_hi[i]))], label=""))
                        add(pid, i, notes=[note.capitalize()])
    levels = support_resistance(b) if "sr" in ids else []
    seen, uniq = set(), []
    for sh in shapes:  # e.g. several follow-up pocket pivots of one bad break recovery share its shakeout
        key = (sh["pattern"], sh["kind"], sh["label"], tuple((q["t"], round(q["p"], 4)) for q in sh["pts"]))
        if key not in seen:
            seen.add(key)
            uniq.append(sh)
    return dict(markers=markers, shapes=uniq, levels=levels)


def support_resistance(b: Bars, look: int = 120, band: float = 0.02, min_touches: int = 3, keep: int = 8) -> list[dict]:
    """Price levels for the last bar: clusters of 2-bar fractal swing highs and lows within a 2% band touched at least
    `min_touches` times in the last `look` bars (the clustering of swing highs in rules.resistance_level, S1-R061,
    applied to swing lows as well). Above the last close = resistance, below = support."""
    n = b.n
    if n < 10:
        return []
    lo = max(2, n - look)
    piv = [(k, float(b.h[k])) for k in range(lo, n - 2) if b.swing_high[k]] + \
          [(k, float(b.l[k])) for k in range(lo, n - 2) if b.swing_low[k]]
    piv.sort(key=lambda x: x[1])
    used = [False] * len(piv)
    out = []
    # greedy: the price with the most pivots inside +-band, then remove those pivots and repeat
    while True:
        best, members = None, []
        for a, (_, x) in enumerate(piv):
            if used[a]:
                continue
            m = [q for q, (_, y) in enumerate(piv) if not used[q] and x * (1 - band) <= y <= x * (1 + band)]
            if len(m) > len(members):
                best, members = x, m
        if best is None or len(members) < min_touches:
            break
        for q in members:
            used[q] = True
        prices = [piv[q][1] for q in members]
        bars = [piv[q][0] for q in members]
        level = float(np.median(prices))
        out.append(dict(price=round(level, 4), touches=len(members), first_t=int(b.t[min(bars)]),
                        last_t=int(b.t[max(bars)]),
                        kind="resistance" if level > b.c[-1] else "support"))
        if len(out) >= keep:
            break
    return out


def _shapes(pid: str, color: str, g: dict, i: int, T) -> list[dict]:
    seg = lambda a, pa, z, pz, label="", dash=False, at="start": dict(  # noqa: E731
        pattern=pid, kind="segment", color=color, dash=dash, label=label, label_at=at,
        pts=[dict(t=T(a), p=float(pa)), dict(t=T(z), p=float(pz))])
    rect = lambda a, hi, z, lo, label="": dict(  # noqa: E731
        pattern=pid, kind="rect", color=color, dash=True, label=label, label_at="start",
        pts=[dict(t=T(a), p=float(hi)), dict(t=T(z), p=float(lo))])
    k = g.get("kind")
    out: list[dict] = []
    if k == "base":
        out.append(seg(g["top_i"], g["top"], i, g["top"],
                       f"{BY_ID[pid].short} pivot {g['top']:.2f} · {g['len']} bars, {g['depth']:.0f}% deep"))
        out.append(rect(g["top_i"], g["top"], i, g["low"]))
        if pid == "cwh":
            out.append(rect(g["handle_from"], g["handle_hi"], i - 1, g["handle_lo"], "handle"))
        for (kh, ph, kl, pl) in g.get("contractions") or []:
            # depth of each pullback, written at its low so it never sits on the pivot label
            out.append(seg(kh, ph, kl, pl, f"-{(1 - pl / ph) * 100:.0f}%", at="end"))
    elif k == "level":
        out.append(seg(g["level_from"], g["level"], i, g["level"], f"{g['level']:.2f}", dash=True))
    elif k == "line":
        if "p1" in g:
            out.append(seg(g["p1"], g["h1"], i, g["line_now"]))
        else:
            out.append(seg(g["s0"], g["h0"], i, g["line_now"]))
    elif k == "bbr":
        out.append(seg(g["shakeout_bar"], g["shakeout_low"], g["reclaim_bar"], g["shakeout_low"],
                       f"shakeout -{g['dd_pct']:.0f}%", dash=True))
    elif k == "box":
        out.append(rect(g["parent"], g["hi"], max(g["inside"][1], g["parent"] + 1), g["lo"], "coil"))
    elif k == "pullback":
        out.append(seg(g["bo_bar"], g["bo_level"], g["peak_bar"], g["bo_level"], dash=True))
        out.append(seg(g["pull"][0], g["pull_lo"], i, g["pull_lo"], "pullback low", dash=True))
    return out
