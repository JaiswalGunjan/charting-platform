"""Admin CLI.

    python -m app.cli init-db
    python -m app.cli load-symbols
    python -m app.cli load-candles --symbols NSE:RELIANCE,NSE:TCS --tf 1m --days 30
    python -m app.cli load-candles --symbols all --tf 1D --days 3650
    python -m app.cli seed            # init + symbols + 30d of 1m + 5y of 1D for the whole universe
    python -m app.cli kite-login      # daily Kite access-token flow
    python -m app.cli import-eod --dir <market_data_daily> --exchanges NSE   # real daily (+ hourly) history from CSVs
    python -m app.cli screen [--exchanges NSE --tf 1D,1W] [--date D | --days 30]  # pattern screener (dashboard)
    python -m app.cli update-names                                            # company names from exchange lists
    python -m app.cli import-eod --only hourly                                # just the 1h bars (EOD_HOURLY_DIR)
"""
import argparse
from pathlib import Path as _Path
import time
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.marketdata.loader import get_source, load_history, resolve_symbol, upsert_symbols
from app.models import Symbol


# the EOD_Market_Data folder next to this project (minute and Alpaca stores)
EOD_DEFAULT = _Path(__file__).resolve().parents[3] / "EOD_Market_Data"

def cmd_init_db(_: argparse.Namespace) -> None:
    init_db()
    print("database ready:", get_settings().database_url)


def cmd_load_symbols(_: argparse.Namespace) -> None:
    init_db()
    source = get_source(get_settings())
    with SessionLocal() as s:
        n = upsert_symbols(s, source.symbols())
    print(f"upserted {n} symbols from {source.name}")


def cmd_load_candles(args: argparse.Namespace) -> None:
    init_db()
    source = get_source(get_settings())
    end = date.today()
    start = end - timedelta(days=args.days)
    with SessionLocal() as s:
        if args.symbols == "all":
            syms = list(s.scalars(select(Symbol).order_by(Symbol.id)))
        else:
            syms = []
            for name in args.symbols.split(","):
                sym = resolve_symbol(s, name)
                if sym is None:
                    sys.exit(f"unknown symbol {name!r}; run load-symbols first")
                syms.append(sym)
        total = 0
        for sym in syms:
            for tf in args.tf.split(","):
                total += load_history(s, source, sym, tf, start, end)
    print(f"loaded {total} bars for {len(syms)} symbols ({start}..{end}) from {source.name}")


def cmd_seed(args: argparse.Namespace) -> None:
    cmd_load_symbols(args)
    cmd_load_candles(argparse.Namespace(symbols="all", tf="1m", days=args.minute_days))
    cmd_load_candles(argparse.Namespace(symbols="all", tf="1D", days=args.daily_days))


NAMES_CACHE = Path(__file__).resolve().parents[1] / "data" / "names"


def _names(exchange: str, root: Path | None, refresh: bool):
    from app.marketdata import names

    got = names.fetch(NAMES_CACHE, force=refresh)
    if got:
        print("downloaded public listing files:", ", ".join(got))
    return names.load(exchange, NAMES_CACHE, root)


def cmd_import_eod(args: argparse.Namespace) -> None:
    from app.marketdata.eod import import_exchange, import_exchange_hourly

    settings = get_settings()
    parts = {p.strip() for p in args.only.split(",")} if args.only else {"daily", "hourly"}
    exchanges = [e.strip().upper() for e in (args.exchanges.split(",") if args.exchanges else settings.eod_exchanges)]
    root = Path(args.dir or settings.eod_dir) if (args.dir or settings.eod_dir) else None
    hroot = Path(args.hourly_dir or settings.eod_hourly_dir) if (args.hourly_dir or settings.eod_hourly_dir) else None
    if "daily" in parts and (root is None or not root.is_dir()):
        sys.exit("pass --dir or set EOD_DIR in .env to your market_data_daily folder")
    if args.only and "hourly" in parts and (hroot is None or not hroot.is_dir()):
        sys.exit("pass --hourly-dir or set EOD_HOURLY_DIR in .env to your market_data_hourly folder")
    init_db()
    with SessionLocal() as s:
        for ex in exchanges:
            names = _names(ex, root, args.refresh_names)
            if "daily" in parts:
                r = import_exchange(s, root, ex, names)
                print(f"{r.exchange}: {r.bars:,} daily bars, {r.symbols:,} symbols, {r.first_date}..{r.last_date} "
                      f"from {r.files:,} files in {r.seconds}s (removed {r.removed_symbols} symbols not in the files)")
            if "hourly" in parts and hroot is not None:
                from app.marketdata.eod import hourly_files

                if not (hroot / ex).is_dir() or not hourly_files(hroot, ex):
                    print(f"{ex}: no hourly files under {hroot / ex}, skipped")
                    continue
                r = import_exchange_hourly(s, hroot, ex, names)
                print(f"{r.exchange}: {r.bars:,} hourly bars, {r.symbols:,} symbols, {r.first_date}..{r.last_date} "
                      f"from {r.files:,} files in {r.seconds}s")


def cmd_scanner_slim(args: argparse.Namespace) -> None:
    """Drop what saved scans do not need (SwingScanner: each scan's chart pages; Charting Lab draws its own charts)."""
    from app.providers import setup_scanners

    for sc in setup_scanners().values():
        if not sc.status().get("configured"):
            print(f"{sc.title}: not set up")
            continue
        n, freed = sc.slim()
        print(f"{sc.title}: slimmed {n} scans, {freed / 1e6:,.0f} MB freed")


def cmd_import_minute(args: argparse.Namespace) -> None:
    """Alpaca 1-minute Parquet files -> the minute store, on our daily bars' basis (app/marketdata/alpaca_minute.py)."""
    from pathlib import Path

    from app.marketdata.alpaca_minute import import_exchange

    eod = Path(args.eod_dir)
    folder = Path(args.dir) if args.dir else eod / "market_data_minute" / args.exchange.upper()
    daily = eod / "market_data_alpaca" / "daily"

    def progress(r):
        print(f"  {r.imported:,} imported ({r.bars:,} bars), {r.skipped_unchanged:,} unchanged, "
              f"{len(r.not_ours)} not ours, {len(r.no_factor)} without daily bars", flush=True)

    r = import_exchange(SessionLocal, folder, args.exchange, daily, limit=args.limit or None, progress=progress)
    print(f"{r.exchange}: {r.imported:,} of {r.files:,} files imported, {r.bars:,} minute bars in {r.seconds}s; "
          f"{r.skipped_unchanged:,} unchanged since the last import; {len(r.not_ours)} not our symbols "
          f"{r.not_ours[:5]}; {len(r.no_factor)} without daily bars {r.no_factor[:5]}")


def cmd_update_geoip(args: argparse.Namespace) -> None:
    """The IP-to-location database for sign-in locations (DB-IP City Lite), then the locations missing so far."""
    from app.auth import geoip

    got = geoip.refresh(if_older_days=args.if_older_days, force=args.force or args.if_older_days is None)
    print(f"downloaded {got['month']} ({got['bytes'] / 1e6:,.0f} MB) to {geoip.DEFAULT_DB}" if got
          else f"up to date: {geoip.info()['path']} ({geoip.age_days():.0f} days old)")
    init_db()                                   # the sign-in tables, if the app has not made them yet
    print("locations filled in:", geoip.backfill(SessionLocal))


def cmd_prune_activity(args: argparse.Namespace) -> None:
    """Delete sign-in records and activity older than ACTIVITY_RETENTION_DAYS (or --days)."""
    from app.api.admin import prune
    from app.config import get_settings

    days = args.days or get_settings().activity_retention_days
    init_db()
    print(f"older than {days} days, deleted:", prune(SessionLocal, days))


def cmd_minute_store(args: argparse.Namespace) -> None:
    """The minute-bar store (BAR_STORES=1m=timescale): set it up, show its size, apply its policies now."""
    from app.marketdata.minute_store import TimescaleMinuteStore

    st = TimescaleMinuteStore()
    st.ensure_schema()
    if args.compress:
        print(f"compressed {st.compress_now()} chunks")
    if args.prune:
        print(f"dropped {st.apply_retention()} chunks older than {st.retention_days} days")
    s = st.stats()
    span = ""
    if s["first"]:
        day = lambda t: time.strftime("%Y-%m-%d", time.gmtime(t + 19800))  # noqa: E731
        span = f", {day(s['first'])}..{day(s['last'])}"
    print(f"minute bars: {s['bars']:,}{span}; {s['bytes'] / 1e6:,.0f} MB in {s['chunks']} weekly chunks "
          f"({s['compressed_chunks']} compressed); kept {s['retention_days']} days, compressed after "
          f"{s['compress_after_days']} (TimescaleDB policies)")


def cmd_screen(args: argparse.Namespace) -> None:
    """'Patterns formed today' for the dashboard (schedule it after the nightly data import)."""
    from app.patterns.screener import backfill_days, run_screen, screen_dates

    settings = get_settings()
    init_db()
    exchanges = [e.strip().upper() for e in (args.exchanges.split(",") if args.exchanges else settings.eod_exchanges)]
    for ex in exchanges:
        for tf in args.tf.replace(",", " ").split():         # "1D,1W" or "1D 1W" (PowerShell splits commas)
            if args.days:
                have = set(screen_dates(ex, tf))
                days = [d for d in backfill_days(SessionLocal, ex, tf, args.days) if d not in have]
                print(f"{ex} {tf}: {len(days)} sessions to screen in the last {args.days} days")
            else:
                days = [args.date or None]
            for day in days:
                r = run_screen(SessionLocal, ex, tf, day=day)
                print(f"{ex} {tf} {r.get('session', '')}: {len(r['rows']):,} symbols with patterns, of "
                      f"{r['scanned']:,} screened, in {r.get('seconds', 0)}s", flush=True)


def cmd_update_names(args: argparse.Namespace) -> None:
    from app.marketdata.eod import apply_names

    settings = get_settings()
    root = Path(settings.eod_dir) if settings.eod_dir else None
    exchanges = [e.strip().upper() for e in (args.exchanges.split(",") if args.exchanges else settings.eod_exchanges)]
    init_db()
    with SessionLocal() as s:
        for ex in exchanges:
            n = apply_names(s, ex, _names(ex, root, args.refresh_names))
            print(f"{ex}: {n:,} symbols have a company name")


def cmd_kite_login(_: argparse.Namespace) -> None:
    from app.marketdata.kite import exchange_request_token, login_url

    settings = get_settings()
    if not settings.kite_api_key or not settings.kite_api_secret:
        sys.exit("set KITE_API_KEY and KITE_API_SECRET in .env first")
    print("1. Open and log in:", login_url(settings))
    print("2. Copy `request_token` from the redirect URL.")
    token = input("request_token: ").strip()
    access = exchange_request_token(settings, token)
    print("\nAdd this to .env (valid until ~6 AM tomorrow):\nKITE_ACCESS_TOKEN=" + access)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db").set_defaults(fn=cmd_init_db)
    sub.add_parser("load-symbols").set_defaults(fn=cmd_load_symbols)
    lc = sub.add_parser("load-candles")
    lc.add_argument("--symbols", required=True, help="comma list (NSE:RELIANCE) or 'all'")
    lc.add_argument("--tf", default="1m", help="1m, 1D or '1m,1D'")
    lc.add_argument("--days", type=int, default=30)
    lc.set_defaults(fn=cmd_load_candles)
    sd = sub.add_parser("seed")
    sd.add_argument("--minute-days", type=int, default=30)
    sd.add_argument("--daily-days", type=int, default=5 * 365)
    sd.set_defaults(fn=cmd_seed)
    ie = sub.add_parser("import-eod", help="replace daily (and hourly) history with local adjusted CSVs")
    ie.add_argument("--dir", default="", help="market_data_daily folder (default: EOD_DIR)")
    ie.add_argument("--hourly-dir", default="", help="market_data_hourly folder (default: EOD_HOURLY_DIR)")
    ie.add_argument("--only", default="", help="daily, hourly or daily,hourly (default: both that are configured)")
    ie.add_argument("--exchanges", default="", help="e.g. NSE or NSE,BSE,NASDAQ,NYSE (default: EOD_EXCHANGES)")
    ie.add_argument("--refresh-names", action="store_true", help="re-download the public listing files")
    ie.set_defaults(fn=cmd_import_eod)
    sl = sub.add_parser("scanner-slim", help="slim the saved setup scans (SwingScanner: remove their chart pages, keep their data)")
    sl.set_defaults(fn=cmd_scanner_slim)
    sc = sub.add_parser("screen", help="patterns formed on the latest bar, for the dashboard")
    sc.add_argument("--exchanges", default="", help="default: EOD_EXCHANGES")
    sc.add_argument("--tf", default="1D,1W", help="1D, 1W or 1D,1W")
    sc.add_argument("--date", default="", help="screen the bar of this session (YYYY-MM-DD; default: the latest)")
    sc.add_argument("--days", type=int, default=0,
                    help="backfill: screen every session of the last N days that has no saved screen")
    sc.set_defaults(fn=cmd_screen)
    un = sub.add_parser("update-names", help="refresh company names from public exchange listings")
    un.add_argument("--exchanges", default="", help="default: EOD_EXCHANGES")
    un.add_argument("--refresh-names", action="store_true", help="re-download the listing files")
    un.set_defaults(fn=cmd_update_names)
    sub.add_parser("kite-login").set_defaults(fn=cmd_kite_login)
    im = sub.add_parser("import-minute", help="Alpaca 1-minute Parquet files -> the minute store (BAR_STORES=1m=...)")
    im.add_argument("--exchange", required=True, help="NASDAQ or NYSE")
    im.add_argument("--eod-dir", default=str(EOD_DEFAULT),
                    help="the EOD_Market_Data folder (market_data_minute/, market_data_alpaca/daily/)")
    im.add_argument("--dir", default="", help="the exchange's Parquet folder (default: <eod-dir>/market_data_minute/<EX>)")
    im.add_argument("--limit", type=int, default=0, help="only the first N files to import (a test run)")
    im.set_defaults(fn=cmd_import_minute)
    gi = sub.add_parser("update-geoip", help="download the IP-to-location database (DB-IP City Lite, monthly)")
    gi.add_argument("--if-older-days", type=float, default=None, help="only when the file is older than this")
    gi.add_argument("--force", action="store_true")
    gi.set_defaults(fn=cmd_update_geoip)
    pa = sub.add_parser("prune-activity", help="delete sign-in records and user activity past ACTIVITY_RETENTION_DAYS")
    pa.add_argument("--days", type=int, default=0)
    pa.set_defaults(fn=cmd_prune_activity)
    ms = sub.add_parser("minute-store", help="minute bars in TimescaleDB: set up, size, policies (BAR_STORES=1m=timescale)")
    ms.add_argument("--compress", action="store_true", help="compress the chunks past the window now")
    ms.add_argument("--prune", action="store_true", help="drop the chunks older than MINUTE_RETENTION_DAYS now")
    ms.set_defaults(fn=cmd_minute_store)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
