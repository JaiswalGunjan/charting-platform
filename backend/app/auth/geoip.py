"""The IP-to-location database for sign-in locations, looked up on this server only (no IP is sent anywhere).

DB-IP's free "IP to City Lite" (https://db-ip.com, CC BY 4.0: shown with "IP Geolocation by DB-IP"), a new edition
every month, no account needed. `python -m app.cli update-geoip` downloads it to backend/data/geoip/ and fills in the
locations of sign-ins recorded without one; the nightly job refreshes it when it is a month old.
"""
import datetime as dt
import gzip
import json
import logging
import shutil
import time
import urllib.request
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

log = logging.getLogger(__name__)
GEO_DIR = Path(__file__).resolve().parents[2] / "data" / "geoip"
DEFAULT_DB = GEO_DIR / "dbip-city-lite.mmdb"
META = GEO_DIR / "dbip-city-lite.json"
URL = "https://download.db-ip.com/free/dbip-city-lite-{month}.mmdb.gz"
SOURCE = "DB-IP IP to City Lite (https://db-ip.com), CC BY 4.0"
CHECK_IP = "8.8.8.8"                       # a known public address: the file must place it


def db_path() -> Path | None:
    """The downloaded DB-IP file; None before the first download."""
    return DEFAULT_DB if DEFAULT_DB.exists() else None


def info() -> dict:
    p = db_path()
    meta = json.loads(META.read_text(encoding="utf-8")) if p and META.exists() else {}
    return dict(path=str(p) if p else "", source=SOURCE if p else "", month=meta.get("month", ""),
                downloaded_at=meta.get("downloaded_at", ""),
                attribution="IP Geolocation by DB-IP (https://db-ip.com)" if p else "")


def _months(today: dt.date) -> list[str]:
    """This month's file, then last month's (a new month's file appears in its first days)."""
    first = today.replace(day=1)
    prev = (first - dt.timedelta(days=1)).replace(day=1)
    return [f"{first:%Y-%m}", f"{prev:%Y-%m}"]


def _check(path: Path) -> None:
    import maxminddb

    with maxminddb.open_database(str(path)) as r:
        rec = r.get(CHECK_IP)
    if not rec or not (rec.get("country") or {}).get("iso_code"):
        raise ValueError(f"{path.name} does not place {CHECK_IP}: not a city database")


def download(dest: Path = DEFAULT_DB, today: dt.date | None = None, opener=urllib.request.urlopen) -> dict:
    """Download the newest DB-IP City Lite file to `dest` (checked before it replaces the old one)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    for month in _months(today or dt.date.today()):
        url = URL.format(month=month)
        gz, tmp = dest.with_suffix(".mmdb.gz.part"), dest.with_suffix(".mmdb.part")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "charting-lab-geoip/1"})
            with opener(req, timeout=300) as r, open(gz, "wb") as fh:
                shutil.copyfileobj(r, fh)
            with gzip.open(gz, "rb") as src, open(tmp, "wb") as out:
                shutil.copyfileobj(src, out)
            _check(tmp)
        except Exception as e:  # noqa: BLE001  try last month's file, then give up
            errors.append(f"{month}: {e}")
            for f in (gz, tmp):
                f.unlink(missing_ok=True)
            continue
        gz.unlink(missing_ok=True)
        tmp.replace(dest)
        meta = dict(source=SOURCE, url=url, month=month, bytes=dest.stat().st_size,
                    downloaded_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        (dest.parent / (dest.stem + ".json")).write_text(json.dumps(meta, indent=1), encoding="utf-8")
        from app.auth import client

        client._reader.cache_clear()                     # lookups use the new file from now on
        log.info("IP location database: %s (%s, %.0f MB)", dest, month, meta["bytes"] / 1e6)
        return meta
    raise RuntimeError("could not download the IP location database: " + "; ".join(errors))


def age_days() -> float | None:
    p = db_path()
    return (time.time() - p.stat().st_mtime) / 86400 if p and p.exists() else None


def refresh(if_older_days: float | None = None, force: bool = False) -> dict | None:
    """Download when there is no file, when forced, or when the file is older than `if_older_days`."""
    age = age_days()
    if force or age is None or (if_older_days is not None and age > if_older_days):
        return download()
    return None


def backfill(session_factory: sessionmaker) -> dict:
    """Fill in the location of sign-ins recorded without one, and each user's last location."""
    from app.auth.client import location, location_text
    from app.models import LoginEvent, User

    filled = users = 0
    with session_factory() as db:
        for ev in db.scalars(select(LoginEvent).where(LoginEvent.ip != "", LoginEvent.country == "")):
            loc = location(ev.ip)
            if loc["country"]:
                ev.country, ev.region, ev.city = loc["country"], loc["region"], loc["city"]
                filled += 1
        for u in db.scalars(select(User).where(User.last_ip != "")):
            text = location_text(location(u.last_ip))
            if text and text != u.last_location:
                u.last_location = text
                users += 1
        db.commit()
    return dict(sign_ins=filled, users=users)
