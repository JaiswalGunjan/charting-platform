"""The admin dashboard: data status, and jobs an admin starts (EOD download, setup and pattern screeners, all of
it). Admins only, API and all. The jobs here run a stand-in command (no download, no scan)."""
import sys

import pytest
from fastapi.testclient import TestClient

from app import admin_jobs
from app.config import get_settings


@pytest.fixture()
def runner(tmp_path, monkeypatch):
    r = admin_jobs.Runner(tmp_path / "admin_jobs.json")
    monkeypatch.setattr(admin_jobs, "_runner", r)
    return r


def fake_command(lines=("downloading NSE ...", "imported 2,979 symbols"), code=0, sleep=0.0):
    def cmd(kind, market, date):
        body = f"import time; time.sleep({sleep}); " + "; ".join(f"print({x!r})" for x in lines) + f"; raise SystemExit({code})"
        return [sys.executable, "-c", body]
    return cmd


def test_the_dashboard_is_for_admins_only(client, monkeypatch, runner):
    from tests.test_m26_auth import FakeGoogle, person, sign_in
    from app.api import auth as auth_api

    s = get_settings()
    monkeypatch.setattr(s, "auth_mode", "google")
    fake = FakeGoogle()
    monkeypatch.setattr(auth_api, "google_client", lambda: fake)
    c = TestClient(client.app)
    assert c.get("/admin/status").status_code == 401                          # signed out
    sign_in(c, fake, person("g-plain", "plain@example.com"))
    for method, path, body in (("get", "/admin/status", None), ("post", "/admin/jobs", {"kind": "full", "market": "NSE"}),
                               ("get", "/admin/jobs/1", None), ("get", "/admin/users", None),
                               ("post", "/screener/patterns-today/run", {"exchange": "NSE"}),
                               ("post", "/scanner/run", {"market": "NSE"})):
        r = getattr(c, method)(path, **({"json": body} if body else {}))
        assert r.status_code == 403, (path, r.status_code)                    # signed in, not an admin
    assert runner.jobs == deque_empty()


def deque_empty():
    from collections import deque

    return deque()


def test_status_shows_the_data_and_the_jobs(client, runner):
    st = client.get("/admin/status").json()                                   # the local user is an admin
    nse = next(x for x in st["exchanges"] if x["exchange"] == "NSE")
    assert nse["symbols"] > 0 and nse["last_daily"] == "2026-11-20"
    assert st["markets"] == {"NSE": ["NSE"], "US": ["NYSE", "NASDAQ"]}
    assert [k["kind"] for k in st["kinds"]] == ["download", "setup_scan", "pattern_screen", "full"]
    assert st["running"] is None and st["jobs"] == []


def test_a_job_runs_its_steps_and_its_output_is_followed(client, runner, monkeypatch):
    monkeypatch.setattr(admin_jobs, "command", fake_command())
    j = client.post("/admin/jobs", json={"kind": "download", "market": "NSE", "date": "2026-11-26"}).json()
    assert j["state"] == "running" and j["title"] == "Download EOD data" and j["by"] == "local@localhost"
    runner.wait()
    got = client.get(f"/admin/jobs/{j['id']}").json()
    assert got["state"] == "done" and got["exit_code"] == 0
    assert got["lines"][-2:] == ["downloading NSE ...", "imported 2,979 symbols"]
    more = client.get(f"/admin/jobs/{j['id']}", params={"since": got["next"]}).json()
    assert more["lines"] == []                                                 # only new lines
    st = client.get("/admin/status").json()
    assert st["jobs"][0]["id"] == j["id"] and st["jobs"][0]["last_line"] == "imported 2,979 symbols"
    # kept across a restart
    again = admin_jobs.Runner(runner.history_file)
    assert again.get(j["id"]).state == "done" and again.get(j["id"]).log[-1] == "imported 2,979 symbols"


def test_one_job_at_a_time_and_a_failed_job_is_shown(client, runner, monkeypatch):
    monkeypatch.setattr(admin_jobs, "command", fake_command(("scanning ...",), code=1, sleep=1.0))
    j = client.post("/admin/jobs", json={"kind": "setup_scan", "market": "US"}).json()
    r = client.post("/admin/jobs", json={"kind": "pattern_screen", "market": "NSE"})
    assert r.status_code == 409 and "Run setup screener" in r.json()["detail"]
    runner.wait()
    got = client.get(f"/admin/jobs/{j['id']}").json()
    assert got["state"] == "error" and got["exit_code"] == 1 and got["lines"][-1] == "scanning ..."


def test_bad_requests(client, runner):
    assert client.post("/admin/jobs", json={"kind": "delete-everything", "market": "NSE"}).status_code == 400
    assert client.post("/admin/jobs", json={"kind": "full", "market": "MOON"}).status_code == 400
    assert client.post("/admin/jobs", json={"kind": "full", "market": "NSE", "date": "26/11/2026"}).status_code == 422
    assert client.get("/admin/jobs/999").status_code == 404


def test_the_command_is_the_nightly_job_with_some_steps(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_jobs_dry_run", False)
    cmd = admin_jobs.command("download", "NSE", "2026-11-26")
    assert cmd[1].endswith("daily_update.py") and cmd[2:] == ["--market", "NSE", "--now", "--only", "download,import",
                                                               "--date", "2026-11-26"]
    assert admin_jobs.command("full", "US", None)[2:] == ["--market", "US", "--now"]
    assert admin_jobs.command("setup_scan", "US", None)[-2:] == ["--only", "scan"]
    monkeypatch.setattr(get_settings(), "admin_jobs_dry_run", True)
    assert admin_jobs.command("pattern_screen", "NSE", None)[-1] == "--dry-run"


def test_a_real_dry_run_of_the_nightly_job(client, runner, monkeypatch):
    """The real script, in dry-run mode, with the test's own log folder."""
    monkeypatch.setattr(get_settings(), "admin_jobs_dry_run", True)
    j = client.post("/admin/jobs", json={"kind": "pattern_screen", "market": "NSE", "date": "2026-11-26"}).json()
    runner.wait(60)
    got = client.get(f"/admin/jobs/{j['id']}").json()
    assert got["state"] == "done", got["lines"]
    assert any("[dry run] would run screen" in x for x in got["lines"])
