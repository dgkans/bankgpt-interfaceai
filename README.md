# Knowledge system that knows what's true now

A question-answering system over five crawls of a credit union's website (May–Sep 2026).
It answers with the **current**, **correctly tiered** value, cites the page it came from,
lists the places where the site contradicts itself, and says "I don't know" when the site
doesn't publish the answer.

- Pure Python standard library: no LLM, no API keys, no network calls.
- Deterministic: the same question always gets the same answer.
- Fast: every snapshot is parsed once at ingest; answers are in-memory lookups.

## Results

| Run | Score | Notes |
|---|---|---|
| Starter solution (baseline) | 0.093 | public practice set |
| **This solution, public practice set** (40 questions) | **0.941** | 0 errors, 0 stale-value ("trap") hits, consistency 1.0, p95 latency ≈ 0.05 s |
| Own reworded + "as of" question set (`dev/paraphrase_eval.jsonl`, 52 questions) | 0.962 | guard against overfitting the public questions |
| Harness self-test, including conflict scoring | 1.000 | conflict found, correct winner |

Ingest of all five snapshots takes about 1–4 s. Tested on Python 3.9, 3.11 (clean venv) and 3.13.

## Quick start

The website snapshots are **not** in this repo (they were supplied for the assignment only).
Copy the kit's `snapshots_zip/` folder into the repo root first; the scorer unpacks it on the first run.

```bash
git clone https://github.com/dgkans/bankgpt-interfaceai.git
cd bankgpt-interfaceai
cp -R /path/to/hackathon-knowledge-kit-participant/snapshots_zip .   # supplied snapshots

python -m pip install -r requirements.txt        # nothing to install: standard library only
python harness/run_eval.py --submission submission --eval eval/public_eval.jsonl
python -m unittest discover -s submission/tests

# Self-test with conflict scoring (runs without the real snapshots)
python harness/run_eval.py --submission submission --snapshots harness/selftest/snapshots \
  --eval harness/selftest/eval.jsonl --conflicts-gold harness/selftest/conflicts_gold.json --out results/selftest
```

## How it decides what's true now

1. **Keep every version.** Each snapshot is stored as its own view of the whole site, so
   `answer(q, as_of="2026-05-31")` uses the latest crawl taken on or before that date. Dates
   written in the question ("as of May 2026") work the same way.
2. **Extract structured facts.** Each rate-table row becomes a fact with everything that makes
   it distinct: product, term, balance / loan-amount / model-year tier, rate type (APY,
   dividend, APR, rate), personal vs business, and the table's "Rates are effective as of" date.
3. **Rank copies by authority, then recency.** Rate sheets and product pages beat
   contact/disclosure pages. Those beat calculators and promo pages, which beat blogs and
   press releases. Within a tier, the latest effective (or publication) date wins. Expired offers are dropped.
4. **Tiers are not conflicts.** Rows of one table are shown together, never compared with each other.
5. **Never hedge in the answer.** Losing values go to `conflict_note` and `conflicts()`, never
   into the answer text.
6. **Refuse honestly.** If the asked-for variant isn't published (e.g. a 7/1 ARM rate, a
   construction-loan rate, hours for an unknown branch), the answer is a fixed
   "I don't know…" with `confident=False` and no numbers.

Non-table questions (programs, eligibility, branch news, hours, addresses) use a small BM25
index over prose, re-weighted by page authority and age. `conflicts()` reports only
contradictions still visible in the newest crawl, once per fact, resolved to the authoritative value.

Full design notes, rules and limitations: **[submission/NOTES.md](submission/NOTES.md)**.
Data exploration and topic traces across snapshots: [dev/DATA_NOTES.md](dev/DATA_NOTES.md).

## Repository layout

```
submission/            the solution (what the scorer loads)
  solution.py          build() -> KnowledgeSystem
  kb/                  config, normalize, store, authority, extract, entities, understand,
                       match, resolve, structured, render, retrieve, textual, conflicts, system
  tests/               unittest suite on synthetic fixtures (no site text)
  NOTES.md             approach, "what is current" rules, as_of, conflicts, refusals, limitations
  requirements.txt     empty: standard library only
dev/                   recon notes, own paraphrase/as-of eval set, debug helpers (not used at runtime)
harness/, eval/, starter/   supplied scoring kit (unchanged)
KIT_README.md          the kit's original README
```

## API keys

None.
