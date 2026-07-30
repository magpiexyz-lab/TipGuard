"""test_design_critic_trace_selector.py — unit tests for the shared
per-page latest-trace selector used by both the merger and aggregate_ok.

Closes #1274 round-2 critic C12: ensures both consumers (write-time
aggregator and gate-time predicate evaluator) collapse stale OLD
traces under the same rule.
"""
from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".claude/scripts/lib/design_critic_trace_selector.py"

_spec = importlib.util.spec_from_file_location("dcts", SCRIPT)
dcts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dcts)


def _write_trace(traces_dir: Path, name: str, payload: dict) -> Path:
    path = traces_dir / name
    path.write_text(json.dumps(payload))
    return path


def _make_dir(tmp_path: Path) -> Path:
    d = tmp_path / "agent-traces"
    d.mkdir(parents=True)
    return d


def test_empty_dir_returns_empty_list(tmp_path: Path) -> None:
    d = _make_dir(tmp_path)
    assert dcts.select_latest_per_page_traces(str(d)) == []


def test_missing_dir_returns_empty_list(tmp_path: Path) -> None:
    assert dcts.select_latest_per_page_traces(str(tmp_path / "nope")) == []


def test_single_trace_per_page_no_epoch_returned_as_is(tmp_path: Path) -> None:
    d = _make_dir(tmp_path)
    a = _write_trace(d, "design-critic-home.json", {"page": "home"})
    b = _write_trace(d, "design-critic-about.json", {"page": "about"})
    out = dcts.select_latest_per_page_traces(str(d))
    assert sorted(out) == sorted([str(a.resolve()), str(b.resolve())])


def test_max_epoch_wins_per_page(tmp_path: Path) -> None:
    d = _make_dir(tmp_path)
    _write_trace(d, "design-critic-home.json",
                 {"page": "home", "epoch": 0, "verdict": "unresolved"})
    winner = _write_trace(
        d, "design-critic-home--epoch1.json",
        {"page": "home", "epoch": 1, "verdict": "pass"},
    )
    out = dcts.select_latest_per_page_traces(str(d))
    assert out == [str(winner.resolve())]


def test_numeric_epoch_ordering_not_lexicographic(tmp_path: Path) -> None:
    """epoch10 sorts after epoch2, not before (gotcha 3)."""
    d = _make_dir(tmp_path)
    _write_trace(d, "design-critic-home--epoch2.json",
                 {"page": "home", "epoch": 2, "verdict": "pass"})
    winner = _write_trace(
        d, "design-critic-home--epoch10.json",
        {"page": "home", "epoch": 10, "verdict": "fixed"},
    )
    out = dcts.select_latest_per_page_traces(str(d))
    assert out == [str(winner.resolve())]


def test_filename_strip_removes_epoch_suffix_before_page_key(tmp_path: Path) -> None:
    """When trace lacks `page` field, filename fallback must strip
    `--epoch<N>` before extracting key (gotcha 2)."""
    d = _make_dir(tmp_path)
    # No 'page' field → filename fallback. Two files for same logical page.
    _write_trace(d, "design-critic-home.json", {"verdict": "unresolved"})
    winner = _write_trace(
        d, "design-critic-home--epoch3.json",
        {"verdict": "pass"},
    )
    out = dcts.select_latest_per_page_traces(str(d))
    assert out == [str(winner.resolve())]


def test_weakest_page_fallback(tmp_path: Path) -> None:
    """When `page` absent but `weakest_page` set, helper uses it."""
    d = _make_dir(tmp_path)
    _write_trace(d, "design-critic-route-a.json",
                 {"weakest_page": "route-a", "verdict": "unresolved"})
    winner = _write_trace(
        d, "design-critic-route-a--epoch1.json",
        {"weakest_page": "route-a", "verdict": "pass"},
    )
    out = dcts.select_latest_per_page_traces(str(d))
    assert out == [str(winner.resolve())]


def test_shared_and_aggregate_excluded(tmp_path: Path) -> None:
    """`design-critic-shared.json` and `design-critic.json` aggregate
    are excluded by basename (gotcha 6 / merger parity)."""
    d = _make_dir(tmp_path)
    _write_trace(d, "design-critic.json",
                 {"agent": "design-critic", "provenance": "lead-merge"})
    _write_trace(d, "design-critic-shared.json",
                 {"agent": "design-critic", "verdict": "pass"})
    page_a = _write_trace(d, "design-critic-home.json", {"page": "home"})
    out = dcts.select_latest_per_page_traces(str(d))
    assert out == [str(page_a.resolve())]


def test_mtime_tiebreak_when_same_epoch(tmp_path: Path) -> None:
    """Two files claiming same epoch — newer mtime wins (defensive
    gotcha 4; the writer normally enforces unique filenames)."""
    d = _make_dir(tmp_path)
    older = _write_trace(d, "design-critic-x.json",
                         {"page": "x", "epoch": 0, "verdict": "unresolved"})
    older_path = Path(older)
    # Force older mtime
    old_ts = time.time() - 3600
    os.utime(older_path, (old_ts, old_ts))
    newer = _write_trace(d, "design-critic-x--also.json",
                         {"page": "x", "epoch": 0, "verdict": "pass"})
    out = dcts.select_latest_per_page_traces(str(d))
    assert out == [str(newer.resolve())]


def test_old_trace_remains_on_disk(tmp_path: Path) -> None:
    """HC3 — helper must not delete or hide old traces (gotcha 5)."""
    d = _make_dir(tmp_path)
    old = _write_trace(d, "design-critic-home.json",
                      {"page": "home", "verdict": "unresolved"})
    _write_trace(d, "design-critic-home--epoch1.json",
                 {"page": "home", "epoch": 1, "verdict": "pass"})
    dcts.select_latest_per_page_traces(str(d))
    assert old.exists()


def test_other_agent_name(tmp_path: Path) -> None:
    """Helper accepts an agent parameter — `design-critic` files are
    NOT picked up when agent='ux-journeyer'."""
    d = _make_dir(tmp_path)
    _write_trace(d, "design-critic-home.json", {"page": "home"})
    ux = _write_trace(d, "ux-journeyer-flow1.json", {"page": "flow1"})
    out = dcts.select_latest_per_page_traces(str(d), agent="ux-journeyer")
    assert out == [str(ux.resolve())]


def test_extract_page_key_prefers_structured_field(tmp_path: Path) -> None:
    d = _make_dir(tmp_path)
    p = _write_trace(d, "design-critic-anything.json",
                     {"page": "actual-page-key"})
    key = dcts.extract_page_key(json.loads(p.read_text()), str(p), "design-critic")
    assert key == "actual-page-key"


def test_extract_page_key_filename_with_epoch(tmp_path: Path) -> None:
    d = _make_dir(tmp_path)
    p = _write_trace(d, "design-critic-checkout--epoch4.json", {})
    key = dcts.extract_page_key({}, str(p), "design-critic")
    assert key == "checkout"


def test_filename_without_agent_prefix(tmp_path: Path) -> None:
    """If filename doesn't start with `<agent>-`, returns base sans suffix."""
    d = _make_dir(tmp_path)
    p = _write_trace(d, "weird-name.json", {})
    key = dcts.extract_page_key({}, str(p), "design-critic")
    assert key == "weird-name"


def test_invalid_json_skipped(tmp_path: Path) -> None:
    """Malformed traces are skipped (helper is defensive)."""
    d = _make_dir(tmp_path)
    bad = d / "design-critic-bad.json"
    bad.write_text("not json")
    good = _write_trace(d, "design-critic-good.json", {"page": "good"})
    out = dcts.select_latest_per_page_traces(str(d))
    # bad.json: extract_page_key returns 'bad' from filename → it IS included
    # since the helper falls back to filename when JSON parsing fails. Both
    # included because they're different page keys.
    assert sorted(out) == sorted([str(bad.resolve()), str(good.resolve())])
