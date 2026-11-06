"""
Choose the current value among competing copies of the same fact.

Rules (each a small named function so any decision can be explained):
  1. drop_expired        - offers whose stated end date is before the snapshot date
  2. authority_order     - higher authority tier wins (rate sheet / product page first)
  3. recency_order       - within a tier, the latest in-page effective date, then crawl time
  4. tiers_are_not_conflicts - rows of one table (balance / term / model-year tiers) are
                           separate facts, so they are rendered together, never compared
Every losing value is kept with its reason for conflict_note and conflicts().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import config
from .facts import PageVersion, RowFact
from .match import Scored

_KIND_PREFERENCE = {"product": 0, "rate_sheet": 1, "reference": 2, "disclosure": 2, "home": 3}
_RATE_KINDS = ("apy", "apr", "rate", "dividend")


@dataclass
class Resolution:
    """The rows to answer from, the winning page, the rule applied and the losing values."""
    rows: List[RowFact]
    page: PageVersion
    rule: str
    dropped: List[Tuple[RowFact, str]] = field(default_factory=list)


def drop_expired(cands: List[Scored], taken_on: str) -> Tuple[List[Scored], List[Tuple[RowFact, str]]]:
    """Rule 1: an offer that says it ended before this snapshot is not current."""
    keep, dropped = [], []
    for s in cands:
        if s.fact.ends_on and s.fact.ends_on < taken_on:
            dropped.append((s.fact, f"offer ended {s.fact.ends_on}"))
        else:
            keep.append(s)
    return keep, dropped


def _neg_date(d: Optional[str]) -> str:
    """Sort key that puts later ISO dates first (missing dates last)."""
    if not d:
        return "~"
    return "".join(chr(ord("9") - ord(c) + ord("0")) if c.isdigit() else c for c in d)


def authority_order(page: PageVersion, eff: Optional[str], canonical: frozenset = frozenset()) -> tuple:
    """Rules 2+3: tier, then latest effective date, then the product's canonical page (the
    one the rate tables link to as "See details"), then product page before rate sheet,
    then newest crawl copy; URL last only to keep the order stable."""
    return (page.tier, _neg_date(eff), 0 if _norm_url(page.url) in canonical else 1,
            _KIND_PREFERENCE.get(page.kind, 4), _neg_date(page.fetched_at[:10]), page.url)


def _norm_url(u: str) -> str:
    return u.split("#")[0].rstrip("/").lower()


def primary_value(f: RowFact, kind: Optional[str] = None):
    """The value that represents a row: the requested kind, else APY/APR/rate/dividend."""
    if kind:
        v = f.value(kind)
        if v:
            return v
    for k in _RATE_KINDS:
        v = f.value(k)
        if v:
            return v
    return f.values[0] if f.values else None


def choose(ranked: List[Scored], taken_on: str, rate_kind: Optional[str] = None) -> Optional[Resolution]:
    """Pick the winning page for the best-matching fact, then that page's matching rows.

    Lexical score only decides *which fact* is asked about; among pages that state that
    fact about equally well (score within PAGE_SCORE_RATIO of the best), authority and
    recency decide which copy is current."""
    if not ranked or ranked[0].score < config.MIN_TABLE_SCORE:
        return None
    ranked, dropped = drop_expired(ranked, taken_on)
    if not ranked:
        return None
    top = ranked[0].score
    by_page: Dict[str, List[Scored]] = {}
    for s in ranked:
        by_page.setdefault(s.fact.page.url, []).append(s)
    eligible = [ss for ss in by_page.values() if ss[0].score >= top * config.PAGE_SCORE_RATIO]
    canonical = frozenset(_norm_url(s.fact.detail_url) for ss in eligible for s in ss[:3] if s.fact.detail_url)
    order = sorted(eligible, key=lambda ss: authority_order(ss[0].fact.page, _page_effective(ss), canonical))
    winner = order[0]
    best = winner[0].score
    rows = tiers_are_not_conflicts([s for s in winner if s.score >= best - config.TABLE_TIE_EPSILON])
    rule = (f"tier {winner[0].fact.page.tier} {winner[0].fact.page.kind} page"
            f"{', effective ' + rows[0].effective_date if rows[0].effective_date else ''}")
    dropped += _losers(rows, order[1:], rate_kind)
    return Resolution(rows=rows, page=winner[0].fact.page, rule=rule, dropped=dropped)


def _page_effective(scored: List[Scored]) -> Optional[str]:
    """Effective date of the page's best-matching row (the copy being compared)."""
    return scored[0].fact.effective_date


def tiers_are_not_conflicts(scored: List[Scored]) -> List[RowFact]:
    """Rule 4: rows of the same table that tie are tiers of one product: keep them all,
    in the order the site prints them."""
    rows = sorted({id(s.fact): s.fact for s in scored}.values(), key=lambda f: (f.table_index, f.row_index))
    return rows[: config.MAX_LIST_ROWS]


def _losers(rows: List[RowFact], others: List[List[Scored]], rate_kind: Optional[str]) -> List[Tuple[RowFact, str]]:
    """Values from lower-ranked pages that differ from the winner's (stale copies)."""
    if len(rows) != 1:
        return []
    win = primary_value(rows[0], rate_kind)
    out = []
    for group in others:
        f = group[0].fact
        v = primary_value(f, win.kind if win else rate_kind)
        if win and v and v.number is not None and v.number != win.number:
            reason = (f"{f.page.kind} page (tier {f.page.tier}"
                      f"{', effective ' + f.effective_date if f.effective_date else ''}) ranks below the winner")
            out.append((f, reason))
    return out
