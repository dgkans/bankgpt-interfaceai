"""
Page-type classification and authority ranking.

A credit-union site repeats the same rate on rate sheets, product pages, calculators,
promo landing pages and years-old press releases. Which copy to believe is a policy
decision; this module applies the policy in config.AUTHORITY_RULES to a URL.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from . import config


@dataclass(frozen=True)
class Authority:
    """How much a page can be trusted, derived from its URL only."""
    tier: int        # 1 = most authoritative
    kind: str        # rate_sheet / product / reference / disclosure / calculator / promo / editorial
    segment: str     # "personal" or "business"
    legacy: bool     # served from a legacy host (e.g. info.dupaco.com)


def url_path(url: str) -> str:
    p = urlparse(url if "//" in url else "https://" + url)
    return (p.path or "/").lower()


def url_host(url: str) -> str:
    p = urlparse(url if "//" in url else "https://" + url)
    return p.netloc.lower()


def classify(url: str) -> Authority:
    """Authority of a page from its URL alone (deterministic, explainable)."""
    path = url_path(url)
    tier, kind = config.DEFAULT_TIER
    for rule_tier, rule_kind, pattern in config.AUTHORITY_RULES:
        if re.search(pattern, path):
            tier, kind = rule_tier, rule_kind
            break
    host = url_host(url)
    legacy = bool(host) and host.endswith("dupaco.com") and host != config.PRIMARY_HOST \
        and host != config.PRIMARY_HOST.replace("www.", "")
    if legacy:
        tier += config.LEGACY_HOST_PENALTY
    segment = "business" if config.BUSINESS_PATH_RE.search(path) else "personal"
    return Authority(tier=tier, kind=kind, segment=segment, legacy=legacy)
