# NOTES — "Knowledge system that knows what's true now"

**API keys needed: none.** No LLM, no paid API, no network calls at ingest or answer time.
Standard library only (`requirements.txt` is intentionally empty). Tested on Python 3.9.6,
3.11.17 (clean venv) and 3.13.

```bash
python harness/run_eval.py --submission submission --eval eval/public_eval.jsonl
python -m unittest discover -s submission/tests
```

## How it works

`solution.py` is a thin `build()`; the logic lives in the `kb/` package:

| module | job |
|---|---|
| `config.py` | every policy knob: authority tiers by URL, synonyms, qualifier words, thresholds, refusal text |
| `normalize.py` | cleanup (`\r\n` escapes, footnote digits glued to values such as `5.39% APR1`), money/percent/tier/model-year/term/date parsing, a small stemmer |
| `store.py` | one `SnapshotView` per crawl (pages, facts, passages, links, entities); parses are cached by content hash; `as_of` selection |
| `authority.py` | URL → tier / page kind / personal-vs-business segment |
| `extract.py` | markdown tables → `RowFact` (heading/caption/section, row label, typed values, "Rates are effective as of" date, "See details" link); `label: value` lines; prose passages; links |
| `entities.py` | routing number, phone, branch addresses (contact-page locator), published branch hours, "About Dupaco" boilerplate counts, "Nth time Forbes…" ordinals |
| `understand.py` | question → `Query` (term, model year, balance/loan amount, rate type, segment, superlative, answer shape, a date stated in the question) |
| `match.py` | scores table rows against the query: IDF word overlap + hard constraints (60-month never matches 48-month, 2025 only matches a model-year tier containing 2025, $15,000 only the balance tier containing it) + penalties for unrequested variants (jumbo, intro, Roth, refinance, business…) |
| `resolve.py` | decides which copy is current (rules below) |
| `structured.py` / `render.py` | single value, tier list, highest/lowest, yes/no, rendered with fixed templates |
| `retrieve.py` / `textual.py` | BM25 over prose for non-table questions, re-weighted by authority and age; links, hours, addresses, counts, dated events |
| `conflicts.py` | curated `conflicts()` |
| `system.py` | routing by question shape, sources, `explain()` debug helper |

All heavy work happens in `ingest` (~1–4 s for all five snapshots). `answer` is in-memory
lookups: p95 ≈ 0.05 s.

## What "current" means (`resolve.py`, one function per rule)

For a question, rows are scored; the best score decides *which fact* is asked about. Every
page whose best row scores at least 75 % of that (`PAGE_SCORE_RATIO`) is a candidate copy
of the same fact, and among those:

1. **`drop_expired`**: an offer whose stated end date is before the snapshot date is not current.
2. **`authority_order`, tier first**: rate sheets (`/rates`, `/business-rates`) and product pages
   (`/personal/…`, `/business/…`) = 1; contact/about/disclosure PDFs = 2; calculators, promo
   landing pages and anything unclassified = 3; blog/newsroom/dated posts = 4. A legacy host
   (`info.dupaco.com`) drops one tier.
3. **Recency within a tier**: latest in-page *effective date* of the matching table, then the
   product's canonical page (the page its rate tables link to as "See details"), then product
   page before rate sheet, then the newest crawl copy. The URL is the last tie-break, so the order is always the same.
4. **`tiers_are_not_conflicts`**: rows of one table that tie (balance / term / loan-amount /
   model-year tiers) are one product's tiers. They are listed together, never compared with each other.
5. Personal pages are preferred unless the question says "business". Business-only products
   (e.g. Business Platinum Visa) are added to "which cards do you offer?" list answers.

For non-table facts, the same ordering applies: tier, then the page's publication date (press
releases carry one), then crawl time. So the branch count comes from the most recently dated
press-release boilerplate, not from a 2022 release.

Losing values never appear in `text`. They go into `conflict_note` (with page and reason)
and `conflicts()`.

## `as_of`

`as_of=None` → newest snapshot. `as_of=D` → the latest snapshot taken on or before D. A date
before the first crawl uses the first snapshot and says so in `conflict_note`. A date stated
in the question ("as of May 2026", "in June 2026", "today (October 2026)") is used the same way
(end of that month). For "is X still open?", the stated closing date is compared with that date.
If a fact is missing from the chosen snapshot, older snapshots are searched (newest first) and
the note says where it was last stated (this is what the harness self-test expects for a page
that disappeared).

## Refusal policy

A fixed template with no digits, `confident=False`:
"I don't know — that isn't listed on the Dupaco website. Please contact Dupaco directly."
It is used when:
- a rate question names a product variant that the matched rows don't carry (7/1 ARM,
  construction or land loan, a jumbo term that isn't published…);
- no table row or passage clears its threshold;
- a named branch has no published address or hours (we never invent hours);
- any internal error happens (`answer()` never raises).

We never ask for ZIP codes, member numbers or authentication.

## Conflict policy (`conflicts()`)

Precision first. A conflict is reported only when, in the **newest snapshot**, two pages state
different values for the *same fact*: same segment, same term, identical balance/loan tier,
overlapping model-year range, same qualifier words (jumbo ≠ regular, Roth ≠ Traditional) and
similar product names. Each fact is reported once, from its most authoritative copy:
`values` = the winner first, then the stale values as printed; `resolution` = the winner;
`reason` = which page outranked which, and why. Branch-count boilerplate and "Nth time Forbes
recognized" counts are added the same way, resolved to the newest release. On the real data this gives
24 entries: stale calculator auto rates, a stale homebuying/refinance landing page mortgage
table, a promo page's old checking APY, branch counts, and Forbes counts. Rate *changes*
between snapshots are not reported as contradictions. They are answered through `as_of`.

## Consistency

Answers are rendered only from the resolved rows with fixed templates. No dates, counts or
other incidental numbers are added, so rewordings that resolve to the same rows give identical
text. Every sort has a stable final key.

## Known limitations

- Lexical matching only: questions that share no words with the page (deep paraphrase) may be
  refused or pick a nearby passage.
- Retrieval answers quote 1–2 sentences. Some questions need facts spread over several pages.
- "Last year" is not interpreted. Newest-dated statements win (e.g. Volunteer Time Off: the newest
  release, about 2024, wins over an older release about 2023).
- Branch hours exist only in branch-opening press releases, so general hours answers list
  the published schedules and ask which branch.

## Data handling

No page text is copied into code, tests or docs beyond tiny illustrative snippets. Tests use
synthetic fixtures. The supplied website snapshots (`snapshots_zip/`, `snapshots/0*/`) are
excluded from the repository by `.gitignore`; copy them in from the kit to run the eval.
No API keys are used or stored.

## Changelog (public eval / own paraphrase set; conflicts scored on the self-test)

| step | public final | paraphrase | traps | errors | p95 |
|---|---|---|---|---|---|
| starter | 0.093 | – | 0 | 0 | 0.10 s |
| table facts only | 0.225 | – | 2 | 0 | 0.00 s |
| authority across close matches + routing by shape | 0.593 | – | 2 | 0 | 0.03 s |
| stemming, plural APRs, branch names | 0.794 | – | 0 | 0 | 0.03 s |
| retrieval: named entities, lead paragraphs, FAQ merge | 0.918 | – | 0 | 0 | 0.04 s |
| section headings, list variants, canonical page | 0.941 | 0.923 | 0 | 0 | 0.04 s |
| paraphrase fixes (lobby "open", count words) | 0.941 | 0.962 | 0 | 0 | 0.05 s |
| self-test with conflict gold | 1.000 | – | 0 | 0 | 0.00 s |

Remaining public misses: `dup-005` has an empty `must_include`, so the scorer gives it 0
whatever the answer; `dup-088` expects the older Volunteer Time Off count (see limitations);
`dup-066` scores 0.85 because of source credit only.
