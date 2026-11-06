"""
Versioned page store: every snapshot keeps its own view of the site.

Each snapshot is the whole site on its date, so "what is current as of D" means "the
latest snapshot taken on or before D". Extraction results are cached by content hash,
so a page that did not change between crawls is parsed once.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

from . import entities, extract
from .authority import classify
from .facts import PageVersion, Passage, RowFact
from .normalize import clean_text

log = logging.getLogger(__name__)


@dataclass
class SnapshotView:
    """Everything extracted from one snapshot; answers are computed against one view."""
    snapshot_id: str
    taken_on: str
    pages: Dict[str, PageVersion] = field(default_factory=dict)
    facts: List[RowFact] = field(default_factory=list)
    passages: List[Passage] = field(default_factory=list)
    links: List[Tuple[str, str, PageVersion]] = field(default_factory=list)   # (anchor, url, page)
    texts: Dict[str, str] = field(default_factory=dict)                       # url -> main text
    entities: List[entities.EntityFact] = field(default_factory=list)


class PageStore:
    """All snapshots in date order, plus the extraction cache."""
    def __init__(self) -> None:
        self.snapshots: List[SnapshotView] = []
        self._cache: Dict[Tuple[str, str], tuple] = {}

    # ------------------------------------------------------------------ ingest
    def add_snapshot(self, snapshot) -> SnapshotView:
        """Extract every page of a snapshot (in URL order, so results never depend on input order)."""
        view = SnapshotView(snapshot.snapshot_id, snapshot.taken_on)
        for page in sorted(snapshot.pages, key=lambda p: p.url):
            self._add_page(view, page)
        self.snapshots.append(view)
        self.snapshots.sort(key=lambda v: (v.taken_on, v.snapshot_id))
        log.info("ingested %s: %d pages, %d facts", view.snapshot_id, len(view.pages), len(view.facts))
        return view

    def _add_page(self, view: SnapshotView, page) -> None:
        """Stamp the page with its snapshot, authority and publication date, then extract it."""
        text = extract.main_content(clean_text(page.markdown))
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
        auth = classify(page.url)
        pv = PageVersion(url=page.url, title=page.title or "", snapshot_id=view.snapshot_id,
                         taken_on=view.taken_on, fetched_at=page.fetched_at or view.taken_on,
                         tier=auth.tier, kind=auth.kind, segment=auth.segment,
                         page_date=extract.page_date(page.url, text), content_hash=digest)
        view.pages[page.url] = pv
        view.texts[page.url] = text
        facts, passages, links, ents = self._extract_cached(pv, text)
        view.facts.extend(facts)
        view.entities.extend(ents)
        view.passages.extend(passages)
        view.links.extend((a, u, pv) for a, u in links)

    def _extract_cached(self, pv: PageVersion, text: str):
        """Re-use the previous parse of identical content; only the page stamp changes."""
        key = (pv.url, pv.content_hash)
        cached = self._cache.get(key)
        if cached is None:
            facts = extract.table_facts(pv, text)
            facts += extract.line_facts(pv, text, first_index=1000)
            cached = (facts, extract.passages(pv, text), extract.links(text), entities.extract(pv, text))
            self._cache[key] = cached
            return cached
        facts, passages, links, ents = cached
        return ([replace(f, page=pv) for f in facts], [replace(p, page=pv) for p in passages], links,
                [replace(e, page=pv) for e in ents])

    # ------------------------------------------------------------------ as_of
    def view_for(self, as_of: Optional[str]) -> Tuple[Optional[SnapshotView], Optional[str]]:
        """Snapshot to answer from, plus a note when the date is before the first crawl."""
        if not self.snapshots:
            return None, None
        if not as_of:
            return self.snapshots[-1], None
        eligible = [v for v in self.snapshots if v.taken_on <= as_of[:10]]
        if eligible:
            return eligible[-1], None
        first = self.snapshots[0]
        return first, f"{as_of} is before the first crawl; answered from the earliest snapshot"

    def history(self, view: SnapshotView) -> List[SnapshotView]:
        """The given snapshot followed by older ones, newest first (fallback order)."""
        idx = self.snapshots.index(view)
        return list(reversed(self.snapshots[: idx + 1]))
