"""Sign-in locations: the DB-IP City Lite download (a fake server here), lookups on this server, and filling in the
places of sign-ins recorded before there was a database."""
import datetime as dt
import gzip
import io
import json

import pytest
from sqlalchemy import select

from app.auth import client as cl
from app.auth import geoip
from app.models import LoginEvent, User


class FakeReader:
    """Stands in for the .mmdb reader: DB-IP's record layout for a few known addresses."""

    PLACES = {"49.36.0.1": ("India", "Karnataka", "Mangaluru"), "8.8.8.8": ("United States", "California", "Mountain View")}

    def get(self, ip):
        if ip not in self.PLACES:
            return None
        c, r, t = self.PLACES[ip]
        en = lambda x: {"names": {"en": x}}  # noqa: E731
        return {"country": en(c), "subdivisions": [en(r)], "city": en(t)}


@pytest.fixture()
def fake_db(tmp_path, monkeypatch):
    f = tmp_path / "dbip-city-lite.mmdb"
    f.write_bytes(b"x")
    monkeypatch.setattr(geoip, "DEFAULT_DB", f)
    monkeypatch.setattr(cl, "_reader", lambda path: FakeReader())
    return f


def test_locations_are_looked_up_here(fake_db):
    assert cl.location_text(cl.location("49.36.0.1")) == "Mangaluru, Karnataka, India"
    for ip in ("192.168.1.5", "10.0.0.1", "127.0.0.1", "::1", "not-an-ip", "", "203.0.113.9"):
        assert cl.location(ip) == dict(country="", region="", city="")     # private, local, unknown: no place


def test_no_database_no_place(monkeypatch, tmp_path):
    monkeypatch.setattr(geoip, "DEFAULT_DB", tmp_path / "missing.mmdb")
    assert geoip.db_path() is None and cl.location("8.8.8.8")["country"] == ""


def test_a_sign_in_records_its_place_and_old_ones_are_filled_in(client, session_factory, fake_db, monkeypatch):
    from app.api import auth as auth_api
    from app.config import get_settings
    from tests.test_m26_auth import FakeGoogle, person, sign_in

    s = get_settings()
    monkeypatch.setattr(s, "auth_mode", "google")
    monkeypatch.setattr(s, "trust_proxy", True)                    # the IP from X-Forwarded-For (a reverse proxy)
    fake = FakeGoogle()
    monkeypatch.setattr(auth_api, "google_client", lambda: fake)
    client.cookies.clear()
    client.headers["x-forwarded-for"] = "49.36.0.1, 10.0.0.2"
    try:
        sign_in(client, fake, person("g-geo", "geo@example.com"))
    finally:
        del client.headers["x-forwarded-for"]
        client.cookies.clear()
    with session_factory() as db:
        u = db.scalar(select(User).where(User.subject == "g-geo"))
        ev = db.scalars(select(LoginEvent).where(LoginEvent.user_id == u.id)).one()
        assert (u.last_ip, u.last_location) == ("49.36.0.1", "Mangaluru, Karnataka, India")
        assert (ev.country, ev.region, ev.city) == ("India", "Karnataka", "Mangaluru")
        # a sign-in recorded before there was a database: filled in later
        db.add(LoginEvent(user_id=u.id, ip="8.8.8.8", email="geo@example.com"))
        u.last_ip, u.last_location = "8.8.8.8", ""
        db.commit()
    got = geoip.backfill(session_factory)
    assert got["sign_ins"] >= 1 and got["users"] >= 1
    with session_factory() as db:
        assert db.scalar(select(User).where(User.subject == "g-geo")).last_location == \
            "Mountain View, California, United States"


def gz(data: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as f:
        f.write(data)
    return buf.getvalue()


class FakeServer:
    """download.db-ip.com: the files it has, by month."""

    def __init__(self, files):
        self.files, self.asked = files, []

    def __call__(self, req, timeout=0):
        url = req.full_url
        self.asked.append(url)
        month = url.rsplit("lite-", 1)[1][:7]
        if month not in self.files:
            raise OSError(f"404 {url}")
        return io.BytesIO(gz(self.files[month]))


def test_download_this_month_else_last_month(tmp_path, monkeypatch):
    checked = []
    monkeypatch.setattr(geoip, "_check", lambda p: checked.append(p.read_bytes()))
    dest = tmp_path / "geo" / "dbip-city-lite.mmdb"
    meta = geoip.download(dest, today=dt.date(2026, 11, 27), opener=FakeServer({"2026-11": b"november"}))
    assert dest.read_bytes() == b"november" and checked == [b"november"] and meta["month"] == "2026-11"
    assert json.loads((dest.parent / "dbip-city-lite.json").read_text())["source"].startswith("DB-IP")
    # on the 1st of a month the new file may not be out yet: last month's
    server = FakeServer({"2026-11": b"november"})
    geoip.download(dest, today=dt.date(2026, 12, 1), opener=server)
    assert [u.rsplit("-lite-", 1)[1] for u in server.asked] == ["2026-12.mmdb.gz", "2026-11.mmdb.gz"]
    assert not list(dest.parent.glob("*.part"))                      # no half files left behind


def test_a_bad_download_never_replaces_a_good_file(tmp_path, monkeypatch):
    def check(p):
        if p.read_bytes() != b"good":
            raise ValueError("not a city database")
    monkeypatch.setattr(geoip, "_check", check)
    dest = tmp_path / "dbip-city-lite.mmdb"
    dest.write_bytes(b"good")
    with pytest.raises(RuntimeError, match="could not download"):
        geoip.download(dest, today=dt.date(2026, 11, 27), opener=FakeServer({"2026-11": b"junk", "2026-10": b"junk"}))
    assert dest.read_bytes() == b"good"


def test_refresh_only_when_missing_or_a_month_old(tmp_path, monkeypatch):
    import os
    import time

    calls = []
    monkeypatch.setattr(geoip, "download", lambda *a, **k: calls.append(1) or {"month": "x"})
    f = tmp_path / "dbip-city-lite.mmdb"
    monkeypatch.setattr(geoip, "DEFAULT_DB", f)
    assert geoip.refresh(if_older_days=30) == {"month": "x"}         # no file yet: download
    f.write_bytes(b"x")
    assert geoip.refresh(if_older_days=30) is None and len(calls) == 1  # fresh: nothing to do
    old = time.time() - 31 * 86400
    os.utime(f, (old, old))
    assert geoip.refresh(if_older_days=30) == {"month": "x"}         # a month old: the new edition
    assert geoip.refresh(force=True) == {"month": "x"} and len(calls) == 3


def test_users_page_credits_db_ip(client, fake_db):
    g = client.get("/admin/users").json()["geoip"]
    assert g["attribution"] == "IP Geolocation by DB-IP (https://db-ip.com)" and "CC BY 4.0" in g["source"]


@pytest.mark.skipif(not geoip.DEFAULT_DB.exists(), reason="the DB-IP file is not downloaded here")
def test_the_downloaded_file_places_known_addresses():
    cl._reader.cache_clear()
    assert cl.location("8.8.8.8")["country"] == "United States"
    assert cl.location("49.36.0.1")["country"] == "India" and cl.location("49.36.0.1")["region"] == "Karnataka"
