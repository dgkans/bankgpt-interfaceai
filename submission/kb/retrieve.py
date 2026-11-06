"""
BM25 lexical index over prose passages (pure standard library).

Used for questions that are not a table lookup: programs, eligibility, how-to, branch
news. Scores are re-weighted by page authority and, for blogs/press releases, by age,
so a 2024 release beats a 2020 one that says something different.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence

from . import config
from .facts import Passage
from .normalize import stem, tokens

_K1, _B = 1.4, 0.7
_ABBREV = r"(?<!\bSt\.)(?<!\bAve\.)(?<!\bRd\.)(?<!\bDr\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bU\.S\.)(?<!\bInc\.)(?<!\bJr\.)"
_SENTENCE_RE = re.compile(_ABBREV + r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])|\n+")
_EXTRA_STOP = {"dupaco", "credit", "union", "s"}


def terms(text: str) -> List[str]:
    return [stem(w) for w in tokens(text) if w not in config.STOPWORDS and w not in _EXTRA_STOP]


@dataclass(frozen=True)
class Hit:
    score: float
    coverage: float
    passage: Passage


def _days_between(a: str, b: str) -> int:
    try:
        return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days
    except ValueError:
        return 0


def page_weight(p: Passage, taken_on: str) -> float:
    """Authority weight, decayed by age for dated editorial pages."""
    w = config.TIER_WEIGHT.get(p.page.tier, 0.3)
    if p.page.kind == "editorial":
        age = max(0, _days_between(p.page.page_date or "2015-01-01", taken_on))
        w *= 0.6 + 0.4 * 0.5 ** (age / config.RECENCY_HALF_LIFE_DAYS)
    return w


class Index:
    """BM25 index over one snapshot's passages, with an inverted index for speed."""
    def __init__(self, passages: Sequence[Passage]) -> None:
        self.passages = list(passages)
        self.docs = [Counter(terms(f"{p.heading} {p.page.title} {p.text}")) for p in self.passages]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0
        df: Counter = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf: Dict[str, float] = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.postings: Dict[str, List[int]] = {}
        for i, d in enumerate(self.docs):
            for t in d:
                self.postings.setdefault(t, []).append(i)

    def search(self, query: str, taken_on: str, k: int = 5, boost: Optional[Dict[str, float]] = None,
               require: Optional[set] = None) -> List[Hit]:
        """Top-k passages; with `require`, only passages whose text or heading contains
        at least one of those terms (the named entity in the question)."""
        q = list(dict.fromkeys(terms(query)))
        if not q:
            return []
        allowed = None
        if require:
            allowed = set()
            for t in require:
                allowed.update(self.postings.get(t, []))
        total_idf = sum(self.idf.get(t, 0.0) for t in q) or 1.0
        scores: Dict[int, float] = {}
        for t in q:
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i in self.postings[t]:
                tf = self.docs[i][t]
                norm = tf * (_K1 + 1) / (tf + _K1 * (1 - _B + _B * self.lengths[i] / self.avg))
                scores[i] = scores.get(i, 0.0) + idf * norm * (boost or {}).get(t, 1.0)
        hits = []
        for i, s in scores.items():
            if allowed is not None and i not in allowed:
                continue
            cov = sum(self.idf.get(t, 0.0) for t in q if t in self.docs[i]) / total_idf
            head = set(terms(self.passages[i].heading))
            head_cov = sum(self.idf.get(t, 0.0) for t in q if t in head) / total_idf
            score = s * page_weight(self.passages[i], taken_on) * (1 + 0.5 * head_cov)
            hits.append(Hit(score=score, coverage=cov, passage=self.passages[i]))
        hits.sort(key=lambda h: (-h.score, h.passage.page.url, h.passage.text))
        return hits[:k]

    def best_sentences(self, hit: Hit, query: str, n: int = 1, prefer=None) -> List[str]:
        """The passage's sentences that share the most query terms (site order kept)."""
        q = set(terms(query))
        sents = [s.strip(" -*") for s in _SENTENCE_RE.split(hit.passage.text) if len(s.strip()) > 3]
        scored = []
        for idx, s in enumerate(sents):
            st = set(terms(s))
            sc = sum(self.idf.get(t, 0.0) for t in q & st)
            if prefer is not None and prefer(s):
                sc += 100.0
            if s.endswith("?"):           # FAQ prompts restate the question; the answer follows
                sc -= 100.0
            scored.append((sc, idx, s))
        top = sorted(scored, key=lambda x: (-x[0], x[1]))[:n]
        return [s for _, _, s in sorted(top, key=lambda x: x[1])]

    def sentence_with_next(self, hit: Hit, sentence: str) -> List[str]:
        """The chosen sentence plus the one after it (a lead sentence and its detail)."""
        sents = [s.strip(" -*") for s in _SENTENCE_RE.split(hit.passage.text) if len(s.strip()) > 3]
        if sentence not in sents:
            return [sentence]
        i = sents.index(sentence)
        return sents[i:i + 2]
