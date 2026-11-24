"""Company names and instrument types for the symbol master.

Sources (public listing files from the exchanges, cached under backend/data/names/):
  * NSE      EQUITY_L.csv, SME_EQUITY_L.csv, eq_etfseclist.csv (nsearchives.nseindia.com)
  * NASDAQ   nasdaqlisted.txt (nasdaqtrader.com)              Symbol|Security Name|...|ETF
  * NYSE/... otherlisted.txt   (nasdaqtrader.com)              ACT Symbol|Security Name|Exchange|...|ETF
  * BSE      <market_data_daily>/tickers.csv (owner's data)  Symbol,Name,Exchange
  * delisted <market_data_daily>/<EX>/delisted_symbols.csv   Symbol,Name,... (US)

Only current listings have names upstream; older delisted tickers fall back to the ticker.
"""
import csv
import io
import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SOURCES = {
    "nse_equity.csv": "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    "nse_sme.csv": "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv",
    "nse_etf.csv": "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv",
    "nasdaqlisted.txt": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "otherlisted.txt": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
}
_UA = "Mozilla/5.0 (compatible; charting-prototype)"  # NSE rejects clients without a browser-like UA


@dataclass(frozen=True)
class NameInfo:
    name: str
    type: str = "EQ"          # EQ | ETF
    isin: str | None = None


def fetch(cache: Path, force: bool = False) -> list[str]:
    """Download the public listing files into `cache` (skips files already present unless force)."""
    cache.mkdir(parents=True, exist_ok=True)
    got = []
    for fname, url in SOURCES.items():
        dest = cache / fname
        if dest.exists() and not force:
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                dest.write_bytes(r.read())
            got.append(fname)
        except Exception as e:  # names are optional: import still works with tickers only
            log.warning("could not download %s: %s", url, e)
    return got


def _us_variants(ticker: str) -> list[str]:
    """Data tickers (BFH.PRA, AAC.WS, BF.B) -> spellings used by the NASDAQ Trader lists."""
    out = [ticker]
    if ".PR" in ticker:
        base, suf = ticker.split(".PR", 1)
        out += [f"{base}${suf}", f"{base}-{suf}"]
    out += [ticker.replace(".", "-"), ticker.replace(".", "")]
    return out


def _clean(name: str) -> str:
    for junk in (" - Common Stock", " Common Stock", " - Ordinary Shares", " Ordinary Shares"):
        name = name.replace(junk, "")
    return name.strip()


def load(exchange: str, cache: Path | None, daily_root: Path | None) -> dict[str, NameInfo]:
    """ticker -> NameInfo for one exchange, from whatever sources are available."""
    exchange = exchange.upper()
    out: dict[str, NameInfo] = {}
    if daily_root is not None:
        delisted = daily_root / exchange / "delisted_symbols.csv"
        if delisted.is_file():
            for r in csv.DictReader(io.StringIO(delisted.read_text(encoding="utf-8", errors="replace"))):
                if r.get("Symbol") and r.get("Name"):
                    out[r["Symbol"].strip().upper()] = NameInfo(r["Name"].strip())
        tickers = daily_root / "tickers.csv"
        if tickers.is_file():
            for r in csv.DictReader(io.StringIO(tickers.read_text(encoding="utf-8", errors="replace"))):
                if (r.get("Exchange") or "").upper() == exchange and r.get("Name"):
                    out[r["Symbol"].strip().upper()] = NameInfo(r["Name"].strip())

    if cache is None:
        return out
    if exchange == "NSE":
        # (file, name column, isin column, type)
        for fname, ni, ii, typ in (("nse_etf.csv", 1, 5, "ETF"), ("nse_sme.csv", 1, 5, "EQ"), ("nse_equity.csv", 1, 6, "EQ")):
            f = cache / fname
            if not f.is_file():
                continue
            rows = csv.reader(io.StringIO(f.read_text(encoding="utf-8", errors="replace")))
            next(rows, None)
            for r in rows:
                if len(r) > max(ni, ii) and r[0].strip():
                    name = r[ni].strip()
                    if typ == "ETF" and len(r) > 2 and r[2].strip():
                        name = f"{r[2].strip()} ({name})"  # SecurityName (underlying)
                    out[r[0].strip().upper()] = NameInfo(name, typ, r[ii].strip() or None)
    elif exchange in ("NASDAQ", "NYSE"):
        us: dict[str, NameInfo] = {}
        f = cache / "nasdaqlisted.txt"
        if exchange == "NASDAQ" and f.is_file():
            for r in csv.DictReader(io.StringIO(f.read_text(encoding="utf-8", errors="replace")), delimiter="|"):
                if r.get("Test Issue") == "N" and r.get("Symbol"):
                    us[r["Symbol"].upper()] = NameInfo(_clean(r["Security Name"]), "ETF" if r.get("ETF") == "Y" else "EQ")
        f = cache / "otherlisted.txt"
        if f.is_file():
            # NYSE-family listings (N = NYSE, A = NYSE American, P = NYSE Arca, Z = Cboe); the owner's
            # NYSE folder holds the NYSE family, so all non-Nasdaq listings are offered as NYSE names
            for r in csv.DictReader(io.StringIO(f.read_text(encoding="utf-8", errors="replace")), delimiter="|"):
                if r.get("Test Issue") == "N" and r.get("ACT Symbol") and exchange == "NYSE":
                    us[r["ACT Symbol"].upper()] = NameInfo(_clean(r["Security Name"]), "ETF" if r.get("ETF") == "Y" else "EQ")
        return _merge_us(out, us)
    return out


def _merge_us(base: dict[str, NameInfo], listed: dict[str, NameInfo]) -> dict[str, NameInfo]:
    out = dict(base)
    out.update(listed)
    # also index data-style spellings (BFH.PRA) of listed preferreds/warrants
    rev = {}
    for k, v in listed.items():
        if "$" in k:
            b, s = k.split("$", 1)
            rev[f"{b}.PR{s}"] = v
    out.update({k: v for k, v in rev.items() if k not in out})
    return out


def lookup(names: dict[str, NameInfo], ticker: str, exchange: str) -> NameInfo | None:
    if exchange.upper() in ("NASDAQ", "NYSE"):
        for t in _us_variants(ticker):
            if t in names:
                return names[t]
        return None
    return names.get(ticker)
