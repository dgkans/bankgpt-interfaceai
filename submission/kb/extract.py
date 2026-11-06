"""
Page -> structured facts (table rows, "label: value" lines) and prose passages.

Tables become one RowFact per row, with the headings above the table, the row-label
cells, the typed value cells (APY / dividend / APR / rate / fee ...) and the in-page
"Rates are effective as of" date. Prose becomes Passages for the retrieval fallback.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from . import config
from .facts import PageVersion, Passage, RowFact, Value
from .normalize import (amount_range, model_year_range, norm_words, parse_date, parse_money,
                        parse_percent, stems, strip_footnotes, term_months)

_RELATED_RE = re.compile(r"^#{1,6}\s*(handpicked for you|related (posts|articles)|you may also like)", re.I | re.M)
_LINK_ONLY_RE = re.compile(r"^\s*(!?\[[^\]]*\]\([^)]*\)\s*)+$")
_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{2,}")
_EFFECTIVE_RE = re.compile(r"effective as of\s+(\d{1,2}/\d{1,2}/\d{4}|\w+ \d{1,2},? \d{4}|\d{4}-\d{2}-\d{2})", re.I)
_DETAIL_LINK_RE = re.compile(r"\[(?:See details|Learn more|Compare[^\]]*)\]\((https?://www\.dupaco\.com[^)#\s]*)", re.I)
_VALUE_CELL_RE = re.compile(r"^[\s$]*\d[\d,]*(?:\.\d+)?\s*%?(?:\s*(?:APR|APY))?(?:\s*[-–]\s*\$?\d[\d,]*(?:\.\d+)?\s*%?)?$", re.I)
_LINE_FACT_RE = re.compile(r"^(?P<label>[^|]{3,140}?)[:\s]\s*(?P<value>\$\s?\d[\d,]*(?:\.\d+)?|\d+(?:\.\d+)?\s*%)")
_LINE_LABEL_RE = re.compile(r"\b(fees?|apy|apr|rates?|dividend|charges?|costs?|price|replacement|premium)\b", re.I)
_ANSWER_KINDS = ("apy", "apr", "rate", "dividend", "fee")
_URL_DATE_RE = re.compile(r"/(20\d{2}|19\d{2})/(\d{2})/(\d{2})/")


def main_content(text: str) -> str:
    """Drop 'Handpicked for You' related-post teasers: they carry other posts' dates/values."""
    m = _RELATED_RE.search(text)
    return text[:m.start()] if m else text


def page_date(url: str, text: str) -> Optional[str]:
    """Publication date of a post: from a /YYYY/MM/DD/ URL, else the first long date near the top."""
    m = _URL_DATE_RE.search(url)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    head = "\n".join(text.splitlines()[:12])
    return parse_date(re.sub(r"\d{1,2}/\d{1,2}/\d{4}", "", head))


def _cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _column_kind(header: str) -> Optional[str]:
    """Value type of a table column from its header ('Dividend Rate' -> dividend). None = label column."""
    h = norm_words(header)
    if "dividend" in h:
        return "dividend"
    if "apy" in h or "yield" in h:
        return "apy"
    if "apr" in h or "annual percentage rate" in h:
        return "apr"
    if "payment" in h:
        return "payment"
    if "points" in h:
        return "points"
    if "min" in h and "open" in h:
        return "min_open"
    if "min" in h and "earn" in h:
        return "min_earn"
    if h in ("rate", "rates", "interest rate", "rate (as low as)"):
        return "rate"
    if any(w in h for w in ("fee", "cost", "charge", "price")):
        return "fee"
    return None


def _value_kind_from_cell(cell: str, default: Optional[str]) -> Optional[str]:
    """A cell that says 'APR'/'APY' overrides the column header."""
    u = cell.upper()
    if re.search(r"\bAPY\b", u):
        return "apy"
    if re.search(r"\bAPR\b", u):
        return "apr"
    return default


def _make_value(kind: str, cell: str) -> Value:
    text = strip_footnotes(cell)
    num = parse_percent(text) if "%" in text else parse_money(text)
    return Value(kind=kind, text=text, number=num)


def _heading_text(line: str) -> str:
    return re.sub(r"^#{1,6}\s*", "", line).strip().strip("*").strip()


def _is_caption(line: str) -> bool:
    """Short heading-like line (product name above a table), not prose, links or footnotes."""
    s = line.strip()
    if not s or s.startswith("|") or _LINK_ONLY_RE.match(s) or len(s) > 70:
        return False
    if _EFFECTIVE_RE.search(s) or s.lower().startswith(("rates are", "apy", "*", "✕")):
        return False
    return not s.endswith((".", ":", "?")) or s.startswith("#")


def _captions_above(lines: List[str], start: int) -> List[Tuple[int, str]]:
    """Up to two caption-like lines right above a table (nearest first), stopping at the
    previous table so captions never leak across tables."""
    captions = []
    i = start - 1
    while i >= 0 and len(captions) < 2:
        s = lines[i].strip()
        if s.startswith("|"):
            break
        if _is_caption(s):
            text = _heading_text(s)
            if text and norm_words(text) not in ("rates", "deposits loans", "depositsloans"):
                captions.append((i, text))
        i -= 1
    return captions


def _last_heading(lines: List[str], start: int) -> Tuple[int, str]:
    for j in range(start - 1, -1, -1):
        if lines[j].startswith("#") and not lines[j].startswith("#####"):
            return j, _heading_text(lines[j])
    return -1, ""


def _after_table(lines: List[str], end: int) -> Tuple[Optional[str], Optional[str]]:
    """Effective date and 'See details' link in the text between this table and the next."""
    eff, detail = None, None
    for s in lines[end:end + 40]:
        if s.strip().startswith("|"):
            break
        if eff is None:
            m = _EFFECTIVE_RE.search(s)
            if m:
                eff = parse_date(m.group(1))
        if detail is None:
            m = _DETAIL_LINK_RE.search(s)
            if m:
                detail = m.group(1).rstrip("/")
    return eff, detail


def _row_fact(page, t_idx, r_idx, header, cells, ctx, caption, eff, detail) -> Optional[RowFact]:
    """One table row -> RowFact. Rows without any rate or fee value (payment examples,
    calculator data points) are dropped: they never answer a member question."""
    labels, values = [], []
    for h, c in zip(header, cells):
        kind = _column_kind(h)
        c_clean = strip_footnotes(c)
        if kind and _VALUE_CELL_RE.match(c_clean):
            values.append(_make_value(_value_kind_from_cell(c_clean, kind), c_clean))
        elif kind is None and _VALUE_CELL_RE.match(c_clean) and "%" in c_clean:
            values.append(_make_value(_value_kind_from_cell(c_clean, "rate"), c_clean))
        elif c_clean and c_clean not in ("—", "-"):
            labels.append(re.sub(r"[\\*]+", "", c_clean).strip())
    if not any(v.kind in _ANSWER_KINDS for v in values):
        return None
    label = " | ".join(labels)
    return _build(page, t_idx, r_idx, ctx, caption, label, values, eff, detail, ends_on=None)


def _build(page, t_idx, r_idx, ctx, caption, label, values, eff, detail, ends_on) -> RowFact:
    """Assemble a RowFact and pre-compute the qualifiers used for matching (term, tiers, words)."""
    desc = f"{caption} {label}"
    return RowFact(
        page=page, table_index=t_idx, row_index=r_idx, context=ctx, caption=caption, label=label,
        values=tuple(values), effective_date=eff, detail_url=detail, ends_on=ends_on,
        term=term_months(label) or term_months(caption), model_years=model_year_range(desc),
        amount=amount_range(label), words=frozenset(stems(f"{ctx} {desc}")),
    )


def table_facts(page: PageVersion, text: str) -> List[RowFact]:
    """Every markdown table on the page -> RowFacts, with captions, the running section heading
    (e.g. 'Credit Cards' above both card tables), effective date and 'See details' link."""
    lines = text.splitlines()
    facts, i, t_idx = [], 0, 0
    section: Optional[Tuple[int, str]] = None
    while i < len(lines):
        if not (lines[i].strip().startswith("|") and i + 1 < len(lines) and _SEPARATOR_RE.match(lines[i + 1].strip())):
            i += 1
            continue
        start, header = i, _cells(lines[i])
        j = i + 2
        rows = []
        while j < len(lines) and lines[j].strip().startswith("|"):
            rows.append(_cells(lines[j]))
            j += 1
        captions = _captions_above(lines, start)
        h_line, heading = _last_heading(lines, start)
        if len(captions) >= 2:
            section = captions[1]          # e.g. "Credit Cards" above "Platinum Visa"
        if section and section[0] < h_line:
            section = None                 # a newer markdown heading starts a new section
        caption = captions[0][1] if captions else ""
        ctx = " / ".join(x for x in (heading, section[1] if section else "") if x and x != caption)
        eff, detail = _after_table(lines, j)
        for r_idx, cells in enumerate(rows):
            f = _row_fact(page, t_idx, r_idx, header, cells, ctx, caption, eff, detail)
            if f:
                facts.append(f)
        t_idx += 1
        i = j
    return facts


def offer_end_date(line: str) -> Optional[str]:
    """'(offer ended 2025-09-30)' -> '2025-09-30'. Compared with the snapshot date later."""
    m = config.EXPIRED_OFFER_RE.search(line)
    return parse_date(m.group(1)) if m else None


def line_facts(page: PageVersion, text: str, first_index: int) -> List[RowFact]:
    """'Label: value' lines outside tables (fee lists, simple rate pages)."""
    facts, heading = [], ""
    for n, raw in enumerate(text.splitlines()):
        s = raw.strip().lstrip("-* ").strip()
        if s.startswith("#"):
            heading = _heading_text(s)
            continue
        if not s or s.startswith("|") or len(s) > 160 or ":" not in s:
            continue
        m = _LINE_FACT_RE.match(s.replace("**", ""))
        if not m:
            continue
        label = m.group("label").strip().rstrip(":").strip()
        rest = s.replace("**", "")[m.end():].strip()
        if len(label.split()) > 10 or len(rest) > 40:
            continue                       # a sentence that merely mentions a number
        if not _LINE_LABEL_RE.search(label) or page.kind == "editorial":
            continue
        value = strip_footnotes(m.group("value"))
        kind = "fee" if value.startswith("$") else _value_kind_from_cell(label, None) or (
            "apy" if "apy" in label.lower() else "rate")
        if "dividend" in label.lower():
            kind = "dividend"
        facts.append(_build(page, first_index + n, 0, heading, heading, label,
                            [_make_value(kind, value)], parse_date(s) if "effective" in s.lower() else None,
                            None, offer_end_date(s)))
    return facts


def links(text: str) -> List[Tuple[str, str]]:
    """(anchor text, url) for every markdown link: used to answer 'what link/URL' questions."""
    return [(a.strip(), u.strip()) for a, u in re.findall(r"(?<!!)\[([^\]]{2,120})\]\((https?://[^)\s]+)\)", text)]


def _prose(block: str) -> str:
    b = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", block)
    return re.sub(r"\[([^\]]*)\]\(([^)]*)\)", r"\1", b).strip()


def passages(page: PageVersion, text: str) -> List[Passage]:
    """Prose paragraphs tagged with their heading. Consecutive bullet items under one heading
    form one passage, and an FAQ question is joined to the answer paragraph after it."""
    out, heading, pending = [], page.title, ""
    blocks = []
    for block in re.split(r"\n\s*\n", text):
        b = block.strip()
        if not b or b.startswith("|") or (_LINK_ONLY_RE.match(b) and not b.startswith("- [")):
            continue
        if b.startswith("#") and "\n" not in b:
            blocks.append(("h", _heading_text(b)))
            continue
        blocks.append(("p", _prose(b)))
    for kind, b in blocks:
        if kind == "h":
            heading = b
            continue
        if b.endswith("?") and len(b) < 200:
            pending = (pending + " " + b.lstrip("- ")).strip()
            continue
        if pending:
            b, pending = f"{pending} {b}", ""
        if out and b.startswith("- ") and out[-1].heading == heading and out[-1].text.startswith("- ") \
                and len(out[-1].text) < 900:
            out[-1] = Passage(page=page, heading=heading, text=f"{out[-1].text}\n{b}", position=out[-1].position)
            continue
        if len(b.split()) < 4 or (len(b.split()) < 8 and (parse_date(b) or "min read" in b)):
            continue                       # bylines, "2 min read", modal button text
        out.append(Passage(page=page, heading=heading, text=b[:1200], position=len(out)))
    return out
