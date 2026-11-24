import json
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import select

from app.ai.analyst import DISCLAIMER, ChartAnalysis, _schema
from app.ai.context import build_context, swing_levels
from app.marketdata.history import Bars
from app.models import AiLog

GOOD = {
    "summary": "RELIANCE on the daily chart is in a moderate uptrend.",
    "trend": "uptrend", "trend_strength": "moderate",
    "momentum": "RSI is mid-range.", "volatility": "ATR is about 1.5% of price.",
    "volume": "Volume is near its 20-bar average.",
    "key_levels": [{"kind": "support", "price": 210.5, "source": "swing", "note": "recent swing low"}],
    "signals_conflicting": [], "what_to_watch": ["A close below the 50 EMA would weaken the trend."],
}


def reply(payload, stop_reason="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        stop_reason=stop_reason, model="claude-opus-5-5", _request_id="req_test",
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=1200, output_tokens=300),
    )


def _bars(n=300, seed=3):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.01, n)))
    h, l = c * 1.005, c * 0.995  # noqa: E741
    t = 1_700_000_000 + 86400 * np.arange(n)
    return Bars(t, c, h, l, c, rng.integers(1000, 5000, n).astype(float), False)


# ---- context ------------------------------------------------------------------

def test_context_numbers_are_consistent():
    ctx = build_context("NSE:X", "1D", _bars())
    px = ctx["price"]["last"]
    assert ctx["moving_averages"]["ema200"]["value"] is not None
    assert all(x > px for x in ctx["levels_from_swings"]["resistance_above"])
    assert all(x < px for x in ctx["levels_from_swings"]["support_below"])
    assert 0 <= ctx["momentum"]["rsi14"] <= 100
    assert len(ctx["recent_bars"]["rows"]) == 30
    assert "session_vwap" not in ctx["volatility"]  # daily chart
    json.dumps(ctx, allow_nan=False)  # no NaN leaks into the prompt


def test_context_needs_history():
    with pytest.raises(ValueError):
        build_context("NSE:X", "1D", _bars(20))


def test_swing_levels():
    h = np.array([1, 2, 3, 9, 3, 2, 1, 2, 3, 4, 5, 6, 7.])
    hi, lo = swing_levels(h, h - 1, w=2)
    assert hi == [9.0] and lo == [0.0]


def test_schema_matches_model():
    s = _schema()
    assert set(s["properties"]) == set(ChartAnalysis.model_fields)
    ChartAnalysis.model_validate(GOOD)


# ---- API ----------------------------------------------------------------------

def test_dry_run_returns_context_without_llm(client, llm):
    r = client.post("/ai/explain", json={"symbol": "NSE:RELIANCE", "tf": "15m", "dry_run": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["analysis"] is None and body["disclaimer"] == DISCLAIMER
    assert body["context"]["timeframe"] == "15m" and "session_vwap" in body["context"]["volatility"]
    assert llm.calls == []


def test_explain_success_and_logged(client, llm, session_factory):
    llm.reply = reply(GOOD)
    r = client.post("/ai/explain", json={"symbol": "RELIANCE", "tf": "1D"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["analysis"]["trend"] == "uptrend" and body["usage"]["input_tokens"] == 1200

    (call,) = llm.calls
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["effort"] == "medium"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert "buy, sell" in call["system"]
    sent_ctx = json.loads(call["messages"][0]["content"].split("\n", 1)[1])
    assert sent_ctx == body["context"]  # the model saw exactly what we return/log

    with session_factory() as s:
        row = s.get(AiLog, body["log_id"])
        assert row.output_json == ChartAnalysis.model_validate(GOOD).model_dump()
        assert row.request_id == "req_test" and row.error is None and row.context_json == sent_ctx


@pytest.mark.parametrize("make_reply,status", [
    (lambda: reply(GOOD, stop_reason="refusal"), 502),
    (lambda: reply(GOOD, stop_reason="max_tokens"), 502),
    (lambda: reply("not json"), 502),
    (lambda: reply({**GOOD, "trend": "to the moon"}), 502),
    (lambda: TypeError("Could not resolve authentication method. Expected one of api_key"), 503),
])
def test_explain_failures_are_mapped_and_logged(client, llm, session_factory, make_reply, status):
    llm.reply = make_reply()
    r = client.post("/ai/explain", json={"symbol": "NSE:TCS", "tf": "1D"})
    assert r.status_code == status, r.text
    with session_factory() as s:
        last = s.scalars(select(AiLog).order_by(AiLog.id.desc()).limit(1)).one()
        assert last.error and last.output_json is None and last.symbol == "NSE:TCS"


def test_explain_bad_inputs(client):
    assert client.post("/ai/explain", json={"symbol": "NSE:NOPE"}).status_code == 404
    assert client.post("/ai/explain", json={"symbol": "NSE:TCS", "tf": "7m"}).status_code == 400
    assert client.post("/ai/explain", json={"symbol": "NSE:INFY"}).status_code == 422  # no history
