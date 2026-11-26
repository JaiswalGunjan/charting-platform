"""Download 1-minute US bars from Alpaca into their own folder, one Parquet file per symbol (resumable).

    python scripts/alpaca_minute.py --exchange NASDAQ                       # last 2 years, every key, one API key
    python scripts/alpaca_minute.py --exchange NASDAQ --shard 0/2 &         # two halves at once, each with its own
    python scripts/alpaca_minute.py --exchange NASDAQ --shard 1/2 &         #   API key (200 requests a minute each)
    python scripts/alpaca_minute.py --exchange NASDAQ --limit 20            # a quick test: the first 20 keys

What it reads (nothing there is written):
  <eod>/market_data_alpaca/universe.csv      every NASDAQ / NYSE key, delisted ones included, with the `asof` date
                                             Alpaca's symbol mapping needs for a delisted company
  <eod>/market_data_alpaca/daily/<EX>/*.pkl  daily bars: tell which keys traded in the window
  <eod>/.alpaca*.env                         the API keys, through EOD_Market_Data's alpaca_api (never printed)

What it writes, under <eod>/market_data_minute/<EX>/:
  _universe_<start>_<end>.csv                the keys of the window (key, symbol, asof, first, last)
  <key>.parquet                              ts (UTC), open, high, low, close, volume, trades, vwap; zstd
  ../logs/minute_<EX>_<shard>_<time>.log

Bars are Alpaca's SIP feed (every US exchange), **as traded** (adjustment=raw), like the daily and hourly Alpaca store:
put them on an adjusted basis with the daily file's factors (f_split, f_spinoff). Every bar Alpaca returns is kept,
pre-market (from 04:00 New York) and after-hours (to 20:00) included; Alpaca writes no bar for a minute without trades.
A key with no bars in the window gets an empty file, so a rerun skips it. Needs pandas, requests, pyarrow.
"""
import argparse
import datetime as dt
import logging
import re
import sys
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EOD = ROOT.parent / "EOD_Market_Data"
NY = "America/New_York"
COLS = {"t": "ts", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "n": "trades", "vw": "vwap"}
WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{d}{i}" for d in ("COM", "LPT") for i in range(10)}

log = logging.getLogger("alpaca_minute")


# ---------------------------------------------------------------- pure helpers (tested in test_m21_alpaca_minute.py)

def key_file(out_dir: Path, key: str) -> Path:
    """File of a key, named like the Alpaca store: '/' -> '~', a Windows reserved name (CON, NUL ...) gets '_'."""
    stem = key.replace("/", "~")
    if stem.split(".")[0].split("@")[0].upper() in WIN_RESERVED:
        stem += "_"
    return out_dir / f"{stem}.parquet"


def in_shard(key: str, shard: tuple[int, int] | None) -> bool:
    return shard is None or zlib.crc32(key.encode()) % shard[1] == shard[0]


def ny_bounds(start: dt.date, end: dt.date) -> tuple[str, str]:
    """RFC 3339 UTC bounds covering the New York calendar days start..end (both whole)."""
    s = pd.Timestamp(start).tz_localize(NY).tz_convert("UTC")
    e = (pd.Timestamp(end) + pd.Timedelta(days=1)).tz_localize(NY).tz_convert("UTC") - pd.Timedelta(seconds=1)
    return s.strftime("%Y-%m-%dT%H:%M:%SZ"), e.strftime("%Y-%m-%dT%H:%M:%SZ")


def frame(bars: list[dict]) -> pd.DataFrame:
    """Alpaca bar records -> the file's columns, sorted by time."""
    df = pd.DataFrame(bars, columns=list(COLS)).rename(columns=COLS)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    for c in ("open", "high", "low", "close", "vwap"):
        df[c] = df[c].astype("float64")
    for c in ("volume", "trades"):
        df[c] = df[c].fillna(0).astype("int64")
    return df.sort_values("ts", kind="stable").drop_duplicates("ts").reset_index(drop=True)


def combine(pages: list[pd.DataFrame]) -> pd.DataFrame:
    """One symbol's page frames -> one frame (a symbol can span pages)."""
    if not pages:
        return frame([])
    df = pd.concat(pages, ignore_index=True) if len(pages) > 1 else pages[0]
    return df.sort_values("ts", kind="stable").drop_duplicates("ts").reset_index(drop=True)


def window_keys(universe: pd.DataFrame, spans: dict[str, tuple[str, str] | None], start: dt.date) -> pd.DataFrame:
    """The keys that traded on or after `start`. `spans` = key -> (first, last daily bar) or None (no daily file).
    An active key without daily bars is a new listing and is kept; any other key needs a daily bar in the window, or
    (no daily file) a delisting date in it."""
    rows = []
    for r in universe.itertuples():
        span = spans.get(r.key)
        delisted = r.delisted if isinstance(r.delisted, str) and r.delisted else ""
        if span is not None:
            keep = span[1] >= start.isoformat()
        else:
            keep = r.status == "active" or (delisted != "" and delisted >= start.isoformat())
        if keep:
            rows.append(dict(key=r.key, symbol=r.symbol, asof=r.asof if isinstance(r.asof, str) else "",
                             first=span[0] if span else "", last=span[1] if span else "", delisted=delisted))
    return pd.DataFrame(rows, columns=["key", "symbol", "asof", "first", "last", "delisted"])


def key_end(row, end: dt.date) -> dt.date:
    """Stop at the delisting date (the day after: its last session) so a reused ticker never brings another company."""
    if row.delisted:
        return min(end, dt.date.fromisoformat(row.delisted[:10]))
    return end


# ---------------------------------------------------------------- Alpaca

def load_alpaca(eod: Path):
    sys.path.insert(0, str(eod))
    import alpaca_api                      # EOD_Market_Data's client: key files, 200/min pacing, 429 back-off
    return alpaca_api


def working_clients(alpaca_api) -> list[tuple[str, object]]:
    out = []
    for name, key, sec in alpaca_api._pools():
        api = alpaca_api.Client(key, sec)
        js, _ = api.get(f"{alpaca_api.DATA_URL}/v2/stocks/bars",
                        dict(symbols="AAPL", timeframe="1Day", start="2024-01-02", end="2024-01-03", feed="sip"),
                        tries=2)
        if js is not None:
            out.append((name, api))
    return out


def fetch(api, data_url: str, symbols: list[str], s: str, e: str, asof: str, stats: dict) -> tuple[dict, list[str]]:
    """{symbol: [page frames]} for a few symbols in one paged request; symbols Alpaca calls invalid are returned
    separately (the request is repeated without them)."""
    ok, bad = list(symbols), []
    while ok:
        params = dict(symbols=",".join(ok), timeframe="1Min", start=s, end=e, adjustment="raw", feed="sip",
                      limit=10000, sort="asc")
        if asof:
            params["asof"] = asof
        got, js, err = {}, None, ""
        while True:
            js, err = api.get(f"{data_url}/v2/stocks/bars", params)
            stats["requests"] += 1
            if js is None:
                break
            for sym, bl in (js.get("bars") or {}).items():
                if bl:                             # one small frame per page: far less memory than the records
                    got.setdefault(sym, []).append(frame(bl))
            tok = js.get("next_page_token")
            if not tok:
                break
            params["page_token"] = tok
        if js is not None:
            return got, bad
        m = re.search(r"invalid symbol: ([^\"}]+)\"", err or "")
        if m and m.group(1) in ok:
            ok.remove(m.group(1))
            bad.append(m.group(1))
            continue
        raise RuntimeError(f"bars request failed for {ok}: {err}")
    return {}, bad


def save(path: Path, df: pd.DataFrame):
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, engine="pyarrow", compression="zstd", index=False)
    tmp.replace(path)


# ---------------------------------------------------------------- main

def build_universe(eod: Path, ex: str, start: dt.date, path: Path) -> pd.DataFrame:
    store = eod / "market_data_alpaca"
    u = pd.read_csv(store / "universe.csv", dtype=str, keep_default_na=False)
    u = u[u.exchange == ex]
    spans = {}
    for r in u.itertuples():
        p = key_file(store / "daily" / ex, r.key).with_suffix(".pkl")
        if p.exists():
            d = pd.read_pickle(p)
            spans[r.key] = (d.index[0].date().isoformat(), d.index[-1].date().isoformat()) if len(d) else ("", "")
    keys = window_keys(u, spans, start)
    tmp = path.with_suffix(".tmp")
    keys.to_csv(tmp, index=False)
    tmp.replace(path)
    return keys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--exchange", default="NASDAQ", choices=["NASDAQ", "NYSE"])
    ap.add_argument("--start", type=dt.date.fromisoformat, help="first New York day (default: 2 years before --end)")
    ap.add_argument("--end", type=dt.date.fromisoformat, help="last New York day (default: yesterday)")
    ap.add_argument("--eod-dir", type=Path, default=DEFAULT_EOD)
    ap.add_argument("--shard", help="i/n: only the keys whose CRC32 %% n == i; shard i uses the i-th working API key")
    ap.add_argument("--chunk", type=int, default=4, help="symbols per request")
    ap.add_argument("--workers", type=int, default=4, help="requests in flight (still paced 200 a minute per key)")
    ap.add_argument("--limit", type=int, help="only the first N keys still to fetch (a test run)")
    a = ap.parse_args(argv)

    end = a.end or dt.date.today() - dt.timedelta(days=1)
    start = a.start or end.replace(year=end.year - 2) + dt.timedelta(days=1)
    shard = tuple(int(x) for x in a.shard.split("/")) if a.shard else None
    out = a.eod_dir / "market_data_minute" / a.exchange
    logs = a.eod_dir / "market_data_minute" / "logs"
    out.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    tag = f"{shard[0]}of{shard[1]}" if shard else "all"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(logs / f"minute_{a.exchange}_{tag}_{dt.datetime.now():%Y%m%d_%H%M%S}.log",
                                                      encoding="utf-8")])

    uni_path = out / f"_universe_{start:%Y%m%d}_{end:%Y%m%d}.csv"
    if uni_path.exists():
        keys = pd.read_csv(uni_path, dtype=str, keep_default_na=False)
    else:
        log.info("building the %s key list for %s..%s from the Alpaca store", a.exchange, start, end)
        keys = build_universe(a.eod_dir, a.exchange, start, uni_path)
    todo = keys[[in_shard(k, shard) and not key_file(out, k).exists() for k in keys.key]]
    if a.limit:
        todo = todo.head(a.limit)
    log.info("%s %s..%s: %d keys in the window, %d to fetch in shard %s", a.exchange, start, end, len(keys),
             len(todo), a.shard or "all")
    if todo.empty:
        return 0

    alpaca_api = load_alpaca(a.eod_dir)
    clients = working_clients(alpaca_api)
    if not clients:
        log.error("no working Alpaca key")
        return 2
    name, api = clients[(shard[0] if shard else 0) % len(clients)]
    log.info("using the API key from %s (%d working)", name, len(clients))

    jobs = []
    for (asof, kend), g in todo.assign(kend=[key_end(r, end) for r in todo.itertuples()]).groupby(["asof", "kend"]):
        for i in range(0, len(g), a.chunk):
            jobs.append((asof, kend, g.iloc[i:i + a.chunk]))

    stats = dict(requests=0, bars=0, keys=0, empty=0, failed=0)
    lock, t0, last = threading.Lock(), time.monotonic(), [time.monotonic()]

    def one(job):
        asof, kend, part = job
        s, e = ny_bounds(start, kend)
        got, bad = fetch(api, alpaca_api.DATA_URL, list(part.symbol), s, e, asof, stats)
        n = 0
        for r in part.itertuples():
            pages = got.pop(r.symbol, [])
            df = combine(pages)
            save(key_file(out, r.key), df)
            n += len(df)
            with lock:
                stats["keys"] += 1
                stats["empty"] += df.empty
        with lock:
            stats["bars"] += n
        if bad:
            log.info("not known to Alpaca (empty file): %s", ", ".join(bad))

    with ThreadPoolExecutor(a.workers) as pool:
        futs = {pool.submit(one, j): j for j in jobs}
        for f in as_completed(futs):
            try:
                f.result()
            except Exception as ex:                            # the chunk stays missing: a rerun fetches it again
                stats["failed"] += len(futs[f][2])
                log.error("%s", ex)
            now = time.monotonic()
            if now - last[0] >= 60 or stats["keys"] + stats["failed"] == len(todo):
                last[0] = now
                done = stats["keys"] + stats["failed"]
                el = now - t0
                eta = el / done * (len(todo) - done) if done else 0
                log.info("%d/%d keys (%.1f%%), %d empty, %d failed | %s bars, %s requests | %.0f min, ETA %.0f min",
                         done, len(todo), 100 * done / len(todo), stats["empty"], stats["failed"],
                         f"{stats['bars']:,}", f"{stats['requests']:,}", el / 60, eta / 60)
    log.info("done: %d keys, %s bars, %d failed (rerun to retry them)", stats["keys"], f"{stats['bars']:,}",
             stats["failed"])
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
