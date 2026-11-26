"""'Why this trade' for SwingScanner signals: the six-part brief and the rulebook lookup."""
import json

from app.scanner_explain import rulebook
from tests.test_m14_scanner import scan_root  # noqa: F401  (fixture)

RULES_S4 = 'NL = "x"\nRULES = [\n    (33, "SH", "Bad break recovery (BBR): price closes below the 50-day SMA.", "c"),\n    (34, "SH", NL, "c"),\n]\n'


def test_explain_a_signal_in_six_parts(client, scan_root):  # noqa: F811
    root, _ = scan_root
    rb = root / "rulebook_unsupervised"
    rb.mkdir()
    (rb / "s07_session4.py").write_text(RULES_S4)
    day = root / "my_scans" / "NSE_daily_2026-11-23"
    meta = json.loads((day / "market.json").read_text())
    meta.update(capital=1000000, config={"risk_pct": 1.0})
    meta["market_row"]["impulse"] = "+-"
    (day / "market.json").write_text(json.dumps(meta))

    r = client.get("/scanner/scans/NSE_daily_2026-11-23/explain", params=dict(symbol="NSE:MARICO", setup="BBR"))
    assert r.status_code == 200
    e = r.json()
    titles = [s["title"] for s in e["sections"]]
    assert titles == ["What the pattern is: Bad break recovery", "Why today is the entry", "Where the stop is and why",
                      "How the position exits", "Position size", "Warnings and context"]
    text = {s["title"]: " ".join(s["lines"]) for s in e["sections"]}
    assert "Rule passed S4-R033: Bad break recovery (BBR)" in text["Why today is the entry"]   # rule text looked up
    stop = text["Where the stop is and why"]
    assert "Stop ₹891.91 = 3.00% below the entry ₹919.50" in stop
    assert "1R = ₹27.59" in stop and "+2R = ₹974.68" in stop and "rulebook stop is ₹904.00" in stop
    assert "₹5,000.00 at risk" in text["Position size"] and "Shares = risk / (entry - stop) = 181" in text["Position size"]
    assert "Market: regime weak bear, impulse +-" in text["Warnings and context"]

    near = client.get("/scanner/scans/NSE_daily_2026-11-23/explain",
                      params=dict(symbol="PRESTIGE", setup="VCP", near=True)).json()
    assert near["valid"] is False and near["sections"][1]["title"] == "Why it is not a breakout today"
    assert "failed: S8-R003" in near["sections"][1]["lines"][-1]
    assert "No position" in " ".join(near["sections"][4]["lines"])
    assert client.get("/scanner/scans/NSE_daily_2026-11-23/explain",
                      params=dict(symbol="NOPE", setup="BBR")).status_code == 404


def test_rulebook_ids_follow_the_session_files(tmp_path):
    rb = tmp_path / "rulebook_unsupervised"
    rb.mkdir()
    for name, n in [("s01_session1.py", 5), ("s03_session2b.py", 7), ("s06_session_doubt.py", 2), ("s15_session9a.py", 11)]:
        (rb / name).write_text(f'RULES = [({n}, "X", "Rule text {n}.", "")]\n')
    (rb / "source_rows.py").write_text("ROWS = []\n")
    assert rulebook(tmp_path) == {"S1-R005": "Rule text 5.", "S2B-R007": "Rule text 7.", "SD-R002": "Rule text 2.",
                                  "S9A-R011": "Rule text 11."}
    assert rulebook(None) == {} and rulebook(tmp_path / "missing") == {}


def test_position_size_follows_the_users_equity(client, scan_root):  # noqa: F811
    root, _ = scan_root
    day = root / "my_scans" / "NSE_daily_2026-11-23"
    meta = json.loads((day / "market.json").read_text())
    meta.update(capital=1000000, config={"risk_pct": 1.0})
    (day / "market.json").write_text(json.dumps(meta))
    q = dict(symbol="MARICO", setup="BBR")
    size = lambda **kw: " ".join(client.get("/scanner/scans/NSE_daily_2026-11-23/explain",  # noqa: E731
                                            params=q | kw).json()["sections"][4]["lines"])
    assert "Portfolio size ₹1,000,000.00" in size() and "= 181;" in size()                  # the scan's own capital
    assert "Portfolio size ₹2,500,000.00" in size(equity=2500000) and "= 453;" in size(equity=2500000)
    assert "= 18;" in size(equity=100000) and "sized by risk" in size(equity=100000)
    assert client.get("/scanner/scans/NSE_daily_2026-11-23/explain", params=q | {"equity": 0}).status_code == 422
    d = client.get("/scanner/scans/NSE_daily_2026-11-23").json()
    assert d["capital"] == 1000000 and d["risk_pct"] == 1.0 and d["max_alloc_pct"] == 45.0


def test_position_cap_at_45_percent():
    from app.scanner_explain import position

    assert position(1_000_000, 919.5, 891.91, 1.0, 0.5) == (181, "risk")
    assert position(1_000_000, 100, 99.5, 1.0, 1.0) == (4500, "max 45% of the portfolio")
    assert position(1_000_000, 100, 100, 1.0, 1.0) == (0, "invalid stop")


def test_risk_per_trade_is_the_users_choice(client, scan_root):  # noqa: F811
    q = dict(symbol="MARICO", setup="BBR")
    size = lambda **kw: " ".join(client.get("/scanner/scans/NSE_daily_2026-11-23/explain",  # noqa: E731
                                            params=q | kw).json()["sections"][4]["lines"])
    two = size(equity=1000000, risk_pct=2)
    assert "risk 2% per trade" in two and "= ₹10,000.00 at risk" in two and "= 362;" in two   # twice the 1% size
    assert "= 90;" in size(equity=1000000, risk_pct=0.5)
    for bad in (0, -1, 101):
        assert client.get("/scanner/scans/NSE_daily_2026-11-23/explain", params=q | {"risk_pct": bad}).status_code == 422
