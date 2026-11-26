"""Import Alpaca 1-minute bars (scripts/alpaca_minute.py's Parquet files) into the minute-bar store.

    python -m app.cli import-minute --exchange NASDAQ [--dir <EOD_Market_Data>/market_data_minute] [--limit N]

Source, per exchange: <dir>/<EX>/<key>.parquet (ts UTC = bar open, open/high/low/close/volume/trades/vwap), as traded
(no adjustment), with pre-market and after-hours bars. A key is our ticker (our US daily bars come from the same Alpaca
store, so the keys match, `SYMBOL@date` ones included); '/' is written '~' in file names, a Windows reserved name ends
in '_'.

What is stored: the regular session only (09:30-16:00 New York, like the stored hourly bars), inside the minute store's
window (the last MINUTE_RETENTION_DAYS), put on the basis of OUR daily bars so every timeframe agrees:
    price = raw / f_day,   volume = raw volume x f_day
f_day = Alpaca's official as-traded close of the day (market_data_alpaca/daily/<EX>/<key>.pkl) / our daily close: it
is exactly constant between corporate actions and steps on them (measured on 120 NASDAQ keys: largest spread inside a
step 0.05%). After the last day of the daily file, the last factor carries on; it changes only where the minute closes
stay more than 8% off our closes for 3 days running (a split after that date), using their median. Days without a
factor before the first known one take the first known one.

Resumable: <dir>/<EX>/_imported.json keeps each imported file's size and time; a rerun imports only new or changed
files (the download can still be running). A symbol's bars are replaced over the span of its file.
"""
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import Symbol
from app.providers import bar_store

log = logging.getLogger(__name__)
NY = "America/New_York"
OPEN_S, CLOSE_S = 9 * 3600 + 30 * 60, 16 * 3600          # 09:30 <= local time < 16:00
STEP = 0.08                                               # a factor change after the daily file: > 8% ...
STEP_DAYS = 3                                             # ... for 3 days running, agreeing with each other
WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{d}{i}" for d in ("COM", "LPT") for i in range(10)}


def key_of(stem: str) -> str:
    """File stem -> key: '~' is '/', and a reserved name's trailing '_' goes."""
    k = stem.replace("~", "/")
    base = k.split(".")[0].split("@")[0]
    if k.endswith("_") and base.rstrip("_").upper() in WIN_RESERVED:
        k = k[:-1]
    return k


PRICES = ("open", "high", "low", "close")


def read_minute(path: Path) -> pd.DataFrame:
    """A minute file with prices in dollars, in either layout the downloader writes: float dollars, or int64
    micro-dollars with the file metadata price_scale = 1000000 (exact; scripts/alpaca_minute.py, 26 Nov 2026)."""
    import pyarrow.parquet as pq

    t = pq.read_table(path, columns=["ts", *PRICES, "volume"])
    df = t.to_pandas()
    scale = int((pq.read_schema(path).metadata or {}).get(b"price_scale", b"0"))
    if scale:
        for c in PRICES:
            df[c] = df[c].astype("float64") / scale
    return df


def regular_session(df: pd.DataFrame) -> pd.DataFrame:
    """Bars inside 09:30-16:00 New York, with their New York date (`day`)."""
    if df.empty:
        return df.assign(day=pd.Series(dtype="object"))
    ny = df["ts"].dt.tz_convert(NY)
    sec = ny.dt.hour * 3600 + ny.dt.minute * 60 + ny.dt.second
    keep = (sec >= OPEN_S) & (sec < CLOSE_S)
    return df[keep].assign(day=ny[keep].dt.date)


def day_factors(days: list, official: pd.Series, ours: pd.Series, minute_close: pd.Series) -> pd.Series:
    """Factor per day (raw price / our price). `official` = Alpaca's official as-traded daily close by date, `ours` =
    our daily close by date, `minute_close` = the day's last regular-session minute close by date."""
    f = (official / ours).replace([np.inf, -np.inf], np.nan).dropna()
    f = f[f > 0]
    out = pd.Series(np.nan, index=pd.Index(days), dtype=float)
    known = f.reindex(out.index)
    out[:] = known
    last_known = f.index.max() if len(f) else None
    # after the daily file: carry the last factor; a sustained gap to our closes is a new factor (a split)
    after = [d for d in days if last_known is None or d > last_known]
    if after:
        cur = f.iloc[-1] if len(f) else np.nan
        r = (minute_close / ours).reindex(after)
        for i, d in enumerate(after):
            window = r.iloc[i:i + STEP_DAYS].dropna()
            if np.isnan(cur) and len(window):
                cur = float(window.median())
            elif (len(window) == STEP_DAYS and ((window / cur - 1).abs() > STEP).all()
                  and ((window / window.median() - 1).abs() <= STEP).all()):   # ... and agree with each other
                cur = float(window.median())
            out[d] = cur
    out = out.ffill().bfill()                                  # gaps (no daily bar that day): the factor around them
    return out


@dataclass
class MinuteImport:
    exchange: str
    files: int = 0
    imported: int = 0
    skipped_unchanged: int = 0
    not_ours: list = field(default_factory=list)
    no_factor: list = field(default_factory=list)
    bars: int = 0
    seconds: float = 0.0


def _state_path(folder: Path) -> Path:
    return folder / "_imported.json"


def import_exchange(session_factory: sessionmaker, folder: Path, exchange: str, daily_dir: Path | None = None,
                    limit: int | None = None, progress=None) -> MinuteImport:
    """Import every new or changed <key>.parquet of `folder` (one exchange) into the minute store."""
    t0 = time.perf_counter()
    exchange = exchange.upper()
    res = MinuteImport(exchange)
    store = bar_store()
    state_file = _state_path(folder)
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    with session_factory() as s:
        ids = dict(s.execute(select(Symbol.ticker, Symbol.id).where(Symbol.exchange == exchange)).all())
    files = sorted(folder.glob("*.parquet"))
    res.files = len(files)
    oldest = getattr(store.store_for("1m") if hasattr(store, "store_for") else store, "oldest_kept", lambda: 0)()
    done = 0
    for p in files:
        st = p.stat()
        sig = [st.st_size, int(st.st_mtime)]
        if state.get(p.name, {}).get("sig") == sig:
            res.skipped_unchanged += 1
            continue
        key = key_of(p.stem)
        sid = ids.get(key)
        if sid is None:
            res.not_ours.append(key)
            state[p.name] = dict(sig=sig, bars=0, note="not one of our symbols")
            continue
        n = _import_file(session_factory, store, p, sid, exchange, daily_dir, oldest)
        if n is None:
            res.no_factor.append(key)
            state[p.name] = dict(sig=sig, bars=0, note="no daily bars to anchor the prices")
        else:
            res.bars += n
            res.imported += 1
            state[p.name] = dict(sig=sig, bars=n)
        done += 1
        if done % 50 == 0:
            state_file.write_text(json.dumps(state), encoding="utf-8")
            if progress:
                progress(res)
        if limit and done >= limit:
            break
    state_file.write_text(json.dumps(state), encoding="utf-8")
    res.seconds = round(time.perf_counter() - t0, 1)
    return res


def _import_file(session_factory, store, path: Path, sid: int, exchange: str, daily_dir: Path | None,
                 oldest: int) -> int | None:
    df = read_minute(path)
    df = df[df["ts"] >= pd.Timestamp(oldest, unit="s", tz="UTC")] if oldest else df
    reg = regular_session(df)
    if reg.empty:
        return 0
    days = sorted(set(reg["day"]))
    with session_factory() as s:
        span_lo = int(pd.Timestamp(days[0]).tz_localize("Asia/Kolkata").timestamp()) - 7 * 86400
        daily = store.read_latest(s, sid, "1D", 100_000, frm=span_lo, cols=("ts", "c"))
    if not len(daily):
        return None
    ours = pd.Series(daily[:, 1], index=pd.to_datetime(daily[:, 0] + 19800, unit="s").date)
    official = pd.Series(dtype=float)
    pk = (daily_dir / exchange / (path.stem + ".pkl")) if daily_dir else None
    if pk is not None and pk.exists():
        k = pd.read_pickle(pk)
        if not k.empty:
            official = pd.Series(k["Close"].to_numpy(float), index=pd.Index(k.index.date))
    minute_close = reg.groupby("day")["close"].last()
    f = day_factors(days, official, ours, minute_close)
    if f.isna().all():
        return None
    fd = reg["day"].map(f).to_numpy(float)
    ok = np.isfinite(fd) & (fd > 0)
    reg, fd = reg[ok], fd[ok]
    ts = ((reg["ts"] - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)).to_numpy(np.int64)   # epoch seconds
    data = {"ts": ts, "o": reg["open"].to_numpy(float) / fd, "h": reg["high"].to_numpy(float) / fd,
            "l": reg["low"].to_numpy(float) / fd, "c": reg["close"].to_numpy(float) / fd,
            "v": reg["volume"].to_numpy(float) * fd}
    with session_factory() as s:
        store.delete_bars(s, exchange, ["1m"], int(ts.min()), int(ts.max()), symbol_ids=[sid])
        return store.append(s, "1m", np.full(len(ts), sid), data)
