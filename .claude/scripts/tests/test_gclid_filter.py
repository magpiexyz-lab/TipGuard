#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/gclid_filter.py."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from gclid_filter import (  # noqa: E402
    PAID_GCLID_EXPR,
    PAID_GCLID_FILTER,
    SYNTHETIC_GCLID_PREFIX,
    is_real_gclid,
)


def test_real_gclid_search_cpc():
    """Cj-prefixed Search CPC gclid (50+ chars) is accepted."""
    assert is_real_gclid("Cj0KCQjwhLPOBhBiEiwA8_wJHI_q6feRhjTZhdqIfEcj1e9nXqMORE_REAL")


def test_real_gclid_pmax():
    """EAI-prefixed Performance Max / Display gclid (60+ chars) is accepted."""
    assert is_real_gclid(
        "EAIaIQobChMI_TEST_INVESTIGATION_2026051300000_LONGENOUGH_PADDING"
    )


def test_real_gclid_cja():
    """CIa-prefixed retargeting gclid is accepted when long enough."""
    assert is_real_gclid("CIa-PADDED_TO_50_CHARS_AT_LEAST_FOR_THIS_TEST_XXXXX")


def test_short_test_excluded():
    """Short 12-char test sentinel rejected by length."""
    assert not is_real_gclid("test123")


def test_manual_verify_excluded_by_prefix():
    """`MANUAL_VERIFY_CHECK_*` padded > 40 chars is rejected by prefix."""
    assert not is_real_gclid("MANUAL_VERIFY_CHECK_PADDED_TO_50_CHARS_FOR_TEST_XX")


def test_analytics_verify_excluded():
    """Real-world bug: 32-char operator string slipped through `length>30`.

    Confirms the tightened `length>40 + prefix` filter rejects it.
    """
    assert not is_real_gclid("analytics-verify-2026050720272")


def test_short_real_prefix_excluded():
    """Real prefix but too short → rejected by length."""
    assert not is_real_gclid("Cj0KCQ")


def test_ads_ready_synthetic_prefix_excluded():
    """Synthetic /ads-ready gclids mimic Cj format but must not count as paid traffic."""
    synthetic = SYNTHETIC_GCLID_PREFIX + "PADDED_TO_LOOK_LONG_ENOUGH_FOR_FILTER"
    assert not is_real_gclid(synthetic)


def test_none_excluded():
    assert not is_real_gclid(None)


def test_empty_excluded():
    assert not is_real_gclid("")


def test_non_string_excluded():
    """Defensive: non-string input doesn't crash; returns False."""
    assert not is_real_gclid(123)  # type: ignore[arg-type]


def test_filter_sql_renders():
    """Smoke test: filter constants are well-formed SQL fragments."""
    assert "$session_entry_gclid" in PAID_GCLID_FILTER
    assert "properties.gclid" in PAID_GCLID_FILTER
    assert "startsWith" in PAID_GCLID_FILTER
    assert "AND NOT startsWith" in PAID_GCLID_FILTER
    assert SYNTHETIC_GCLID_PREFIX in PAID_GCLID_FILTER
    assert "40" in PAID_GCLID_FILTER
    # PAID_GCLID_EXPR is the operand reused 5 times in the filter expression
    assert PAID_GCLID_FILTER.count(PAID_GCLID_EXPR) >= 4


def test_expr_uses_coalesce():
    """PAID_GCLID_EXPR must read from BOTH $session_entry_gclid and properties.gclid."""
    assert "coalesce" in PAID_GCLID_EXPR
    assert "$session_entry_gclid" in PAID_GCLID_EXPR
    assert "properties.gclid" in PAID_GCLID_EXPR


if __name__ == "__main__":
    try:
        import pytest
        sys.exit(pytest.main([__file__, "-v"]))
    except ImportError:
        # Fallback: run tests directly if pytest unavailable
        import inspect
        passed = 0
        failed = []
        for name, fn in list(globals().items()):
            if name.startswith("test_") and inspect.isfunction(fn):
                try:
                    fn()
                    print(f"PASS  {name}")
                    passed += 1
                except AssertionError as e:
                    print(f"FAIL  {name}: {e}")
                    failed.append(name)
        print(f"\n{passed} passed, {len(failed)} failed")
        sys.exit(1 if failed else 0)
