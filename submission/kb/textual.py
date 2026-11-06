"""
Answers that are not rate tables: links, routing/phone, branch addresses and hours,
boilerplate counts, dated events ("when does X close"), and the retrieval fallback.

Each function returns (text, sources-as-(page, quote) list) or None to decline; the
caller turns a decline into the refusal template.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from . import config, entities
from .entities import EntityFact
from .facts import PageVersion
from .normalize import all_dates, tokens
from .retrieve import Index, stem, terms
from .understand import Query

Result = Tuple[str, List[Tuple[PageVersion, str]]]
_BRANCH_NAME_RE = re.compile(r"\b((?:[A-Z][\w'\-.]*\s+){1,3})(?:[Bb]ranch|[Ll]ocation|[Oo]ffice)\b")
_GENERIC_NAMES = {"dupaco", "the", "your", "a", "any", "each", "every", "all", "my", "which", "what", "is", "do", "can"}


def branch_name(raw: str) -> Optional[str]:
    """'lobby hours for the Mullan Avenue branch' -> 'Mullan Avenue' (None for generic)."""
    m = _BRANCH_NAME_RE.search(raw)
    if not m:
        return None
    words = [w for w in m.group(1).split() if w.lower().strip("'s") not in _GENERIC_NAMES]
    return " ".join(words) or None


def _name_terms(name: str) -> set:
    t = {stem(w) for w in tokens(name)}
    return {"ave" if w == "avenue" else "st" if w == "street" else w for w in t}


def _cite(facts: List[EntityFact], value: str) -> List[Tuple[PageVersion, str]]:
    """Up to three pages stating the winning value, most authoritative first."""
    same = sorted((f for f in facts if f.value == value), key=lambda f: (f.page.tier, f.page.url))
    return [(f.page, f.quote) for f in same][: config.MAX_SOURCES]


def routing(ents: List[EntityFact]) -> Optional[Result]:
    facts = [e for e in ents if e.kind == "routing"]
    f = entities.best(facts)
    return (f"Dupaco's routing number is {f.value}.", _cite(facts, f.value)) if f else None


def phone(ents: List[EntityFact]) -> Optional[Result]:
    f = entities.best([e for e in ents if e.kind == "phone"])
    return (f"Call Dupaco at {f.value}.", [(f.page, f.quote)]) if f else None


def address(ents: List[EntityFact], name: Optional[str]) -> Optional[Result]:
    """Address of a named branch from the contact-page locator; None if no address matches."""
    if not name:
        return None
    want = _name_terms(name)
    locs = [e for e in ents if e.kind == "location" and "branch" in e.key.lower()]
    hits = [e for e in locs if want <= _name_terms(e.value)]
    if not hits:
        return None
    hits = sorted({h.value: h for h in hits}.values(), key=lambda e: e.value)[:5]
    text = " ".join(f"The {name} branch is at {h.value}." for h in hits) if len(hits) == 1 else \
        f"Dupaco branches matching {name}: " + "; ".join(h.value for h in hits) + "."
    return text, [(hits[0].page, hits[0].quote)]


def _hours_kind(q: Query) -> List[str]:
    if re.search(r"drive|drive-up|drive-thru|drive through", q.text):
        return ["drive-up"]
    if "lobby" in q.text:
        return ["lobby"]
    return ["lobby", "drive-up"]


def hours(ents: List[EntityFact], q: Query, name: Optional[str], texts, pages) -> Optional[Result]:
    """General question -> every published schedule (hours vary by branch); a named branch
    -> only schedules published for that branch, else decline (never invent hours)."""
    facts = [e for e in ents if e.kind == "hours"]
    if name:
        want = _name_terms(name)
        facts = [e for e in facts if want <= {stem(w) for w in tokens(e.page.title + " " + texts.get(e.page.url, "")[:600])}]
        if not facts:
            return None
    parts, srcs = [], []
    for kind in _hours_kind(q):
        rows = entities.schedules(facts, kind)
        if not rows:
            continue
        label = "Lobby" if kind == "lobby" else "Drive-up"
        scheds = " | ".join(f"({i + 1}) {value}" for i, (value, _, _) in enumerate(rows[:4]))
        parts.append(f"{label} hours: {scheds}.")
        srcs += [(f.page, f.quote) for _, _, f in rows[:2]]
    if not parts:
        return None
    lead = f"{name} branch hours published on the site. " if name else \
        "Hours vary by branch; schedules published on the site: "
    tail = "" if name else " Which branch would you like?"
    locator = [(p, "Find a Location Near You (branch and ATM locator)") for p in pages.values()
               if p.kind == "reference" and p.url.rstrip("/").endswith("/contact")]
    return lead + " ".join(parts) + tail, (locator[:1] + srcs)


def stat(ents: List[EntityFact], q: Query) -> Optional[Result]:
    """Count questions answerable from the 'About Dupaco' boilerplate (branches, members, ...)."""
    qwords = set(q.words) - {stem(w) for w in ("dupaco", "many", "total", "number")}
    extras = {stem(w) for w in ("have", "operate", "there", "does", "currently", "open", "run")}
    for name, vocab in entities.STAT_WORDS.items():
        if qwords and qwords <= {stem(w) for w in vocab} | extras:
            f = entities.best([e for e in ents if e.kind == f"stat:{name}"])
            if f:
                return entities.STAT_TEMPLATES[name].format(v=f.value), [(f.page, f.quote)]
    return None


def _has_date(s: str) -> bool:
    return bool(all_dates(s))


def named_terms(raw: str) -> set:
    """Capitalised words after the first word ('Forbes', 'Hy-Vee', 'Volunteer Time Off'):
    the entity the member is asking about, so passages must mention it."""
    words = re.findall(r"(?<!^)(?<![.?!]\s)\b([A-Z][A-Za-z$'\-]+)", raw.strip())
    out = set()
    for w in words:
        for t in terms(w):
            if t not in ("dupaco", "i"):
                out.add(t)
    return out


def _definitional(q: Query) -> bool:
    """'What is X?', 'What recognition has Dupaco received?': answered by a lead paragraph."""
    return bool(re.match(r"^(what is|what's|what are|tell me about|explain|describe|"
                         r"what \w+ (?:has|have|did|does))\b", q.text)) and not q.asks_rate


def retrieve(index: Index, q: Query, taken_on: str, shape: str) -> Optional[Result]:
    """Retrieval fallback: best passage -> 1-2 sentences, or None (caller refuses) when
    nothing clears the score and coverage thresholds."""
    named = {t for t in named_terms(q.raw) if t in index.idf}
    hits = index.search(q.text, taken_on, k=8, boost={t: 2.0 for t in named}, require=named or None)
    hits = [h for h in hits if h.coverage >= config.MIN_QUERY_COVERAGE]
    if not hits or hits[0].score < config.MIN_RETRIEVAL_SCORE:
        return None
    hit = _pick_hit(hits, q, shape)
    prefer = _sentence_preference(q, shape, named)
    sents = index.best_sentences(hit, q.text, n=1, prefer=prefer)
    if not sents:
        return None
    text = sents[0]
    pair = " ".join(index.sentence_with_next(hit, text))
    if len(pair) <= config.MAX_ANSWER_CHARS or len(text) < 60 or _definitional(q):
        text = pair
    text = _event_prefix(re.sub(r"\*\*|__", "", text), q, taken_on, shape)
    return text.strip(), [(hit.passage.page, hit.passage.text[:300])]


def eligibility(index: Index, ents: List[EntityFact], q: Query, taken_on: str) -> Optional[Result]:
    """Membership eligibility = the site's 'who can join' text plus the charter area
    (the counties Dupaco serves, from the newest 'About Dupaco' statement)."""
    got = retrieve(index, q, taken_on, "single")
    f = entities.best([e for e in ents if e.kind == "stat:counties"])
    if not f:
        return got
    area = entities.STAT_TEMPLATES["counties"].format(v=f.value)
    if not got:
        return area, [(f.page, f.quote)]
    return f"{got[0]} {area}", got[1] + [(f.page, f.quote)]


def _count_pattern(q: Query):
    """'how many employees ...' -> regex for '<number> (up to 3 words) employee(s)'."""
    m = re.search(r"\bhow many ((?:\w+ ){0,2}?\w+)", q.text)
    if not m:
        return None
    nouns = [stem(w) for w in m.group(1).split() if w not in ("dupaco", "dupaco's", "of", "the")]
    if not nouns:
        return None
    return re.compile(r"\b\d[\d,]*\**\s+(?:\S+\s+){0,3}?" + re.escape(nouns[0]), re.I)


def _sentence_preference(q: Query, shape: str, named: set):
    """Which sentence to quote: dated for 'when', counted for 'how many', else
    the one naming the asked-about entity."""
    if shape == "when":
        return _has_date
    pattern = _count_pattern(q) if shape == "count" else None
    if pattern is not None:
        return lambda s: bool(pattern.search(s))
    if named:
        return lambda s: bool(named & set(terms(s)))
    return None


def _pick_hit(hits, q: Query, shape: str):
    """Dated passages for 'when' questions; the page's lead paragraph for 'what is' ones."""
    top = hits[0]
    pattern = _count_pattern(q) if shape == "count" else None
    if pattern is not None:
        counted = [h for h in hits if pattern.search(h.passage.text) and h.score >= 0.3 * top.score]
        return counted[0] if counted else top
    if shape == "when":
        dated = [h for h in hits if _has_date(h.passage.text) and h.score >= 0.6 * top.score]
        return dated[0] if dated else top
    if _definitional(q):
        # Inverted pyramid: definitions and press-release news are in the lead paragraph.
        same_page = [h for h in hits if h.passage.page.url == top.passage.page.url and h.score >= 0.6 * top.score]
        return min(same_page, key=lambda h: h.passage.position)
    return top


def _event_prefix(text: str, q: Query, taken_on: str, shape: str) -> str:
    """'Is X still open?' -> 'No. ...' when the stated closing date has passed."""
    if shape != "when" or not re.search(r"\b(still open|open today|still there|still operating)\b", q.text):
        return text
    dates = [d for d, _ in all_dates(text)]
    ref = q.as_of or taken_on
    if dates and re.search(r"\bclos", text, re.I):
        return ("No. " if max(dates) <= ref else "Yes, for now. ") + text
    return text


def link(index: Index, links, pages, q: Query, taken_on: str) -> Optional[Result]:
    """Best URL for a 'what link / how do I ... online' question, from anchors + targets."""
    qt = set(terms(q.text)) - {"link", "url", "use", "online", "website", "page", "web"}
    if not qt:
        return None
    best = None
    for anchor, url, page in links:
        if re.search(r"\.(png|jpe?g|svg|webp|pdf)\b|[?&]|mailto:|tel:", url):
            continue
        target = pages.get(url.split("#")[0]) or pages.get(url.split("#")[0].rstrip("/") + "/")
        words = set(terms(anchor + " " + re.sub(r"[/_.-]", " ", url.split("//")[-1]) + " " +
                          (target.title if target else "")))
        overlap = sum(index.idf.get(t, 1.0) for t in qt & words)
        if overlap <= 0:
            continue
        legacy = "info.dupaco.com" in url
        host_hit = any(t in url.split("//")[-1].split("/")[0] for t in qt)   # join.dupaco.com for "join"
        key = (overlap - (2.0 if legacy else 0.0) + (0.5 if target else 0.0) + (1.5 if host_hit else 0.0),
               -len(url))
        if best is None or key > best[0]:
            best = (key, url.split("#")[0], page, anchor)
    if best is None or best[0][0] < 2.0:
        return None
    _, url, page, anchor = best
    return f"Use {url}", [(page, f"[{anchor}]({url})")]
