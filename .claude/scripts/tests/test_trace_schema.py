#!/usr/bin/env python3
"""test_trace_schema.py — validate the unified trace schema contract.

Generates synthetic traces for every `provenance` value and runs them
through the same validation logic that artifact-integrity-gate.sh uses.
Catches schema drift when agent authors hand-roll trace JSON.

Usage:
    python3 .claude/scripts/tests/test_trace_schema.py

Exit 0 on all-pass, 1 on any failure.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
GATE = ROOT / ".claude/hooks/artifact-integrity-gate.sh"
REGISTRY = ROOT / ".claude/patterns/agent-registry.json"


def run_gate(content: dict, file_path: str) -> tuple[int, str, str]:
    """Invoke artifact-integrity-gate.sh via a synthetic tool payload.

    Returns (exit_code, stderr, stdout).
    """
    payload = json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": json.dumps(content)},
    })
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(ROOT)
    # Make sure a *-context.json exists so the early-exit doesn't fire
    runs = ROOT / ".runs"
    runs.mkdir(exist_ok=True)
    ctx = runs / "test-schema-context.json"
    ctx.write_text(json.dumps({
        "skill": "test",
        "branch": "main",
        "timestamp": "2026-04-21T00:00:00Z",
        "run_id": "test-2026-04-21T00:00:00Z",
        "completed_states": [],
    }))
    try:
        proc = subprocess.run(
            ["bash", str(GATE)],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
        )
        return proc.returncode, proc.stderr, proc.stdout
    finally:
        try:
            ctx.unlink()
        except FileNotFoundError:
            pass


class TestTraceSchema(unittest.TestCase):
    maxDiff = None

    def _trace_path(self, basename: str) -> str:
        return str(ROOT / ".runs" / "agent-traces" / f"{basename}.json")

    def _assert_passes(self, trace: dict, basename: str = "design-critic"):
        rc, err, _ = run_gate(trace, self._trace_path(basename))
        self.assertEqual(rc, 0, f"expected allow for {basename} trace, stderr={err}")

    def _assert_blocks(self, trace: dict, expected_substr: str, basename: str = "design-critic"):
        rc, err, _ = run_gate(trace, self._trace_path(basename))
        self.assertNotEqual(rc, 0, f"expected block for {basename} trace, stderr={err}")
        self.assertIn(expected_substr, err,
                      f"expected stderr to mention {expected_substr!r}; got {err}")

    # --- Required base fields ---

    def test_missing_agent_field_blocks(self):
        self._assert_blocks(
            {"timestamp": "2026-04-21T00:00:00Z", "verdict": "pass",
             "checks_performed": ["x"], "provenance": "self"},
            "missing or empty: agent",
        )

    def test_init_stub_allowed(self):
        self._assert_passes({
            "agent": "design-critic",
            "status": "started",
            "timestamp": "2026-04-21T00:00:00Z",
        })

    # --- Provenance: self ---

    def test_self_pass_valid(self):
        self._assert_passes({
            "agent": "design-critic",
            "timestamp": "2026-04-21T00:00:00Z",
            "verdict": "pass",
            "provenance": "self",
            "partial": False,
            "checks_performed": ["layer1", "layer2", "layer3"],
            "run_id": "verify-2026-04-21T00:00:00Z",
        })

    def test_self_with_partial_true_blocks(self):
        self._assert_blocks(
            {
                "agent": "design-critic",
                "timestamp": "2026-04-21T00:00:00Z",
                "verdict": "pass",
                "provenance": "self",
                "partial": True,
                "checks_performed": ["x"],
            },
            "provenance=self with partial:true is contradictory",
        )

    # --- Provenance: self-degraded ---

    def test_self_degraded_requires_degraded_reason(self):
        self._assert_blocks(
            {
                "agent": "design-critic",
                "timestamp": "2026-04-21T00:00:00Z",
                "verdict": "degraded",
                "provenance": "self-degraded",
                "partial": True,
                "checks_performed": ["x"],
            },
            "requires degraded_reason",
        )

    def test_self_degraded_requires_partial_true(self):
        self._assert_blocks(
            {
                "agent": "design-critic",
                "timestamp": "2026-04-21T00:00:00Z",
                "verdict": "degraded",
                "provenance": "self-degraded",
                "partial": False,
                "checks_performed": ["x"],
                "degraded_reason": "cause",
            },
            "requires partial:true",
        )

    def test_self_degraded_valid(self):
        self._assert_passes({
            "agent": "design-critic",
            "timestamp": "2026-04-21T00:00:00Z",
            "verdict": "degraded",
            "provenance": "self-degraded",
            "partial": True,
            "checks_performed": ["layer1"],
            "degraded_reason": "image exceeded 2000px",
            "run_id": "verify-2026-04-21T00:00:00Z",
        })

    # --- Provenance: recovery ---

    def test_recovery_requires_legacy_mirror(self):
        self._assert_blocks(
            {
                "agent": "design-critic",
                "timestamp": "2026-04-21T00:00:00Z",
                "verdict": "recovery",
                "provenance": "recovery",
                "partial": True,
                "checks_performed": ["exhaustion-recovery"],
                "degraded_reason": "crash",
                "recovery": False,
            },
            "requires recovery:true",
        )

    def test_recovery_valid(self):
        self._assert_passes({
            "agent": "design-critic",
            "timestamp": "2026-04-21T00:00:00Z",
            "verdict": "recovery",
            "provenance": "recovery",
            "partial": True,
            "checks_performed": ["exhaustion-recovery"],
            "degraded_reason": "image-dimension limit",
            "recovery": True,
            "recovery_validated": False,
            "run_id": "verify-2026-04-21T00:00:00Z",
        })

    # --- Provenance: lead-merge ---

    def test_lead_merge_without_csi_blocks(self):
        self._assert_blocks(
            {
                "agent": "design-critic",
                "timestamp": "2026-04-21T00:00:00Z",
                "verdict": "pass",
                "provenance": "lead-merge",
                "partial": True,
                "checks_performed": ["merge"],
            },
            "contributing_spawn_indexes",
        )

    def test_lead_merge_with_csi_valid(self):
        self._assert_passes({
            "agent": "design-critic",
            "timestamp": "2026-04-21T00:00:00Z",
            "verdict": "pass",
            "provenance": "lead-merge",
            "partial": True,
            "checks_performed": ["merge"],
            "contributing_spawn_indexes": [1, 2, 3],
            "run_id": "verify-2026-04-21T00:00:00Z",
        })

    # --- AOC v1.1 Provenance: lead-on-behalf ---

    def test_lead_on_behalf_requires_source(self):
        self._assert_blocks(
            {
                "agent": "design-critic",
                "timestamp": "2026-04-21T00:00:00Z",
                "verdict": "pass",
                "provenance": "lead-on-behalf",
                "partial": True,
                "checks_performed": ["layer1"],
                "run_id": "verify-2026-04-21T00:00:00Z",
            },
            "lead-on-behalf requires source",
        )

    def test_lead_on_behalf_requires_partial_true(self):
        self._assert_blocks(
            {
                "agent": "design-critic",
                "timestamp": "2026-04-21T00:00:00Z",
                "verdict": "pass",
                "provenance": "lead-on-behalf",
                "partial": False,
                "checks_performed": ["layer1"],
                "source": "agent-returned-text",
                "run_id": "verify-2026-04-21T00:00:00Z",
            },
            "requires partial:true",
        )

    def test_lead_on_behalf_valid(self):
        self._assert_passes({
            "agent": "design-critic",
            "timestamp": "2026-04-21T00:00:00Z",
            "verdict": "pass",
            "provenance": "lead-on-behalf",
            "partial": True,
            "checks_performed": ["layer1", "layer2"],
            "source": "agent-returned-text",
            "recovery_validated": False,
            "run_id": "verify-2026-04-21T00:00:00Z",
        })

    # --- AOC v1.1 Provenance: lead-synthesized ---

    def test_lead_synthesized_requires_coverage_provider(self):
        self._assert_blocks(
            {
                "agent": "design-critic",
                "timestamp": "2026-04-21T00:00:00Z",
                "verdict": "pass",
                "provenance": "lead-synthesized",
                "partial": True,
                "checks_performed": [],
                "no_fixes_claimed": True,
                "run_id": "verify-2026-04-21T00:00:00Z",
            },
            "lead-synthesized requires coverage_provider",
        )

    def test_lead_synthesized_rejects_fixes(self):
        self._assert_blocks(
            {
                "agent": "design-critic",
                "timestamp": "2026-04-21T00:00:00Z",
                "verdict": "pass",
                "provenance": "lead-synthesized",
                "partial": True,
                "checks_performed": [],
                "coverage_provider": "tests/flows.test.ts",
                "fixes": [{"file": "x.ts", "symptom": "y", "fix": "z"}],
                "run_id": "verify-2026-04-21T00:00:00Z",
            },
            "must not claim fixes",
        )

    def test_lead_synthesized_valid_empty_marker(self):
        self._assert_passes({
            "agent": "design-critic",
            "timestamp": "2026-04-21T00:00:00Z",
            "verdict": "pass",
            "provenance": "lead-synthesized",
            "partial": True,
            "checks_performed": [],
            "coverage_provider": "tests/flows.test.ts",
            "no_fixes_claimed": True,
            "run_id": "verify-2026-04-21T00:00:00Z",
        })

    # --- AOC v1.1 Provenance: lead-fix ---

    def test_lead_fix_requires_lead_attestation(self):
        self._assert_blocks(
            {
                "agent": "design-critic",
                "timestamp": "2026-04-21T00:00:00Z",
                "verdict": "pass",
                "provenance": "lead-fix",
                "partial": True,
                "checks_performed": [],
                "run_id": "verify-2026-04-21T00:00:00Z",
            },
            "lead-fix requires lead_attestation:true",
        )

    def test_lead_fix_valid(self):
        self._assert_passes({
            "agent": "design-critic",
            "timestamp": "2026-04-21T00:00:00Z",
            "verdict": "pass",
            "provenance": "lead-fix",
            "partial": True,
            "checks_performed": [],
            "lead_attestation": True,
            "run_id": "verify-2026-04-21T00:00:00Z",
        })

    # --- Unknown provenance ---

    def test_invalid_provenance_blocks(self):
        self._assert_blocks(
            {
                "agent": "design-critic",
                "timestamp": "2026-04-21T00:00:00Z",
                "verdict": "pass",
                "provenance": "bogus",
                "checks_performed": ["x"],
            },
            "provenance must be one of",
        )

    def test_provenance_error_message_lists_v11_values(self):
        """The error message must enumerate all 7 AOC v1.1 provenance values."""
        rc, err, _ = run_gate(
            {
                "agent": "design-critic",
                "timestamp": "2026-04-21T00:00:00Z",
                "verdict": "pass",
                "provenance": "bogus",
                "checks_performed": ["x"],
            },
            self._trace_path("design-critic"),
        )
        self.assertNotEqual(rc, 0)
        for value in (
            "self", "self-degraded", "recovery", "lead-merge",
            "lead-on-behalf", "lead-synthesized", "lead-fix",
        ):
            self.assertIn(repr(value), err,
                          f"v1.1 provenance value {value!r} missing from error message: {err}")


def main():
    if not GATE.is_file():
        print(f"ERROR: gate not found at {GATE}", file=sys.stderr)
        return 2
    result = unittest.main(exit=False, verbosity=2).result
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
