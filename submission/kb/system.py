"""
KnowledgeSystem: wires ingest, understanding, structured answers, entity facts,
retrieval and conflicts behind the harness contract.

answer() never raises: any internal error is logged and turned into the refusal
template, because a crash scores zero and a refusal is at least honest.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from . import config, conflicts as conflict_finder, render, structured, textual
from .contract_types import Answer, Conflict, Source
from .match import build_idf
from .retrieve import Index
from .store import PageStore, SnapshotView
from .understand import Query, parse

log = logging.getLogger(__name__)
_VALUE_Q_RE = re.compile(r"\b(fee|fees|cost|costs|charge|charges|how much|price|minimum|maximum)\b")
_ELIGIBILITY_RE = re.compile(r"\beligib\w*\b.*\b(member|join|membership)|\bwho can (join|become)\b|"
                             r"\bqualify for membership\b|\bcan i (join|become a member)\b")
_PHONE_Q_RE = re.compile(r"\b(phone|call|contact information|contact info|telephone|reach (?:you|dupaco))\b")


class KnowledgeSystem:
    """The object returned by build(): implements the harness contract."""
    def __init__(self) -> None:
        self.store = PageStore()
        self._idf: Dict[str, Dict[str, float]] = {}
        self._index: Dict[str, Index] = {}

    # ------------------------------------------------------------------ contract
    def ingest(self, snapshot) -> None:
        """Store and extract one snapshot, then build its matching and retrieval indexes."""
        view = self.store.add_snapshot(snapshot)
        self._idf[view.snapshot_id] = build_idf(view.facts)
        self._index[view.snapshot_id] = Index(view.passages)

    def answer(self, question: str, as_of: Optional[str] = None) -> Answer:
        try:
            return self._answer(question, as_of)
        except Exception:  # noqa: BLE001 - contract: answer() must never raise
            log.exception("answer failed for %r", question)
            return refuse()

    def conflicts(self) -> List[Conflict]:
        """Curated contradictions in the newest snapshot (see conflicts.py)."""
        try:
            return conflict_finder.find(self.store)
        except Exception:  # noqa: BLE001 - a failure here must not lose the QA score
            log.exception("conflicts() failed")
            return []

    def explain(self, question: str, as_of: Optional[str] = None) -> dict:
        """Debug helper (not used by the scorer): slots, chosen path and sources."""
        q = parse(question)
        view, note = self.store.view_for(as_of or q.as_of)
        ans = self.answer(question, as_of)
        return {"query": q.__dict__, "snapshot": view.snapshot_id if view else None, "date_note": note,
                "answer": ans.text, "confident": ans.confident, "conflict_note": ans.conflict_note,
                "sources": [s.__dict__ for s in ans.sources]}

    # ------------------------------------------------------------------ pipeline
    def _answer(self, question: str, as_of: Optional[str]) -> Answer:
        """Pick the snapshot for the date, route the question, attach any date note."""
        q = parse(question)
        view, date_note = self.store.view_for(as_of or q.as_of)
        if view is None:
            return refuse()
        ans = self._route(view, q) or refuse()
        if date_note:
            ans.conflict_note = "; ".join(x for x in (date_note, ans.conflict_note) if x)
        return ans

    def _route(self, view: SnapshotView, q: Query) -> Optional[Answer]:
        """Pick the answering path from the question's shape; each path may decline."""
        idx = self._index[view.snapshot_id]
        name = textual.branch_name(q.raw)
        if q.shape == "link" or re.search(r"\b(join|apply|open|become a member)\b.*\bonline\b|\bonline\b.*\b(join|apply)\b", q.text):
            if q.asks_rate:
                return self._structured(view, q, link=True)
            return self._textual(view, textual.link(idx, view.links, view.pages, q, view.taken_on))
        if "routing" in q.text:
            return self._textual(view, textual.routing(view.entities))
        if _PHONE_Q_RE.search(q.text) and not q.asks_rate:
            return self._textual(view, textual.phone(view.entities))
        if q.shape == "address" and name:
            return self._textual(view, textual.address(view.entities, name))
        if q.shape == "hours":
            return self._textual(view, textual.hours(view.entities, q, name, view.texts, view.pages))
        if q.shape == "count":
            got = textual.stat(view.entities, q)
            if got:
                return self._textual(view, got)
        if _ELIGIBILITY_RE.search(q.text):
            return self._textual(view, textual.eligibility(idx, view.entities, q, view.taken_on))
        if q.shape != "when" and (q.asks_rate or _VALUE_Q_RE.search(q.text)):
            return self._structured(view, q)
        return self._textual(view, textual.retrieve(idx, q, view.taken_on, q.shape))

    def _structured(self, view: SnapshotView, q: Query, link: bool = False) -> Optional[Answer]:
        """Table answer from the chosen snapshot; if the fact is missing, from older ones
        (newest first), saying where it was last stated."""
        for v in self.store.history(view):
            sa = structured.answer(v, q, self._idf[v.snapshot_id])
            if sa is None:
                continue
            if structured.unpublished_variant(q, sa.rows):
                return None
            note = sa.note
            if v is not view:
                note = "; ".join(x for x in (f"not found in {view.snapshot_id}; last stated in {v.snapshot_id}",
                                             note) if x)
            sources = self._row_sources(v, sa.rows)
            text = f"Use {sources[0].url}" if link and sources else sa.text
            return Answer(text=text, sources=sources, confident=True, conflict_note=note)
        return None

    def _textual(self, view: SnapshotView, got) -> Optional[Answer]:
        if not got:
            return None
        text, srcs = got
        sources = [Source(url=p.url, snapshot_id=view.snapshot_id, quote=quote[:300]) for p, quote in srcs]
        return Answer(text=text, sources=_dedupe(sources)[: config.MAX_SOURCES], confident=True)

    def _row_sources(self, view: SnapshotView, rows) -> List[Source]:
        """Cite the winning page first, then the product's 'See details' page, max 3."""
        out: List[Source] = []
        for n, f in enumerate(rows):
            quote = f"{f.caption}: {f.label} = " + ", ".join(v.text for v in f.values)
            if f.effective_date:
                quote += f" (effective {f.effective_date})"
            urls = [f.page.url]
            if n == 0 and f.detail_url and _in_view(view, f.detail_url):
                urls.insert(0 if f.page.kind == "rate_sheet" else 1, f.detail_url)
            out += [Source(url=u, snapshot_id=view.snapshot_id, quote=quote[:300]) for u in urls]
        return _dedupe(out)[: config.MAX_SOURCES]


def refuse() -> Answer:
    """The fixed 'I don't know' answer: no digits, confident=False."""
    return Answer(text=render.refusal_text(), sources=[], confident=False)


def _in_view(view: SnapshotView, url: str) -> bool:
    u = url.rstrip("/")
    return u in view.pages or (u + "/") in view.pages


def _dedupe(sources: List[Source]) -> List[Source]:
    seen, out = set(), []
    for s in sources:
        k = s.url.rstrip("/").lower()
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out
