"""
Value objects that flow between ingest, resolution and answering.

PageVersion = one page as seen in one snapshot. RowFact = one row of a rate/fee table
(or one "label: value" line) with every qualifier that makes it a distinct fact.
Passage = a prose chunk for lexical retrieval. All are immutable so caching is safe.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple



@dataclass(frozen=True)
class PageVersion:
    """One page as it appeared in one snapshot, with its authority stamp."""
    url: str
    title: str
    snapshot_id: str
    taken_on: str                  # snapshot date (ISO)
    fetched_at: str                # crawl timestamp of this copy
    tier: int                      # authority tier, 1 = best
    kind: str                      # page kind from authority.classify
    segment: str                   # personal / business
    page_date: Optional[str]       # publication date for posts (ISO) if stated
    content_hash: str


@dataclass(frozen=True)
class Value:
    """One value cell, typed by its column (APY, APR, dividend rate, ...)."""
    kind: str                      # apy / dividend / apr / rate / fee / points / payment / min_open / min_earn
    text: str                      # as printed on the site, footnote digits removed
    number: Optional[float]        # first numeric value, for comparisons


@dataclass(frozen=True)
class RowFact:
    """One table row (or one 'label: value' line). The page reference carries snapshot,
    date and authority; everything else here describes *which* fact this is."""
    page: PageVersion
    table_index: int               # order of the table on the page (site's lead table = 0)
    row_index: int
    context: str                   # headings/captions above the table
    caption: str                   # nearest caption, e.g. "Share Savings"
    label: str                     # row label cells, e.g. "Share Savings | $10,000 - $24,999.99"
    values: Tuple[Value, ...]
    effective_date: Optional[str]  # "Rates are effective as of ..." below the table
    detail_url: Optional[str]      # "See details" link of the table, if any
    ends_on: Optional[str]         # end date stated by the offer text on the row/line, if any
    term: Optional[int]            # months
    model_years: Optional[Tuple[int, int]]
    amount: Optional[Tuple[float, float]]
    words: frozenset = field(default_factory=frozenset)

    def value(self, kind: str) -> Optional[Value]:
        for v in self.values:
            if v.kind == kind:
                return v
        return None

    @property
    def table_key(self) -> tuple:
        return (self.page.url, self.table_index)



@dataclass(frozen=True)
class Passage:
    """A prose chunk used by the retrieval fallback."""
    page: PageVersion
    heading: str
    text: str
    position: int = 0              # order on the page (lead paragraphs come first)
