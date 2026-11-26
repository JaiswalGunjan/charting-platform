"""Setup Screener: why the market rule stops (or shrinks) new entries, sizes on a blocked day, and the score note."""
import json

from app.scanner_explain import explain, market_note, score_note
from tests.test_m14_scanner import scan_root  # noqa: F401  (fixture)

RULES = {"S7-R007": "Strong bear: 20 WMA below 50, both falling.", "S7-R014": "Small-cap index below its 10-day low.",
         "S7-R025": "Impulse system on the small-cap index.", "S7-R026": "Skip setups when both are down."}
ROW = dict(idx_close=17630.6, idx_wma20=17641.19, idx_wma50=17522.14, idx_low10_prior=17000.0)


def test_impulse_down_blocks_entries():
    n = market_note("NSE", dict(ROW, regime="weak_bear", impulse="--", risk_mult=0.0), RULES)
    assert n["blocked"] is True and n["title"] == "Market rule: no new entries today"
    assert n["index"] == "Nifty SmallCap 250"
    assert "13-day EMA and its MACD histogram both ticked down" in n["lines"][0]
    assert "weak bear" in n["lines"][1] and "17,641.19" in n["lines"][1]
    assert [r["id"] for r in n["rules"]] == ["S7-R025", "S7-R026"]


def test_ten_day_low_and_strong_bear():
    n = market_note("NYSE", dict(ROW, regime="strong_bear", impulse="-+", risk_mult=0.0, warn_10d_low=True), RULES)
    assert n["blocked"] and n["index"] == "Russell 2000"
    assert "below its prior 10-day low 17,000.00" in n["lines"][0]
    assert any("strong bear" in x for x in n["lines"]) and any("half size" in x for x in n["lines"])
    assert [r["id"] for r in n["rules"]] == ["S7-R014", "S7-R025", "S7-R007"]


def test_reduced_size_and_a_clear_market():
    n = market_note("NSE", dict(ROW, regime="weak_bear", impulse="+-", risk_mult=0.5), RULES)
    assert n["blocked"] is False and n["title"] == "Market rule: positions at x0.5 size"
    assert market_note("NSE", dict(ROW, regime="strong_bull", impulse="++", risk_mult=1.0), RULES) is None
    assert market_note("NSE", {}, RULES) is None


def test_score_note_comes_from_the_report(tmp_path):
    (tmp_path / "index.html").write_text("<p class='note'>Score = the backtester's priority score: a + b, minus 0.25 per "
                                         "soft miss. Higher = bought first.</p>", encoding="utf-8")
    assert score_note(tmp_path).startswith("Score = the backtester's priority score: a + b")
    assert score_note(tmp_path / "missing") == ""


def test_blocked_day_still_sizes_the_position():
    row = {"symbol": "TCS", "setup": "BBR", "date": "2026-11-25", "valid": "True", "close": "100", "stop": "95",
           "stop_pct": "5", "rules_ok": "", "also": "", "stop_note": "", "rule_stop": "95", "rule_stop_pct": "5",
           "notes": "", "weak": "", "reject": "", "size_mult": "1", "stage": "", "phase": "", "ext": "", "rs60": "",
           "score": "8"}
    meta = {"capital": 1_000_000, "config": {"risk_pct": 1.0},
            "market_row": dict(ROW, regime="weak_bear", impulse="--", risk_mult=0.0)}
    lines = explain(row, "NSE", {"name": "BBR", "what": "", "why": ""}, {}, meta)["sections"][4]["lines"]
    assert lines[0].startswith("The market rule blocks new entries today")
    assert "x market multiplier 1 = ₹10,000.00 at risk" in lines[1] and "= 2,000;" in lines[2]   # 10,000 / 5


def test_scan_answer_carries_both_notes(client, scan_root):  # noqa: F811
    root, _ = scan_root
    day = root / "my_scans" / "NSE_daily_2026-11-23"
    meta = json.loads((day / "market.json").read_text())
    meta["market_row"] = dict(ROW, regime="weak_bear", impulse="--", risk_mult=0.0)
    (day / "market.json").write_text(json.dumps(meta))
    d = client.get("/scanner/scans/NSE_daily_2026-11-23").json()
    assert d["market_note"]["blocked"] is True and d["market_note"]["lines"]
    assert d["score_note"].startswith("Score = ")                      # no report page here: the brief version
