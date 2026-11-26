"""Neutral wording for everything shown on screen: no "buy" / "sell" recommendations (SEBI).

The owner's rulebook, the SwingScanner's files and the generated pattern rules use trading words (would buy, the buy
point, sell into strength, ...). Their files are never edited; their text passes through `neutral()` on its way to the
screen. A signal to enter is a "breakout", a signal to exit a "breakdown"; other uses become entry / exit words.
"""
import re

# whole phrases first (order matters), then single words; each is matched case-insensitively and keeps the case
_PHRASES = [
    (r"would\s+buy", "breakout"),
    (r"\bbuy\s*:", "breakout:"),
    (r"\bsell\s*:", "breakdown:"),
    (r"buy\s+setups", "breakout setups"),
    (r"buy\s+signals", "breakouts"),
    (r"buy\s+signal", "breakout"),
    (r"sell\s+signals", "breakdowns"),
    (r"sell\s+signal", "breakdown"),
    (r"buy\s+(price|point|level|zone|area|stop|date|day|bar|trigger|order)", r"entry \1"),
    (r"sell\s+(price|point|level|zone|order|rules?)", r"exit \1"),
    (r"selling\s+rules?", "exit rules"),
    (r"buy\s+and\s+sell", "entry and exit"),
    (r"buy/sell", "entry/exit"),
    (r"how\s+we\s+would\s+sell", "how the position exits"),
    (r"(not\s+a)\s+buy", r"\1 breakout"),
    (r"(buying|selling)\s+(a|an|the|it|into|on|at|when|after|before|stocks?|shares?)\b", None),   # verb: handled below
    (r"(institutional|heavy|strong|real|smart|big|fund)\s+buying", r"\1 accumulation"),
    (r"(institutional|heavy|strong|real|smart|big|fund)\s+selling", r"\1 distribution"),
    (r"buying\s+pressure", "demand"),
    (r"selling\s+pressure", "supply"),
]
_VERB_BEFORE = (r"(to|not|would|will|we|you|i|they|can|cannot|can't|could|should|then|and|or|never|don't|dont|didn't|"
                r"only|always|must|may|might|did|does|do)")
_WORDS = [
    (rf"\b{_VERB_BEFORE}\s+buy\b", r"\1 enter"),
    (rf"\b{_VERB_BEFORE}\s+sell\b", r"\1 exit"),
    (r"\b(is|are|was|were|be|been|not|keep|keeps|kept|stop|stops|stopped|start|started|without|avoid|avoids)\s+buying\b",
     r"\1 entering"),
    (r"\b(is|are|was|were|be|been|not|keep|keeps|kept|stop|stops|stopped|start|started|without|avoid|avoids)\s+selling\b",
     r"\1 exiting"),
    (r"\bbuying\b", "accumulation"),
    (r"\bselling\b", "distribution"),
    (r"\bbuyers\b", "bulls"),
    (r"\bsellers\b", "bears"),
    (r"\bbuyer\b", "investor"),
    (r"\bseller\b", "holder"),
    (r"\bbuys\b", "entries"),
    (r"\bsells\b", "exits"),
    (r"\bbought\b", "entered"),
    (r"\bsold\b", "exited"),
    (r"\bbuy\b", "entry"),
    (r"\bsell\b", "exit"),
]


def _keep_case(src: str, out: str) -> str:
    if src.isupper() and len(src) > 1:
        return out.upper()
    if src[:1].isupper():
        return out[:1].upper() + out[1:]
    return out


def _sub(pattern: str, repl, text: str) -> str:
    def one(m: re.Match) -> str:
        r = m.expand(repl) if isinstance(repl, str) else repl(m)
        return _keep_case(m.group(0), r)
    return re.sub(pattern, one, text, flags=re.IGNORECASE)


def _verb(m: re.Match) -> str:
    word, rest = m.group(1).lower(), m.group(2)
    return ("entering " if word == "buying" else "exiting ") + rest


def neutral(text: str | None) -> str | None:
    """`text` without buy / sell recommendation words."""
    if not text or not re.search(r"buy|sell|bought|sold", text, re.IGNORECASE):
        return text
    for pat, repl in _PHRASES:
        text = _sub(pat, repl if repl is not None else _verb, text)
    for pat, repl in _WORDS:
        text = _sub(pat, repl, text)
    return text


def neutral_all(obj):
    """neutral() applied to every string inside lists / dicts (keys are left alone)."""
    if isinstance(obj, str):
        return neutral(obj)
    if isinstance(obj, list):
        return [neutral_all(x) for x in obj]
    if isinstance(obj, dict):
        return {k: neutral_all(v) for k, v in obj.items()}
    return obj


_TAG = re.compile(r"(<script\b.*?</script>|<style\b.*?</style>|<[^>]+>)", re.IGNORECASE | re.DOTALL)


def neutral_html(html: str) -> str:
    """neutral() on the visible text of an HTML page; tags, attributes, scripts and styles are left as they are."""
    parts = _TAG.split(html)
    return "".join(p if i % 2 else neutral(p) for i, p in enumerate(parts))
