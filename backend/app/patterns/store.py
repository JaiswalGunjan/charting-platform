"""Pattern screens kept as JSON files (SCREEN_STORE=json): app.ports.ScreenStore.

    <screens dir>/EX_TF_YYYY-MM-DD.json   the screen of one session
    <screens dir>/EX_TF.json              the newest screen (what the Pattern Screener opens first)

The screens dir is SCREENS_DIR, else backend/data/screens. Files are written whole (via a .tmp file), so a reader
never sees half a screen.
"""
import json
import logging
import re
import time
from pathlib import Path

log = logging.getLogger(__name__)
SCREEN_DIR = Path(__file__).resolve().parents[2] / "data" / "screens"
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
IST = 19800


def session_date(ts: int) -> str:
    """ISO trading date of a daily bar (daily bars are stamped at IST midnight of their date, every exchange)."""
    return time.strftime("%Y-%m-%d", time.gmtime(int(ts) + IST))


def screens_dir() -> Path:
    """Where screens are saved: SCREENS_DIR if set (the end-to-end tests use their own), else SCREEN_DIR."""
    from app.config import get_settings

    d = get_settings().screens_dir
    return Path(d) if d else SCREEN_DIR


def screen_path(exchange: str, tf: str, root: Path | None = None, day: str | None = None) -> Path:
    """The newest screen (EX_TF.json), or the screen of one session (EX_TF_YYYY-MM-DD.json)."""
    return (root or screens_dir()) / (f"{exchange.upper()}_{tf}.json" if not day else f"{exchange.upper()}_{tf}_{day}.json")


def _read(p: Path) -> dict | None:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class JsonScreenStore:
    """Screens as JSON files in `root` (default: the screens dir, looked up on every call)."""

    name = "json"

    def __init__(self, root: Path | None = None):
        self.root = root

    def read(self, exchange: str, tf: str, day: str | None = None) -> dict | None:
        """The screen saved for exactly session `day`; day None = the newest screen."""
        if not day:
            return _read(screen_path(exchange, tf, self.root))
        res = _read(screen_path(exchange, tf, self.root, day))
        if res is None:                       # the newest screen may be that session (saved before dated files)
            res = _read(screen_path(exchange, tf, self.root))
            if not res or not res.get("last_session") or session_date(res["last_session"]) != day:
                return None
        return res

    def dates(self, exchange: str, tf: str) -> list[str]:
        """Session dates with a saved screen, newest first."""
        d = self.root or screens_dir()
        pre = f"{exchange.upper()}_{tf}_"
        out = {f.stem[len(pre):] for f in d.glob(f"{pre}*.json") if DATE_RE.fullmatch(f.stem[len(pre):])}
        latest = _read(screen_path(exchange, tf, self.root))
        if latest and latest.get("last_session"):
            out.add(session_date(latest["last_session"]))
        return sorted(out, reverse=True)

    def write(self, res: dict, newest: bool) -> dict:
        """Save a screen under its session date; the newest session is also the default screen."""
        exchange, tf, root = res["exchange"], res["tf"], self.root
        if newest:
            # the screen being replaced as the newest keeps its own dated file (older screens were saved only there)
            old = _read(screen_path(exchange, tf, root))
            if old and old.get("last_session") and old.get("last_session") != res.get("last_session"):
                keep = screen_path(exchange, tf, root, session_date(old["last_session"]))
                if not keep.exists():
                    keep.parent.mkdir(parents=True, exist_ok=True)
                    keep.write_text(json.dumps(dict(old, session=session_date(old["last_session"]))), encoding="utf-8")
        paths = ([screen_path(exchange, tf, root, res["session"])] if res.get("session") else []) + \
            ([screen_path(exchange, tf, root)] if newest else [])
        for p in paths:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(res), encoding="utf-8")
            tmp.replace(p)
        return res
