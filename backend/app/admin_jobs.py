"""Jobs an admin starts from the dashboard: the EOD download, the setup screener, the pattern screener, or all of it.

Each job runs the nightly job's own script (scripts/daily_update.py) with some of its steps, at once (--now: no random
start, one download try), as a separate process, so the tools it runs are the ones named in daily_update.toml and a
long download never blocks the web server. One job at a time; its output is kept line by line for the dashboard, and
the last jobs are saved to backend/data/logs/admin_jobs.json. ADMIN_JOBS_DRY_RUN=true only logs what would be done
(the browser tests use it)."""
import itertools
import json
import os
import subprocess
import sys
import threading
import time
import tomllib
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.config import get_settings

ROOT = Path(__file__).resolve().parents[2]                 # Charting-platform
SCRIPT = ROOT / "scripts" / "daily_update.py"
CONFIG = ROOT / "scripts" / "daily_update.toml"
HISTORY = Path(os.environ.get("DAILY_LOGS_DIR", ROOT / "backend" / "data" / "logs")) / "admin_jobs.json"
KEEP_JOBS, KEEP_LINES = 30, 2000
# kind -> (the daily job's steps, title)
KINDS = {"download": ("download,import", "Download EOD data"),
         "setup_scan": ("scan", "Run setup screener"),
         "pattern_screen": ("screen", "Run pattern screener"),
         "full": ("", "Full update (download, import, setup and pattern screeners)")}


class Busy(RuntimeError):
    pass


@dataclass
class Job:
    id: int
    kind: str
    title: str
    market: str
    date: str
    by: str
    started: float
    finished: float | None = None
    state: str = "running"                     # running | done | error
    exit_code: int | None = None
    log: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        d = asdict(self)
        d.pop("log")
        d["lines"] = len(self.log)
        d["last_line"] = self.log[-1] if self.log else ""
        return d


def markets() -> dict[str, list[str]]:
    """The daily job's markets and their exchanges (daily_update.toml): NSE -> [NSE], US -> [NYSE, NASDAQ]."""
    try:
        cfg = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    except OSError:
        return {}
    return {k: list(v.get("exchanges", [])) for k, v in cfg.get("markets", {}).items()}


def command(kind: str, market: str, date: str | None) -> list[str]:
    steps = KINDS[kind][0]
    cmd = [sys.executable, str(SCRIPT), "--market", market, "--now"]
    if steps:
        cmd += ["--only", steps]
    if date:
        cmd += ["--date", date]
    if get_settings().admin_jobs_dry_run:
        cmd.append("--dry-run")
    return cmd


class Runner:
    def __init__(self, history: Path = HISTORY):
        self.lock = threading.Lock()
        self.history_file = history
        self.jobs: deque[Job] = deque(self._load(), maxlen=KEEP_JOBS)
        self.ids = itertools.count(max((j.id for j in self.jobs), default=0) + 1)
        self.current: Job | None = None

    def _load(self) -> list[Job]:
        try:
            rows = json.loads(self.history_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        out = []
        for r in rows:
            j = Job(**r)
            if j.state == "running":                       # the server stopped while it ran
                j.state, j.log = "error", j.log + ["(the server stopped while this job ran)"]
            out.append(j)
        return out

    def _save(self) -> None:
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        rows = [asdict(j) | {"log": j.log[-300:]} for j in self.jobs]
        tmp = self.history_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows), encoding="utf-8")
        tmp.replace(self.history_file)

    def start(self, kind: str, market: str, date: str | None, by: str) -> Job:
        if kind not in KINDS:
            raise ValueError(f"unknown job {kind!r}: one of {list(KINDS)}")
        if market not in markets():
            raise ValueError(f"unknown market {market!r}: one of {list(markets())}")
        with self.lock:
            if self.current is not None and self.current.state == "running":
                raise Busy(f"{self.current.title} ({self.current.market}) is running; wait for it to finish")
            job = Job(id=next(self.ids), kind=kind, title=KINDS[kind][1], market=market, date=date or "", by=by,
                      started=time.time())
            self.current = job
            self.jobs.appendleft(job)
        cmd = command(kind, market, date)
        job.log.append("$ " + " ".join(Path(c).name if i < 2 else c for i, c in enumerate(cmd)))
        threading.Thread(target=self._run, args=(job, cmd), name=f"admin-job-{job.id}", daemon=True).start()
        return job

    def _run(self, job: Job, cmd: list[str]) -> None:
        try:
            p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONUTF8="1"))
            for line in p.stdout:                          # live, line by line
                line = line.rstrip()
                if line:
                    job.log.append(line)
                    if len(job.log) > KEEP_LINES:
                        del job.log[1:len(job.log) - KEEP_LINES + 1]
            job.exit_code = p.wait()
            job.state = "done" if job.exit_code == 0 else "error"
        except Exception as e:  # noqa: BLE001  reported on the dashboard
            job.log.append(f"could not run the job: {e!r}")
            job.state = "error"
        finally:
            job.finished = time.time()
            with self.lock:
                self._save()

    def get(self, job_id: int) -> Job | None:
        return next((j for j in self.jobs if j.id == job_id), None)

    def wait(self, timeout: float = 30) -> None:
        """Until no job runs (tests)."""
        end = time.time() + timeout
        while self.current is not None and self.current.state == "running" and time.time() < end:
            time.sleep(0.05)


_runner: Runner | None = None


def runner() -> Runner:
    global _runner
    if _runner is None:
        _runner = Runner()
    return _runner
