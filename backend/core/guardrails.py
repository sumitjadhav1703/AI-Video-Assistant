"""Redact common sensitive values before text reaches storage or models."""
import re
from langchain.agents.middleware.pii import detect_email, detect_credit_card


class GuardrailError(Exception):
    pass


_EMAIL = re.compile(r'\b[A-Z0-9._%+-]+@\s*[A-Z0-9.-]+\.[A-Z]{2,}\b', re.I)
_CREDENTIAL = re.compile(r'''\b(?:api[_-]?key|password|passwd|secret|access[_-]?token|authorization)["']?\s*[:=]\s*(?:"(?P<double>[^"\r\n]*)"|'(?P<single>[^'\r\n]*)'|(?P<bare>(?:(?:Bearer|Basic)\s+)?[^\s"',;]+))''', re.I)
_PHONE = re.compile(r'(?<!\w)(?:\+\d{1,3}[ -]?)?(?:\(?\d{2,4}\)?[ -])?\d{3,5}[ -]\d{4,6}(?!\w)|(?<!\w)\+\d{10,15}(?!\w)')
_CARD = re.compile(r'(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)')


def _luhn(value):
    digits = [int(c) for c in value if c.isdigit()]
    return 13 <= len(digits) <= 19 and sum((d * 2 - 9 if d * 2 > 9 else d * 2) if i % 2 else d for i, d in enumerate(reversed(digits))) % 10 == 0


def sanitize_text(text: str) -> str:
    if not isinstance(text, str):
        raise GuardrailError('Expected text.')
    spans = [(m['start'], m['end']) for m in detect_email(text) + detect_credit_card(text)]
    spans += [m.span() for m in _EMAIL.finditer(text)]
    spans += [m.span(m.lastgroup) for m in _CREDENTIAL.finditer(text)]
    spans += [m.span() for m in re.finditer(r'\b(?:sk-(?:proj-)?|ghp_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{16,}\b', text)]
    spans += [m.span() for m in _CARD.finditer(text) if _luhn(m.group())]
    spans += [m.span() for m in _PHONE.finditer(text) if len(re.sub(r'\D', '', m.group())) >= 10]
    spans += [m.span() for m in re.finditer(r'(?<![\w\d])[6-9]\d{9}(?![\w\d])', text)]
    chars = list(text)
    for start, end in spans:
        chars[start:end] = '█' * (end - start)
    return ''.join(chars)
