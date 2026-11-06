"""
Unit tests on small synthetic fixtures (no site text). Run:
    python -m unittest discover -s submission/tests
"""
from __future__ import annotations

import re
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kb import config, extract, normalize, understand  # noqa: E402
from kb.authority import classify  # noqa: E402
from kb.facts import PageVersion  # noqa: E402
from kb.resolve import authority_order, drop_expired  # noqa: E402
from kb.match import Scored  # noqa: E402
from kb.system import KnowledgeSystem  # noqa: E402

REFUSAL_RE = re.compile(  # same pattern as harness/scoring.py
    r"\b(i (?:do not|don't|can't|cannot) (?:know|find|confirm)|not (?:sure|able to confirm)|"
    r"no (?:longer )?(?:available|offered)|isn't listed|is not listed|please (?:contact|call|visit)|"
    r"no information)\b", re.I)


@dataclass(frozen=True)
class FakePage:
    url: str
    title: str
    markdown: str
    fetched_at: str


@dataclass(frozen=True)
class FakeSnapshot:
    snapshot_id: str
    taken_on: str
    pages: list


RATES_V1 = """# Rates

Certificates

Regular Certificates

| Certificate | Dividend Rate | Annual Percentage Yield (APY) | Min. to Earn |
| --- | --- | --- | --- |
| 12 Month | 2.97% | 3.00%1 | $1,000.00 |
| 6 Month | 2.47% | 2.50%1 | $1,000.00 |

Rates are effective as of 01/02/2026 and are subject to change without notice.

Auto Loans

| Loan Program | Term | Annual Percentage Rate (As Low As) |
| --- | --- | --- |
| 2024-27 Model Year | 60 Months | 5.00% APR1 |
| 2020-23 Model Year | 60 Months | 6.00% APR1 |

Rates are effective as of 01/02/2026.
"""
RATES_V2 = RATES_V1.replace("2.50%1", "2.75%1").replace("2.47%", "2.72%").replace("01/02/2026", "03/01/2026")
CALC = """# Auto calculator

Auto Loan Rates

| Loan Program | Term | Annual Percentage Rate |
| --- | --- | --- |
| 2023-26 Model Year | 60 Months | 4.75% APR |
"""
CONTACT = "# Contact\n\n**Phone:** [555-000-1111](tel:5550001111)\n\n**Routing Number:** 123456789\n"


def page(url, md, date="2026-01-05T00:00:00Z"):
    return FakePage(url=url, title=url.rsplit("/", 1)[-1], markdown=md, fetched_at=date)


def system():
    ks = KnowledgeSystem()
    ks.ingest(FakeSnapshot("01_2026-01-05_a", "2026-01-05", [
        page("https://www.dupaco.com/rates", RATES_V1), page("https://www.dupaco.com/calculators/auto", CALC),
        page("https://www.dupaco.com/contact", CONTACT)]))
    ks.ingest(FakeSnapshot("02_2026-03-05_b", "2026-03-05", [
        page("https://www.dupaco.com/rates", RATES_V2), page("https://www.dupaco.com/calculators/auto", CALC),
        page("https://www.dupaco.com/contact", CONTACT)]))
    return ks


class NormalizeTests(unittest.TestCase):
    def test_footnotes_stripped_values_kept(self):
        self.assertEqual(normalize.strip_footnotes("5.39% APR1"), "5.39% APR")
        self.assertEqual(normalize.strip_footnotes("0.15%1"), "0.15%")
        self.assertEqual(normalize.strip_footnotes("12.50% – 19.50%2"), "12.50% – 19.50%")
        self.assertEqual(normalize.strip_footnotes("$1,000.00"), "$1,000.00")

    def test_escaped_newlines(self):
        self.assertEqual(normalize.clean_text("a\\\\r\\\\nb"), "a\nb")

    def test_ranges(self):
        self.assertEqual(normalize.amount_range("$10,000 – $24,999.99"), (10000.0, 24999.99))
        self.assertEqual(normalize.amount_range("$25,000+"), (25000.0, normalize.INF))
        self.assertEqual(normalize.amount_range("$832,750 or less"), (0.0, 832750.0))
        self.assertEqual(normalize.model_year_range("2024-27 Model Year"), (2024, 2027))
        self.assertEqual(normalize.model_year_range("Model Year 2026-23"), (2023, 2026))
        self.assertEqual(normalize.model_year_range("2016 Model Year (and older)"), (0, 2016))

    def test_terms_and_dates(self):
        self.assertEqual(normalize.term_months("30-Year Fixed"), 360)
        self.assertEqual(normalize.term_months("six month certificate"), 6)
        self.assertEqual(normalize.parse_date("effective as of 06/02/2026"), "2026-06-02")
        self.assertEqual(normalize.parse_date("June 20, 2025"), "2025-06-20")
        self.assertEqual(normalize.stem("branches"), normalize.stem("branch"))


class UnderstandTests(unittest.TestCase):
    def test_slots(self):
        q = understand.parse("What's the APR for a 60-month auto loan on a 2025 model-year vehicle?")
        self.assertEqual((q.term, q.model_year, q.rate_kind), (60, 2025, "apr"))
        q = understand.parse("Current APY on a six month share certificate?")
        self.assertEqual(q.term, 6)
        self.assertIn("certificat", q.words)

    def test_date_in_question(self):
        self.assertEqual(understand.date_in_question("rate as of May 2026?"), "2026-05-31")
        self.assertEqual(understand.date_in_question("open today (October 2026)?"), "2026-10-31")


class ExtractAndAuthorityTests(unittest.TestCase):
    def test_table_rows(self):
        pv = PageVersion("https://www.dupaco.com/rates", "Rates", "s", "2026-01-05", "", 1, "rate_sheet",
                         "personal", None, "h")
        facts = extract.table_facts(pv, RATES_V1)
        six = [f for f in facts if f.term == 6][0]
        self.assertEqual(six.caption, "Regular Certificates")
        self.assertEqual(six.value("apy").text, "2.50%")
        self.assertEqual(six.effective_date, "2026-01-02")
        auto = [f for f in facts if f.model_years == (2024, 2027)][0]
        self.assertEqual(auto.value("apr").number, 5.0)

    def test_authority(self):
        self.assertEqual(classify("https://www.dupaco.com/rates").tier, 1)
        self.assertEqual(classify("https://www.dupaco.com/calculators/x").tier, 3)
        self.assertEqual(classify("https://www.dupaco.com/newsroom/x").kind, "editorial")
        self.assertGreater(classify("https://info.dupaco.com/rates").tier, classify("https://www.dupaco.com/rates").tier)
        self.assertEqual(classify("https://www.dupaco.com/business-rates").segment, "business")


class ResolveRuleTests(unittest.TestCase):
    def _pv(self, url, tier, kind="product"):
        return PageVersion(url, "", "s", "2026-03-05", "2026-03-05", tier, kind, "personal", None, "h")

    def test_authority_beats_recency_across_tiers(self):
        self.assertLess(authority_order(self._pv("a", 1), "2026-01-01"), authority_order(self._pv("b", 3), "2026-03-01"))

    def test_recency_within_tier(self):
        self.assertLess(authority_order(self._pv("b", 1), "2026-03-01"), authority_order(self._pv("a", 1), "2026-01-01"))

    def test_drop_expired(self):
        pv = self._pv("p", 3, "promo")
        md = "Summer special: 6-month certificate APY 2.95% (offer ended 2025-09-30)\n"
        f = extract.line_facts(pv, md, 0)[0]
        keep, dropped = drop_expired([Scored(5.0, f, "")], "2026-03-05")
        self.assertEqual((keep, len(dropped)), ([], 1))


class SystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ks = system()

    def test_current_value_and_tier(self):
        a = self.ks.answer("What is the 6-month certificate APY?")
        self.assertIn("2.75%", a.text)
        self.assertNotIn("2.50%", a.text)
        self.assertTrue(a.sources and a.sources[0].url.endswith("/rates"))

    def test_as_of(self):
        self.assertIn("2.50%", self.ks.answer("6-month certificate APY?", as_of="2026-02-01").text)
        self.assertIn("2.50%", self.ks.answer("6-month certificate APY in January 2026?").text)

    def test_stale_calculator_loses(self):
        a = self.ks.answer("APR for a 60-month auto loan on a 2025 model year car?")
        self.assertIn("5.00%", a.text)
        self.assertNotIn("4.75%", a.text)

    def test_entities(self):
        self.assertIn("123456789", self.ks.answer("What is the routing number?").text)

    def test_refusal_template(self):
        a = self.ks.answer("What is your 7/1 adjustable-rate mortgage rate?")
        self.assertFalse(a.confident)
        self.assertRegex(a.text, REFUSAL_RE)
        self.assertIsNone(re.search(r"\d", config.REFUSAL_TEXT))

    def test_determinism(self):
        q = "What is the 12-month certificate APY?"
        self.assertEqual(self.ks.answer(q).text, self.ks.answer(q).text)

    def test_never_raises(self):
        self.assertFalse(self.ks.answer("").confident)

    def test_conflicts(self):
        cs = self.ks.conflicts()
        auto = [c for c in cs if "60-month" in c.topic]
        self.assertTrue(auto)
        self.assertEqual(auto[0].resolution, "5.00%")
        self.assertIn("4.75%", auto[0].values)


if __name__ == "__main__":
    unittest.main()
