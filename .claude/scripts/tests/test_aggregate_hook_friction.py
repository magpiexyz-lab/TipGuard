#!/usr/bin/env python3
"""Tests for .claude/scripts/aggregate-hook-friction.py (#1895 run scoping + tail cutoff).

Run:
  python3 -m pytest .claude/scripts/tests/test_aggregate_hook_friction.py -v
  # OR (no pytest dependency):
  python3 .claude/scripts/tests/test_aggregate_hook_friction.py

The aggregator is CWD-relative by contract (repo root), so every test runs it
as a subprocess inside a tempdir shaped like a repo (.runs/...).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

SCRIPT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "aggregate-hook-friction.py")
)

RUN_A = "iterate-cross-2026-07-27T15:16:59Z"
RUN_B = "iterate-cross-2026-07-27T03:16:19Z"


def _row(run_id, hook="skill-agent-gate.sh", reason="denied", ts="2026-07-27T16:00:00Z",
         action_type="block"):
    return {
        "hook": hook,
        "tool_name": "Bash",
        "blocked_command": "",
        "reason": reason,
        "action_type": action_type,
        "run_id": run_id,
        "skill": "iterate-cross",
        "timestamp": ts,
    }


def _setup(td, context=None, rows=None):
    runs = os.path.join(td, ".runs")
    os.makedirs(runs, exist_ok=True)
    if context is not None:
        json.dump(context, open(os.path.join(runs, "iterate-cross-context.json"), "w"))
    if rows is not None:
        with open(os.path.join(runs, "hook-friction.jsonl"), "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    return os.path.join(runs, "hook-friction-summary.json")


def _run(td):
    env = dict(os.environ)
    env.pop("AGGREGATE_HOOK_FRICTION_DRY_RUN", None)  # default (dry-run) path
    proc = subprocess.run(
        [sys.executable, SCRIPT], cwd=td, env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return proc


def _active_ctx(run_id=RUN_A):
    return {"skill": "iterate-cross", "run_id": run_id,
            "timestamp": "2026-07-27T15:16:59Z", "completed": False}


def test_orphan_and_cross_run_rows_excluded():
    """#1895 defect 1: empty-run_id orphan rows and other runs' rows never
    enter the active run's summary."""
    with tempfile.TemporaryDirectory() as td:
        out_p = _setup(td, context=_active_ctx(), rows=[
            _row(RUN_A, hook="gate-a.sh", reason="r1"),
            _row(RUN_A, hook="gate-b.sh", reason="r2", action_type="warn-mode-bypass"),
            _row("", hook="gate-a.sh", reason="orphan self-test") ,
            _row("", hook="gate-c.sh", reason="orphan self-test"),
            _row(RUN_B, hook="gate-a.sh", reason="prior run"),
        ])
        _run(td)
        s = json.load(open(out_p))
        assert s["run_id"] == RUN_A
        assert s["total"] == 2
        assert set(s["hooks"]) == {"gate-a.sh", "gate-b.sh"}
        assert s["hooks"]["gate-a.sh"]["count"] == 1
        assert s["action_type_counts"]["block"] == 1
        assert s["action_type_counts"]["warn-mode-bypass"] == 1
        # normalized_groups built from the same filtered loop — no orphan leakage
        assert all(g["count"] == 1 for g in s["normalized_groups"].values())
        assert len(s["normalized_groups"]) == 2


def test_no_active_run_writes_empty_summary_never_unscoped():
    """#1895 coupling guard: with no resolvable active run (context completed),
    the persistent jsonl must NOT be aggregated unscoped."""
    with tempfile.TemporaryDirectory() as td:
        out_p = _setup(
            td,
            context={**_active_ctx(), "completed": True},
            rows=[_row(""), _row(""), _row(RUN_B)],
        )
        _run(td)
        s = json.load(open(out_p))
        assert s["run_id"] is None
        assert s["total"] == 0
        assert s["hooks"] == {}
        assert "aggregated_at" in s


def test_missing_jsonl_writes_fresh_empty_summary():
    """Unconditional invocation contract: a friction-free run gets a fresh
    empty summary (never inherits the previous run's stale one)."""
    with tempfile.TemporaryDirectory() as td:
        out_p = _setup(td, context=_active_ctx(), rows=None)
        # Simulate a stale previous-run summary that must be overwritten.
        json.dump({"run_id": RUN_B, "total": 99, "hooks": {"x": {"count": 99}}},
                  open(out_p, "w"))
        _run(td)
        s = json.load(open(out_p))
        assert s["run_id"] == RUN_A
        assert s["total"] == 0
        assert s["hooks"] == {}
        assert "aggregated_at" in s


def test_aggregated_at_is_utc_iso():
    with tempfile.TemporaryDirectory() as td:
        out_p = _setup(td, context=_active_ctx(), rows=[_row(RUN_A)])
        _run(td)
        s = json.load(open(out_p))
        at = s["aggregated_at"]
        assert isinstance(at, str) and at.endswith("Z") and len(at) == 20
        # Sortable against row timestamps (the rows_after_cutoff contract).
        assert at > "2026-01-01T00:00:00Z"


def test_rerun_is_idempotent_full_rebuild():
    """Tail-refresh contract (#1895 defect 2): a later re-run picks up rows
    appended after the first pass; counts never accumulate across runs."""
    with tempfile.TemporaryDirectory() as td:
        out_p = _setup(td, context=_active_ctx(), rows=[_row(RUN_A, reason="early")])
        _run(td)
        assert json.load(open(out_p))["total"] == 1
        with open(os.path.join(td, ".runs", "hook-friction.jsonl"), "a") as f:
            f.write(json.dumps(_row(RUN_A, hook="late-gate.sh", reason="tail",
                                    ts="2026-07-27T16:20:13Z")) + "\n")
        _run(td)
        s = json.load(open(out_p))
        assert s["total"] == 2
        assert "late-gate.sh" in s["hooks"]


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if failures else 0)
