"""'Why this trade' edge cases, on the builder directly: US dollars, a missing market.json, the setup multiplier,
many rules, long rule text, stop notes, and a stop that was not widened."""
from app.scanner_explain import explain

SETUP = {"name": "Pocket pivot", "what": "An up day on volume above every down day.", "why": "Shows buying."}
ROW = {"symbol": "AAPL", "setup": "PP", "date": "2026-11-17", "valid": "True", "close": "200", "stop": "190",
       "stop_pct": "5.0", "rules_ok": "S3B-R001,S3B-R006,S3B-R008,S3B-R009,S1-R051", "also": "",
       "stop_note": "below the low of 2026-11-17 | second note", "rule_stop": "190", "rule_stop_pct": "5.0",
       "notes": "Pocket pivot: volume 9,000 > 8,000 | extra", "weak": "", "reject": "", "shares": "50",
       "value": "10000", "size_mult": "1.0", "stage": "2", "phase": "trend", "ext": "", "rs60": "", "score": "7.5"}
META = {"capital": 1_000_000, "config": {"risk_pct": 1.0}, "market_row": {"regime": "bull", "impulse": "++", "risk_mult": 1.0}}


def text(e, i):
    return " ".join(e["sections"][i]["lines"])


def test_us_signal_in_dollars():
    e = explain(ROW, "NYSE", SETUP, {}, META)
    assert e["symbol"] == "NYSE:AAPL"
    assert "Stop $190.00 = 5.00% below the entry $200.00" in text(e, 2) and "1R = $10.00" in text(e, 2)
    assert "₹" not in " ".join(text(e, i) for i in range(6))
    assert "Portfolio size $1,000,000.00" in text(e, 4) and "= 1,000;" in text(e, 4)        # 10,000 at risk / 10 a share


def test_more_than_three_rules_and_unknown_rule_text():
    rules = {"S3B-R001": "Up day on volume above every down day of the prior 10 bars. " * 5}
    e = explain(ROW, "NSE", SETUP, rules, META)
    lines = e["sections"][1]["lines"]
    assert lines[0] == "Pocket pivot: volume 9,000 > 8,000"                    # today's trigger, first note only
    assert lines[1].startswith("Rule passed S3B-R001: Up day") and lines[1].endswith("…") and len(lines[1]) < 175
    assert lines[2] == "Rule passed S3B-R006"                                  # id only when the rulebook lacks it
    assert lines[4] == "Other rules satisfied: S3B-R009, S1-R051"


def test_stop_notes_split_and_no_widening_line_when_unchanged():
    e = explain(ROW, "NSE", SETUP, {}, META)
    t = e["sections"][2]["lines"]
    assert "Below the low of 2026-11-17" in t and "Second note" in t           # each part on its own line, capitalised
    assert not any("rulebook stop" in x for x in t)                            # rule stop == stop: nothing to explain


def test_setup_multiplier_and_missing_market_file():
    row = dict(ROW, size_mult="0.5")
    e = explain(row, "NSE", SETUP, {}, META)
    assert "x setup multiplier 0.5 = ₹5,000.00 at risk" in text(e, 4) and "= 500;" in text(e, 4)
    e = explain(ROW, "NSE", SETUP, {}, {})                                     # no market.json
    assert e["sections"][4]["lines"] == ["Daily signals are bought at the close of the signal day; the stop is first "
                                         "tested the next session."]
    assert not any(x.startswith("Market:") for x in e["sections"][5]["lines"])
    e = explain(ROW, "NSE", SETUP, {}, {}, equity=500_000)                    # the user's equity still sizes it
    assert "Portfolio size ₹500,000.00" in text(e, 4) and "= 500;" in text(e, 4)


def test_setup_without_a_description_and_context_line():
    e = explain(ROW, "NSE", {"name": "PP", "what": "", "why": ""}, {}, META)
    assert e["sections"][0] == {"title": "What the pattern is: PP", "lines": []}
    assert e["sections"][5]["lines"][-1] == "Stage 2, cycle phase 'trend', rank score 7.50."


def test_position_capped_at_45_percent_is_explained():
    row = dict(ROW, close="100", stop="99.9")                                  # a very tight stop
    e = explain(row, "NSE", SETUP, {}, META)
    assert "= 4,500;" in text(e, 4) and "sized by max 45% of the portfolio" in text(e, 4) and "(45.0% of the portfolio)" in text(e, 4)
