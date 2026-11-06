"""
Entity facts that are not rate tables: routing number, phone, branch addresses,
published branch hours, and the "About Dupaco" boilerplate counts (branches, members).

Each fact keeps its page, so the same authority/recency rules apply: the routing number
from the contact page, the branch count from the most recently dated press release.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .facts import PageVersion

_ROUTING_RE = re.compile(r"routing (?:number|#|no\.?)\W{0,12}(?:is\s*)?(?:\*\*)?\s*\(?(\d{9})\b", re.I)
_PHONE_RE = re.compile(r"\*\*Phone:\*\*\s*\[?(\d{3}-\d{3}-\d{4})")
_LOCATION_RE = re.compile(r"^###\s+(?P<name>.+)\n\n(?P<type>[^\n]+)\n\n(?P<addr>[^\n]+,\s*[A-Z]{2},\s*\d{5})", re.M)
_HOURS_RE = re.compile(r"\*\*(Lobby|Drive-up|Drive-thru|Drive up)\*\*\s*(.*?)(?=\*\*[A-Z]|\n\s*\n\s*\n|$)", re.S | re.I)
_DAY_LINE_RE = re.compile(r"((?:Mon|Tues?|Wed|Thu|Fri|Sat|Sun)\w*(?:\s*[-–]\s*\w+)?):\s*([^\n]+)", re.I)
STAT_PATTERNS = {
    "branches": re.compile(r"(\d{1,3}) (?:full-service )?branch office locations", re.I),
    "members": re.compile(r"membership has grown to (?:more than|over|nearly) ([\d,]+)", re.I),
    "assets": re.compile(r"assets (?:exceeding|of nearly|of more than|of) (\$[\d.]+ billion)", re.I),
    "employees": re.compile(r"(?:over|more than|nearly) (\d{3,4}) employees", re.I),
    "counties": re.compile(r"serves residents in (\d{1,3}) counties", re.I),
}
_ORDINAL_RE = re.compile(r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth) time "
                         r"([A-Z][A-Za-z]+) (?:has )?(?:recognized|named|ranked|honored)", re.I)
STAT_WORDS = {
    "branches": {"branch", "branches", "location", "locations", "office", "offices"},
    "members": {"member", "members", "membership"},
    "assets": {"asset", "assets", "big", "size"},
    "employees": {"employee", "employees", "staff", "work", "people"},
    "counties": {"county", "counties", "serve", "serves"},
}
STAT_TEMPLATES = {
    "branches": "Dupaco has {v} branch office locations.",
    "members": "Dupaco has more than {v} members.",
    "assets": "Dupaco has assets exceeding {v}.",
    "employees": "Dupaco has over {v} employees.",
    "counties": "Dupaco serves residents in {v} counties throughout Iowa, northwest Illinois and southwest Wisconsin.",
}


@dataclass(frozen=True)
class EntityFact:
    """A non-table fact with the page it came from (for authority and recency)."""
    kind: str                # routing / phone / location / hours / stat:<name>
    key: str                 # branch name, stat name, ...
    value: str
    page: PageVersion
    quote: str


def _clean(s: str) -> str:
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    return re.sub(r"\s+", " ", s.replace("**", "")).strip()


def hours_schedule(block: str) -> str:
    """'Monday-Thursday: 8:30 a.m.-5 p.m. / Friday: ...' as one normalised line."""
    days = [f"{d.strip()}: {_clean(h).rstrip('.')}" for d, h in _DAY_LINE_RE.findall(block)]
    return "; ".join(days).replace("–", "-")


def extract(page: PageVersion, text: str) -> List[EntityFact]:
    """All entity facts on one page. Boilerplate counts and ordinals are only read from
    press releases/blogs, where they come with a publication date."""
    out: List[EntityFact] = []
    for m in _ROUTING_RE.finditer(text):
        out.append(EntityFact("routing", "", m.group(1), page, _clean(m.group(0))))
    for m in _PHONE_RE.finditer(text):
        out.append(EntityFact("phone", "main", m.group(1), page, _clean(m.group(0))))
    for m in _LOCATION_RE.finditer(text):
        out.append(EntityFact("location", m.group("type").strip(), _clean(m.group("addr")), page,
                              _clean(m.group("addr"))))
    for m in _HOURS_RE.finditer(text):
        sched = hours_schedule(m.group(2))
        if sched:
            kind = "lobby" if m.group(1).lower() == "lobby" else "drive-up"
            out.append(EntityFact("hours", kind, sched, page, _clean(m.group(0))[:300]))
    if page.kind == "editorial":
        for m in _ORDINAL_RE.finditer(text):
            out.append(EntityFact(f"ordinal:{m.group(2)}", m.group(2), m.group(1).lower(), page, _clean(m.group(0))))
        for name, rx in STAT_PATTERNS.items():
            m = rx.search(text)
            if m:
                out.append(EntityFact(f"stat:{name}", name, m.group(1), page, _clean(m.group(0))))
    return out


def best(facts: List[EntityFact]) -> Optional[EntityFact]:
    """Authority first, then the most recently dated page, then crawl time; URL for stability."""
    if not facts:
        return None
    return sorted(facts, key=lambda f: (f.page.tier, _neg(f.page.page_date), _neg(f.page.fetched_at), f.page.url))[0]


def _neg(d: Optional[str]) -> str:
    if not d:
        return "~"
    return "".join(chr(ord("9") - ord(c) + ord("0")) if c.isdigit() else c for c in d)


def schedules(facts: List[EntityFact], kind: str) -> List[Tuple[str, int, EntityFact]]:
    """Distinct published schedules of one kind, most common first, then newest."""
    groups: Dict[str, List[EntityFact]] = {}
    for f in facts:
        if f.kind == "hours" and f.key == kind:
            groups.setdefault(f.value.lower(), []).append(f)
    rows = []
    for fs in groups.values():
        newest = best(fs)
        rows.append((newest.value, len(fs), newest))
    rows.sort(key=lambda r: (-r[1], _neg(r[2].page.page_date), r[0]))
    return rows
