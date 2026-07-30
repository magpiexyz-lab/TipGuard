#!/usr/bin/env python3
"""test_state_11_build_self_check — EARC slice 2 (closes #1182 root cause).

Verifies the state-11 VERIFY assertion correctly demands `build_passing: true`
on the phase-a-sentinel.json, and rejects sentinels lacking that field. This
prevents the #1182 failure mode where scaffold-init's invalid Phase A
content (e.g., bad next/font config) escapes into the sealed window and
forces shell-bypass repairs.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _read_verify(state_id: str = "11") -> str:
    """Pull the canonical VERIFY command for bootstrap state-11 from the registry."""
    reg = json.load(open(ROOT / ".claude/patterns/state-registry.json"))
    return reg["bootstrap"][state_id]["verify"]


def _run_verify(cmd: str, cwd: str) -> subprocess.CompletedProcess:
    """Run the VERIFY one-liner the way state-completion-gate.sh would —
    via /bin/sh -c so quoting matches the runtime shape."""
    return subprocess.run(
        ["/bin/sh", "-c", cmd], cwd=cwd, capture_output=True, text=True
    )


def _write_sentinel(td: Path, **kwargs):
    (td / ".runs/gate-verdicts").mkdir(parents=True, exist_ok=True)
    json.dump(kwargs, (td / ".runs/gate-verdicts/phase-a-sentinel.json").open("w"))


def _write_context(td: Path, archetype: str = "web-app"):
    (td / ".runs").mkdir(parents=True, exist_ok=True)
    json.dump({"archetype": archetype}, (td / ".runs/bootstrap-context.json").open("w"))


class TestState11VerifyBuildPassing(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="test_state11_"))
        self.verify_cmd = _read_verify()

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_passing_sentinel_succeeds(self):
        _write_context(self.td, "web-app")
        _write_sentinel(
            self.td,
            phase_a_complete=True,
            build_passing=True,
            timestamp="2026-04-30T00:00:00Z",
            files=["src/app/layout.tsx"],
        )
        r = _run_verify(self.verify_cmd, str(self.td))
        self.assertEqual(r.returncode, 0, msg=f"stderr={r.stderr}")

    def test_missing_build_passing_field_fails(self):
        """Sentinel without build_passing field -> VERIFY rejects (closes #1182)."""
        _write_context(self.td, "web-app")
        _write_sentinel(
            self.td,
            phase_a_complete=True,
            timestamp="2026-04-30T00:00:00Z",
            files=["src/app/layout.tsx"],
        )
        r = _run_verify(self.verify_cmd, str(self.td))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("build_passing", r.stderr)

    def test_build_passing_false_fails(self):
        _write_context(self.td, "web-app")
        _write_sentinel(
            self.td,
            phase_a_complete=True,
            build_passing=False,
            timestamp="2026-04-30T00:00:00Z",
            files=["src/app/layout.tsx"],
        )
        r = _run_verify(self.verify_cmd, str(self.td))
        self.assertNotEqual(r.returncode, 0)

    def test_service_archetype_skips_check(self):
        """service archetype skips Phase A entirely; VERIFY must not require sentinel."""
        _write_context(self.td, "service")
        r = _run_verify(self.verify_cmd, str(self.td))
        self.assertEqual(r.returncode, 0, msg=f"stderr={r.stderr}")

    def test_cli_archetype_skips_check(self):
        _write_context(self.td, "cli")
        r = _run_verify(self.verify_cmd, str(self.td))
        self.assertEqual(r.returncode, 0, msg=f"stderr={r.stderr}")

    def test_missing_sentinel_fails_for_web_app(self):
        _write_context(self.td, "web-app")
        r = _run_verify(self.verify_cmd, str(self.td))
        self.assertNotEqual(r.returncode, 0)


class TestState11RepairEvidenceSlot(unittest.TestCase):
    """Slice 2 also adds the repair_evidence forward-declaration so slice 3
    can wire bootstrap/gates/write.sh ALSO-ALLOW path. Confirm the registry
    has the slot populated."""

    def test_repair_evidence_slot_present(self):
        reg = json.load(open(ROOT / ".claude/patterns/state-registry.json"))
        s11 = reg["bootstrap"]["11"]
        self.assertIn("repair_evidence", s11)
        re = s11["repair_evidence"]
        self.assertEqual(re.get("writer"), ".claude/scripts/write-phase-a-repair.sh")
        self.assertIn("build-result.json", re.get("evidence_sources", []))
        self.assertEqual(re.get("provenance"), "lead-fix")


if __name__ == "__main__":
    unittest.main()
