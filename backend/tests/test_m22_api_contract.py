"""The web API is the contract between the UI and the backend: docs/api/openapi.json describes every endpoint, its
parameters and answers. A change to the API shows up here, so it is made on purpose: a UI (this one, or a
replacement) can rely on the file. After an intended change, refresh the file:

    UPDATE_API_CONTRACT=1 python -m pytest tests/test_m22_api_contract.py
"""
import json
import os
from pathlib import Path

CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.json"


def _spec(client) -> str:
    return json.dumps(client.app.openapi(), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def test_the_api_matches_its_contract(client):
    got = _spec(client)
    if os.environ.get("UPDATE_API_CONTRACT") or not CONTRACT.exists():
        CONTRACT.parent.mkdir(parents=True, exist_ok=True)
        CONTRACT.write_text(got, encoding="utf-8")
    want = CONTRACT.read_text(encoding="utf-8")
    if got != want:
        a, b = json.loads(want)["paths"], json.loads(got)["paths"]
        added, removed = sorted(set(b) - set(a)), sorted(set(a) - set(b))
        changed = sorted(p for p in set(a) & set(b) if a[p] != b[p])
        raise AssertionError(f"the API differs from docs/api/openapi.json: added {added}, removed {removed}, "
                             f"changed {changed} (and/or schemas). If intended, refresh it: "
                             f"UPDATE_API_CONTRACT=1 python -m pytest tests/test_m22_api_contract.py")


def test_the_contract_covers_what_the_ui_calls(client):
    """Every backend path the UI calls (frontend/src/api.ts) is in the contract."""
    import re

    paths = json.loads(CONTRACT.read_text(encoding="utf-8"))["paths"]
    api_ts = (CONTRACT.parents[2] / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    called = {m.split("?")[0] for m in re.findall(r'req<[^>]*>\(\s*[`"](/[^`"$?]*)', api_ts)}
    known = [re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", p) + "$") for p in paths]
    # a path cut at a ${...} part ends in "/": that part is a path parameter
    missing = sorted(c for c in called if not any(k.match(c + "x" if c.endswith("/") else c) for k in known))
    assert called and not missing, missing
