"""Activity stats: requests and active time per user and day, requests per feature, stocks opened.

Counted in memory on every signed-in request and written every FLUSH_S seconds (and at shutdown), so a busy user
costs no database write per request. Active time = the gaps between a user's requests that are shorter than
IDLE_S (5 minutes): a chart left open and idle does not count."""
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from app.models import User, UserDay, UserFeatureDay, UserSession, UserSymbol

IDLE_S = 300
FLUSH_S = 30
# the first path segment -> a feature name in the stats
FEATURES = {"history": "chart", "indicators": "indicators", "custom-indicators": "indicators", "patterns": "patterns",
            "drawings": "drawings", "watchlists": "watchlists", "quotes": "chart", "symbols": "search",
            "exchanges": "search", "markets": "search", "screener": "pattern_screener", "scanner": "setup_screener",
            "alerts": "alerts", "ai": "ai", "ws": "live", "admin": "admin"}


def feature_of(path: str) -> str:
    seg = path.strip("/").split("/", 1)[0]
    return FEATURES.get(seg, seg or "home")


def _day(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


class Recorder:
    def __init__(self):
        self.lock = threading.Lock()
        self.last_seen: dict[int, float] = {}            # user id -> time of the last request (for active time)
        self._reset()
        self.last_flush = time.time()

    def _reset(self):
        self.days = defaultdict(lambda: [0, 0.0, None, 0.0])       # (user, day) -> [requests, active s, first, last]
        self.features = defaultdict(int)                            # (user, day, feature) -> count
        self.symbols = defaultdict(lambda: [0, 0.0])                # (user, symbol) -> [count, last]
        self.sessions = defaultdict(lambda: [0, 0.0, 0.0])          # session id -> [requests, active s, last]
        self.users = defaultdict(lambda: [0, 0.0, 0.0])             # user id -> [requests, active s, last]

    def record(self, user_id: int, session_id: int | None, path: str, symbol: str | None = None,
               now: float | None = None) -> None:
        now = now or time.time()
        day = _day(now)
        with self.lock:
            prev = self.last_seen.get(user_id)
            active = (now - prev) if prev is not None and 0 <= now - prev < IDLE_S else 0.0
            self.last_seen[user_id] = now
            d = self.days[(user_id, day)]
            d[0] += 1
            d[1] += active
            d[2] = d[2] or now
            d[3] = now
            self.features[(user_id, day, feature_of(path))] += 1
            if symbol:
                s = self.symbols[(user_id, symbol.upper())]
                s[0] += 1
                s[1] = now
            u = self.users[user_id]
            u[0] += 1
            u[1] += active
            u[2] = now
            if session_id is not None:
                ss = self.sessions[session_id]
                ss[0] += 1
                ss[1] += active
                ss[2] = now

    def due(self) -> bool:
        return time.time() - self.last_flush >= FLUSH_S

    def flush(self, session_factory: sessionmaker) -> None:
        """Add what was counted to the tables."""
        with self.lock:
            days, features, symbols, sessions, users = self.days, self.features, self.symbols, self.sessions, self.users
            self._reset()
            self.last_flush = time.time()
        if not (days or users):
            return
        with session_factory() as db:
            for (uid, day), (n, act, first, last) in days.items():
                row = db.get(UserDay, (uid, day))
                if row is None:
                    db.add(UserDay(user_id=uid, day=day, requests=n, active_seconds=act, first_seen_at=first,
                                   last_seen_at=last))
                else:
                    row.requests += n
                    row.active_seconds += act
                    row.last_seen_at = max(row.last_seen_at, last)
            for (uid, day, feat), n in features.items():
                row = db.get(UserFeatureDay, (uid, day, feat))
                if row is None:
                    db.add(UserFeatureDay(user_id=uid, day=day, feature=feat, count=n))
                else:
                    row.count += n
            for (uid, sym), (n, last) in symbols.items():
                row = db.get(UserSymbol, (uid, sym))
                if row is None:
                    db.add(UserSymbol(user_id=uid, symbol=sym, count=n, first_at=last, last_at=last))
                else:
                    row.count += n
                    row.last_at = max(row.last_at, last)
            for sid, (n, act, last) in sessions.items():
                row = db.get(UserSession, sid)
                if row is not None:
                    row.requests += n
                    row.active_seconds += act
                    row.last_seen_at = max(row.last_seen_at, last)
            for uid, (n, act, last) in users.items():
                row = db.get(User, uid)
                if row is not None:
                    row.request_count += n
                    row.active_seconds += act
                    row.last_seen_at = max(row.last_seen_at or 0, last)
            db.commit()


recorder = Recorder()
