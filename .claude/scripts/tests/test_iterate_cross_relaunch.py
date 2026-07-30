#!/usr/bin/env python3
"""Tests for .claude/scripts/lib/iterate_cross_relaunch.py.

Run:
  python3 .claude/scripts/tests/test_iterate_cross_relaunch.py
  # OR:
  python3 -m pytest .claude/scripts/tests/test_iterate_cross_relaunch.py -v
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import iterate_cross_relaunch as rl  # noqa: E402


def test_parse_relaunch_at_valid_and_empty():
    assert rl.parse_relaunch_at("2026-07-25") == "2026-07-25"
    assert rl.parse_relaunch_at("  2026-07-25  ") == "2026-07-25"
    assert rl.parse_relaunch_at("2026-07-25T13:04:00Z") == "2026-07-25"
    assert rl.parse_relaunch_at("2026-07-25 09:00:00") == "2026-07-25"
    assert rl.parse_relaunch_at(None) is None
    assert rl.parse_relaunch_at("") is None
    assert rl.parse_relaunch_at("   ") is None


def test_parse_relaunch_at_rejects_garbage():
    for bad in ("next week", "07/25/2026", "2026-7-5", "2026-13-01", "2026-02-30"):
        try:
            rl.parse_relaunch_at(bad)
            raise AssertionError(f"expected ValueError for {bad!r}")
        except ValueError:
            pass


def test_relaunch_at_for_reads_mapping():
    mm = {"mooncub": {"phase1_relaunch_at": "2026-07-25"}, "botscore": {}}
    assert rl.relaunch_at_for("mooncub", mm) == "2026-07-25"
    assert rl.relaunch_at_for("botscore", mm) is None
    assert rl.relaunch_at_for("absent", mm) is None
    assert rl.relaunch_at_for("mooncub", None) is None


def test_posthog_lower_bound_expr():
    assert rl.posthog_lower_bound_expr(365, None) == "now() - INTERVAL 365 DAY"
    expr = rl.posthog_lower_bound_expr(365, "2026-07-25")
    assert expr == "greatest(now() - INTERVAL 365 DAY, toDateTime('2026-07-25 00:00:00'))"


def test_postgres_lower_bound_expr():
    assert (
        rl.postgres_lower_bound_expr("created_at", 90, None)
        == "\"created_at\" >= now() - INTERVAL '90 days'"
    )
    expr = rl.postgres_lower_bound_expr("created_at", 90, "2026-07-25")
    assert "greatest(" in expr
    assert "timestamptz '2026-07-25'" in expr
    assert expr.startswith('"created_at" >= greatest(')


def test_campaign_passes_relaunch():
    # No relaunch → everything counts.
    assert rl.campaign_passes_relaunch("2026-01-01", None) is True
    assert rl.campaign_passes_relaunch("", None) is True
    # With relaunch → only on/after the cut, and only valid dates.
    assert rl.campaign_passes_relaunch("2026-07-25", "2026-07-25") is True   # inclusive
    assert rl.campaign_passes_relaunch("2026-07-26", "2026-07-25") is True
    assert rl.campaign_passes_relaunch("2026-07-01", "2026-07-25") is False  # old flight
    # Missing/malformed Start date under an active relaunch is conservative (drop).
    assert rl.campaign_passes_relaunch("", "2026-07-25") is False
    assert rl.campaign_passes_relaunch(None, "2026-07-25") is False
    assert rl.campaign_passes_relaunch("garbage", "2026-07-25") is False


def test_window_never_widens_past_global():
    # greatest() guarantees the relaunch bound only narrows, never widens: the
    # expression always contains the global window term as a floor.
    expr = rl.posthog_lower_bound_expr(30, "2026-07-25")
    assert "now() - INTERVAL 30 DAY" in expr


if __name__ == "__main__":
    import inspect

    failed = 0
    passed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn) and inspect.signature(fn).parameters == {}:
            try:
                fn()
                print(f"PASS  {name}")
                passed += 1
            except Exception as e:
                print(f"FAIL  {name}: {e!r}")
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
