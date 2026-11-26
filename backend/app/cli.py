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
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.marketdata.loader import get_source, load_history, resolve_symbol, upsert_symbols
from app.models import Symbol


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
    """Remove the charts/ folder of every saved scan (Charting Lab draws its own charts)."""
    from app.api.scanner import scanner_dir, slim_scans

    root = scanner_dir()
    if root is None:
        print("SCANNER_DIR is not set")
        return
    n, freed = slim_scans(root)
    print(f"removed the chart pages of {n} scans, {freed / 1e6:,.0f} MB freed")


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
    sl = sub.add_parser("scanner-slim", help="remove the chart pages from saved SwingScanner scans (keeps their data)")
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
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
