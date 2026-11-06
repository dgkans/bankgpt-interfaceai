"""
Curated list of real contradictions on the site.

A conflict is reported only when, inside one snapshot, two pages state different values
for the *same* fact: same product, term, model-year/balance tier, rate type and segment.
The authoritative row (rate sheet / product page) is matched against every other row
with the same machinery used to answer questions; tiers of one table are never compared.
Findings for the same fact across snapshots are merged into one Conflict, resolved to
the value the newest snapshot's winning page states. Precision matters more than recall.
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, List, Tuple

from . import entities
from .contract_types import Conflict, Source
from .facts import RowFact
from .match import build_idf, rank
from .config import QUALIFIER_WORDS
from .normalize import norm_words, stem, stems
from .resolve import authority_order
from .understand import Query

_RATE_KINDS = ("apy", "apr", "rate", "dividend")
_MIN_SAME_FACT = 0.6           # other row must match the winner's own description this well


def _self_query(f: RowFact) -> Query:
    """Describe a row as if a member asked for it (product words + its qualifiers)."""
    words = tuple(w for w in stems(f"{f.caption} {f.label}") if not w[0].isdigit())
    my = f.model_years[0] if f.model_years else None
    amount = f.amount[0] if f.amount else None
    return Query(raw=f.label, text=f"{f.caption} {f.label}".lower(), words=words, rate_kind=None,
                 term=f.term, model_year=my, amount=amount,
                 segment="business" if f.page.segment == "business" else None, superlative=None,
                 shape="single", asks_rate=True, value_in_q=None, as_of=None)


def _same_fact(win: RowFact, other: RowFact) -> bool:
    """True when `other` states the same fact as `win`: same segment, same term, identical
    balance tier, overlapping model years, same qualifiers and similar product names."""
    if other.page.url == win.page.url or other.page.segment != win.page.segment:
        return False
    if (win.term is None) != (other.term is None) or (win.amount is None) != (other.amount is None):
        return False
    if win.amount and other.amount and (abs(win.amount[0] - other.amount[0]) > 1 or
                                        abs(min(win.amount[1], 1e12) - min(other.amount[1], 1e12)) > 1):
        return False                       # different balance / loan-amount tier
    a_words = _product_words(win)
    b_words = _product_words(other)
    if other.ends_on:                      # a dated offer restating the product: compare labels only
        a_words = _product_words(win, label_only=True)
        b_words = _product_words(other, label_only=True) - _OFFER_WORDS
        return bool(a_words) and a_words <= b_words
    if not a_words or len(a_words & b_words) / len(a_words | b_words) < 0.5:
        return False
    if (a_words & _QUALIFIERS) != (b_words & _QUALIFIERS):
        return False                       # jumbo vs regular, Roth vs Traditional, intro vs standard
    if win.model_years and other.model_years:
        a, b = win.model_years, other.model_years
        if a[1] < b[0] or b[1] < a[0]:
            return False
    return True


_QUALIFIERS = {stem(w) for w in QUALIFIER_WORDS} - {"fixed", "standard", "purchase", "variable"}
_GENERIC = {"rate", "rat", "loan", "account", "the", "and", "month", "year", "model", "tier", "balance", "&"}


_OFFER_WORDS = {stem(w) for w in ("special", "summer", "winter", "spring", "fall", "promo", "offer", "limited")}


def _product_words(f: RowFact, label_only: bool = False) -> set:
    """Product-naming words of a row (numbers and generic words removed)."""
    text = f.label if label_only else f"{f.caption} {f.label}"
    return {w for w in stems(text) if not w[0].isdigit() and w not in _GENERIC}


def _topic(f: RowFact, kind: str) -> str:
    """Plain-words topic, e.g. '60-month Auto & Motorcycle Loans 2024-27 Model Year | 60 Months APR'."""
    term = f"{f.term}-month " if f.term else ""
    label = f.label if f.caption.lower() in f.label.lower() else f"{f.caption} {f.label}"
    topic = f"{term}{label} {kind.upper() if kind in ('apy', 'apr') else kind}".strip()
    if {"home", "loan"} <= set(stems(f.caption)):
        topic += " (mortgage)"
    return topic


def _table_conflicts(view, idf) -> List[Tuple[RowFact, RowFact, str]]:
    """(winner row, losing row, value kind) for one snapshot. A row reports only if it is
    the most authoritative copy of its fact, so every fact is reported once."""
    out = []
    winners = [f for f in view.facts if f.page.tier == 1 and any(f.value(k) for k in _RATE_KINDS)]
    for win in winners:
        q = _self_query(win)
        ranked = rank(view.facts, q, idf)
        own = next((s.score for s in ranked if s.fact is win), None)
        if not own or own <= 0:
            continue
        group = [s.fact for s in ranked if s.score >= own * _MIN_SAME_FACT and _same_fact(win, s.fact)]
        canonical = frozenset(f.detail_url.rstrip("/").lower() for f in group + [win] if f.detail_url)

        def rank_of(f: RowFact) -> tuple:
            return authority_order(f.page, f.effective_date, canonical)
        if any(rank_of(f) < rank_of(win) for f in group):
            continue
        for other in group:
            for kind in _RATE_KINDS:
                a, b = win.value(kind), other.value(kind)
                if a and b and a.number is not None and b.number is not None and a.number != b.number:
                    out.append((win, other, kind))
                    break
    return out


def _stat_conflicts(view) -> List[Conflict]:
    """Branch count: press-release boilerplates disagree; the newest dated one wins."""
    facts = [e for e in view.entities if e.kind == "stat:branches"]
    counts = Counter(e.value for e in facts)
    best = entities.best(facts)
    if len(counts) < 2 or best is None:
        return []
    values = sorted(counts, key=int)
    srcs = [Source(url=entities.best([e for e in facts if e.value == v]).page.url, snapshot_id=view.snapshot_id,
                   quote=f"{v} branch office locations") for v in values]
    return [Conflict(topic="number of branch office locations (branch count)",
                     values=[f"{v} branches" for v in values], sources=srcs[:4],
                     resolution=f"{best.value} branches",
                     reason=f"most recently dated press release ({best.page.page_date}) states {best.value}; "
                            "older releases repeat older boilerplate")]


def _key(win: RowFact, kind: str) -> str:
    """Fact identity that ignores formatting ('$100,000' == '$100000', '-' == '\u2013')."""
    label = norm_words(win.label).replace(",", "").replace(" ", "")
    return f"{win.page.segment}|{norm_words(win.caption)}|{label}|{kind}"


def _strip_unit(text: str) -> str:
    return text.replace(" APR", "").replace(" APY", "").strip()


def _ordinal_conflicts(view) -> List[Conflict]:
    """'the fourth time Forbes recognized Dupaco' vs 'the fifth time': newest release wins."""
    facts = [e for e in view.entities if e.kind.startswith("ordinal:")]
    out = []
    for kind in sorted({e.kind for e in facts}):
        group = [e for e in facts if e.kind == kind]
        values = sorted({e.value for e in group})
        best = entities.best(group)
        if len(values) < 2 or best is None:
            continue
        who = kind.split(":", 1)[1]
        out.append(Conflict(
            topic=f"number of times {who} recognized Dupaco ({who} recognition count)",
            values=values, sources=[Source(url=e.page.url, snapshot_id=view.snapshot_id, quote=e.quote)
                                    for e in sorted(group, key=lambda e: e.page.url)][:4],
            resolution=best.value,
            reason=f"newest release ({best.page.page_date}) says {best.value}; older releases give older counts"))
    return out


def find(store) -> List[Conflict]:
    """One Conflict per fact. Only contradictions still visible in the newest snapshot are reported: an old copy
    that was later fixed is history, not a current contradiction."""
    if not store.snapshots:
        return []
    view = store.snapshots[-1]
    found: Dict[str, Conflict] = {}
    for win, other, kind in _table_conflicts(view, build_idf(view.facts)):
        key = _key(win, kind)
        c = found.get(key)
        if c is None:
            c = found[key] = Conflict(
                topic=_topic(win, kind), values=[_strip_unit(win.value(kind).text)],
                sources=[_source(win, kind, view)], resolution=_strip_unit(win.value(kind).text),
                reason=_reason(win, other, view))
        v = _strip_unit(other.value(kind).text)
        if v not in c.values:
            c.values.append(v)
            if len(c.sources) < 4:
                c.sources.append(_source(other, kind, view))
    out = [found[k] for k in sorted(found)]
    return out + _stat_conflicts(view) + _ordinal_conflicts(view)


def _source(f: RowFact, kind: str, view) -> Source:
    return Source(url=f.page.url, snapshot_id=view.snapshot_id, quote=f"{f.caption}: {f.label} = {f.value(kind).text}")


def _reason(win: RowFact, other: RowFact, view) -> str:
    """Human-readable explanation of why the winner's value was chosen."""
    return (f"{win.page.kind} page {win.page.url} (tier {win.page.tier}"
            f"{', effective ' + win.effective_date if win.effective_date else ''}) outranks "
            f"{other.page.kind} page {other.page.url} (tier {other.page.tier}"
            f"{', effective ' + other.effective_date if other.effective_date else ''}) in {view.snapshot_id}")
