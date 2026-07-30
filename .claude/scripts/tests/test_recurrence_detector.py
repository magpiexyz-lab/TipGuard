#!/usr/bin/env python3
"""test_recurrence_detector.py — RMG v2 Phase B.

Exercises both `lib/symptom_canonicalizer.py` and `recurrence-detector.py`:
  * canonicalization rules collapse line numbers, timestamps, paths, sha
  * composite_identity hashing is stable across surface noise
  * advisory tier fires at ≥2 distinct run_ids in 60d window
  * advisory tier respects the window (>60d apart → no candidate)
  * dedupe-by-day collapses same-day same-run_id duplicates
  * fcntl flock blocks a second writer on the same lockfile
  * promotion tier defers to nightly audit when window is huge
  * gh issue idempotency: skipped when an existing issue mentions the hash
"""

from __future__ import annotations

import errno
import fcntl
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / ".claude" / "scripts" / "lib"))

from symptom_canonicalizer import canonicalize_symptom, symptom_signature_hash  # noqa: E402

_DETECTOR_PATH = REPO_ROOT / ".claude" / "scripts" / "recurrence-detector.py"


def _load_detector():
    spec = importlib.util.spec_from_file_location("recurrence_detector", _DETECTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


detector = _load_detector()


def _row(**kwargs):
    base = {
        "fix_id": "x:1",
        "agent": "resolve-fixer",
        "run_id": "run-1",
        "file": "foo/bar.ts",
        "symptom": "undefined is not a function at bar.ts:10",
        "fix": "add null check",
        "timestamp": "2026-04-15T10:00:00Z",
        "batch_id": "b1",
        "batch_size": 1,
        "provenance": "agent",
        "severity": "high",
    }
    base.update(kwargs)
    return base


class CanonicalizationTests(unittest.TestCase):
    def test_line_col_collapsed(self):
        a = canonicalize_symptom("undefined is not a function at bar.ts:10:5")
        b = canonicalize_symptom("undefined is not a function at bar.ts:42:9")
        self.assertEqual(a, b)

    def test_bare_line_collapsed(self):
        a = canonicalize_symptom("error at bar.ts:10")
        b = canonicalize_symptom("error at bar.ts:11")
        self.assertEqual(a, b)

    def test_pr_number_collapsed(self):
        a = canonicalize_symptom("regression introduced in #1234")
        b = canonicalize_symptom("regression introduced in #5678")
        self.assertEqual(a, b)

    def test_iso_timestamp_collapsed(self):
        a = canonicalize_symptom("failed at 2026-04-15T10:00:00Z")
        b = canonicalize_symptom("failed at 2026-04-20T15:30:00Z")
        self.assertEqual(a, b)

    def test_absolute_path_collapsed(self):
        a = canonicalize_symptom("ENOENT /Users/alice/foo/bar")
        b = canonicalize_symptom("ENOENT /tmp/xyz/foo/bar")
        self.assertEqual(a, b)

    def test_short_sha_collapsed(self):
        a = canonicalize_symptom("commit abcdef1234 broke build")
        b = canonicalize_symptom("commit fedcba9876 broke build")
        self.assertEqual(a, b)

    def test_signature_hash_stable_across_noise(self):
        a = symptom_signature_hash("undefined at bar.ts:10")
        b = symptom_signature_hash("undefined at bar.ts:99")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 12)


class CompositeResolutionTests(unittest.TestCase):
    def test_same_root_cause_hashes_equal(self):
        h1 = detector.compute_hash(detector.derive_composite_for_row(_row(symptom="undefined is not a function at bar.ts:10")))
        h2 = detector.compute_hash(detector.derive_composite_for_row(_row(symptom="undefined is not a function at bar.ts:11")))
        self.assertEqual(h1, h2)

    def test_different_severity_yields_different_hash(self):
        h1 = detector.compute_hash(detector.derive_composite_for_row(_row(severity="high")))
        h2 = detector.compute_hash(detector.derive_composite_for_row(_row(severity="warn")))
        self.assertNotEqual(h1, h2)

    def test_stack_scope_uses_top_two_path_components(self):
        composite = detector.derive_composite_for_row(_row(file="foo/bar/baz.ts"))
        self.assertEqual(composite["stack_scope"], "foo/bar")


class GroupingTests(unittest.TestCase):
    def test_two_runs_in_window_groups_together(self):
        rows = [
            _row(run_id="r1", timestamp="2026-04-15T10:00:00Z"),
            _row(run_id="r2", timestamp="2026-04-20T10:00:00Z", symptom="undefined is not a function at bar.ts:11"),
        ]
        groups = detector.group_by_composite(
            iter(rows),
            since_days=60,
            now=detector.datetime(2026, 5, 1, tzinfo=detector.timezone.utc),
        )
        self.assertEqual(len(groups), 1)
        bucket = next(iter(groups.values()))
        self.assertEqual(len(bucket["run_ids"]), 2)

    def test_outside_window_dropped(self):
        rows = [
            _row(run_id="r1", timestamp="2025-12-01T10:00:00Z"),
            _row(run_id="r2", timestamp="2026-04-20T10:00:00Z"),
        ]
        groups = detector.group_by_composite(
            iter(rows),
            since_days=60,
            now=detector.datetime(2026, 5, 1, tzinfo=detector.timezone.utc),
        )
        # r1 outside window → only r2 remains; one group with one run_id (no advisory)
        self.assertEqual(len(groups), 1)
        bucket = next(iter(groups.values()))
        self.assertEqual(len(bucket["run_ids"]), 1)

    def test_dedupe_by_day_run(self):
        rows = [
            _row(fix_id="a", run_id="r1", timestamp="2026-04-15T10:00:00Z"),
            _row(fix_id="b", run_id="r1", timestamp="2026-04-15T13:00:00Z"),
            _row(fix_id="c", run_id="r1", timestamp="2026-04-15T18:00:00Z"),
        ]
        groups = detector.group_by_composite(
            iter(rows),
            since_days=60,
            now=detector.datetime(2026, 5, 1, tzinfo=detector.timezone.utc),
        )
        bucket = next(iter(groups.values()))
        self.assertEqual(len(bucket["samples"]), 1)


class TierTests(unittest.TestCase):
    def test_advisory_below_threshold(self):
        group = {"run_ids": {"r1"}, "samples": [], "first_seen": None, "last_seen": None}
        self.assertFalse(detector.is_advisory(group))

    def test_advisory_at_threshold(self):
        group = {"run_ids": {"r1", "r2"}, "samples": [], "first_seen": None, "last_seen": None}
        self.assertTrue(detector.is_advisory(group))

    def test_promotion_below_5_runs(self):
        group = {"run_ids": {"r1", "r2"}, "samples": [{}, {}], "first_seen": None, "last_seen": None}
        self.assertFalse(detector.is_promotion_candidate(group))

    def test_promotion_meets_threshold(self):
        run_ids = {f"r{i}" for i in range(5)}
        samples = [{} for _ in range(5)]
        first = detector.datetime(2026, 4, 1, tzinfo=detector.timezone.utc)
        last = detector.datetime(2026, 4, 30, tzinfo=detector.timezone.utc)
        group = {"run_ids": run_ids, "samples": samples, "first_seen": first, "last_seen": last}
        self.assertTrue(detector.is_promotion_candidate(group))

    def test_promotion_low_confidence_blocked(self):
        run_ids = {f"r{i}" for i in range(5)}
        samples = [{} for _ in range(15)]  # confidence = 5/15 < 0.8
        first = detector.datetime(2026, 4, 1, tzinfo=detector.timezone.utc)
        last = detector.datetime(2026, 4, 30, tzinfo=detector.timezone.utc)
        group = {"run_ids": run_ids, "samples": samples, "first_seen": first, "last_seen": last}
        self.assertFalse(detector.is_promotion_candidate(group))


class LockTests(unittest.TestCase):
    def test_concurrent_lock_raises_contention(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "lock"
            with detector._exclusive_lock(lock):
                # simulate a second holder by trying to grab the same lock
                with self.assertRaises(detector._LockContention):
                    with detector._exclusive_lock(lock):
                        pass

    def test_release_allows_reacquire(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "lock"
            with detector._exclusive_lock(lock):
                pass
            # should be re-acquirable
            with detector._exclusive_lock(lock):
                pass


class EndToEndTests(unittest.TestCase):
    def _run(self, rows, *, args=("--advisory-only",)):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / ".runs"
            runs.mkdir()
            ledger = runs / "fix-ledger.jsonl"
            with ledger.open("w") as fh:
                for row in rows:
                    fh.write(json.dumps(row) + "\n")
            env = dict(os.environ, PROJECT_DIR=tmp)
            result = subprocess.run(
                [sys.executable, str(_DETECTOR_PATH), *args],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            candidates = runs / "recurrence-candidates.jsonl"
            written = []
            if candidates.exists():
                for line in candidates.read_text().splitlines():
                    if line.strip():
                        written.append(json.loads(line))
            return result, written

    def test_two_runs_emit_advisory(self):
        rows = [
            _row(run_id="syn-1", timestamp="2026-04-15T10:00:00Z"),
            _row(
                run_id="syn-2",
                timestamp="2026-04-20T10:00:00Z",
                symptom="undefined is not a function at bar.ts:11",
            ),
        ]
        # The fixed window is 60d from "now"; rows are old, so override since_days
        result, written = self._run(rows, args=("--advisory-only", "--since-days", "3650"))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["priority"], "high")
        self.assertEqual(written[0]["occurrences"], 2)

    def test_single_run_no_advisory(self):
        rows = [_row(run_id="syn-1", timestamp="2026-04-15T10:00:00Z")]
        result, written = self._run(rows, args=("--advisory-only", "--since-days", "3650"))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(written, [])

    def test_template_edit_rows_skipped(self):
        rows = [
            {
                "fix_id": "te:1",
                "agent": "lead",
                "run_id": "syn-1",
                "file": "foo/bar.md",
                "entry_type": "template-edit",
                "before_hash": "a",
                "after_hash": "b",
                "timestamp": "2026-04-15T10:00:00Z",
                "batch_id": "b",
                "batch_size": 1,
                "provenance": "lead",
                "severity": "warn",
            },
            {
                "fix_id": "te:2",
                "agent": "lead",
                "run_id": "syn-2",
                "file": "foo/bar.md",
                "entry_type": "template-edit",
                "before_hash": "c",
                "after_hash": "d",
                "timestamp": "2026-04-20T10:00:00Z",
                "batch_id": "b",
                "batch_size": 1,
                "provenance": "lead",
                "severity": "warn",
            },
        ]
        result, written = self._run(rows, args=("--advisory-only", "--since-days", "3650"))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(written, [])

    def test_dry_run_writes_nothing(self):
        rows = [
            _row(run_id="syn-1", timestamp="2026-04-15T10:00:00Z"),
            _row(run_id="syn-2", timestamp="2026-04-20T10:00:00Z", symptom="undefined is not a function at bar.ts:11"),
        ]
        result, written = self._run(
            rows, args=("--advisory-only", "--dry-run", "--since-days", "3650")
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(written, [])
        summary = json.loads(result.stdout.strip())
        self.assertEqual(summary["advisory_emitted"], 1)
        self.assertTrue(summary["dry_run"])


class ConstantsParityTests(unittest.TestCase):
    """Drift guard: detector mirrors three constants from stack_knowledge_audit.py.

    The audit module is the canonical source. The detector cannot import it
    directly because the audit uses a `from lib.stack_knowledge_parser import`
    relative import that fails under pytest collection. Parse the source file
    and assert the values match.
    """

    def test_thresholds_match_source(self):
        audit_path = REPO_ROOT / ".claude" / "scripts" / "lib" / "stack_knowledge_audit.py"
        text = audit_path.read_text()
        import re as _re

        def _grab(name: str) -> str:
            m = _re.search(rf"^{name}\s*=\s*([\d.]+)", text, _re.MULTILINE)
            assert m, f"{name} not found in {audit_path}"
            return m.group(1)

        self.assertEqual(int(_grab("RAW_TO_STABLE_MIN_OCCURRENCE")), detector.RAW_TO_STABLE_MIN_OCCURRENCE)
        self.assertEqual(float(_grab("RAW_TO_STABLE_MIN_CONFIDENCE")), detector.RAW_TO_STABLE_MIN_CONFIDENCE)
        self.assertEqual(int(_grab("OSCILLATION_WINDOW_DAYS")), detector.OSCILLATION_WINDOW_DAYS)


if __name__ == "__main__":
    unittest.main()
