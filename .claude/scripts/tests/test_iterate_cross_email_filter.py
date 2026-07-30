#!/usr/bin/env python3
"""Tests for iterate_cross_email_filter.py."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from iterate_cross_email_filter import classify_email, filter_signups, gmail_normalize, redact_email  # noqa: E402


CFG = {
    "email_filter": {
        "rules": {
            "test_tlds": [".test", ".example", ".invalid", ".localhost", ".local"],
            "test_domains": ["example.com", "example.org", "example.net", "test.com", "email.com", "verify.com"],
            "test_suffixes": [".internal"],
            "team_domains": ["magpiexyz.io", "draftlabs.org"],
        },
        "team_emails": ["oculusmetaverse21@gmail.com", "anuragiitjee@gmail.com"],
        "plus_alias_team_prefixes": ["oculusmetaverse21"],
        "test_emails": ["known.real.looking@gmail.com"],
    }
}


def test_rfc_reserved_and_placeholder_domains_are_test():
    assert classify_email("a@test.example", CFG) == ("test", "rfc-reserved-tld")
    assert classify_email("a@site.local", CFG) == ("test", "rfc-reserved-tld")
    assert classify_email("a@example.com", CFG) == ("test", "placeholder-domain")


def test_team_domains_include_subdomains():
    assert classify_email("dev@magpiexyz.io", CFG) == ("team", "team-domain")
    assert classify_email("dev@gapsmith.draftlabs.org", CFG) == ("team", "team-domain")


def test_gmail_normalization_and_operator_overrides():
    assert gmail_normalize("anurag.iitj.ee@gmail.com") == "anuragiitjee@gmail.com"
    assert classify_email("anurag.iitj.ee@gmail.com", CFG) == ("team", "operator-team-email")
    assert classify_email("known.real.looking@gmail.com", CFG) == ("test", "operator-test-email")


def test_plus_alias_for_team_prefix_is_test():
    assert classify_email("oculusmetaverse21+foundry@gmail.com", CFG) == ("test", "team-plus-alias")


def test_redact_email_never_keeps_full_local_part():
    assert redact_email("anything@x.com") == "any***@x.com"
    assert redact_email("ab@x.com") == "ab***@x.com"


def test_localpart_test_token_on_real_domain_is_test():
    # The main leak class: automated test signups on real mailbox domains.
    assert classify_email("perky-test-1444600@gmail.com", CFG) == ("test", "localpart-test-token")
    assert classify_email("perky-test-2502100@qq.com", CFG) == ("test", "localpart-test-token")
    assert classify_email("test-signup-1778592194@gmail.com", CFG) == ("test", "localpart-test-token")
    assert classify_email("smoke-test@outlook.com", CFG) == ("test", "localpart-test-token")
    assert classify_email("qa@hotmail.com", CFG) == ("test", "localpart-test-token")


def test_seed_fixture_mock_localpart_token_is_test():
    assert classify_email("seed-ahmad-k@gmail.com", CFG) == ("test", "localpart-test-token")
    assert classify_email("fixture-user@gmail.com", CFG) == ("test", "localpart-test-token")
    assert classify_email("mock.user@gmail.com", CFG) == ("test", "localpart-test-token")
    assert classify_email("preview+launch@gmail.com", CFG) == ("test", "localpart-test-token")


def test_synthetic_timestamp_localpart_is_test():
    assert classify_email("testingtest900033300@gmail.com", CFG) == ("test", "localpart-synthetic")
    assert classify_email("launch-check-1775801680@gmail.com", CFG) == ("test", "localpart-synthetic")


def test_placeholder_localpart_is_test():
    assert classify_email("you@company.com", CFG) == ("test", "placeholder-localpart")
    assert classify_email("name@somerealco.com", CFG) == ("test", "placeholder-localpart")


def test_test_domains_match_subdomains():
    # example.com subdomain must be caught even when localpart is not test-y.
    assert classify_email("anybody@subshield.example.com", CFG) == ("test", "placeholder-domain")


def test_test_labeled_domain_is_test():
    assert classify_email("launch@rubberduck-test.com", CFG) == ("test", "test-labeled-domain")
    assert classify_email("hi@test-app.io", CFG) == ("test", "test-labeled-domain")
    assert classify_email("micheal@testing.com", CFG) == ("test", "test-labeled-domain")


def test_disposable_domain_is_test():
    assert classify_email("random@gonrr.net", CFG) == ("test", "disposable-domain")


def test_fuzzy_team_domain_typo_is_team():
    assert classify_email("priyanshu@magpiexy.io", CFG) == ("team", "team-domain-typo")


def test_product_owned_internal_domain_is_test():
    assert classify_email(
        "founder@app.alpha.dev",
        CFG,
        internal_domains=("alpha.dev",),
    ) == ("test", "product-own-domain")


def test_repeated_char_localpart_is_test():
    assert classify_email("ahmaddddddddddaasa@gmail.com", CFG) == ("test", "localpart-mashed")


def test_false_positives_stay_real():
    # QQ numbers are all-digit real users — must never be flagged.
    assert classify_email("2524621338@qq.com", CFG) == ("real", "singleton-real")
    # Real customer on company.com (existing design intent — not blacklisted).
    assert classify_email("customer@company.com", CFG) == ("real", "singleton-real")
    # Surnames / words containing "test" as a substring are not tokens.
    assert classify_email("testa@gmail.com", CFG) == ("real", "singleton-real")
    assert classify_email("latest.deals@gmail.com", CFG) == ("real", "singleton-real")
    # "test" substring in domain label but not delimited (fastest != test).
    assert classify_email("hello@fastest.com", CFG) == ("real", "singleton-real")
    assert classify_email("hello@testimonial.com", CFG) == ("real", "singleton-real")
    # Test-token prefixes inside real company domains must not be over-matched.
    assert classify_email("hello@qantas.com", CFG) == ("real", "singleton-real")
    assert classify_email("hello@democrat.com", CFG) == ("real", "singleton-real")
    assert classify_email("hello@e2enetworks.com", CFG) == ("real", "singleton-real")
    assert classify_email("hello@sandboxfinancial.com", CFG) == ("real", "singleton-real")
    # Soft marker without a 5+ digit run stays real.
    assert classify_email("contest2024@gmail.com", CFG) == ("real", "singleton-real")


def test_filter_signups_counts_and_redacts():
    rows = [
        {"email": "real.user@example.org", "signup_at": "2026-05-01T00:00:00Z"},
        {"email": "customer@company.com", "signup_at": "2026-05-03T00:00:00Z"},
        {"email": "dev@magpiexyz.io", "signup_at": "2026-05-02T00:00:00Z"},
    ]
    result = filter_signups(rows, CFG)
    assert result["raw"] == 3
    assert result["real"] == 1
    assert result["team"] == 1
    assert result["test"] == 1
    assert result["first_real_signup_at"] == "2026-05-03T00:00:00Z"
    dumped = json.dumps(result)
    assert "customer@company.com" not in dumped
    assert "cus***@company.com" in dumped
