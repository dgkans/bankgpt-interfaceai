"""
Text cleanup and value parsing shared by extraction and question understanding.

The crawled markdown carries literal "\\r\\n" escapes, footnote digits glued to values
("5.39% APR1", "0.15%1") and many spellings of terms, tiers and dates. These pure
functions turn them into comparable values so the same fact always looks the same.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional, Tuple

from .config import NUMBER_WORDS

INF = float("inf")
_ESCAPED_NEWLINE_RE = re.compile(r"(?:\\\\|\\)r(?:\\\\|\\)n")
_FOOTNOTE_RE = re.compile(r"(%|\bAPR|\bAPY)\s*[0-9¹²³]{1,2}(?![0-9.,%])")
_MONEY_RE = re.compile(r"\$\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december"]
_LONG_DATE_RE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\.?\s+(\d{1,2}),?\s+(20\d{2})\b", re.I)
_US_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b")
_ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")


def clean_text(markdown: str) -> str:
    """Normalise crawl artefacts: escaped CR/LF, non-breaking spaces, Windows newlines."""
    text = _ESCAPED_NEWLINE_RE.sub("\n", markdown or "")
    return text.replace("\r\n", "\n").replace(" ", " ")


def strip_footnotes(cell: str) -> str:
    """'5.39% APR1' -> '5.39% APR', '0.15%1' -> '0.15%'. Digits inside values are kept."""
    return _FOOTNOTE_RE.sub(r"\1", cell).strip()


def norm_words(text: str) -> str:
    """Lower-case, unify dashes, drop markdown punctuation; keeps $ % . for values."""
    t = (text or "").lower().replace("–", "-").replace("—", "-").replace("’", "'")
    t = re.sub(r"[*_`#|\\\[\]()]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def tokens(text: str) -> list:
    """Word tokens for matching (letters/digits, with '1st'-style ordinals kept)."""
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", norm_words(text))


_SUFFIXES = ("ization", "ational", "ition", "ation", "izes", "ized", "ize", "ing", "ed")


def stem(w: str) -> str:
    """Small suffix stripper: 'branches' == 'branch', 'recognized' == 'recognition',
    'loans' == 'loan'. Deliberately crude but applied identically to questions and pages."""
    if len(w) <= 3 or w[0].isdigit():
        return w
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith(("ches", "shes", "xes", "sses")):
        w = w[:-2]
    elif w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            w = w[: -len(suf)]
            break
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    return w


def stems(text: str) -> list:
    return [stem(w) for w in tokens(text)]


def parse_money(text: str) -> Optional[float]:
    m = _MONEY_RE.search(text or "")
    if not m:
        return None
    return float(m.group(1).replace(",", "") + ("." + m.group(2) if m.group(2) else ""))


def parse_percent(text: str) -> Optional[float]:
    m = _PERCENT_RE.search(text or "")
    return float(m.group(1)) if m else None


def amount_range(label: str) -> Optional[Tuple[float, float]]:
    """Balance / loan-amount tier label -> (low, high). None when the label has no money."""
    t = (label or "").replace("–", "-").replace("—", "-")
    nums = [float((a or b).replace(",", "") + ("." + c if c else ""))
            for a, b, c in re.findall(
                r"(?:\$\s*(\d{1,3}(?:,\d{3})+|\d+)|\b(\d{1,3}(?:,\d{3})+|\d{4,}))(?:\.(\d+))?", t)]
    if "$" not in t or not nums:
        return None
    if re.search(r"or less|and under|up to|less than", t, re.I):
        return (0.0, nums[0])
    if "+" in t or re.search(r"and (?:up|over|above)|or more", t, re.I):
        return (nums[0], INF)
    if len(nums) >= 2:
        return (nums[0], nums[1])
    return (nums[0], nums[0])


def model_year_range(label: str) -> Optional[Tuple[int, int]]:
    """'2024-27 Model Year' -> (2024, 2027); 'Model Year 2026-23' -> (2023, 2026);
    '2016 Model Year (and older)' -> (0, 2016)."""
    t = (label or "").replace("–", "-")
    if not re.search(r"model year", t, re.I):
        return None
    m = re.search(r"\b(19|20)(\d{2})\s*-\s*(\d{2,4})\b", t)
    if m:
        a = int(m.group(1) + m.group(2))
        b_raw = m.group(3)
        b = int(b_raw) if len(b_raw) == 4 else int(m.group(1) + b_raw)
        return (min(a, b), max(a, b))
    m = re.search(r"\b((?:19|20)\d{2})\b", t)
    if not m:
        return None
    y = int(m.group(1))
    if re.search(r"older|prior|before", t, re.I):
        return (0, y)
    if re.search(r"newer|later", t, re.I):
        return (y, 9999)
    return (y, y)


def words_to_numbers(text: str) -> str:
    """'six month' -> '6 month', 'five-year' -> '5-year'."""
    def repl(m):
        return str(NUMBER_WORDS[m.group(1).lower()])
    return re.sub(r"\b(" + "|".join(NUMBER_WORDS) + r")\b(?=[\s-]*(?:month|year|yr|mo)\b)", repl, text, flags=re.I)


def term_months(text: str) -> Optional[int]:
    """First loan/certificate term in the text, in months ('30-Year' -> 360, '60 Months' -> 60)."""
    t = words_to_numbers((text or "").lower())
    m = re.search(r"\b(\d{1,3})\s*-?\s*(months?|mos?|years?|yrs?)\b", t)
    if not m:
        return None
    n = int(m.group(1))
    return n * 12 if m.group(2).startswith("y") else n



def parse_date(text: str) -> Optional[str]:
    """First date in the text as ISO 'YYYY-MM-DD' (long, US or ISO form)."""
    best = None
    for rx, kind in ((_LONG_DATE_RE, "long"), (_US_DATE_RE, "us"), (_ISO_DATE_RE, "iso")):
        m = rx.search(text or "")
        if not m:
            continue
        try:
            if kind == "long":
                d = date(int(m.group(3)), _MONTHS.index(m.group(1).lower()) + 1, int(m.group(2)))
            elif kind == "us":
                d = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            else:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if best is None or m.start() < best[0]:
            best = (m.start(), d.isoformat())
    return best[1] if best else None


def all_dates(text: str) -> list:
    """Every long-form date in the text as (iso, matched_text)."""
    out = []
    for m in _LONG_DATE_RE.finditer(text or ""):
        try:
            d = date(int(m.group(3)), _MONTHS.index(m.group(1).lower()) + 1, int(m.group(2)))
        except ValueError:
            continue
        out.append((d.isoformat(), m.group(0)))
    return out


def month_name(n: int) -> str:
    return _MONTHS[n - 1].capitalize()
