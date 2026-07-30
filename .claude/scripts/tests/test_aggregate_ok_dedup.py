"""test_aggregate_ok_dedup.py — verifies aggregate_ok dedupes per-page
siblings via the shared selector helper (closes #1274 round-2 critic C12).

Without dedup: an OLD per-page trace with verdict=unresolved + a NEW
post-fix epoch trace with verdict=pass would BOTH appear as siblings;
the OLD one fails the predicate or-chain → aggregate_ok red even after
the re-spawn lands.

With dedup (this test): only the NEW (highest-epoch) trace per page key
is evaluated; the OLD trace stays on disk for HC3 forensic provenance
but does not gate.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".claude/scripts/evaluate-hard-gate-predicates.py"

_spec = importlib.util.spec_from_file_location("ehgp", SCRIPT)
ehgp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ehgp)


def _write_trace(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload))
    return path


def _make_traces_dir(tmp_path: Path) -> Path:
    d = tmp_path / "agent-traces"
    d.mkdir(parents=True)
    return d


def _aggregate_trace(spawn_indexes=(0,)) -> dict:
    return {
        "agent": "design-critic",
        "provenance": "lead-merge",
        "contributing_spawn_indexes": list(spawn_indexes),
        "status": "completed",
        "verdict": "pass",
    }


def test_old_unresolved_plus_new_pass_yields_aggregate_ok(tmp_path: Path) -> None:
    d = _make_traces_dir(tmp_path)
    _write_trace(
        d / "design-critic-home.json",
        {
            "agent": "design-critic", "page": "home",
            "status": "completed",
            "verdict": "unresolved", "result": "partial", "provenance": "self",
            "epoch": 0, "partial": False,
            "checks_performed": ["x"],
        },
    )
    _write_trace(
        d / "design-critic-home--epoch1.json",
        {
            "agent": "design-critic", "page": "home",
            "status": "completed",
            "verdict": "pass", "result": "fixed", "provenance": "self",
            "epoch": 1, "partial": False,
            "checks_performed": ["x", "rerun"],
            "fixes_applied": 1,
        },
    )
    aggr = _aggregate_trace()
    assert ehgp.aggregate_ok(aggr, "design-critic", str(d)) is True


def test_new_unresolved_overrides_old_pass_yields_aggregate_red(tmp_path: Path) -> None:
    """If the latest epoch is RED, aggregate_ok must reflect that — the
    selector picks the latest, so a regression is properly surfaced."""
    d = _make_traces_dir(tmp_path)
    _write_trace(
        d / "design-critic-home.json",
        {
            "agent": "design-critic", "page": "home",
            "status": "completed",
            "verdict": "pass", "result": "clean", "provenance": "self",
            "epoch": 0, "partial": False,
            "checks_performed": ["x"],
        },
    )
    _write_trace(
        d / "design-critic-home--epoch1.json",
        {
            "agent": "design-critic", "page": "home",
            "status": "completed",
            "verdict": "unresolved", "result": "partial", "provenance": "self",
            "epoch": 1, "partial": False,
            "checks_performed": ["x", "rerun"],
        },
    )
    aggr = _aggregate_trace()
    assert ehgp.aggregate_ok(aggr, "design-critic", str(d)) is False


def test_single_sibling_no_epochs_unchanged(tmp_path: Path) -> None:
    """No --epoch suffix anywhere → existing aggregate_ok behavior holds."""
    d = _make_traces_dir(tmp_path)
    _write_trace(
        d / "design-critic-home.json",
        {
            "agent": "design-critic", "page": "home",
            "status": "completed",
            "verdict": "pass", "result": "clean", "provenance": "self",
            "partial": False,
            "checks_performed": ["x"],
        },
    )
    aggr = _aggregate_trace()
    assert ehgp.aggregate_ok(aggr, "design-critic", str(d)) is True


def test_shared_and_aggregate_excluded(tmp_path: Path) -> None:
    """Helper drops design-critic-shared.json + design-critic.json."""
    d = _make_traces_dir(tmp_path)
    _write_trace(
        d / "design-critic.json",
        _aggregate_trace(),  # the aggregate itself; must not be evaluated
    )
    _write_trace(
        d / "design-critic-shared.json",
        {
            "agent": "design-critic", "page": "shared",
            "status": "completed",
            "verdict": "pass", "result": "clean", "provenance": "self",
            "partial": False, "checks_performed": ["x"],
        },
    )
    _write_trace(
        d / "design-critic-home.json",
        {
            "agent": "design-critic", "page": "home",
            "status": "completed",
            "verdict": "pass", "result": "clean", "provenance": "self",
            "partial": False, "checks_performed": ["x"],
        },
    )
    aggr = _aggregate_trace()
    assert ehgp.aggregate_ok(aggr, "design-critic", str(d)) is True


def test_multi_pages_one_page_resolved_via_epoch(tmp_path: Path) -> None:
    """Two pages: page A has only epoch0=pass, page B has epoch0=unresolved
    + epoch1=pass. Aggregate must be green (latest of each wins)."""
    d = _make_traces_dir(tmp_path)
    _write_trace(
        d / "design-critic-page-a.json",
        {
            "agent": "design-critic", "page": "page-a",
            "status": "completed",
            "verdict": "pass", "result": "clean", "provenance": "self",
            "partial": False, "checks_performed": ["x"],
        },
    )
    _write_trace(
        d / "design-critic-page-b.json",
        {
            "agent": "design-critic", "page": "page-b",
            "status": "completed",
            "verdict": "unresolved", "result": "partial", "provenance": "self",
            "epoch": 0, "partial": False, "checks_performed": ["x"],
        },
    )
    _write_trace(
        d / "design-critic-page-b--epoch1.json",
        {
            "agent": "design-critic", "page": "page-b",
            "status": "completed",
            "verdict": "pass", "result": "fixed", "provenance": "self",
            "epoch": 1, "partial": False, "checks_performed": ["x", "rerun"],
            "fixes_applied": 1,
        },
    )
    aggr = _aggregate_trace()
    assert ehgp.aggregate_ok(aggr, "design-critic", str(d)) is True
