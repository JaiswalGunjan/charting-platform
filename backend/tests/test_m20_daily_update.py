"""The daily update job (scripts/daily_update.py) for NSE and the US: holidays of each market, which session a run
updates, the retry schedule (5 x ~5 min, then 5 x ~10 min, random) and the order of the steps after a successful
download. Nothing is downloaded and nobody waits: the steps are stubbed."""
import datetime as dt
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "daily_update.py"


@pytest.fixture()
def job(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("daily_update", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "DAILY", tmp_path / "market_data_daily")
    monkeypatch.setattr(m, "NSE_HOLIDAYS", tmp_path / "nse_holidays.json")
    monkeypatch.setattr(m, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(m, "SCANNER", tmp_path / "SwingScanner")
    (tmp_path / "nse_holidays.json").write_text(json.dumps({"2026": ["2026-11-24", "2026-12-25"]}))
    return m


NSE, US = "NSE", "US"
DAY = dt.date(2026, 11, 26)        # a Thursday (Thanksgiving in the US)


# ---------------------------------------------------------------- holidays and the session to update
def test_nse_weekends_and_holidays(job, monkeypatch):
    monkeypatch.setattr(job, "fetch_nse_holidays", lambda y: pytest.fail("cached: no fetch"))
    m = job.MARKETS[NSE]
    assert job.trading_day(m, dt.date(2026, 11, 24)) == (False, "NSE trading holiday")
    assert job.trading_day(m, dt.date(2026, 11, 28)) == (False, "weekend")
    assert job.trading_day(m, DAY) == (True, "trading day")                 # an Indian trading day


def test_nse_holiday_list_is_fetched_once_and_cached(job, monkeypatch):
    calls = []
    monkeypatch.setattr(job, "fetch_nse_holidays", lambda y: calls.append(y) or [f"{y}-01-26"])
    assert job.nse_holidays(2027) == {"2027-01-26"} and job.nse_holidays(2027) == {"2027-01-26"}
    assert calls == [2027]
    monkeypatch.setattr(job, "fetch_nse_holidays", lambda y: (_ for _ in ()).throw(OSError("offline")))
    assert job.nse_holidays(2028) is None
    assert job.trading_day(job.MARKETS[NSE], dt.date(2028, 1, 26)) == (True, "weekday (holiday list unavailable)")


@pytest.mark.parametrize("year, expected", [
    (2025, ["2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26", "2025-06-19", "2025-07-04",
            "2025-09-01", "2025-11-27", "2025-12-25"]),
    (2026, ["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
            "2026-09-07", "2026-11-26", "2026-12-25"]),
    (2027, ["2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05",
            "2027-09-06", "2027-11-25", "2027-12-24"]),
    (2022, ["2022-01-17", "2022-02-21", "2022-04-15", "2022-05-30", "2022-06-20", "2022-07-04", "2022-09-05",
            "2022-11-24", "2022-12-26"]),        # New Year's Day on a Saturday: no Friday holiday (NYSE rule)
])
def test_us_holidays_follow_the_nyse_rules(job, year, expected):
    assert sorted(job.us_holidays(year)) == expected


def test_us_and_indian_holidays_are_separate(job):
    us, nse = job.MARKETS[US], job.MARKETS[NSE]
    assert job.trading_day(us, DAY) == (False, "US market holiday")           # Thanksgiving: US closed, India open
    assert job.trading_day(nse, DAY) == (True, "trading day")
    assert job.trading_day(us, dt.date(2026, 11, 24)) == (True, "trading day")  # NSE holiday: US open


def test_which_session_a_run_updates(job):
    utc = dt.timezone.utc
    # 08:00 India time on Thursday 26 Nov = 21:30 Wednesday in New York: the US run updates Wednesday's session
    at_8am_ist = dt.datetime(2026, 11, 26, 2, 30, tzinfo=utc)
    assert job.session_day(job.MARKETS[US], at_8am_ist) == dt.date(2026, 11, 25)
    assert job.session_day(job.MARKETS[NSE], at_8am_ist) == dt.date(2026, 11, 26)
    # in summer (daylight saving) 08:00 India time = 22:30 in New York: still the same evening's session
    assert job.session_day(job.MARKETS[US], dt.datetime(2026, 7, 2, 2, 30, tzinfo=utc)) == dt.date(2026, 7, 1)
    # Monday 08:00 India time = Sunday evening in New York: a weekend, so the run skips
    monday = dt.datetime(2026, 11, 30, 2, 30, tzinfo=utc)
    assert job.trading_day(job.MARKETS[US], job.session_day(job.MARKETS[US], monday))[0] is False


# ---------------------------------------------------------------- download retries
@pytest.mark.parametrize("market", [NSE, US])
def test_retry_schedule_until_every_file_is_out(job, monkeypatch, market):
    m = job.MARKETS[market]
    attempts, slept = [], []

    def fake_run(cmd, cwd, name, timeout=0, env=None):
        attempts.append(cmd)
        if len(attempts) == 8:                                              # published before the 8th try
            for ex in m.exchanges:
                f = job.day_file(ex, DAY)
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("x")
        return True

    monkeypatch.setattr(job, "run", fake_run)
    assert job.download(m, DAY, dry=False, sleep=slept.append) is True
    assert len(attempts) == 8 and all(list(m.exchanges) == c[3:3 + len(m.exchanges)] for c in attempts)
    start, waits = slept[0], slept[1:]
    assert 0 <= start <= job.START_JITTER_MIN * 60                          # a random start
    for got, nominal in zip(waits, [5, 5, 5, 5, 5, 10, 10]):
        assert nominal * 60 * 0.8 <= got <= nominal * 60 * 1.2              # each wait +/-20%


def test_us_needs_both_exchanges(job, monkeypatch):
    f = job.day_file("NYSE", DAY)
    f.parent.mkdir(parents=True)
    f.write_text("x")                                                       # NASDAQ's file is still missing
    attempts = []
    monkeypatch.setattr(job, "run", lambda cmd, cwd, name, timeout=0, env=None: attempts.append(name) or True)
    assert job.download(job.MARKETS[US], DAY, dry=False, sleep=lambda s: None) is False
    assert len(attempts) == 11                                              # the first try + 10 retries


def test_gives_up_after_five_plus_five_retries(job, monkeypatch):
    attempts, slept = [], []
    monkeypatch.setattr(job, "run", lambda cmd, cwd, name, timeout=0, env=None: attempts.append(name) or True)
    assert job.download(job.MARKETS[NSE], DAY, dry=False, sleep=slept.append) is False
    assert len(attempts) == 11 and attempts[-1].endswith("(attempt 11/11)")
    waits = slept[1:]
    assert len(waits) == 10 and 60 * 75 * 0.8 <= sum(waits) <= 60 * 75 * 1.2   # about 75 minutes in all


def test_waits_are_random_not_fixed(job):
    got = {round(job.jittered(300)) for _ in range(50)}
    assert len(got) > 10 and min(got) >= 240 and max(got) <= 360


# ---------------------------------------------------------------- after the download
def test_after_the_download_setup_scan_then_pattern_screen(job, monkeypatch):
    calls = []
    monkeypatch.setattr(job, "run", lambda cmd, cwd, name, timeout=0, env=None: calls.append((name, cmd, env)) or True)
    steps = job.after_download(job.MARKETS[US], DAY, dry=False)
    names = [c[0] for c in calls]
    assert names == ["import NYSE,NASDAQ into Charting Lab", "setup scan NYSE", "setup scan NASDAQ",
                     "drop chart pages", "pattern screen"]
    assert steps == dict(import_eod=True, setup_scan=True, pattern_screen=True)
    scan_cmd = calls[1][1]
    if job.SCAN_PY.is_file():                                               # US scans run from the scanner's source
        assert "swingbt.scan" in [str(x) for x in scan_cmd] and calls[1][2]["SWINGBT_CONFIG"].endswith("swingbt_config.ini")
    calls.clear()
    job.after_download(job.MARKETS[NSE], DAY, dry=False)                    # NSE scans with SwingScanner.exe
    assert str(calls[1][1][0]).endswith("SwingScanner.exe")


def test_a_saved_scan_is_not_run_again(job, monkeypatch):
    (job.SCANNER / "scans" / "NSE_daily_2026-11-26").mkdir(parents=True)
    (job.SCANNER / "scans" / "NSE_daily_2026-11-26" / "signals.csv").write_text("x")
    names = []
    monkeypatch.setattr(job, "run", lambda cmd, cwd, name, timeout=0, env=None: names.append(name) or True)
    job.after_download(job.MARKETS[NSE], DAY, dry=False)
    assert "setup scan NSE" not in names and "pattern screen" in names


def test_main_skips_a_closed_day_and_records_the_status(job, monkeypatch):
    monkeypatch.setattr(job, "download", lambda *a, **k: pytest.fail("a closed day downloads nothing"))
    assert job.main(["--market", "US", "--date", "2026-11-26"]) == 0       # Thanksgiving
    st = json.loads((job.LOGS / "daily_us_status.json").read_text())
    assert st["result"] == "skipped: US market holiday" and st["market"] == "US"
    assert job.main(["--market", "NSE", "--date", "2026-11-24"]) == 0
    assert json.loads((job.LOGS / "daily_nse_status.json").read_text())["result"] == "skipped: NSE trading holiday"
    monkeypatch.setattr(job, "download", lambda *a, **k: False)
    monkeypatch.setattr(job, "after_download", lambda *a, **k: pytest.fail("not after a failed download"))
    assert job.main(["--market", "NSE", "--date", "2026-11-26"]) == 1
    assert json.loads((job.LOGS / "daily_nse_status.json").read_text())["result"].startswith("data not available")
