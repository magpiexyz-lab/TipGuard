"""#1257 — unit tests for merge-design-consistency-checker-traces.py.

Locks the lead-merge contract that aggregate_ok hard-gate predicate
(`evaluate-hard-gate-predicates.py:131-174`) consumes:

  * provenance == "lead-merge"
  * contributing_spawn_indexes is a non-empty list
  * result == "count_summary"
  * status == "completed"

Plus aggregation correctness:
  * Inconsistencies deduped by (check, sorted-pages, severity, detail)
  * pages_reviewed = sum across batches
  * pages_remaining = union across batches
  * partial = any-of across batches
  * verdict invariant: fail iff inconsistent_count > 0
  * severity = max-of (none < minor < major)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
MERGER = REPO_ROOT / ".claude" / "scripts" / "merge-design-consistency-checker-traces.py"


def _setup_run(
    tmp: Path,
    *,
    run_id: str,
    batches: list[dict],
    spawn_log: list[dict] | None = None,
    prepass: dict | None = None,
) -> Path:
    """Build a tmpdir with .runs/agent-traces/design-consistency-checker-batch*.json siblings."""
    traces_dir = tmp / ".runs" / "agent-traces"
    traces_dir.mkdir(parents=True)
    for i, batch in enumerate(batches, start=1):
        with open(traces_dir / f"design-consistency-checker-batch{i}.json", "w") as f:
            json.dump(batch, f)
    # verify-context.json supplies run_id to the merger
    with open(tmp / ".runs" / "verify-context.json", "w") as f:
        json.dump({"skill": "verify", "run_id": run_id}, f)
    # agent-spawn-log.jsonl: one entry per batch with skill-agent-gate
    if spawn_log is None:
        spawn_log = [
            {"agent": "design-consistency-checker", "run_id": run_id, "hook": "skill-agent-gate", "spawn_index": i}
            for i in range(len(batches))
        ]
    with open(tmp / ".runs" / "agent-spawn-log.jsonl", "w") as f:
        for rec in spawn_log:
            f.write(json.dumps(rec) + "\n")
    # Optional prepass artifact (consumed by merger telemetry-append path; #1257)
    if prepass is not None:
        with open(tmp / ".runs" / "consistency-check-prepass.json", "w") as f:
            json.dump(prepass, f)
    # Symlink .claude/scripts/lib so the merger can import design_critic_trace_selector
    (tmp / ".claude" / "scripts").mkdir(parents=True)
    os.symlink(REPO_ROOT / ".claude" / "scripts" / "lib", tmp / ".claude" / "scripts" / "lib")
    return traces_dir


def _run_merger(tmp: Path) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["python3", str(MERGER)],
        cwd=str(tmp),
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _read_aggregate(tmp: Path) -> dict:
    with open(tmp / ".runs" / "agent-traces" / "design-consistency-checker.json") as f:
        return json.load(f)


class TestMergerCanonicalContract(unittest.TestCase):
    def test_aggregate_emits_lead_merge_provenance(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_run(tmp, run_id="r1", batches=[
                {"agent": "design-consistency-checker", "verdict": "pass", "result": "count_summary",
                 "inconsistencies": [], "inconsistent_count": 0, "pages_reviewed": ["p1", "p2"], "pages_reviewed_count": 2},
                {"agent": "design-consistency-checker", "verdict": "pass", "result": "count_summary",
                 "inconsistencies": [], "inconsistent_count": 0, "pages_reviewed": ["p3"], "pages_reviewed_count": 1},
            ])
            rc, _, err = _run_merger(tmp)
            self.assertEqual(rc, 0, f"merger failed: {err}")
            agg = _read_aggregate(tmp)
            self.assertEqual(agg["provenance"], "lead-merge")
            self.assertEqual(agg["result"], "count_summary")
            self.assertEqual(agg["status"], "completed")
            self.assertIsInstance(agg["contributing_spawn_indexes"], list)
            self.assertGreater(len(agg["contributing_spawn_indexes"]), 0)
            self.assertEqual(agg["coverage_provider"], ".runs/consistency-check-prepass.json")

    def test_aggregate_contributing_spawn_indexes_from_log(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_run(tmp, run_id="r1", batches=[
                {"agent": "design-consistency-checker", "verdict": "pass", "inconsistencies": []},
                {"agent": "design-consistency-checker", "verdict": "pass", "inconsistencies": []},
                {"agent": "design-consistency-checker", "verdict": "pass", "inconsistencies": []},
            ], spawn_log=[
                {"agent": "design-consistency-checker", "run_id": "r1", "hook": "skill-agent-gate", "spawn_index": 4},
                {"agent": "design-consistency-checker", "run_id": "r1", "hook": "skill-agent-gate", "spawn_index": 5},
                {"agent": "design-consistency-checker", "run_id": "r1", "hook": "skill-agent-gate", "spawn_index": 6},
                # Other agents shouldn't pollute
                {"agent": "design-critic", "run_id": "r1", "hook": "skill-agent-gate", "spawn_index": 99},
            ])
            rc, _, err = _run_merger(tmp)
            self.assertEqual(rc, 0, err)
            agg = _read_aggregate(tmp)
            self.assertEqual(agg["contributing_spawn_indexes"], [4, 5, 6])

    def test_aggregate_csi_fallback_when_log_missing(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_run(tmp, run_id="r1", batches=[
                {"agent": "design-consistency-checker", "verdict": "pass", "inconsistencies": []},
                {"agent": "design-consistency-checker", "verdict": "pass", "inconsistencies": []},
            ], spawn_log=[])
            rc, _, err = _run_merger(tmp)
            self.assertEqual(rc, 0, err)
            agg = _read_aggregate(tmp)
            # Fallback: range(len(siblings))
            self.assertEqual(agg["contributing_spawn_indexes"], [0, 1])


class TestMergerAggregation(unittest.TestCase):
    def test_dedupe_inconsistencies(self):
        same_inc = {"check": "C1", "severity": "minor", "pages": ["pricing"], "detail": "bg-gray vs majority bg-slate"}
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_run(tmp, run_id="r1", batches=[
                {"agent": "design-consistency-checker", "verdict": "fail", "inconsistencies": [same_inc],
                 "inconsistent_count": 1, "pages_reviewed": ["pricing", "p1"], "severity": "minor"},
                {"agent": "design-consistency-checker", "verdict": "fail", "inconsistencies": [same_inc],
                 "inconsistent_count": 1, "pages_reviewed": ["p2", "pricing"], "severity": "minor"},
            ])
            rc, _, err = _run_merger(tmp)
            self.assertEqual(rc, 0, err)
            agg = _read_aggregate(tmp)
            self.assertEqual(agg["inconsistent_count"], 1)
            self.assertEqual(len(agg["inconsistencies"]), 1)

    def test_pages_reviewed_sum(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_run(tmp, run_id="r1", batches=[
                {"agent": "design-consistency-checker", "verdict": "pass", "inconsistencies": [],
                 "pages_reviewed": ["a", "b", "c"]},
                {"agent": "design-consistency-checker", "verdict": "pass", "inconsistencies": [],
                 "pages_reviewed": ["d", "e"]},
            ])
            rc, _, err = _run_merger(tmp)
            self.assertEqual(rc, 0, err)
            agg = _read_aggregate(tmp)
            self.assertEqual(agg["pages_reviewed"], 5)

    def test_partial_propagation(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_run(tmp, run_id="r1", batches=[
                {"agent": "design-consistency-checker", "verdict": "pass", "inconsistencies": [], "partial": False},
                {"agent": "design-consistency-checker", "verdict": "pass", "inconsistencies": [], "partial": True},
            ])
            rc, _, err = _run_merger(tmp)
            self.assertEqual(rc, 0, err)
            agg = _read_aggregate(tmp)
            self.assertTrue(agg["partial"])

    def test_verdict_invariant_fail(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_run(tmp, run_id="r1", batches=[
                {"agent": "design-consistency-checker", "verdict": "fail",
                 "inconsistencies": [{"check": "C1", "severity": "major", "pages": ["x"], "detail": "d"}],
                 "inconsistent_count": 1, "severity": "major"},
                {"agent": "design-consistency-checker", "verdict": "pass",
                 "inconsistencies": [], "inconsistent_count": 0},
            ])
            rc, _, err = _run_merger(tmp)
            self.assertEqual(rc, 0, err)
            agg = _read_aggregate(tmp)
            self.assertEqual(agg["verdict"], "fail")
            self.assertEqual(agg["inconsistent_count"], 1)

    def test_verdict_invariant_pass(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_run(tmp, run_id="r1", batches=[
                {"agent": "design-consistency-checker", "verdict": "pass", "inconsistencies": []},
                {"agent": "design-consistency-checker", "verdict": "pass", "inconsistencies": []},
            ])
            rc, _, err = _run_merger(tmp)
            self.assertEqual(rc, 0, err)
            agg = _read_aggregate(tmp)
            self.assertEqual(agg["verdict"], "pass")
            self.assertEqual(agg["inconsistent_count"], 0)

    def test_severity_max_of(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_run(tmp, run_id="r1", batches=[
                {"agent": "design-consistency-checker", "verdict": "fail", "inconsistencies": [{"check": "C1", "severity": "minor", "pages": ["a"], "detail": "x"}], "severity": "minor"},
                {"agent": "design-consistency-checker", "verdict": "fail", "inconsistencies": [{"check": "C2", "severity": "major", "pages": ["b"], "detail": "y"}], "severity": "major"},
                {"agent": "design-consistency-checker", "verdict": "pass", "inconsistencies": [], "severity": "none"},
            ])
            rc, _, err = _run_merger(tmp)
            self.assertEqual(rc, 0, err)
            agg = _read_aggregate(tmp)
            self.assertEqual(agg["severity"], "major")


class TestMergerErrors(unittest.TestCase):
    def test_no_siblings_returns_nonzero(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / ".runs" / "agent-traces").mkdir(parents=True)
            with open(tmp / ".runs" / "verify-context.json", "w") as f:
                json.dump({"skill": "verify", "run_id": "r1"}, f)
            (tmp / ".claude" / "scripts").mkdir(parents=True)
            os.symlink(REPO_ROOT / ".claude" / "scripts" / "lib", tmp / ".claude" / "scripts" / "lib")
            rc, _, err = _run_merger(tmp)
            self.assertEqual(rc, 1)
            self.assertIn("no sibling", err)

    def test_malformed_sibling_returns_2(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / ".runs" / "agent-traces").mkdir(parents=True)
            (tmp / ".runs" / "agent-traces" / "design-consistency-checker-batch1.json").write_text("not json {{")
            with open(tmp / ".runs" / "verify-context.json", "w") as f:
                json.dump({"skill": "verify", "run_id": "r1"}, f)
            (tmp / ".claude" / "scripts").mkdir(parents=True)
            os.symlink(REPO_ROOT / ".claude" / "scripts" / "lib", tmp / ".claude" / "scripts" / "lib")
            rc, _, err = _run_merger(tmp)
            self.assertEqual(rc, 2)


class TestMergerTelemetry(unittest.TestCase):
    """#1257 hardening — best-effort telemetry append for multi-batch attestation
    observability. Multi-batch only; raw-fields record (no precomputed `attesting`)."""

    REQUIRED_FIELDS = {
        "timestamp", "run_id", "provenance", "partition_size",
        "contributing_spawn_indexes_count", "contributing_spawn_indexes",
        "pages_reviewed_total", "verdict", "status",
    }

    def _read_telemetry(self, tmp: Path) -> list[dict]:
        path = tmp / ".runs" / "consistency-soak-telemetry.jsonl"
        if not path.exists():
            return []
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    def test_telemetry_emitted_on_multi_batch(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_run(
                tmp,
                run_id="r-multi",
                batches=[
                    {"agent": "design-consistency-checker", "verdict": "pass",
                     "inconsistencies": [], "pages_reviewed": ["p1", "p2"]},
                    {"agent": "design-consistency-checker", "verdict": "pass",
                     "inconsistencies": [], "pages_reviewed": ["p3"]},
                ],
                prepass={
                    "partition": [
                        {"batch_id": "batch1", "pages": ["p1", "p2"]},
                        {"batch_id": "batch2", "pages": ["p3"]},
                    ],
                },
            )
            rc, _, err = _run_merger(tmp)
            self.assertEqual(rc, 0, err)
            records = self._read_telemetry(tmp)
            self.assertEqual(len(records), 1, f"expected 1 telemetry record, got {len(records)}")
            rec = records[0]
            self.assertEqual(set(rec.keys()), self.REQUIRED_FIELDS,
                             f"telemetry schema drift: {set(rec.keys())}")
            self.assertNotIn("attesting", rec,
                             "telemetry must NOT precompute attesting flag (#1257 R2/8cf178ea45ab)")
            self.assertEqual(rec["provenance"], "lead-merge")
            self.assertEqual(rec["partition_size"], 2)
            self.assertEqual(rec["contributing_spawn_indexes_count"], 2)
            self.assertEqual(rec["pages_reviewed_total"], 3)
            self.assertEqual(rec["verdict"], "pass")
            self.assertEqual(rec["status"], "completed")
            self.assertEqual(rec["run_id"], "r-multi")

    def test_telemetry_not_emitted_on_single_batch(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_run(
                tmp,
                run_id="r-single",
                batches=[
                    {"agent": "design-consistency-checker", "verdict": "pass",
                     "inconsistencies": [], "pages_reviewed": ["p1"]},
                ],
                prepass={"partition": [{"batch_id": "single", "pages": ["p1"]}]},
            )
            rc, _, err = _run_merger(tmp)
            self.assertEqual(rc, 0, err)
            self.assertFalse(
                (tmp / ".runs" / "consistency-soak-telemetry.jsonl").exists(),
                "telemetry must NOT be emitted on single-batch (partition_size<=1 guard)",
            )

    def test_telemetry_skipped_when_no_run_id(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _setup_run(
                tmp,
                run_id="",  # empty run_id → telemetry write should skip silently
                batches=[
                    {"agent": "design-consistency-checker", "verdict": "pass",
                     "inconsistencies": [], "pages_reviewed": ["p1"]},
                    {"agent": "design-consistency-checker", "verdict": "pass",
                     "inconsistencies": [], "pages_reviewed": ["p2"]},
                ],
                prepass={
                    "partition": [
                        {"batch_id": "batch1", "pages": ["p1"]},
                        {"batch_id": "batch2", "pages": ["p2"]},
                    ],
                },
            )
            rc, _, err = _run_merger(tmp)
            self.assertEqual(rc, 0, err)
            self.assertFalse(
                (tmp / ".runs" / "consistency-soak-telemetry.jsonl").exists(),
                "telemetry must NOT be emitted when run_id is empty",
            )


if __name__ == "__main__":
    unittest.main()
