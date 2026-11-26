"""No buy / sell recommendation words on screen (SEBI): a signal to enter is a "breakout", to exit a "breakdown".
The rulebook's and the scanner's own text is rewritten on its way out; their files are never changed."""
import re

import pytest

from app.wording import neutral, neutral_all, neutral_html
from tests.test_m14_scanner import scan_root  # noqa: F401  (fixture)

BANNED = re.compile(r"\b(buy|buys|buying|buyer|buyers|bought|sell|sells|selling|seller|sellers|sold)\b", re.IGNORECASE)


def texts(obj, key=""):
    """Every string value in a JSON answer (keys and ids are code, not screen text)."""
    if isinstance(obj, str):
        yield key, obj
    elif isinstance(obj, list):
        for x in obj:
            yield from texts(x, key)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from texts(v, k)


def assert_clean(obj):
    bad = [(k, v) for k, v in texts(obj) if BANNED.search(v) and k not in ("chart", "chart_href", "report_href", "id")]
    assert not bad, bad[:5]


@pytest.mark.parametrize("src, out", [
    ("would buy", "breakout"),
    ("Would Buy", "Breakout"),
    ("BUY: entry Rs 919.50", "BREAKOUT: entry Rs 919.50"),
    ("3 buy signals", "3 breakouts"),
    ("a sell signal", "a breakdown"),
    ("Not a buy - failed: S8-R003", "Not a breakout - failed: S8-R003"),
    ("The buy is the follow-up pocket pivot", "The entry is the follow-up pocket pivot"),
    ("the scanner would not buy it", "the scanner would not enter it"),
    ("the stop moves up to the buy price", "the stop moves up to the entry price"),
    ("Sell into strength, sell below the day's low", "Exit into strength, exit below the day's low"),
    ("a loser is sold", "a loser is exited"),
    ("the exit comes from the selling rules.", "the exit comes from the exit rules."),
    ("the dip was bought by stronger hands", "the dip was entered by stronger hands"),
    ("avoids buying a dead-cat bounce", "avoids entering a dead-cat bounce"),
    ("institutional buying", "institutional accumulation"),
    ("How we would sell", "How the position exits"),
    ("Institutions cannot buy a stock in one day", "Institutions cannot enter a stock in one day"),
    ("the footprint of a big buyer", "the footprint of a big investor"),
    ("says buyers have taken control", "says bulls have taken control"),
    ("almost no sellers left above", "almost no bears left above"),
    ("holders are not selling.", "holders are not exiting."),
    ("selling pressure", "supply"),
    ("no trading words here", "no trading words here"),
    ("Buyback news; sellotape", "Buyback news; sellotape"),       # only whole words change
])
def test_neutral_wording(src, out):
    assert neutral(src) == out
    assert not BANNED.search(neutral(src))


def test_neutral_all_and_html():
    assert neutral_all({"buy": "would buy", "n": [1, "sold"]}) == {"buy": "breakout", "n": [1, "exited"]}
    html = '<p class="buy" data-x="sell">would buy <b>BUY</b></p><script>api("/api/buy")</script><style>.sell{}</style>'
    assert neutral_html(html) == ('<p class="buy" data-x="sell">breakout <b>ENTRY</b></p>'
                                  '<script>api("/api/buy")</script><style>.sell{}</style>')   # tags, scripts untouched


def test_scanner_answers_have_no_buy_sell_words(client, scan_root):  # noqa: F811
    d = client.get("/scanner/scans/NSE_daily_2026-11-23").json()
    assert d["signals"][0]["status"] == "breakout"                    # the scanner's "would buy"
    assert d["signals"][0]["buy"] is True                             # the field name is code, not screen text
    assert_clean(d)
    for near in (False, True):
        e = client.get("/scanner/scans/NSE_daily_2026-11-23/explain",
                       params=dict(symbol="PRESTIGE" if near else "MARICO", setup="VCP" if near else "BBR",
                                   near="true" if near else "false")).json()
        assert_clean(e)
    assert_clean(client.get("/scanner/setups").json())


def test_pattern_answers_have_no_buy_sell_words(client):
    assert_clean(client.get("/patterns").json())
    ids = ",".join(p["id"] for p in client.get("/patterns").json())
    assert_clean(client.get("/patterns/scan", params=dict(symbol="NSE:RELIANCE", tf="1D", ids=ids, limit=600)).json())


def test_report_page_text_has_no_buy_sell_words(client, scan_root):  # noqa: F811
    root, _ = scan_root
    day = root / "my_scans" / "NSE_daily_2026-11-23"
    (day / "index.html").write_text('<html><head><title>x</title></head><body><h1>BUY: entry Rs 919.50</h1>'
                                    '<span class="badge buy">would buy</span><p>Sell into strength.</p>'
                                    '<button data-action="buy">Enter trade</button></body></html>', encoding="utf-8")
    html = client.get("/scanner/report/NSE_daily_2026-11-23/index.html").text
    visible = re.sub(r"<script\b.*?</script>|<style\b.*?</style>|<[^>]+>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    assert not BANNED.search(visible), BANNED.findall(visible)
    assert "BREAKOUT: entry Rs 919.50" in html and 'class="badge buy"' in html     # markup kept


CODE = re.compile(r"\b(?:S\d+[A-Z]?|SD)-R\d")


@pytest.mark.parametrize("src, out", [
    ("Rule passed S4-R039: Three-touch-point trendline", "Rule passed: Three-touch-point trendline"),
    ("Soft miss S8-R004: stochastic 64 >= 50", "Soft miss: stochastic 64 >= 50"),
    ("Not a breakout - failed: S8-R003: no ATR; S5B-R008: no volume", "Not a breakout - failed: no ATR; no volume"),
    ("S8-R003: no ATR(1) contraction", "no ATR(1) contraction"),
    ("the stop moves up to the entry price (S6A-R012/R020).", "the stop moves up to the entry price."),
    ("exit on the first down-tick (S6B-R009/R011/R01…", "exit on the first down-tick"),      # cut short
    ("Liquidity: turnover 1,383 >= 100 (S4-R047) = PASS", "Liquidity: turnover 1,383 >= 100 = PASS"),
    ("no rule codes here", "no rule codes here"),
])
def test_rule_codes_are_removed(src, out):
    from app.wording import no_rule_codes
    assert no_rule_codes(src) == out


def test_lines_that_only_listed_codes_are_dropped():
    from app.wording import for_screen_all
    lines = ["Rule passed S4-R033: Bad break recovery", "Rule passed S3B-R006", "Other rules satisfied: S5B-R008, S8-R004",
             "Hard checks (each one must pass):", "- Liquidity (S4-R047) = PASS"]
    assert for_screen_all(lines) == ["Rule passed: Bad break recovery", "Hard checks (each one must pass):",
                                     "- Liquidity = PASS"]                   # a heading of its own stays
    assert for_screen_all({"id": "S7-R025", "text": "x (S7-R025)"}) == {"id": "S7-R025", "text": "x"}   # ids are code


def test_setup_screener_answers_have_no_rule_codes(client, scan_root):  # noqa: F811
    d = client.get("/scanner/scans/NSE_daily_2026-11-23").json()
    e = client.get("/scanner/scans/NSE_daily_2026-11-23/explain", params=dict(symbol="MARICO", setup="BBR")).json()
    n = client.get("/scanner/scans/NSE_daily_2026-11-23/explain",
                   params=dict(symbol="PRESTIGE", setup="VCP", near="true")).json()
    for answer in (d, e, n):
        bad = [(k, v) for k, v in texts(answer) if CODE.search(v) and k not in ("id", "chart", "chart_href")]
        assert not bad, bad[:3]
