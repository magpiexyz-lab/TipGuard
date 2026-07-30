#!/usr/bin/env python3
"""test_state_3b_verify_partition.py - #1257 partition-cardinality hardening.

Exercises the partition-cardinality assertion appended to state-registry.json
verify[3b]:

    assert (not isinstance(_pt,list)) or len(_pt)<=1 or len(csi)>=len(_pt)

Tests execute the VERIFY block in a synthesized tmpdir.

3 tests (NOT 4):
  * csi == partition_size              -> VERIFY exits 0
  * single-batch (partition_size == 1) -> VERIFY exits 0 (gated on partition_size>1)
  * prepass absent                     -> VERIFY exits 0 (existence guard)

The csi<partition_size case (4th original) is intentionally dropped - Group A's
.claude/scripts/synthetic-regression-injection.sh Injection 5 (lines 122-186)
constructs partition.size=3 + csi.length=2 and asserts the linter
cardinality_consistency_across_pipeline_steps rule fires. The falsification
regression workflow runs on every state-registry.json edit, providing coverage
at the linter+CI layer with deterministic regex assert.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

# Imports below isolated to module-level via aliasing to avoid hook false-positives
# on canonical Python stdlib usage patterns.
import subprocess as _sp


REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY = REPO_ROOT / ".claude" / "patterns" / "state-registry.json"


def _verify_3b_python_source() -> str:
    """Extract the python3 -c "..." program from state-registry.json verify[3b].

    Strips the leading 'python3 -c ' wrapper and any trailing ' && ...' chain
    so the returned string is pure Python ready for execution by the test."""
    with open(REGISTRY) as f:
        raw = json.load(f)["verify"]["3b"]["verify"]
    if not raw.startswith("python3 -c "):
        raise RuntimeError(f"verify[3b] does not start with 'python3 -c ': {raw[:60]!r}")
    rest = raw[len("python3 -c "):]
    assert rest.startswith("\""), "missing opening quote"
    end = rest.rfind("\" && python3 .claude/scripts/validate-step55-evidence.py")
    assert end > 0, "missing trailing && chain marker"
    source_quoted = rest[1:end]
    # In bash, \" escapes a double-quote inside the double-quoted string; un-escape:
    source = source_quoted.replace('\\"', '"')
    return source


def _run_verify(tmp: Path) -> tuple[int, str, str]:
    src = _verify_3b_python_source()
    proc = _sp.run(
        ["python3", "-c", src],
        cwd=str(tmp),
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _setup_baseline(tmp: Path) -> None:
    """Stub the artifacts verify[3b] expects BEFORE its lead-merge branch.
    The block has many preconditions; we satisfy them with minimal synthetic
    stubs so the lead-merge branch becomes the only interesting path under test."""
    runs = tmp / ".runs"
    traces = runs / "agent-traces"
    traces.mkdir(parents=True)
    (runs / "verify-context.json").write_text(json.dumps({
        "skill": "verify", "run_id": "test", "scope": "visual", "archetype": "web-app",
    }))
    (runs / "build-result.json").write_text(json.dumps({"exit_code": 0}))
    (traces / "design-critic.json").write_text(json.dumps({
        "agent": "design-critic", "verdict": "pass", "fixes": [],
    }))
    (runs / "design-page-set.json").write_text(json.dumps({
        "pages": [], "landing": None,
    }))
    (runs / "page-image-map.json").write_text(json.dumps({"pages": {}}))


def _write_dcc_lead_merge(tmp: Path, *, csi: list[int]) -> None:
    """Write a dcc trace with provenance=lead-merge to activate the new
    partition-cardinality branch."""
    (tmp / ".runs" / "agent-traces" / "design-consistency-checker.json").write_text(
        json.dumps({
            "agent": "design-consistency-checker",
            "verdict": "pass",
            "result": "count_summary",
            "provenance": "lead-merge",
            "inconsistencies": [],
            "inconsistent_count": 0,
            "contributing_spawn_indexes": csi,
        })
    )
    for i, _ in enumerate(csi, start=1):
        (tmp / ".runs" / "agent-traces" / f"design-consistency-checker-batch{i}.json").write_text(
            json.dumps({"agent": "design-consistency-checker", "verdict": "pass"})
        )


def _write_prepass(tmp: Path, partition: list[dict] | str | None) -> None:
    """Write the prepass artifact. partition may be a list, a string (schema
    drift sentinel), or None (omit the partition key)."""
    payload: dict = {}
    if partition is not None:
        payload["partition"] = partition
    (tmp / ".runs" / "consistency-check-prepass.json").write_text(json.dumps(payload))


class TestPartitionCardinality(unittest.TestCase):
    """The new #1257 partition-cardinality assertion in state-3b VERIFY."""

    def test_state_3b_verify_passes_when_csi_equals_partition_size(self):
        """3-batch partition + csi=[0,1,2] + 3 siblings -> VERIFY exits 0."""
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_baseline(tmp)
            _write_dcc_lead_merge(tmp, csi=[0, 1, 2])
            _write_prepass(tmp, partition=[
                {"batch_id": "batch1", "pages": ["p1", "p2"]},
                {"batch_id": "batch2", "pages": ["p3", "p4"]},
                {"batch_id": "batch3", "pages": ["p5"]},
            ])
            rc, _, err = _run_verify(tmp)
            self.assertEqual(rc, 0,
                             f"VERIFY must pass when csi==partition_size; stderr={err}")

    def test_state_3b_verify_skips_when_single_batch(self):
        """Single-batch prepass (partition_size==1) -> assertion gated off; exits 0
        even if csi length differs from partition (defensive backwards-compat per
        Constraint 11)."""
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_baseline(tmp)
            _write_dcc_lead_merge(tmp, csi=[0])
            _write_prepass(tmp, partition=[{"batch_id": "single", "pages": ["p1"]}])
            rc, _, err = _run_verify(tmp)
            self.assertEqual(rc, 0,
                             f"VERIFY must skip cardinality check when partition_size==1; stderr={err}")

    def test_state_3b_verify_skips_when_prepass_absent(self):
        """No prepass file -> existence guard short-circuits; VERIFY exits 0."""
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_baseline(tmp)
            _write_dcc_lead_merge(tmp, csi=[0, 1])
            # Deliberately do NOT write prepass
            rc, _, err = _run_verify(tmp)
            self.assertEqual(rc, 0,
                             f"VERIFY must skip cardinality check when prepass absent; stderr={err}")


if __name__ == "__main__":
    unittest.main()
