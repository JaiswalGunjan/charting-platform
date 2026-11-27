"""Who is asking: the client's IP address, browser, and approximate location.

The IP is the connection's address; behind a reverse proxy (TRUST_PROXY=true) the first X-Forwarded-For entry.
Location comes from DB-IP's free IP to City Lite database, downloaded to this server (app/auth/geoip.py,
`app.cli update-geoip`); without it the location stays empty. No outside service is asked."""
import ipaddress
import logging
from functools import lru_cache

from app.config import get_settings  # noqa: F401  (client_ip)

log = logging.getLogger(__name__)


def client_ip(headers, client_host: str | None) -> str:
    if get_settings().trust_proxy:
        fwd = headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()[:64]
    return (client_host or "")[:64]


def user_agent(headers) -> str:
    return (headers.get("user-agent") or "")[:400]


@lru_cache(maxsize=1)
def _reader(path: str):
    try:
        import maxminddb                       # the reader of the .mmdb file format DB-IP publishes in

        return maxminddb.open_database(path)
    except Exception as e:  # noqa: BLE001  no database, or no reader: location stays empty
        log.warning("no IP location lookup (%s): %s", path, e)
        return None


def location(ip: str) -> dict:
    """{country, region, city} of an IP address; empty for private addresses or without a database."""
    from app.auth.geoip import db_path

    out = dict(country="", region="", city="")
    p = db_path()
    path = str(p) if p else ""
    try:
        if not path or not ip or ipaddress.ip_address(ip).is_private or ipaddress.ip_address(ip).is_loopback:
            return out
    except ValueError:
        return out
    r = _reader(path)
    if r is None:
        return out
    try:
        rec = r.get(ip) or {}
    except Exception:  # noqa: BLE001  a malformed address for the reader
        return out
    name = lambda d: ((d or {}).get("names") or {}).get("en", "")  # noqa: E731
    subs = rec.get("subdivisions") or [{}]
    out.update(country=name(rec.get("country")), region=name(subs[0]), city=name(rec.get("city")))
    return out


def location_text(loc: dict) -> str:
    return ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x)
