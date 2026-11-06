"""
All tunable rules in one place: page authority tiers, synonyms, thresholds, templates.

Everything a judge might ask "why did it pick that?" about is a named constant here,
so the decision logic in the other modules stays generic and the policy stays readable.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- authority tiers
# Lower number = more authoritative. Rules are tried in order; first match wins.
# (tier, kind, path regex matched against the URL path, lower-cased)
AUTHORITY_RULES = [
    (1, "rate_sheet", r"^/(rates|business-rates)(/|$)"),
    (4, "editorial", r"^/business/resources/"),           # member stories, not product pages
    (1, "product", r"^/(personal|business)(/|$)"),
    (1, "product", r"^/(savings-account|checking|loans|personal-loans|mobile|online-and-mobile-banking|"
                   r"membership|protection|financial-services|manage-account-alerts)(/|$)"),
    (2, "reference", r"^/(contact|about|connect|disclosures|privacy-policy|digital-privacy-policy)(/|$)"),
    (2, "disclosure", r"^/hubfs/"),
    (2, "home", r"^/?$"),
    (3, "calculator", r"^/(calculators|business-calculators)(/|$)"),
    (4, "editorial", r"^/(learn|newsroom|dupacodaily|community)(/|$)"),
    (4, "editorial", r"^/\d{4}/\d{2}/"),                   # dated legacy blog posts
]
DEFAULT_TIER = (3, "promo")          # landing pages, grants, campaigns: often stale copies
LEGACY_HOST_PENALTY = 1              # info.dupaco.com ranks one tier below www
PRIMARY_HOST = "www.dupaco.com"
BUSINESS_PATH_RE = re.compile(r"^/(business|business-rates|business-calculators)(/|-|$)")

# ---------------------------------------------------------------- question normalisation
# Applied as regex substitutions on the lower-cased question, in order.
SYNONYMS = [
    (r"\bcds?\b", "certificate"),
    (r"\bcertificates? of deposits?\b", "certificate"),
    (r"\bcertificates? of accounts?\b", "certificate"),
    (r"\bshare certificates?\b", "certificate"),
    (r"\bterm share certificates?\b", "certificate"),
    (r"\bcertificates\b", "certificate"),
    (r"\bmortgages?\b", "home loan"),
    (r"\bhome loans\b", "home loan"),
    (r"\bheloc\b", "home equity line of credit"),
    (r"\bcredit cards\b", "credit card"),
    (r"\bvisas\b", "visa"),
    (r"\bannual percentage yield\b", "apy"),
    (r"\bannual percentage rate\b", "apr"),
    (r"\byield\b", "apy"),
    (r"\bdividends?\b", "dividend"),
    (r"\bcars?\b|\bvehicles?\b|\btrucks?\b", "auto"),
    (r"\bmotorcycles?\b", "motorcycle"),
    (r"\bmoney market\b", "money market"),
    (r"\bhsa\b", "health savings account"),
    (r"\bira\b", "ira"),
    (r"\bsavings accounts?\b", "savings"),
    (r"\bchecking accounts?\b", "checking"),
    (r"\bfirst rate\b", "1st rate"),
    (r"\bboats?\b", "boat"),
    (r"\brvs?\b", "rv"),
]

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "seventeen": 17,
    "eighteen": 18, "twenty": 20, "thirty": 30,
}

# Words that carry no product meaning in a question.
STOPWORDS = set("""
a an the is are was were be been of for on in at to and or what whats what's which who how
do does did can could would should i me my we our you your it its this that these those
there their with by from as about any all get give tell please current currently now today
right rate rates interest apy apr dividend much dupaco dupacos dupaco's offer offers have has
know like want need see find show list provide month months year years term mo yr
""".split())

# Qualifier words: if a table row carries one of these and the question does not,
# the row is a different product variant and is penalised (e.g. "jumbo", "intro").
QUALIFIER_WORDS = {
    "jumbo", "special", "introductory", "intro", "roth", "traditional", "ira", "refinance",
    "business", "balance", "transfer", "rewards", "standard", "kasasa", "youth", "student",
    "equity", "improvement", "boat", "rv", "atv", "snowmobile", "jet", "variable", "fixed",
    "purchase", "holiday", "launchpad", "bright", "investor", "high", "health", "club",
}
# Qualifiers that only weakly separate variants (site leads with them anyway).
SOFT_QUALIFIERS = {"fixed", "standard", "purchase", "variable"}

# ---------------------------------------------------------------- matching thresholds
MIN_TABLE_SCORE = 2.0          # below this the structured path declines (falls to retrieval)
PAGE_SCORE_RATIO = 0.75       # pages scoring >= 75% of the best match compete on authority
TABLE_TIE_EPSILON = 0.25       # rows within this of the best score are "the same fact family"
QUALIFIER_PENALTY = 1.5        # per unrequested hard qualifier on a row
SOFT_QUALIFIER_PENALTY = 0.2
LIST_QUALIFIER_FACTOR = 0.1    # list questions ("what cards do you offer") keep all variants
MIN_RETRIEVAL_SCORE = 6.0      # BM25 floor; below it we refuse rather than guess
MIN_QUERY_COVERAGE = 0.3       # share of rare question terms a retrieved passage must contain
MAX_SOURCES = 3
MAX_ANSWER_CHARS = 320         # retrieval answers: best sentence + the next one if it fits
MAX_LIST_ROWS = 14             # cap rows rendered for "list all" answers
RECENCY_HALF_LIFE_DAYS = 365   # editorial pages lose half their weight per year of age
TIER_WEIGHT = {1: 1.0, 2: 0.9, 3: 0.55, 4: 0.8, 5: 0.35}

# ---------------------------------------------------------------- templates
REFUSAL_TEXT = ("I don't know — that isn't listed on the Dupaco website. "
                "Please contact Dupaco directly.")

# Expired-offer markers on a line, e.g. "(offer ended 2025-09-30)", "offer expires 9/30/2025".
EXPIRED_OFFER_RE = re.compile(
    r"\b(?:offer|promotion|special|promo)?\s*(?:ended|ends|expired|expires|valid through|through)\s+"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})", re.I)

# Product-variant words: if the question names one of these and the matched row does not
# carry it, the site does not publish that variant (e.g. a 7/1 ARM or a construction-loan
# rate) and we refuse instead of quoting the nearest other product.
PRODUCT_VARIANT_TERMS = {
    "adjustable", "arm", "construction", "land", "lot", "jumbo", "fha", "va", "usda", "bridge",
    "reverse", "balloon", "interest-only", "sba", "agricultural", "farm", "commercial", "rental",
    "investment", "condo", "manufactured", "mobile", "solar", "tractor", "private", "payday",
    "title", "pawn", "overdraft", "wire", "cashier", "money order", "notary", "coin",
    "roth", "traditional", "ira", "hsa", "health", "kasasa", "youth", "student", "bright",
    "launchpad", "holiday", "rewards", "platinum", "business", "motorcycle", "boat", "rv",
    "atv", "snowmobile", "heloc", "equity", "improvement", "refinance", "special",
}
