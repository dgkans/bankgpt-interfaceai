# Data notes (Phase 1 recon)

Snapshot sizes: 637 / 634 / 635 / 683 / 705 pages. Starter baseline: **0.093**.

## Initial assumptions about the data, checked

| claim | verdict |
|---|---|
| `manifest.json` has `snapshot_id`, `taken_on`, `pages[url,title,fetched_at,file]` | ✅ (plus `label`, `description`) |
| some `fetched_at` earlier than the snapshot date | ✅ e.g. latest: 681 pages fetched 09-28, others 08-27, 09-03, 06-09…06-15 |
| URL families | ✅ `learn` 255, `newsroom` 167, `business` 131, `calculators` 30, `hubfs` 28, `personal` 18, plus promo/LP pages; `/business/resources/` are member stories, not product pages |
| rates in markdown tables with tiers | ✅ term / balance / model-year / loan-amount columns |
| footnotes glued to values | ✅ `5.39% APR1`, `0.15%1`, `12.50% – 19.50%2` |
| "Rates are effective as of" per table, several per page | ✅ (Share Savings even carries two different dates) |
| literal `\\r\\n` | ✅ inside footnote paragraphs |
| stale copies | ✅ see below |
| rate vs APY etc. are different facts | ✅ |
| extra (not in prompt) | newsroom pages end with "Handpicked for You" teasers of *other* posts (other dates, values); we cut them. Post dates are the first long date under the byline. Branch hours exist only in branch-opening press releases. `/contact` has a 33-entry locator (addresses, no hours, no branch names). |

## Topic traces

| topic | pages | across snapshots | authoritative |
|---|---|---|---|
| 60-mo auto APR | `/rates`, `/personal/loans/auto-motorcycle-loans`, (05) `/personal/loans/auto-loans/`; stale copies on `/calculators/vehicle-affordability`, `/switch-and-earn`, and (01–04) `/personal/checking-accounts` | rate sheet: 2023-26 tier 5.19% (01–04) → 2024-27 tier 5.39% (05). Calculator/promo stuck at 2023–26 5.34% in every snapshot | product page / rate sheet |
| 10-mo jumbo special | `/rates`, `/personal/savings-account`, `/business-rates`, `/business/savings-accounts` | 3.90% APY (01–04) → 4.00% (05); 17-mo special appears in 03 (3.85%) → 04 (3.95%; `/business-rates` lagging at 3.85%) → 05 (4.10%, jumbo 4.20%) | rate sheet, by effective date |
| Share Savings tiers | `/rates`, `/personal/savings-account`; business copies | personal 0.15% for $10k–24,999.99 in all; `/business-rates` shows dividend 0.20% vs APY 0.15% (01–04) | personal rate sheet |
| 30-yr mortgage ($100k tier) | `/personal/loans/home-loans`, `/rates` (05), copies on `/personal/loans/home-improvement-loan/`; stale `/homebuying-guidance` (effective 04/22/2026, 5.750% / 5.884% APR in every snapshot), `/mortgage-refi` | 5.875% (01) → 6.250 (02) → 6.125 (03) → 6.375 (04) → 7.13% / 7.27% APR (05, effective 09/25/2026) | home-loans page |
| fee | the site publishes few fees as tables; the self-test covers "label: value" fee lines | – | – |
| branch closure | newsroom "plans Hy-Vee branch closure" (June 2025): closes March 31, 2026; members are pointed to Key West and Sycamore Street | same in all | newsroom post (only source) |
| branch count | "About Dupaco" boilerplate: 19/20/22/23/24 across releases; newest release (Apr 2026) says 22 | 24 present on 2 posts in 01–04 | newest dated release |
| routing number | `/contact`, `/business/cash-management`, checking pages, tax blog: 273974581 everywhere | stable | any; contact page |
| Forbes | 2020 / 2023 ("fourth time") / 2024 ("fifth time") releases | stable | newest release |

Trap values in the public eval that are **not** in any snapshot (271176899, 9.9%, "3% APY" as
written, "0.00%–0.35%") come from the old bot's own wrong answers, so they cannot be conflicts.

## Design decisions that came out of the recon (and why)

- One `RowFact` per table **row** with typed values (rate/APR/dividend/APY…), not one per cell:
  answers need the rate+APR pair of a row, and the row is what a judge can trace.
- Fact identity is matched at question time (scored rows plus hard constraints), not looked up from a
  precomputed canonical key. Pages describe the same product with different labels ("2023–26"
  vs "2024-27 Model Year", "Auto Loan Rates" vs "Auto & Motorcycle Loans"), so an exact key
  would split one fact into many.
- Extra modules: `match.py` (row scoring), `entities.py` (non-table facts), `structured.py` /
  `textual.py` (the answer paths), `contract_types.py` (contract import with fallback).
- Discrepancy between "a missing page is gone" and the harness: the self-test expects "$2.50" for a fee page that
  vanished from the newest snapshot. We follow the harness: fall back to older snapshots
  (newest first) when the fact is missing, and say so in `conflict_note`.
