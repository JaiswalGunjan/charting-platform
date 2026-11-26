"""Which adapter plays each replaceable part (app/ports.py), chosen by settings.

    SETUP_SCANNER=swingscanner      a built-in name from REGISTRY, or
    SETUP_SCANNER=mypkg.scan:MyScanner   any class (or factory) by import path: no product code changes

Adapters are made once per setting value and reused. Tests (or a different deployment) can put any object in a part
with use(); reset() forgets the made adapters and the overrides.
"""
from __future__ import annotations

import importlib
from typing import Any

from app.config import get_settings

# part -> {built-in name: "module:attribute"}; the setting that chooses it is in SETTING
REGISTRY: dict[str, dict[str, str]] = {
    "setup_scanner": {"swingscanner": "app.adapters.swingscanner:SwingScanner",
                      "none": "app.adapters.null:NoSetupScanner"},
    "pattern_engine": {"rulebook": "app.patterns.engine:RulebookPatterns"},
    "screen_store": {"json": "app.patterns.store:JsonScreenStore"},
    "bar_store": {"sql": "app.marketdata.barstore:SqlBarStore",
                  "timescale": "app.marketdata.minute_store:TimescaleMinuteStore"},   # 1m bars, last 2 years
    "tick_source": {},                  # built-in feeds are made in app/live/ticks.py (they need the settings)
}
SETTING = {"setup_scanner": "setup_scanner", "pattern_engine": "pattern_engine", "screen_store": "screen_store",
           "bar_store": "bar_store"}

_made: dict[tuple[str, str], Any] = {}
_override: dict[str, Any] = {}


class ProviderError(RuntimeError):
    pass


def load(part: str, choice: str) -> Any:
    """A new adapter for `part`: a built-in name, or "package.module:Attribute" (a class or factory, called with no
    arguments)."""
    spec = REGISTRY.get(part, {}).get(choice, choice)
    if ":" not in spec:
        known = ", ".join(sorted(REGISTRY.get(part, {})))
        raise ProviderError(f"unknown {part} '{choice}': use one of {known}, or 'package.module:Class'")
    mod, attr = spec.split(":", 1)
    try:
        target = getattr(importlib.import_module(mod), attr)
    except (ImportError, AttributeError) as e:
        raise ProviderError(f"{part} '{choice}' ({spec}) cannot be loaded: {e}") from e
    return target() if callable(target) else target


def get(part: str) -> Any:
    if part in _override:
        return _override[part]
    choice = str(getattr(get_settings(), SETTING[part]))
    key = (part, choice)
    if key not in _made:
        _made[key] = load(part, choice)
    return _made[key]


def use(part: str, adapter: Any) -> None:
    """Put `adapter` in `part` (tests, embedding); None removes the override."""
    if adapter is None:
        _override.pop(part, None)
    else:
        _override[part] = adapter


def reset() -> None:
    _made.clear()
    _override.clear()


def _names(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


def setup_scanners() -> dict:
    """Every setup scanner in use, by name, the default first: SETUP_SCANNERS (several), else SETUP_SCANNER.
    Names must be unique (each adapter's `name`)."""
    if "setup_scanners" in _override:                      # tests / embedding: several, by name
        return dict(_override["setup_scanners"])
    if "setup_scanner" in _override:
        one = _override["setup_scanner"]
        return {one.name: one}
    s = get_settings()
    choices = _names(s.setup_scanners) or [s.setup_scanner]
    out: dict = {}
    for c in choices:
        key = ("setup_scanner", c)
        if key not in _made:
            _made[key] = load("setup_scanner", c)
        sc = _made[key]
        if sc.name in out:
            raise ProviderError(f"two setup scanners are named '{sc.name}' ({choices})")
        out[sc.name] = sc
    return out


def setup_scanner(name: str | None = None):
    """A SetupScanner by name; None = the default (the first of SETUP_SCANNERS, or SETUP_SCANNER)."""
    all_ = setup_scanners()
    if not name:
        return next(iter(all_.values()))
    if name not in all_:
        raise ProviderError(f"no setup scanner named '{name}': {', '.join(all_)}")
    return all_[name]


def pattern_engine():
    """The PatternEngine in use: PATTERN_ENGINES combined into one (several), else PATTERN_ENGINE."""
    if "pattern_engine" in _override:
        return _override["pattern_engine"]
    names = _names(get_settings().pattern_engines)
    if len(names) <= 1:
        return get("pattern_engine") if not names else _one("pattern_engine", names[0])
    key = ("pattern_engine", ",".join(names))
    if key not in _made:
        from app.patterns.combined import CombinedPatterns

        _made[key] = CombinedPatterns([_one("pattern_engine", n) for n in names])
    return _made[key]


def _one(part: str, choice: str):
    key = (part, choice)
    if key not in _made:
        _made[key] = load(part, choice)
    return _made[key]


def screen_store():
    """The ScreenStore in use (SCREEN_STORE)."""
    return get("screen_store")


def bar_store():
    """The BarStore in use: BAR_STORE, with BAR_STORES routing single timeframes to other stores
    ("1m=mypkg.ch:ClickHouseBars"); the product sees one store either way."""
    if "bar_store" in _override:
        return _override["bar_store"]
    routes = {}
    for part in _names(get_settings().bar_stores):
        tf, _, choice = part.partition("=")
        if not choice:
            raise ProviderError(f"BAR_STORES entry '{part}': use timeframe=store, e.g. 1m=sql")
        routes[tf.strip()] = choice.strip()
    if not routes:
        return get("bar_store")
    key = ("bar_store", "routed:" + ",".join(f"{k}={v}" for k, v in sorted(routes.items())))
    if key not in _made:
        from app.marketdata.barstore import RoutedBarStore

        _made[key] = RoutedBarStore(get("bar_store"), {tf: _one("bar_store", c) for tf, c in routes.items()})
    return _made[key]
