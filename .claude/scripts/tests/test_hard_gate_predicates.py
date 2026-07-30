#!/usr/bin/env python3
"""test_hard_gate_predicates.py — exercise check_hard_gate_predicates via the
bash wrapper chain (lib.sh -> lib-verdict.sh shim -> lib-hard-gate.sh ->
evaluate-hard-gate-predicates.py). This is the regression net for the
bash-Python boundary; companion file test_evaluate_hard_gate_predicates.py
unit-tests the Python evaluator directly.

Each test constructs a trace + a synthetic verify-report.md CONTENT
(simulating the Write payload) and invokes the function from the bash wrapper.
Validates the predicate semantics that ultimately decide whether
verify-report-gate.sh allows `hard_gate_failure:false`.

Predicates covered:
  - pass_self_pass_or_fail
  - validated_fallback
  - aggregate_ok (lead-merge + contributing_spawn_indexes count match)
  - legacy_pass_no_recovery
  - additional_block_conditions (eq, gt, all)

Run: python3 .claude/scripts/tests/test_hard_gate_predicates.py
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
LIB = ROOT / ".claude/hooks/lib.sh"


class TestHardGatePredicates(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_hgp_"))
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        shutil.copytree(ROOT / ".claude", self.tmp / ".claude", dirs_exist_ok=True)
        self.runs = self.tmp / ".runs"
        self.runs.mkdir()
        self.traces = self.runs / "agent-traces"
        self.traces.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_trace(self, name: str, data: dict):
        (self.traces / f"{name}.json").write_text(json.dumps(data, indent=2))

    def _invoke(self, agent: str, report_content: str) -> tuple[str, int]:
        """Source lib.sh, set CONTENT + ERRORS, call check_hard_gate_predicates,
        print ERRORS array. Returns (stderr_joined, exit_code)."""
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        trace_dir = str(self.traces)
        # We quote the content carefully via bash heredoc
        script = f"""
source '{LIB}'
CONTENT={json.dumps(report_content)}
ERRORS=()
check_hard_gate_predicates '{agent}' '{trace_dir}'
if (( ${{#ERRORS[@]}} > 0 )); then
  for e in "${{ERRORS[@]}}"; do printf 'ERR: %s\\n' "$e"; done
fi
"""
        proc = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, env=env, timeout=15,
        )
        return proc.stdout + proc.stderr, proc.returncode

    # ---- pass_self_pass_or_fail ----

    def test_pass_self_allows_pass_without_gate_flag(self):
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "self",
            "partial": False,
            "checks_performed": ["x"],
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: false\n")
        self.assertNotIn("ERR:", out, f"pass_self=pass should allow without gate flag, got {out}")

    def test_pass_self_allows_fail(self):
        # design-critic allow_predicates includes pass_self_pass_or_fail, so
        # verdict:fail provenance:self should still pass (caller records fail elsewhere)
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "fail",
            "provenance": "self",
            "partial": False,
            "checks_performed": ["x"],
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: false\n")
        self.assertNotIn("ERR:", out)

    def test_pass_self_rejects_unresolved(self):
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "unresolved",
            "provenance": "self",
            "partial": False,
            "checks_performed": ["x"],
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: false\n")
        self.assertIn("ERR:", out)
        self.assertIn("no allow_predicate satisfied", out)

    def test_pass_self_accepts_when_report_sets_gate_true(self):
        # Same failing trace, but report declares hard_gate_failure:true → no error
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "unresolved",
            "provenance": "self",
            "partial": False,
            "checks_performed": ["x"],
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: true\n")
        self.assertNotIn("ERR:", out)

    # ---- validated_fallback ----

    def test_recovery_validated_allows(self):
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "recovery",
            "provenance": "recovery",
            "partial": True,
            "recovery": True,
            "recovery_validated": True,
            "checks_performed": ["exhaustion-recovery"],
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: false\n")
        self.assertNotIn("ERR:", out, f"recovery+validated should allow, got {out}")

    def test_recovery_not_validated_blocks(self):
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "recovery",
            "provenance": "recovery",
            "partial": True,
            "recovery": True,
            "recovery_validated": False,
            "checks_performed": ["exhaustion-recovery"],
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: false\n")
        self.assertIn("ERR:", out)

    def test_self_degraded_validated_allows(self):
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "degraded",
            "provenance": "self-degraded",
            "partial": True,
            "degraded_reason": "image limit",
            "recovery_validated": True,
            "checks_performed": ["layer1"],
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: false\n")
        self.assertNotIn("ERR:", out)

    # ---- aggregate_ok (lead-merge) ----

    def test_lead_merge_allows_when_siblings_pass(self):
        # Aggregate
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "lead-merge",
            "partial": True,
            "contributing_spawn_indexes": [1, 2],
            "checks_performed": ["merge"],
        })
        # Two sibling traces, both self+pass
        self._write_trace("design-critic-landing", {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "self",
            "partial": False,
            "checks_performed": ["x"],
        })
        self._write_trace("design-critic-pricing", {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "self",
            "partial": False,
            "checks_performed": ["x"],
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: false\n")
        self.assertNotIn("ERR:", out, f"lead-merge with good siblings should allow, got {out}")

    def test_lead_merge_blocks_when_sibling_unresolved(self):
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "lead-merge",
            "partial": True,
            "contributing_spawn_indexes": [1, 2],
            "checks_performed": ["merge"],
        })
        self._write_trace("design-critic-landing", {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "self",
            "partial": False,
            "checks_performed": ["x"],
        })
        # sibling with unresolved + self — not satisfying pass_self_pass_or_fail
        self._write_trace("design-critic-pricing", {
            "agent": "design-critic",
            "verdict": "unresolved",
            "provenance": "self",
            "partial": False,
            "checks_performed": ["x"],
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: false\n")
        self.assertIn("ERR:", out)

    def test_lead_merge_blocks_when_csi_missing(self):
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "lead-merge",
            "partial": True,
            "checks_performed": ["merge"],
            # contributing_spawn_indexes absent
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: false\n")
        self.assertIn("ERR:", out)

    def test_lead_merge_allows_when_siblings_self_degraded_validated(self):
        """#1042 Session C happy path: aggregate with one self+pass sibling
        and one self-degraded+recovery_validated sibling (DEMO_MODE fixture
        short-circuit) passes aggregate_ok. No lead override required."""
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "unresolved",
            "provenance": "lead-merge",
            "partial": True,
            "contributing_spawn_indexes": [0, 1],
            "checks_performed": ["merge"],
        })
        self._write_trace("design-critic-landing", {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "self",
            "partial": False,
            "checks_performed": ["layer1_functional"],
        })
        self._write_trace("design-critic-quote-detail", {
            "agent": "design-critic",
            "verdict": "unresolved",
            "provenance": "self-degraded",
            "partial": True,
            "degraded_reason": "demo-mode-fixture-short-circuit",
            "recovery_validated": True,
            "no_fixes_claimed": True,
            "review_method": "source-only",
            "source_review_verdict": "pass",
            "checks_performed": ["source-review-structural"],
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: false\n")
        self.assertNotIn(
            "ERR:", out,
            f"aggregate_ok should accept self+pass + self-degraded+validated siblings, got: {out}",
        )

    def test_lead_merge_blocks_when_degraded_sibling_unvalidated(self):
        """#1042 negative: same happy-path topology but recovery_validated=false
        on the self-degraded sibling — aggregate_ok must block."""
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "unresolved",
            "provenance": "lead-merge",
            "partial": True,
            "contributing_spawn_indexes": [0, 1],
            "checks_performed": ["merge"],
        })
        self._write_trace("design-critic-landing", {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "self",
            "partial": False,
            "checks_performed": ["layer1_functional"],
        })
        self._write_trace("design-critic-quote-detail", {
            "agent": "design-critic",
            "verdict": "unresolved",
            "provenance": "self-degraded",
            "partial": True,
            "degraded_reason": "demo-mode-fixture-short-circuit",
            "recovery_validated": False,   # Stage-1c never ran or failed
            "no_fixes_claimed": True,
            "review_method": "source-only",
            "checks_performed": ["source-review-structural"],
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: false\n")
        self.assertIn(
            "ERR:", out,
            f"aggregate_ok must block when self-degraded sibling is unvalidated, got: {out}",
        )

    # ---- legacy_pass_no_recovery ----

    def test_legacy_pass_no_recovery_allows_unmigrated(self):
        # Legacy trace: no provenance field, verdict=pass, recovery absent
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "pass",
            "checks_performed": ["x"],
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: false\n")
        self.assertNotIn("ERR:", out, "legacy pass+no-recovery should allow without gate flag")

    def test_legacy_recovery_true_blocks_without_gate_flag(self):
        # Legacy recovery-tainted trace
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "recovery",
            "recovery": True,
            "checks_performed": ["x"],
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: false\n")
        self.assertIn("ERR:", out)

    # ---- additional_block_conditions ----

    def test_ux_journeyer_unresolved_dead_ends_blocks(self):
        # ux-journeyer has additional_block_conditions: unresolved_dead_ends > 0
        self._write_trace("ux-journeyer", {
            "agent": "ux-journeyer",
            "verdict": "pass",
            "provenance": "self",
            "partial": False,
            "unresolved_dead_ends": 3,
            "checks_performed": ["journey"],
        })
        out, _ = self._invoke("ux-journeyer", "hard_gate_failure: false\n")
        self.assertIn("ERR:", out, "unresolved_dead_ends>0 must block even with pass verdict")

    def test_ux_journeyer_pass_zero_dead_ends_allows(self):
        self._write_trace("ux-journeyer", {
            "agent": "ux-journeyer",
            "verdict": "pass",
            "provenance": "self",
            "partial": False,
            "unresolved_dead_ends": 0,
            "checks_performed": ["journey"],
        })
        out, _ = self._invoke("ux-journeyer", "hard_gate_failure: false\n")
        self.assertNotIn("ERR:", out)

    def test_security_fixer_partial_with_unresolved_critical_blocks(self):
        # security-fixer additional_block_conditions uses all: [verdict=partial, unresolved_critical>0]
        self._write_trace("security-fixer", {
            "agent": "security-fixer",
            "verdict": "partial",
            "provenance": "self",
            "partial": False,
            "unresolved_critical": 2,
            "checks_performed": ["fix"],
        })
        out, _ = self._invoke("security-fixer", "hard_gate_failure: false\n")
        self.assertIn("ERR:", out)

    def test_no_trace_file_is_noop(self):
        out, _ = self._invoke("nonexistent-agent", "hard_gate_failure: false\n")
        self.assertNotIn("ERR:", out)

    # ---- AOC v1.1: validated_fallback extended to lead-on-behalf ----

    def test_lead_on_behalf_validated_allows_via_validated_fallback(self):
        # design-critic's allow_predicates list includes validated_fallback,
        # which AOC v1.1 extended to accept lead-on-behalf with recovery_validated:true.
        # No new predicate registration on hard_gates required.
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "lead-on-behalf",
            "partial": True,
            "source": "agent-returned-text",
            "recovery_validated": True,
            "checks_performed": ["layer1", "layer2"],
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: false\n")
        self.assertNotIn("ERR:", out, f"lead-on-behalf+validated should allow, got {out}")

    def test_lead_on_behalf_not_validated_blocks(self):
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "lead-on-behalf",
            "partial": True,
            "source": "agent-returned-text",
            "recovery_validated": False,
            "checks_performed": ["layer1"],
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: false\n")
        self.assertIn("ERR:", out, "lead-on-behalf without recovery_validated must block")

    # ---- AOC v1.1: aggregate_ok accepts new lead-* siblings ----

    def test_lead_merge_with_lead_on_behalf_sibling_validated(self):
        # Aggregate composed from one self-passed and one lead-on-behalf sibling
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "lead-merge",
            "partial": True,
            "contributing_spawn_indexes": [1, 2],
            "checks_performed": ["merge"],
        })
        self._write_trace("design-critic-landing", {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "self",
            "partial": False,
            "checks_performed": ["x"],
        })
        # Sibling: lead-on-behalf transcribed (e.g., agent's write blocked)
        self._write_trace("design-critic-pricing", {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "lead-on-behalf",
            "partial": True,
            "source": "agent-returned-text",
            "recovery_validated": True,
            "checks_performed": ["x"],
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: false\n")
        self.assertNotIn(
            "ERR:", out,
            f"aggregate_ok should accept lead-on-behalf sibling with recovery_validated, got {out}",
        )

    def test_lead_merge_with_lead_on_behalf_sibling_unvalidated_blocks(self):
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "lead-merge",
            "partial": True,
            "contributing_spawn_indexes": [1, 2],
            "checks_performed": ["merge"],
        })
        self._write_trace("design-critic-landing", {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "self",
            "partial": False,
            "checks_performed": ["x"],
        })
        self._write_trace("design-critic-pricing", {
            "agent": "design-critic",
            "verdict": "pass",
            "provenance": "lead-on-behalf",
            "partial": True,
            "source": "agent-returned-text",
            "recovery_validated": False,  # NOT validated
            "checks_performed": ["x"],
        })
        out, _ = self._invoke("design-critic", "hard_gate_failure: false\n")
        self.assertIn(
            "ERR:", out,
            "aggregate_ok must block when lead-on-behalf sibling is not recovery_validated",
        )

    # ---- Boundary check: missing evaluator script must NOT silently pass ----

    def test_missing_evaluator_script_loud_failure(self):
        """If .claude/scripts/evaluate-hard-gate-predicates.py is absent, the
        bash wrapper must append a loud error — never silently return OK.

        Regression test for the bash-Python subprocess boundary introduced when
        the Python evaluator was extracted from lib-verdict.sh's heredoc. Before
        the existence guard, python3 reported the missing file to stderr while
        stdout stayed empty, and the case "OK|\"\"" branch silently passed every
        hard gate.

        Setup detail: lib-core.sh:36 unconditionally overrides CLAUDE_PROJECT_DIR
        to `git rev-parse --show-toplevel`, so we cd into self.tmp (already
        `git init`'d in setUp) before sourcing lib.sh. That makes the function
        resolve script path inside our isolated tmp tree, where the unlink takes
        effect."""
        # Sabotage the synthetic project: remove the evaluator script
        script = self.tmp / ".claude/scripts/evaluate-hard-gate-predicates.py"
        self.assertTrue(script.exists(), "fixture should have copied the script")
        script.unlink()

        # Trace would otherwise BLOCK (verdict=fail with allow=pass_self_strict
        # in registry), so a silent pass here is provably wrong
        self._write_trace("design-critic", {
            "agent": "design-critic",
            "verdict": "fail",
            "provenance": "self",
            "partial": False,
            "checks_performed": ["x"],
        })

        # Manual invocation (cannot use _invoke because we need to cd into tmp
        # BEFORE sourcing lib.sh so lib-core.sh's get_project_dir resolves to tmp)
        bash_script = f"""
cd '{self.tmp}'
source '{LIB}'
CONTENT={json.dumps('hard_gate_failure: false')}
ERRORS=()
check_hard_gate_predicates 'design-critic' '{self.traces}'
if (( ${{#ERRORS[@]}} > 0 )); then
  for e in "${{ERRORS[@]}}"; do printf 'ERR: %s\\n' "$e"; done
fi
"""
        proc = subprocess.run(
            ["bash", "-c", bash_script],
            capture_output=True, text=True, timeout=15,
        )
        out = proc.stdout + proc.stderr
        self.assertIn("ERR:", out,
                      f"missing evaluator script must produce an error, not silent pass. Got: {out!r}")
        self.assertIn("evaluator script missing", out,
                      "error message should name the missing-script root cause")


if __name__ == "__main__":
    unittest.main(verbosity=2)
