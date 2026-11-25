"""A brief 'why this trade' for a SwingScanner signal, in the same six parts as the scanner's own report:
what the pattern is, why today is the entry, where the stop is, how we would sell, position size, warnings.

Built only from what the scanner saved (signals.csv / near_misses.csv row, market.json) plus its setup
explanations (explain.py) and rulebook text (rulebook_unsupervised/*.py, in the scanner folder). All of those are
read as data with `ast`; no scanner code is run.
"""
import ast
import json
import math
import re
from functools import lru_cache
from pathlib import Path

US = {"NASDAQ", "NYSE"}
RULE_FILE = re.compile(r"^s\d+_session(?P<tag>.+)\.py$")


def _prefix(tag: str) -> str:
    """session file tag -> rule-id prefix: '1' -> S1, '2b' -> S2B, '_doubt' -> SD."""
    tag = tag.strip("_")
    return "SD" if tag == "doubt" else f"S{tag.upper()}"


@lru_cache(maxsize=4)
def _rulebook(folder: str, mtime: float) -> dict[str, str]:  # noqa: ARG001  (mtime only busts the cache)
    out: dict[str, str] = {}
    for f in Path(folder).glob("s*_session*.py"):
        m = RULE_FILE.match(f.name)
        if not m:
            continue
        pre = _prefix(m.group("tag"))
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "RULES" for t in node.targets) \
                    and isinstance(node.value, ast.List):
                for el in node.value.elts:
                    if isinstance(el, ast.Tuple) and len(el.elts) >= 3 and all(
                            isinstance(x, ast.Constant) for x in el.elts[:3]):
                        n, _, text = (x.value for x in el.elts[:3])
                        if isinstance(n, int) and isinstance(text, str):
                            out[f"{pre}-R{n:03d}"] = text
    return out


def rulebook(scanner_root: Path | None) -> dict[str, str]:
    """{rule id: rule text} from the scanner's bundled rulebook, {} when it is not there."""
    if scanner_root is None:
        return {}
    d = scanner_root / "rulebook_unsupervised"
    if not d.is_dir():
        return {}
    mt = max((p.stat().st_mtime for p in d.glob("*.py")), default=0.0)
    return _rulebook(str(d), mt)


def position(equity: float, entry: float, stop: float, risk_pct: float = 1.0, risk_mult: float = 1.0,
             size_mult: float = 1.0, max_alloc_pct: float = 45.0) -> tuple[int, str]:
    """The scanner's sizing (swingbt/rules/sizing.py `shares`, without the cash and turnover caps):
    floor(equity x risk% x market multiplier x setup multiplier / (entry - stop)), at most max_alloc_pct of equity."""
    risk = entry - stop
    if risk <= 0 or entry <= 0 or equity <= 0:
        return 0, "invalid stop"
    n = math.floor(equity * risk_pct / 100 * risk_mult * size_mult / risk)
    cap = math.floor(equity * max_alloc_pct / 100 / entry)
    return (cap, f"max {max_alloc_pct:g}% of the portfolio") if n > cap else (max(n, 0), "risk")


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _short(text: str, n: int = 150) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def explain(row: dict, market: str, setup: dict, rules: dict[str, str], meta: dict, equity: float | None = None,
            risk_pct: float | None = None) -> dict:
    """row = one raw CSV row of signals.csv / near_misses.csv; setup = {name, what, why}; meta = market.json;
    equity = the user's portfolio size (position size recomputed with the scanner's rule), else the scan's capital;
    risk_pct = the user's risk per trade in % of the portfolio, else the scan's setting (default 1%)."""
    cur = "$" if market in US else "₹"
    money = lambda x: f"{cur}{x:,.2f}"  # noqa: E731
    entry, stop = _f(row.get("close")), _f(row.get("stop"))
    one_r = entry - stop if entry is not None and stop is not None else None
    valid = (row.get("valid") or "").lower() == "true"
    notes = [p.strip() for p in (row.get("notes") or "").split("|") if p.strip()]
    sections = []

    # 1. what the pattern is
    what = [setup.get("what") or ""] + ([f"Why it works: {setup['why']}"] if setup.get("why") else [])
    sections.append(dict(title=f"What the pattern is: {setup.get('name') or row.get('setup')}", lines=[x for x in what if x]))

    # 2. why today is the entry (or why it is not)
    ok = [r.strip() for r in (row.get("rules_ok") or "").split(",") if r.strip()]
    lines = notes[:1]
    for rid in ok[:3]:
        lines.append(f"Rule passed {rid}: {_short(rules.get(rid, ''), 140)}" if rid in rules else f"Rule passed {rid}")
    if len(ok) > 3:
        lines.append("Other rules satisfied: " + ", ".join(ok[3:]))
    if row.get("also"):
        lines.append(f"Other setups on the same bar: {row['also']} (the tightest stop is kept).")
    if not valid and row.get("reject"):
        lines.append("Not a buy - failed: " + "; ".join(_short(x, 110) for x in row["reject"].split(";") if x.strip()))
    sections.append(dict(title="Why today is the entry" if valid else "Why it is not a buy today", lines=lines))

    # 3. where the stop is and why
    lines = []
    if one_r is not None:
        lines.append(f"Stop {money(stop)} = {_f(row.get('stop_pct')) or 0:.2f}% below the entry {money(entry)} "
                     f"(the signal day's close); 1R = {money(one_r)}.")
        lines.append("Targets are not fixed: " + ", ".join(f"+{k}R = {money(entry + k * one_r)}" for k in (1, 2, 3))
                     + "; the exit comes from the selling rules.")
    for part in (row.get("stop_note") or "").split("|"):
        if part.strip():
            lines.append(_short(part.strip()[0].upper() + part.strip()[1:], 220))
    rs, rsp = _f(row.get("rule_stop")), _f(row.get("rule_stop_pct"))
    if rs is not None and stop is not None and abs(rs - stop) > 1e-6:
        lines.append(f"The rulebook stop is {money(rs)} ({rsp or 0:.2f}%); the optimised rule set widened it to the "
                     "stop floor (an experiment, not in the rulebook).")
    sections.append(dict(title="Where the stop is and why", lines=lines))

    # 4. how we would sell (the rulebook's exit rules, brief)
    sections.append(dict(title="How we would sell", lines=[
        "Break-even: after +1R (or a new 52-week high) the stop moves up to the buy price (S6A-R012/R020).",
        "Defensive: if the 10 WMA crosses below the 20 WMA before the third extension, the stop goes to that day's "
        "low (S6B-R015).",
        "Sell into strength: after the 3rd stochastic extension or a hot run, sell below the day's low on the first "
        "MACD-histogram down-tick (S6B-R009/R011/R016).",
        "Market protection: if the index closes below its 10-day low, a loser is sold and a winner's stop is raised "
        "(S7-R014). The stop is never lowered.",
    ]))

    # 5. position size
    mr = meta.get("market_row") or {}
    cfg = meta.get("config") or {}
    cap = equity if equity else _f(meta.get("capital"))
    if risk_pct is None:
        risk_pct = _f(cfg.get("risk_pct"))
        risk_pct = 1.0 if risk_pct is None else risk_pct
    mult = _f(mr.get("risk_mult"))
    mult = 1.0 if mult is None else mult
    size_mult = _f(row.get("size_mult")) or 1.0
    lines = []
    if cap:
        at_risk = cap * risk_pct / 100 * mult * size_mult
        lines.append(f"Portfolio size {money(cap)}, risk {risk_pct:g}% per trade x market multiplier {mult:g}"
                     + (f" x setup multiplier {size_mult:g}" if size_mult != 1 else "") + f" = {money(at_risk)} at risk.")
    if valid and cap and one_r and one_r > 0:
        shares, by = position(cap, entry, stop, risk_pct, mult, size_mult, _f(cfg.get("max_alloc_pct")) or 45.0)
        value = shares * entry
        lines.append(f"Shares = risk / (entry - stop) = {shares:,}; position {money(value)} "
                     f"({value / cap * 100:.1f}% of the portfolio), sized by {by}; a stop-out loses about {money(shares * one_r)}.")
    elif not valid:
        lines.append("No position: the signal failed a hard rule, so the scanner would not buy it.")
    lines.append("Daily signals are bought at the close of the signal day; the stop is first tested the next session.")
    sections.append(dict(title="Position size", lines=lines))

    # 6. warnings and context
    lines = [f"Soft miss {_short(w.strip(), 160)}" for w in (row.get("weak") or "").split(";") if w.strip()]
    if mr:
        lines.append(f"Market: regime {str(mr.get('regime', '-')).replace('_', ' ')}, impulse {mr.get('impulse', '-')}, "
                     f"risk multiplier {mr.get('risk_mult', '-')}.")
    ctx = []
    if row.get("stage"):
        ctx.append(f"stage {row['stage']}")
    if row.get("phase"):
        ctx.append(f"cycle phase '{row['phase']}'")
    if row.get("ext"):
        ctx.append(f"extensions since the base {row['ext']}")
    if _f(row.get("rs60")) is not None:
        ctx.append(f"RS vs the index over 60 days {_f(row['rs60']):.1f} points")
    if _f(row.get("score")) is not None:
        ctx.append(f"rank score {_f(row['score']):.2f}")
    if ctx:
        text = ", ".join(ctx)
        lines.append(text[0].upper() + text[1:] + ".")
    sections.append(dict(title="Warnings and context", lines=lines))
    return dict(symbol=f"{market}:{row.get('symbol')}", setup=row.get("setup"), date=row.get("date"), valid=valid,
                sections=sections)


def load_meta(folder: Path) -> dict:
    try:
        return json.loads((folder / "market.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
