"""Admin CLI.

    python -m app.cli init-db
    python -m app.cli load-symbols
    python -m app.cli load-candles --symbols NSE:RELIANCE,NSE:TCS --tf 1m --days 30
    python -m app.cli load-candles --symbols all --tf 1D --days 3650
    python -m app.cli seed            # init + symbols + 30d of 1m + 5y of 1D for the whole universe
    python -m app.cli kite-login      # daily Kite access-token flow
"""
import argparse
import logging
import sys
from datetime import date, timedelta

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
    sub.add_parser("kite-login").set_defaults(fn=cmd_kite_login)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
