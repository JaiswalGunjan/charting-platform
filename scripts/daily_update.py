"""Daily market update, run by Windows Task Scheduler (register with scripts/register_daily_update.ps1).

    python scripts/daily_update.py --market NSE      # weekday evenings in India: today's NSE session
    python scripts/daily_update.py --market US       # 08:00 India time: the US session that closed overnight
    python scripts/daily_update.py --market US --date 2026-11-25 --dry-run

Each run:
  1. skips a day the market was closed: weekends, and NSE trading holidays (NSE's own list from nseindia.com, cached
     per year) or US market holidays (NYSE rules, computed here)
  2. downloads the day until its `done` file(s) exist: first try, then 5 retries ~5 minutes apart and 5 retries ~10
     minutes apart (each wait +/-20% at random, and the first try starts a random 0-8 minutes late), then gives up
  3. imports the day into Charting Lab, runs the setup scan of each exchange (skipped when its `done` file exists),
     slims the scans, then runs the pattern screens (daily and weekly; saved sessions are skipped)

The tools each step runs (today: the EOD downloader, Charting Lab's CSV import, the SwingScanner) are named only in
scripts/daily_update.toml (or --config / DAILY_CONFIG): replacing one is an edit there, not here.

Logs: backend/data/logs/daily_<market>_<date>.log; the last result in backend/data/logs/daily_<market>_status.json.
"""
import argparse
import datetime as dt
import json
import logging
import os
import random
import re
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
APP = HERE.parent                                            # Charting-platform
BACKEND = APP / "backend"
APP_PY = APP / ".venv" / "Scripts" / "python.exe"
PROJECTS = APP.parent
CONFIG = Path(os.environ.get("DAILY_CONFIG", HERE / "daily_update.toml"))
ENV_PATHS = {"eod": "DAILY_EOD_DIR", "scanner": "DAILY_SCANNER_DIR"}    # environment overrides of [paths]
LOGS = Path(os.environ.get("DAILY_LOGS_DIR", BACKEND / "data" / "logs"))   # tests use their own
NSE_HOLIDAYS = BACKEND / "data" / "nse_holidays.json"
WAITS_MIN = [5] * 5 + [10] * 5          # between attempts: 5 x 5 minutes, then 5 x 10 minutes
JITTER = 0.2                            # each wait +/-20% at random
START_JITTER_MIN = 8                    # the first try starts 0..8 minutes late, at random
IST = ZoneInfo("Asia/Kolkata")
NEW_YORK = ZoneInfo("America/New_York")

log = logging.getLogger("daily_update")


def load_config(path: Path = CONFIG) -> dict:
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    for key, env in ENV_PATHS.items():
        if os.environ.get(env):
            cfg.setdefault("paths", {})[key] = os.environ[env]
    return cfg


CFG = load_config()


@dataclass(frozen=True)
class Market:
    name: str                  # NSE | US
    exchanges: tuple           # the exchanges downloaded, imported, scanned and screened
    calendar: str              # NSE | US: whose holidays and which session a run updates
    scan: str                  # the [scan.*] profile of the config


def markets(cfg: dict | None = None) -> dict[str, Market]:
    cfg = cfg if cfg is not None else CFG
    return {k: Market(k, tuple(m["exchanges"]), m.get("calendar", k), m.get("scan", "exe"))
            for k, m in cfg.get("markets", {}).items()}


MARKETS = markets()


# ---------------------------------------------------------------- the config's placeholders
_FIELD = re.compile(r"\{([a-z_]+)\}")


def _context(market: Market | None = None, day: dt.date | None = None, exchange: str | None = None) -> dict:
    ctx = dict(app=APP, backend=BACKEND, projects=PROJECTS, app_py=APP_PY)
    if market is not None:
        ctx.update(market=market.name, exchanges=",".join(market.exchanges))
    if day is not None:
        ctx.update(day=day.isoformat(), yyyymmdd=f"{day:%Y%m%d}")
    if exchange is not None:
        ctx["exchange"] = exchange
    return {k: str(v) for k, v in ctx.items()}


def fill(text: str, ctx: dict) -> str:
    """`text` with its {placeholders} filled from `ctx` and the config's [paths] (which may use each other)."""
    paths = CFG.get("paths", {})

    def one(m: re.Match) -> str:
        k = m.group(1)
        if k in ctx:
            return ctx[k]
        if k in paths:
            return fill(paths[k], ctx)
        raise KeyError(f"unknown placeholder {{{k}}} in {text!r} ({CONFIG})")
    return _FIELD.sub(one, text)


def path(name: str) -> Path:
    """A [paths] entry of the config."""
    return Path(fill("{" + name + "}", _context()))


def command(step: dict, market: Market, day: dt.date, exchange: str | None = None) -> list[str]:
    ctx = _context(market, day, exchange)
    out: list[str] = []
    for arg in step["command"]:
        out += list(market.exchanges) if arg == "{exchanges...}" else [fill(arg, ctx)]
    return out


def run_step(step: dict, market: Market, day: dt.date, exchange: str | None = None, name: str | None = None,
             timeout: int = 3 * 3600) -> bool:
    ctx = _context(market, day, exchange)
    env = {k: fill(v, ctx) for k, v in step.get("env", {}).items()} or None
    return run(command(step, market, day, exchange), Path(fill(step.get("cwd", "{app}"), ctx)),
               name or fill(step.get("name", "step"), ctx), timeout=timeout, env=env)


def done_file(step: dict, market: Market, day: dt.date, exchange: str) -> Path | None:
    return Path(fill(step["done"], _context(market, day, exchange))) if step.get("done") else None


def fetch_nse_holidays(year: int) -> list[str]:
    """NSE's trading holidays (capital market segment) for `year`, as ISO dates, from nseindia.com."""
    import requests

    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                      "Referer": "https://www.nseindia.com/resources/exchange-communication-holidays"})
    s.get("https://www.nseindia.com/", timeout=20)                       # cookies, as the EOD downloader does
    time.sleep(random.uniform(1, 3))
    r = s.get("https://www.nseindia.com/api/holiday-master?type=trading", timeout=20)
    r.raise_for_status()
    out = set()
    for row in r.json().get("CM", []):                                   # "26-Jan-2026"
        d = dt.datetime.strptime(row["tradingDate"], "%d-%b-%Y").date()
        if d.year == year:
            out.add(d.isoformat())
    return sorted(out)


def nse_holidays(year: int) -> set[str] | None:
    """The year's NSE trading holidays: cached in backend/data/nse_holidays.json, fetched when missing.
    None when they cannot be had (then only weekends are skipped; a holiday simply finds no bhavcopy)."""
    cache = {}
    if NSE_HOLIDAYS.is_file():
        try:
            cache = json.loads(NSE_HOLIDAYS.read_text(encoding="utf-8"))
        except ValueError:
            cache = {}
    if str(year) in cache:
        return set(cache[str(year)])
    try:
        days = fetch_nse_holidays(year)
    except Exception as e:  # noqa: BLE001  the network or NSE may be down; the run goes on
        log.warning("could not fetch NSE's holiday list for %s: %s", year, e)
        return None
    if days:
        cache[str(year)] = days
        NSE_HOLIDAYS.parent.mkdir(parents=True, exist_ok=True)
        NSE_HOLIDAYS.write_text(json.dumps(cache, indent=1), encoding="utf-8")
        log.info("NSE holidays %s: %d days cached", year, len(days))
    return set(days)


def _easter(y: int) -> dt.date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return dt.date(y, month, (h + l - 7 * m + 114) % 31 + 1)


def _nth_weekday(y: int, month: int, weekday: int, n: int) -> dt.date:
    """The n-th `weekday` (0 = Monday) of the month; n = -1 for the last one."""
    if n > 0:
        d = dt.date(y, month, 1)
        d += dt.timedelta((weekday - d.weekday()) % 7)
        return d + dt.timedelta(weeks=n - 1)
    d = dt.date(y + (month == 12), month % 12 + 1, 1) - dt.timedelta(1)
    return d - dt.timedelta((d.weekday() - weekday) % 7)


def _observed(d: dt.date) -> dt.date:
    """A fixed-date holiday on a Saturday is observed the Friday before, on a Sunday the Monday after."""
    return d - dt.timedelta(1) if d.weekday() == 5 else d + dt.timedelta(1) if d.weekday() == 6 else d


def us_holidays(year: int) -> set[str]:
    """NYSE / NASDAQ full-day holidays (NYSE rules). New Year's Day on a Saturday is not moved to the Friday before."""
    new_year = dt.date(year, 1, 1)
    days = [
        new_year if new_year.weekday() < 5 else (new_year + dt.timedelta(1) if new_year.weekday() == 6 else None),
        _nth_weekday(year, 1, 0, 3),                     # Martin Luther King Jr. Day: 3rd Monday of January
        _nth_weekday(year, 2, 0, 3),                     # Washington's Birthday: 3rd Monday of February
        _easter(year) - dt.timedelta(2),                 # Good Friday
        _nth_weekday(year, 5, 0, -1),                    # Memorial Day: last Monday of May
        _observed(dt.date(year, 6, 19)) if year >= 2022 else None,   # Juneteenth
        _observed(dt.date(year, 7, 4)),                  # Independence Day
        _nth_weekday(year, 9, 0, 1),                     # Labor Day: 1st Monday of September
        _nth_weekday(year, 11, 3, 4),                    # Thanksgiving: 4th Thursday of November
        _observed(dt.date(year, 12, 25)),                # Christmas
    ]
    return {d.isoformat() for d in days if d is not None}


def trading_day(market: Market, day: dt.date) -> tuple[bool, str]:
    if day.weekday() >= 5:
        return False, "weekend"
    if market.calendar == "US":
        return (False, "US market holiday") if day.isoformat() in us_holidays(day.year) else (True, "trading day")
    hol = nse_holidays(day.year)
    if hol is not None and day.isoformat() in hol:
        return False, "NSE trading holiday"
    return True, "trading day" if hol is not None else "weekday (holiday list unavailable)"


def session_day(market: Market, now: dt.datetime | None = None) -> dt.date:
    """The session to update: NSE = today in India; US = the New York session that has closed (at 08:00 India time
    it is the previous evening in New York, so that day)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if market.calendar == "US":
        ny = now.astimezone(NEW_YORK)
        return ny.date() if ny.time() >= dt.time(17, 0) else ny.date() - dt.timedelta(1)
    return now.astimezone(IST).date()


# ---------------------------------------------------------------- steps
def day_file(exchange: str, day: dt.date, market: Market | None = None) -> Path:
    """The file that shows the day's data of `exchange` is out (the download's `done`)."""
    market = market or next((m for m in MARKETS.values() if exchange in m.exchanges), Market("", (exchange,), "", ""))
    return done_file(CFG["download"], market, day, exchange)


def jittered(seconds: float) -> float:
    """`seconds` +/- up to JITTER of itself, at random."""
    return seconds * random.uniform(1 - JITTER, 1 + JITTER)


def run(cmd: list, cwd: Path, name: str, timeout: int = 3 * 3600, env: dict | None = None) -> bool:
    log.info("%s: %s", name, " ".join(str(c) for c in cmd))
    t = time.time()
    p = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env=dict(os.environ, PYTHONUTF8="1", **(env or {})))
    lines = [x for x in (p.stdout + p.stderr).splitlines() if x.strip() and "chunks |" not in x]
    for x in lines[-8:]:
        log.info("   %s", x)
    log.info("%s: %s in %.0fs", name, "ok" if p.returncode == 0 else f"FAILED (exit {p.returncode})", time.time() - t)
    return p.returncode == 0


def download(market: Market, day: dt.date, dry: bool, sleep=time.sleep, now: bool = False) -> bool:
    """Run the download step until the `done` file of every exchange exists: first try (a random few minutes late),
    then 5 waits of ~5 minutes and 5 of ~10 minutes. now=True (an admin's click): one try, at once."""
    targets = [day_file(ex, day, market) for ex in market.exchanges]
    if all(t.is_file() for t in targets):
        log.info("%s data for %s is already here", market.name, day)
        return True
    if dry:
        log.info("[dry run] would download %s for %s, retrying %s minutes apart (+/-%d%%)", "/".join(market.exchanges),
                 day, WAITS_MIN, JITTER * 100)
        return True
    waits = [] if now else WAITS_MIN
    if not now:
        first = random.uniform(0, START_JITTER_MIN * 60)
        log.info("starting in %.1f minutes (random, so the requests are not at the same second every day)", first / 60)
        sleep(first)
    for attempt in range(len(waits) + 1):
        dl = CFG["download"]
        run_step(dl, market, day, name=f"download (attempt {attempt + 1}/{len(waits) + 1})",
                 timeout=int(dl.get("timeout_min", 60)) * 60)
        missing = [t.name for t in targets if not t.is_file()]
        if not missing:
            log.info("%s data for %s downloaded", market.name, day)
            return True
        if attempt < len(waits):
            wait = jittered(waits[attempt] * 60)
            log.info("not out yet (%s): next try in %.1f minutes", ", ".join(missing), wait / 60)
            sleep(wait)
    log.error("%s data for %s still missing after %d attempts: giving up for today", market.name, day,
              len(waits) + 1)
    return False


def scan_profile(market: Market) -> dict:
    prof = CFG["scan"][market.scan]
    needs = prof.get("needs")
    if needs and not Path(fill(needs, _context(market))).is_file() and prof.get("fallback"):
        prof = CFG["scan"][prof["fallback"]]
    return prof


def scan(market: Market, exchange: str, day: dt.date) -> bool:
    """The setup scan of one exchange and day, unless its `done` file exists."""
    prof = scan_profile(market)
    done = done_file(prof, market, day, exchange)
    if done is not None and done.is_file():
        log.info("setup scan %s %s is already saved", exchange, day)
        return True
    ok = run_step(prof, market, day, exchange)
    if done is None:
        return ok
    # done only when that day's scan is saved (a scanner may exit normally after scanning an earlier day)
    if done.is_file():
        return True
    log.error("setup scan %s %s: no scan of that day was saved", exchange, day)
    return False


def after_download(market: Market, day: dt.date, dry: bool, only: set[str] | None = None) -> dict:
    """Import, setup scan (+ slim), pattern screen; `only` picks some of "import", "scan", "screen"."""
    want = only or {"import", "scan", "screen"}
    ex = ",".join(market.exchanges)
    if dry:
        log.info("[dry run] would run %s for %s %s", ", ".join(x for x in ("import", "scan", "screen") if x in want),
                 ex, day)
        names = {"import": "import_eod", "scan": "setup_scan", "screen": "pattern_screen"}
        return {names[k]: "dry run" for k in ("import", "scan", "screen") if k in want}
    steps = {}
    if "import" in want:
        steps["import_eod"] = run_step(CFG["import"], market, day)
    if "scan" in want:
        steps["setup_scan"] = all([scan(market, e, day) for e in market.exchanges])
        if CFG.get("slim"):
            run_step(CFG["slim"], market, day)
    if "screen" in want:
        steps["pattern_screen"] = run_step(CFG["screen"], market, day)
    return steps


def maintenance(market: Market, day: dt.date, dry: bool) -> dict:
    """The config's [[maintenance]] steps (the location database, old activity records ...): every run, trading day
    or not; a failed one is logged and does not fail the run."""
    out = {}
    for step in CFG.get("maintenance", []):
        name = step.get("name", " ".join(step["command"][:3]))
        if dry:
            log.info("[dry run] would run %s", name)
            out[name] = "dry run"
            continue
        out[name] = run_step(step, market, day, name=name, timeout=int(step.get("timeout_min", 30)) * 60)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", choices=sorted(MARKETS), required=True)
    ap.add_argument("--date", help="the session (YYYY-MM-DD; default: NSE today in India, US the last New York session)")
    ap.add_argument("--dry-run", action="store_true", help="only log what would be done")
    ap.add_argument("--only", default="", help="some steps: download,import,scan,screen (a run by hand; default: all, "
                                                "plus the maintenance chores)")
    ap.add_argument("--now", action="store_true", help="download at once and try once (no random start, no retries)")
    a = ap.parse_args(argv)
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    bad = only - set(("download", "import", "scan", "screen"))
    if bad:
        ap.error(f"unknown steps {sorted(bad)}: use download, import, scan, screen")
    market = MARKETS[a.market]
    day = dt.date.fromisoformat(a.date) if a.date else session_day(market)

    LOGS.mkdir(parents=True, exist_ok=True)
    tag = market.name.lower()
    for h in list(log.handlers):
        log.removeHandler(h)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(LOGS / f"daily_{tag}_{day:%Y%m%d}.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)
    status = dict(market=market.name, day=day.isoformat(), started=dt.datetime.now().isoformat(timespec="seconds"),
                  dry_run=a.dry_run)
    lock = LOGS / f"daily_{tag}.lock"
    if lock.exists() and time.time() - lock.stat().st_mtime < 4 * 3600:
        log.warning("another %s run is in progress (%s): stopping", market.name, lock)
        return 0
    lock.write_text(str(os.getpid()))
    try:
        status["only"] = sorted(only) if only else "all"
        if not only:
            status["maintenance"] = maintenance(market, day, a.dry_run)
        ok, why = trading_day(market, day)
        log.info("%s %s: %s", market.name, day, why)
        status["trading_day"] = why
        if not ok:
            status["result"] = f"skipped: {why}"
            return 0
        if (not only or "download" in only) and not download(market, day, a.dry_run, now=a.now):
            status["result"] = "data not available: nothing else was run"
            return 1
        rest = (only or {"import", "scan", "screen"}) - {"download"}
        status["steps"] = after_download(market, day, a.dry_run, rest) if rest else {}
        good = all(v is True or v == "dry run" for v in status["steps"].values())   # (no steps: the download did it)
        status["result"] = "done" if good else "done with errors"
        log.info("finished: %s", status["result"])
        return 0 if good else 1
    finally:
        status["finished"] = dt.datetime.now().isoformat(timespec="seconds")
        (LOGS / f"daily_{tag}_status.json").write_text(json.dumps(status, indent=1), encoding="utf-8")
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
