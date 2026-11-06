"""
Question slots -> scored table rows (which fact is being asked about).

Scoring is lexical (IDF-weighted overlap between question words and the row's headings
and labels) plus hard qualifier constraints: a 60-month question never matches a
48-month row, a 2025 model year only matches a model-year tier that contains 2025, a
$15,000 balance only matches the balance tier that contains it.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from . import config
from .facts import RowFact
from .normalize import stem, stems
from .understand import Query


_QUALIFIERS = {stem(w) for w in config.QUALIFIER_WORDS}
_SOFT = {stem(w) for w in config.SOFT_QUALIFIERS}


@dataclass(frozen=True)
class Scored:
    """A candidate row with its match score and a short trace of why."""
    score: float
    fact: RowFact
    why: str


def build_idf(facts: Iterable[RowFact]) -> Dict[str, float]:
    """Word rarity over all rows of a snapshot: rare product words count more."""
    df, n = Counter(), 0
    for f in facts:
        n += 1
        df.update(f.words)
    return {w: math.log(1 + n / c) for w, c in df.items()}


def _row_words(f: RowFact) -> set:
    """Words that describe the row itself (caption + label), not the page section."""
    return set(stems(f"{f.caption} {f.label}"))


def _constraint_bonus(f: RowFact, q: Query) -> Optional[float]:
    """None = the row contradicts an explicit qualifier in the question."""
    bonus = 0.0
    if q.term is not None:
        if f.term is None:
            bonus -= 1.0
        elif f.term != q.term:
            return None
        else:
            bonus += 2.0
    if q.model_year is not None and f.model_years is not None:
        lo, hi = f.model_years
        if not lo <= q.model_year <= hi:
            return None
        bonus += 1.5
    if q.amount is not None and f.amount is not None:
        lo, hi = f.amount
        if not lo <= q.amount <= hi + 0.01:
            return None
        width = (hi - lo) if hi != float("inf") else 1e9
        bonus += 1.5 + 0.5 / (1 + math.log10(1 + width))   # tightest containing tier wins
    if q.rate_kind and q.rate_kind != "rate" and f.value(q.rate_kind) is None:
        bonus -= 0.75
    return bonus


def _qualifier_penalty(f: RowFact, q: Query) -> float:
    """Penalise variants the member did not ask for (jumbo, intro, Roth, refinance...)."""
    qwords = set(q.words)
    penalty = 0.0
    for w in _row_words(f) & _QUALIFIERS:
        if w in qwords or (w == "intro" and "introductory" in qwords):
            continue
        penalty += config.SOFT_QUALIFIER_PENALTY if w in _SOFT else config.QUALIFIER_PENALTY
    # "What credit cards do you offer?" wants every variant, so variants are barely penalised.
    return penalty * (config.LIST_QUALIFIER_FACTOR if q.shape == "list" else 1.0)


def _segment_penalty(f: RowFact, q: Query) -> float:
    """Personal pages first unless the question says business (and vice versa)."""
    if q.segment == "business":
        return 0.0 if f.page.segment == "business" else 2.0
    return 1.5 if f.page.segment == "business" else 0.0


def score_row(f: RowFact, q: Query, idf: Dict[str, float]) -> Optional[Scored]:
    """Match score of one row for the question; None if a hard constraint rules it out."""
    qwords = set(q.words)
    overlap = qwords & f.words
    if not overlap:
        return None
    lexical = sum(idf.get(w, 0.0) for w in overlap)
    # Words matched in the row's own caption/label count extra: they name the product.
    lexical += 0.5 * sum(idf.get(w, 0.0) for w in overlap & _row_words(f))
    bonus = _constraint_bonus(f, q)
    if bonus is None:
        return None
    score = lexical + bonus - _qualifier_penalty(f, q) - _segment_penalty(f, q)
    return Scored(score=score, fact=f, why=f"words={sorted(overlap)} bonus={bonus:+.2f}")


def rank(facts: List[RowFact], q: Query, idf: Dict[str, float]) -> List[Scored]:
    """All matching rows, best first. Ties are broken by tier and URL so results are stable."""
    out = [s for s in (score_row(f, q, idf) for f in facts) if s is not None]
    out.sort(key=lambda s: (-s.score, s.fact.page.tier, s.fact.page.url, s.fact.table_index, s.fact.row_index))
    return out
