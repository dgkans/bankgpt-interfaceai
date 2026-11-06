"""
Fixed answer templates.

Answers are rendered only from the resolved facts, with one template per shape, so two
wordings of a question that resolve to the same fact produce byte-identical text.
Stale or competing values never appear in `text`; they go to `conflict_note`.
"""
from __future__ import annotations

import re
from typing import List, Optional

from . import config
from .facts import RowFact, Value
from .normalize import norm_words

_RATE_KINDS = ("rate", "apr", "dividend", "apy")
_SUFFIX = {"apy": "APY", "apr": "APR", "dividend": "dividend rate", "rate": "interest rate"}


def refusal_text() -> str:
    return config.REFUSAL_TEXT


def value_phrase(v: Value) -> str:
    suffix = _SUFFIX.get(v.kind)
    if not suffix or suffix.split()[0].upper() in v.text.upper():
        return v.text
    return f"{v.text} {suffix}"


def values_for(f: RowFact, rate_kind: Optional[str]) -> List[Value]:
    """The values worth stating for a row: the requested kind, else every rate-like column."""
    if rate_kind and rate_kind != "rate" and f.value(rate_kind):
        return [f.value(rate_kind)]
    if rate_kind == "rate" and f.value("rate"):
        return [v for v in f.values if v.kind in ("rate", "apr")]
    picked = [v for v in f.values if v.kind in _RATE_KINDS]
    return picked or [v for v in f.values if v.kind == "fee"] or list(f.values[:1])


def short_label(f: RowFact) -> str:
    """Row label without a repeated caption: 'Share Savings | $25,000+' -> '$25,000+'."""
    parts = [p for p in f.label.split(" | ") if norm_words(p) != norm_words(f.caption)]
    return ", ".join(parts) or f.caption


def row_phrase(f: RowFact, rate_kind: Optional[str]) -> str:
    vals = " / ".join(value_phrase(v) for v in values_for(f, rate_kind))
    label = short_label(f)
    return vals if norm_words(label) == norm_words(_title(f)) else f"{label}: {vals}"


def _title(f: RowFact) -> str:
    cap = f.caption or f.context or f.page.title
    return re.sub(r"\s+", " ", cap).strip()


def single(f: RowFact, rate_kind: Optional[str]) -> str:
    label = short_label(f)
    title = _title(f)
    name = label if norm_words(title) in norm_words(label) else f"{title} ({label})"
    vals = " / ".join(value_phrase(v) for v in values_for(f, rate_kind))
    return f"{name}: {vals}."


def table_list(rows: List[RowFact], rate_kind: Optional[str]) -> str:
    """Rows grouped by their table caption, in site order."""
    groups: List[tuple] = []
    for f in rows:
        if not groups or groups[-1][0] != f.table_key:
            groups.append((f.table_key, _title(f), []))
        groups[-1][2].append(row_phrase(f, rate_kind))
    return " ".join(f"{title}: {'; '.join(lines)}." for _, title, lines in groups)


def extreme(f: RowFact, kind_word: str, rate_kind: Optional[str]) -> str:
    return f"The {kind_word} {_title(f)} rate is {single(f, rate_kind)}"


def yes_no(found: Optional[RowFact], best: RowFact, rate_kind: Optional[str]) -> str:
    if found is not None:
        return f"Yes. {single(found, rate_kind)}"
    return f"No. The highest {_title(best)} tier is {single(best, rate_kind)}"
