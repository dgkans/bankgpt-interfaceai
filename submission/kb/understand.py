"""
Question -> structured intent (slots + answer shape).

Normalises wording (CD -> certificate, "six month" -> 6-month, mortgage -> home loan),
then pulls out the slots that make a fact distinct: term, model year, balance/loan
amount, rate type, segment, superlatives, an embedded date and the expected shape.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from typing import Optional, Tuple

from . import config
from .normalize import month_name, parse_money, parse_percent, stem, term_months, tokens, words_to_numbers

_MONTHS = [month_name(i).lower() for i in range(1, 13)]
_MONTH_YEAR_RE = re.compile(r"\b(?:as of|in|during|on|by|for|around|back in|at the end of)?\s*(" +
                            "|".join(_MONTHS) + r")\.?\s+(?:(\d{1,2}),?\s+)?(20\d{2})\b", re.I)
_ISO_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_RATE_WORD_RE = re.compile(r"\b(rates?|apys?|aprs?|dividends?|interest|yield|percent)\b|%")


@dataclass(frozen=True)
class Query:
    """The parsed question. Everything downstream works from these slots."""
    raw: str
    text: str                       # normalised question
    words: Tuple[str, ...]          # content words (stopwords removed), in order
    rate_kind: Optional[str]        # apy / dividend / apr / rate (explicit only)
    term: Optional[int]             # months
    model_year: Optional[int]
    amount: Optional[float]
    segment: Optional[str]          # "business" when asked about business products
    superlative: Optional[str]      # "max" / "min"
    shape: str                      # single / list / yesno / link / count / hours / address / when / general
    asks_rate: bool
    value_in_q: Optional[float]     # a percentage stated in the question ("pay 0.35%?")
    as_of: Optional[str]            # date stated inside the question, ISO


def normalise(question: str) -> str:
    """Lower-case and apply synonyms so rewordings become the same text."""
    t = words_to_numbers(question.lower().replace("’", "'"))
    t = t.replace("–", "-").replace("—", "-")
    for pattern, repl in config.SYNONYMS:
        t = re.sub(pattern, repl, t)
    t = re.sub(r"\b(\d+)\s*-?\s*(month|year)s?\b", r"\1-\2", t)
    return re.sub(r"\s+", " ", t).strip()


def date_in_question(question: str) -> Optional[str]:
    """'as of May 2026' -> '2026-05-31' (end of that month); explicit days are kept."""
    m = _ISO_RE.search(question)
    if m:
        return m.group(0)
    m = _MONTH_YEAR_RE.search(question)
    if not m:
        return None
    month = _MONTHS.index(m.group(1).lower()) + 1
    year = int(m.group(3))
    day = int(m.group(2)) if m.group(2) else calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-{day:02d}"


def _rate_kind(t: str) -> Optional[str]:
    if re.search(r"\bdividend\b", t):
        return "dividend"
    if re.search(r"\bapy\b", t):
        return "apy"
    if re.search(r"\bapr\b", t):
        return "apr"
    if re.search(r"\binterest rate\b|\bnote rate\b", t):
        return "rate"
    return None


def _model_year(t: str) -> Optional[int]:
    """A vehicle model year in the question ('2025 model-year', 'a 2024 car')."""
    m = re.search(r"\b(19[89]\d|20[0-3]\d)\b(?=[^.?]*\b(model|auto|motorcycle|atv|snowmobile)\b)", t) or \
        re.search(r"\b(?:model[- ]year|my)\s*(19[89]\d|20[0-3]\d)\b", t)
    if m and re.search(r"model|auto|motorcycle|atv|snowmobile|jet ski", t):
        return int(m.group(1))
    return None


def _amount(t: str) -> Optional[float]:
    """Balance / loan amount in the question ('$15,000', '15k', 'between $10,000 and ...')."""
    m = re.search(r"\$\s*\d[\d,]*(?:\.\d+)?\s*(k|thousand|million)?", t)
    if m:
        val = parse_money(m.group(0))
        if m.group(1) in ("k", "thousand"):
            val *= 1000
        elif m.group(1) == "million":
            val *= 1_000_000
        return val
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(k|thousand)\b", t)
    return float(m.group(1)) * 1000 if m else None


def _shape(t: str, raw: str) -> str:
    """What kind of answer is expected (decides the answering path). Order matters:
    the first matching shape wins."""
    if re.search(r"\b(link|url|web ?address|web ?page|website for|webpage|locator)\b", t):
        return "link"
    if re.search(r"\bhow many\b|\bnumber of\b(?! the routing)", t):
        return "count"
    if re.search(r"\bhours?\b|\bwhat time\b|\bopen on\b", t) or \
            re.search(r"\b(lobb(?:y|ies)|drive[- ]?(?:up|thru|through))\b.*\b(open|close)\b", t):
        return "hours"
    if re.search(r"\baddress\b|\bwhere is\b|\blocated\b", t):
        return "address"
    if re.search(r"\bwhen (?:does|did|will|is)\b|\bstill open\b|\bclos(?:e|ing|ed)\b", t):
        return "when"
    if re.search(r"^(do|does|is|are|can|will)\b", t) and parse_percent(t) is not None:
        return "yesno"
    if re.search(r"\brates\b|\baprs\b|\bapys\b|\ball\b|\blist\b|\boptions\b|\bwhat .* offer\b|\bwhat are\b|"
                 r"\bkinds?\b|\btypes?\b", t):
        return "list"
    return "single"


def _superlative(t: str) -> Optional[str]:
    if re.search(r"\b(highest|best|top|most|maximum|max)\b", t):
        return "max"
    if re.search(r"\b(lowest|cheapest|least|minimum|min)\b", t):
        return "min"
    return None


def parse(question: str) -> Query:
    """Question -> Query (pure function, so the same question always gives the same slots)."""
    t = normalise(question)
    words = tuple(stem(w) for w in tokens(t) if w not in config.STOPWORDS and not re.fullmatch(r"\d+", w))
    segment = "business" if re.search(r"\bbusiness\b|\bcommercial\b", t) else None
    value = parse_percent(t)
    term = term_months(t)
    shape = _shape(t, question)
    return Query(
        raw=question, text=t, words=words, rate_kind=_rate_kind(t), term=term,
        model_year=_model_year(t), amount=_amount(t), segment=segment,
        superlative=_superlative(t), shape=shape, asks_rate=bool(_RATE_WORD_RE.search(t)),
        value_in_q=value, as_of=date_in_question(question),
    )
