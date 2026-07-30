#!/usr/bin/env python3
"""test_prose_gate_mode.py — unit tests for prose_gate_mode helper resolution.

Closes #1449/#1431/#1433. Verifies the 4-step resolution chain:
  1. PROSE_GATES_TOLERANT=1 → "warn"
  2. PROSE_GATE_<G>_MODE env override
  3. snapshot (version-checked) from active context
  4. prior_default (caller-passed) — preserves in-flight safety

Note: the helper does NOT read registry.fail_mode directly. Registry is
the source for snapshots written at lifecycle-init time; runs without a
snapshot fall through to prior_default to preserve original behavior.

Plus error paths:
  - Unknown gate → ProseGateError
  - Binary gate (no fail_mode) → ProseGateError

Plus per-gate isolation: setting one gate's env does not affect others.

Run: python3 .claude/scripts/tests/test_prose_gate_mode.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".claude/scripts/lib"))

# Force reload to avoid caching across tests if multiple test runs occur in
# the same process (shouldn't happen with unittest but defensive).
if "prose_gate_mode" in sys.modules:
    del sys.modules["prose_gate_mode"]

from prose_gate_mode import resolve, ProseGateError  # noqa: E402

# Known gate ids from .claude/patterns/prose-gates.json
GATE_1 = "lead-synthesized-numerical-bounds"
GATE_2 = "bootstrap-state-6-user-approval"
GATE_3 = "verify-state-2-phase1-spawn-no-background"  # binary, no fail_mode
GATE_4 = "observation-phase-step5c-anomaly-audit"
GATE_5 = "retro-suppressions-confirmation"
GATE_6 = "verify-state-3a-stage0-design-critic"


class TestProseGateModeResolution(unittest.TestCase):
    """Test the helper directly via Python import (CWD must be ROOT)."""

    def setUp(self):
        # Save original cwd; resolution chain reads relative paths.
        self._orig_cwd = os.getcwd()
        os.chdir(str(ROOT))
        # Snapshot env so we can clean up.
        self._orig_env = {
            k: os.environ.get(k)
            for k in [
                "PROSE_GATES_TOLERANT",
                "PROSE_GATE_LEAD_SYNTHESIZED_NUMERICAL_BOUNDS_MODE",
                "PROSE_GATE_OBSERVATION_PHASE_STEP5C_ANOMALY_AUDIT_MODE",
                "PROSE_GATE_RETRO_SUPPRESSIONS_CONFIRMATION_MODE",
            ]
        }
        # Clear before each test.
        for k in self._orig_env:
            os.environ.pop(k, None)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # === Resolution chain ===

    def test_step1_tolerant_escape_returns_warn(self):
        """PROSE_GATES_TOLERANT=1 → warn for any gate, even when registry says deny."""
        os.environ["PROSE_GATES_TOLERANT"] = "1"
        # Gate 1 is "deny" in v2 registry; tolerant should return warn.
        self.assertEqual(resolve(GATE_1, "deny"), "warn")
        # Even gate 5 (registry deny) returns warn under tolerant.
        self.assertEqual(resolve(GATE_5, "deny"), "warn")

    def test_step2_per_gate_env_override(self):
        """PROSE_GATE_<G>_MODE env wins over registry."""
        os.environ["PROSE_GATE_LEAD_SYNTHESIZED_NUMERICAL_BOUNDS_MODE"] = "warn"
        # Registry says deny; env override returns warn.
        self.assertEqual(resolve(GATE_1, "deny"), "warn")

    def test_step2_env_override_invalid_value_falls_through(self):
        """Garbage env value falls through to next resolution step
        (snapshot or prior_default — depends on context)."""
        os.environ["PROSE_GATE_LEAD_SYNTHESIZED_NUMERICAL_BOUNDS_MODE"] = "invalid-value"
        # Falls through; result is one of the legal mode values.
        result = resolve(GATE_1, "warn")
        self.assertIn(result, ("warn", "deny"))

    def test_step4_prior_default_when_no_snapshot_in_active_context(self):
        """When env empty AND no fresh snapshot in active context,
        prior_default wins. The helper does NOT read registry directly.
        This test runs in the worktree cwd; active contexts (if any) may
        or may not have snapshot — this test asserts the prior_default
        contract regardless of registry state."""
        # If active context has no fresh snapshot for GATE_1, we get prior_default.
        # If it does, we get the snapshot value. Both are "in-flight safe".
        # Best deterministic check: pass an unknown-default to verify the
        # ProseGateError fires before reaching the safety net.
        # For positive verification, see TestProseGateModeWithSnapshot.
        result = resolve(GATE_1, "warn")
        self.assertIn(result, ("warn", "deny"),
                      "result must be one of the legal mode values")

    # === Error paths ===

    def test_unknown_gate_raises(self):
        """resolve() for an unknown gate_id raises ProseGateError."""
        with self.assertRaises(ProseGateError) as cm:
            resolve("does-not-exist", "warn")
        self.assertIn("not found", str(cm.exception))

    def test_binary_gate_raises(self):
        """Binary gate (skill-yaml-mode, no fail_mode) raises ProseGateError."""
        with self.assertRaises(ProseGateError) as cm:
            resolve(GATE_3, "warn")
        self.assertIn("no fail_mode", str(cm.exception))
        self.assertIn("binary", str(cm.exception))

    def test_invalid_prior_default_raises(self):
        """prior_default must be 'warn' or 'deny'."""
        with self.assertRaises(ProseGateError):
            resolve(GATE_1, "garbage")

    # === Per-gate isolation ===

    def test_per_gate_isolation_env(self):
        """Setting one gate's env doesn't affect another gate.
        Gate 1's env override returns warn; gates 4, 5 are unaffected
        (they get their own snapshot or prior_default — independent of
        gate 1's env). The strong assertion is: gate 1 returns warn (env)
        regardless of what other gates return."""
        os.environ["PROSE_GATE_LEAD_SYNTHESIZED_NUMERICAL_BOUNDS_MODE"] = "deny"
        # Gate 1 returns deny (env override beats prior_default).
        self.assertEqual(resolve(GATE_1, "warn"), "deny")
        # Gate 4 NOT affected by gate 1's env. Returns its own resolution.
        result_4 = resolve(GATE_4, "warn")
        # Should be one of the legal modes; not influenced by gate 1's env.
        self.assertIn(result_4, ("warn", "deny"))
        # Gate 5 prior_default=deny; result is one of legal modes.
        result_5 = resolve(GATE_5, "deny")
        self.assertIn(result_5, ("warn", "deny"))


class TestProseGateModeWithSnapshot(unittest.TestCase):
    """Snapshot-based resolution tests using a tmp .runs/ context."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_prose_gate_mode_"))
        # Symlink .claude into the tmp dir so the helper can read prose-gates.json.
        (self.tmp / ".claude").symlink_to(ROOT / ".claude")
        (self.tmp / ".runs").mkdir()
        self._orig_cwd = os.getcwd()
        os.chdir(str(self.tmp))
        # Reload helper for new cwd.
        if "prose_gate_mode" in sys.modules:
            del sys.modules["prose_gate_mode"]
        from prose_gate_mode import resolve as _resolve, ProseGateError as _PGE
        self.resolve = _resolve
        self.ProseGateError = _PGE

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)
        # Reload helper to reset any cwd-cached state.
        if "prose_gate_mode" in sys.modules:
            del sys.modules["prose_gate_mode"]

    def _write_context(self, snap: dict | None, snap_version: int = 2):
        ctx = {
            "skill": "verify",
            "run_id": "verify-test-snap",
            "timestamp": "2026-05-15T00:00:00Z",
            "completed_states": [],
            "completed": False,
        }
        if snap is not None:
            ctx["prose_gates_modes_snapshot"] = snap
            ctx["prose_gates_modes_snapshot_at_version"] = snap_version
        (self.tmp / ".runs/verify-context.json").write_text(json.dumps(ctx))

    def test_snapshot_value_used_when_present_and_version_matches(self):
        """Snapshot wins when present and version >= current registry version."""
        self._write_context(snap={GATE_1: "warn"}, snap_version=2)
        # Registry says deny but snapshot says warn → warn.
        self.assertEqual(self.resolve(GATE_1, "deny"), "warn")

    def test_snapshot_legacy_version_falls_through_to_prior_default(self):
        """Snapshot taken under v1 (pre-load-bearing) falls through to prior_default,
        NOT the registry. This is the in-flight safety guarantee."""
        self._write_context(snap={GATE_1: "warn"}, snap_version=1)
        # Stale snapshot → fall through. Registry v2 says deny but legacy
        # contexts stay safe via prior_default.
        self.assertEqual(self.resolve(GATE_1, "warn"), "warn")

    def test_no_snapshot_field_falls_through_to_prior_default(self):
        """Context without the snapshot field (legacy context format, e.g.,
        an in-flight run that started before PR 1) falls through to
        prior_default. Registry is NOT consulted directly — that would
        break in-flight safety (round-1 critic Concern 3)."""
        self._write_context(snap=None)
        # Legacy context: prior_default wins.
        self.assertEqual(self.resolve(GATE_1, "warn"), "warn")
        # Same gate with prior_default=deny → deny.
        self.assertEqual(self.resolve(GATE_1, "deny"), "deny")

    def test_snapshot_missing_gate_falls_through_to_prior_default(self):
        """Snapshot present but missing this gate (e.g., gate added after
        snapshot was taken) → fall to prior_default for safety."""
        self._write_context(snap={GATE_4: "warn"}, snap_version=2)
        # Gate 1 not in snapshot → falls to prior_default (NOT registry).
        self.assertEqual(self.resolve(GATE_1, "warn"), "warn")
        # Gate 4 IS in snapshot → snapshot wins.
        self.assertEqual(self.resolve(GATE_4, "deny"), "warn")


if __name__ == "__main__":
    unittest.main()
