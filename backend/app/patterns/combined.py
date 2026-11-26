"""Several pattern engines as one (PATTERN_ENGINES=rulebook,mypkg.candles:Candles): app.ports.PatternEngine.

The chart's pattern menu, its marks and counts, and the Pattern Screener see one catalog. Each pattern id belongs
to exactly one engine (a clash is an error at start-up, so an id always means the same pattern); a scan asks each
engine only for its own ids, on the same bars, and merges the answers.
"""
from collections.abc import Sequence


class PatternIdClash(ValueError):
    pass


class CombinedPatterns:
    name = "combined"

    def __init__(self, engines: Sequence):
        self.engines = list(engines)
        self.owner: dict[str, object] = {}
        for eng in self.engines:
            for pid in eng.ids():
                if pid in self.owner:
                    raise PatternIdClash(f"pattern id '{pid}' is in both '{self.owner[pid].name}' and '{eng.name}'")
                self.owner[pid] = eng
        self.warmup = max((e.warmup for e in self.engines), default=0)

    def catalog(self) -> list[dict]:
        return [dict(p, engine=eng.name) for eng in self.engines for p in eng.catalog()]

    def ids(self) -> set[str]:
        return set(self.owner)

    def signal_ids(self) -> set[str]:
        return set().union(*(e.signal_ids() for e in self.engines)) if self.engines else set()

    def scan(self, t, o, h, l, c, v, ids: set[str], first: int = 0) -> dict:  # noqa: E741
        out: dict[str, list] = dict(markers=[], shapes=[], levels=[])
        for eng in self.engines:
            mine = {i for i in ids if self.owner.get(i) is eng}
            if not mine:
                continue
            got = eng.scan(t, o, h, l, c, v, mine, first)
            for k in out:
                out[k] += got.get(k) or []
        out["markers"].sort(key=lambda m: m["t"])
        return out
