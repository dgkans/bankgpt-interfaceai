"""
Structured answering: rate / fee questions answered from resolved table facts.

Flow: rank rows for the question (match.py) -> pick the current copy (resolve.py) ->
apply the answer shape (single value, tier list, highest/lowest, yes/no) -> render
with a fixed template and cite the winning page first.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from . import config, render
from .facts import RowFact
from .match import rank
from .resolve import Resolution, choose, primary_value
from .store import SnapshotView
from .normalize import stem, stems
from .understand import Query


@dataclass
class StructuredAnswer:
    """Text plus the rows it was rendered from (for sources) and the conflict note."""
    text: str
    rows: List[RowFact]
    resolution: Resolution
    note: Optional[str]


def _extreme_row(rows: List[RowFact], q: Query) -> RowFact:
    def key(f: RowFact):
        v = primary_value(f, q.rate_kind)
        return (v.number if v and v.number is not None else float("-inf"))
    ordered = sorted(rows, key=lambda f: (key(f), -f.row_index))
    return ordered[-1] if q.superlative == "max" else ordered[0]


def _business_extras(view: SnapshotView, q: Query, idf, rows: List[RowFact]) -> List[RowFact]:
    """'Which credit cards do you offer?' with no segment: add business-only products
    (different caption) so the list is complete; same-name business copies are skipped."""
    if q.segment or q.shape != "list":
        return []
    bq = Query(**{**q.__dict__, "segment": "business"})
    res = choose(rank([f for f in view.facts if f.page.segment == "business"], bq, idf), view.taken_on)
    if not res:
        return []
    have = {r.caption.lower() for r in rows}
    return [r for r in res.rows if r.caption.lower() not in have and "business" in r.caption.lower()]


def answer(view: SnapshotView, q: Query, idf: Dict[str, float]) -> Optional[StructuredAnswer]:
    """Answer a rate/fee question from table facts, or None to let the caller decline."""
    res = choose(rank(view.facts, q, idf), view.taken_on, q.rate_kind)
    if res is None:
        return None
    rows = res.rows
    if q.shape == "yesno" and q.value_in_q is not None:
        found = next((f for f in rows for v in f.values
                      if v.number is not None and abs(v.number - q.value_in_q) < 1e-9), None)
        lead = [f for f in rows if f.table_key == rows[0].table_key]
        q2 = Query(**{**q.__dict__, "superlative": "max"})
        text = render.yes_no(found, _extreme_row(lead, q2), q.rate_kind)
        rows = [found] if found else [_extreme_row(lead, q2)]
    elif q.superlative and len(rows) > 1:
        lead = [f for f in rows if f.table_key == rows[0].table_key]
        best = _extreme_row(lead, q)
        rows = [best]
        text = render.extreme(best, "highest" if q.superlative == "max" else "lowest", q.rate_kind)
    elif len(rows) == 1:
        text = render.single(rows[0], q.rate_kind)
    else:
        rows = rows + _business_extras(view, q, idf, rows)
        text = render.table_list(rows[: config.MAX_LIST_ROWS], q.rate_kind)
    note = None
    if res.dropped:
        parts = [f"{render.value_phrase(primary_value(f, q.rate_kind))} on {f.page.url} ({why})"
                 for f, why in res.dropped[:3]]
        note = "Other pages disagree and were not used: " + "; ".join(parts)
    return StructuredAnswer(text=text, rows=rows, resolution=res, note=note)


def unpublished_variant(q: Query, rows: List[RowFact]) -> bool:
    """True when the question names a product variant none of the chosen rows carry,
    e.g. '7/1 adjustable-rate mortgage' matched to fixed-rate rows."""
    asked = set(q.words) & {stem(w) for w in config.PRODUCT_VARIANT_TERMS}
    if not asked:
        return False
    have = set()
    for f in rows:
        have |= f.words | set(stems(f.page.title))
    return bool(asked - have)
