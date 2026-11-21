"""Baseline redaction, not a guarantee of anonymization; human review is required."""
from html.parser import HTMLParser
import re
from .normalize import normalize_text


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif not self.hidden:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


RULES = [
    ("email", re.compile(r"(?<![A-Z0-9._%+-])[A-Z0-9._%+-]{1,64}@[A-Z0-9.-]{1,253}\.[A-Z]{2,63}(?![A-Z0-9-])", re.I)),
    ("credential", re.compile(r"\b(?:password|passwd|api[_ -]?key|secret|token)\s*[:=]\s*[^\s,;]+", re.I)),
    ("phone", re.compile(r"(?<!\w)(?:\+?\d[\d(). -]{7,}\d)(?!\w)")),
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]


def sanitize(value: str) -> tuple[str, list[str]]:
    parser = PlainText()
    parser.feed(value)
    parser.close()
    text = normalize_text(" ".join(parser.parts))
    kinds = []
    for name, pattern in RULES:
        text, count = pattern.subn(f"[{name.upper()}_REDACTED]", text)
        if count:
            kinds.append(name)
    return text, sorted(kinds)


def csv_safe(value: str) -> str:
    # Quoting does not stop spreadsheet formulas. Check after leading whitespace.
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
