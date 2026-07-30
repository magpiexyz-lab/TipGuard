#!/usr/bin/env python3
"""Email classification for /iterate --cross DB signup counts."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from gclid_filter import is_real_gclid


RFC_RESERVED_TLDS = {".test", ".example", ".invalid", ".localhost", ".local"}
PLACEHOLDER_DOMAINS = {"example.com", "example.org", "example.net", "test.com", "email.com", "verify.com"}
DISPOSABLE_DOMAINS = {"gonrr.net", "nuitx.com", "cadinr.com", "dosbee.com"}

# Localpart values that are obviously form-placeholders, never real signups
# (e.g. you@company.com). Kept deliberately narrow — role addresses like
# admin@/info@/contact@ are NOT included because they can be real.
PLACEHOLDER_LOCALPARTS = {
    "you", "yourname", "your-name", "youremail", "your-email", "name",
    "firstname", "lastname", "fullname", "email", "example", "placeholder",
    "someone", "none",
}
# Delimited localpart tokens that mark an automated / manual test signup
# (e.g. perky-test-1444600@gmail.com, smoke-test@x, deploy@x). Matched as a
# whole token split on [._+-]; a real surname like "Testa" is NOT a token.
TEST_LOCALPART_TOKENS = {
    "test", "tests", "testing", "qa", "smoke", "smoketest", "staging",
    "sandbox", "demo", "dummy", "fake", "sample", "e2e", "mvptest",
    "healthcheck", "livecheck", "noreply", "no-reply", "seed", "seeds",
    "fixture", "mock", "preview",
}
DOMAIN_TEST_LABEL_TOKENS = {"test", "testing", "qa", "staging", "sandbox", "demo", "e2e"}
# Soft markers that only count as test when paired with a 5+ digit run
# (synthetic timestamp ids: testingtest900033300, launch-check-1775801680).
_LOCAL_SOFT = re.compile(r"(?:test|qa|smoke|demo|staging|sandbox|e2e|check|signup|newuser|trial|verify)")
_DIGIT_RUN = re.compile(r"\d{5,}")
_REPEATED_LOCAL_CHAR = re.compile(r"(.)\1\1\1")


def _localpart_test_reason(raw_local: str, tokens: set[str], placeholders: set[str]) -> str | None:
    """Return a reason string if the localpart looks like a test/placeholder, else None.

    Never keys off all-digit localparts — those are valid (e.g. QQ numbers
    like 2524621338@qq.com are real users).
    """
    rl = (raw_local or "").lower()
    if not rl:
        return None
    if rl in placeholders:
        return "placeholder-localpart"
    parts = [t for t in re.split(r"[._+\-]", rl) if t]
    if any(t in tokens for t in parts):
        return "localpart-test-token"
    if _REPEATED_LOCAL_CHAR.search(rl):
        return "localpart-mashed"
    if _LOCAL_SOFT.search(rl) and _DIGIT_RUN.search(rl):
        return "localpart-synthetic"
    return None


def _normalize_domain(value: str | None) -> str:
    v = (value or "").strip().lower()
    if not v:
        return ""
    if "://" in v:
        v = v.split("://", 1)[1]
    v = v.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in v:
        v = v.rsplit("@", 1)[1]
    if ":" in v:
        v = v.split(":", 1)[0]
    return v.lstrip("*.").strip(".")


def _domain_matches(domain: str, candidate: str | None) -> bool:
    c = _normalize_domain(candidate)
    return bool(c and (domain == c or domain.endswith("." + c)))


def _domain_test_label(domain: str, tokens: set[str]) -> bool:
    # Split labels on dot and hyphen. Equality catches testing.com via the
    # explicit "testing" token while avoiding word substrings like testimonial.
    for label in [p for p in re.split(r"[.-]", domain.lower()) if p]:
        if label in tokens:
            return True
    return False


def _levenshtein_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (0 if ca == cb else 1),
            ))
        previous = current
    return previous[-1]


def _fuzzy_team_domain(domain: str, team_domains: set[str]) -> bool:
    for td in team_domains:
        candidate = _normalize_domain(td)
        if candidate and _levenshtein_distance(domain, candidate) == 1:
            return True
    return False


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def internal_domains_for_mvp(config: dict[str, Any], mvp_name: str | None) -> tuple[str, ...]:
    """Return explicit product-owned domains configured for one MVP."""
    if not mvp_name:
        return ()
    mappings = config.get("mvp_mappings") or {}
    mapping = mappings.get(mvp_name) or {}
    domains: list[str] = []
    domains.extend(_as_list(mapping.get("deploy_domain")))

    cfg = config.get("email_filter") or {}
    product_domains = cfg.get("product_domains") or {}
    if isinstance(product_domains, dict):
        domains.extend(_as_list(product_domains.get(mvp_name)))

    normalized = [_normalize_domain(d) for d in domains]
    return tuple(d for d in normalized if d)


def gmail_normalize(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email:
        return email
    local, domain = email.rsplit("@", 1)
    if domain in {"gmail.com", "googlemail.com"}:
        local = local.split("+", 1)[0].replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def redact_email(email: str) -> str:
    email = (email or "").strip()
    if "@" not in email:
        return "***"
    local, domain = email.rsplit("@", 1)
    keep = local[:3] if len(local) >= 3 else local
    return f"{keep}***@{domain}"


def _email_sets(config: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    cfg = config.get("email_filter") or {}
    team = {gmail_normalize(e) for e in cfg.get("team_emails") or []}
    test = {gmail_normalize(e) for e in cfg.get("test_emails") or []}
    prefixes = {
        (p or "").strip().lower().replace(".", "")
        for p in cfg.get("plus_alias_team_prefixes") or []
    }
    return team, test, prefixes


def _rules(config: dict[str, Any]) -> dict[str, Any]:
    cfg = config.get("email_filter") or {}
    r = cfg.get("rules") or {}
    return {
        "test_tlds": set(r.get("test_tlds") or RFC_RESERVED_TLDS),
        "test_domains": set(r.get("test_domains") or PLACEHOLDER_DOMAINS),
        "disposable_domains": set(r.get("disposable_domains") or DISPOSABLE_DOMAINS),
        "test_suffixes": set(r.get("test_suffixes") or [".internal"]),
        "team_domains": set(r.get("team_domains") or []),
        "test_localpart_tokens": set(r.get("test_localpart_tokens") or TEST_LOCALPART_TOKENS),
        "placeholder_localparts": set(r.get("placeholder_localparts") or PLACEHOLDER_LOCALPARTS),
        "domain_test_label": bool(r.get("domain_test_label", True)),
        "domain_test_label_tokens": set(r.get("domain_test_label_tokens") or DOMAIN_TEST_LABEL_TOKENS),
    }


def classify_email(email: str, config: dict[str, Any], internal_domains=()) -> tuple[str, str]:
    """Return (category, reason): category is real/team/test."""
    email_l = (email or "").strip().lower()
    norm = gmail_normalize(email_l)
    if "@" not in norm:
        return "test", "malformed-email"
    local, domain = norm.rsplit("@", 1)
    domain = _normalize_domain(domain)
    team_emails, test_emails, plus_prefixes = _email_sets(config)
    rules = _rules(config)

    raw_local = email_l.rsplit("@", 1)[0] if "@" in email_l else local
    if "+" in raw_local:
        base = gmail_normalize(f"{raw_local.split('+', 1)[0]}@{domain}").split("@", 1)[0]
        if base in plus_prefixes or f"{base}@{domain}" in team_emails:
            return "test", "team-plus-alias"

    if norm in team_emails:
        return "team", "operator-team-email"
    if norm in test_emails:
        return "test", "operator-test-email"

    for internal_domain in internal_domains or ():
        if _domain_matches(domain, internal_domain):
            return "test", "product-own-domain"

    for td in rules["team_domains"]:
        if _domain_matches(domain, td):
            return "team", "team-domain"
    if _fuzzy_team_domain(domain, rules["team_domains"]):
        return "team", "team-domain-typo"

    for td in rules["test_domains"]:
        if _domain_matches(domain, td):
            return "test", "placeholder-domain"
    for dd in rules["disposable_domains"]:
        if _domain_matches(domain, dd):
            return "test", "disposable-domain"
    for suffix in rules["test_suffixes"]:
        if domain.endswith(suffix.lower()):
            return "test", "test-domain-suffix"
    for tld in rules["test_tlds"]:
        if domain.endswith(tld.lower()):
            return "test", "rfc-reserved-tld"
    if rules["domain_test_label"] and _domain_test_label(domain, rules["domain_test_label_tokens"]):
        return "test", "test-labeled-domain"

    localpart_reason = _localpart_test_reason(
        raw_local, rules["test_localpart_tokens"], rules["placeholder_localparts"]
    )
    if localpart_reason:
        return "test", localpart_reason

    return "real", "singleton-real"


def filter_signups(rows: list[dict[str, Any]], config: dict[str, Any], internal_domains=()) -> dict[str, Any]:
    """Classify rows and return counts plus a redacted audit trail."""
    audit = []
    counts: Counter[str] = Counter()
    real_times: list[str] = []
    saw_gclid_field = any(("gclid" in row or "click_id" in row) for row in rows)
    paid = 0
    for row in rows:
        email = row.get("email")
        if not email:
            counts["test"] += 1
            audit.append({"email_redacted": "***", "category": "test", "reason": "missing-email"})
            continue
        category, reason = classify_email(str(email), config, internal_domains=internal_domains)
        counts[category] += 1
        audit.append({
            "email_redacted": redact_email(str(email)),
            "category": category,
            "reason": reason,
        })
        if category == "real" and row.get("signup_at"):
            real_times.append(str(row["signup_at"]))
        if category == "real" and is_real_gclid(row.get("gclid") or row.get("click_id")):
            paid += 1

    return {
        "raw": len(rows),
        "real": counts["real"],
        "team": counts["team"],
        "test": counts["test"],
        "paid": paid if saw_gclid_field else None,
        "audit": audit,
        "first_real_signup_at": min(real_times) if real_times else None,
    }
