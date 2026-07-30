#!/usr/bin/env python3
"""Tests for verify-linter subsystem C: declared-field / prose drift.

Subsystem C contains:
  - check_declared_drift          (allows_early_exit_when + verify_semantics)
  - check_x1_forward_early_exit   (#928 + #1043 forward-drift detector)
  - check_x2_baseline_parity      (#928 baseline-parity detector)

These functions had ZERO test coverage before this PR. Coverage matters
because they are regex-driven and a stray whitespace change in the
extracted code (PR2) could silently break detection.

Each test builds a tmpdir mini-repo with:
  - .claude/scripts/verify-linter.sh + lib/ (real)
  - .claude/patterns/state-registry.json with one skill, one state
  - .claude/patterns/template-coherence-rules.json (empty rules — focus on subsys C)
  - .claude/skills/<skill>/state-<id>-foo.md (varied per test)

Then runs verify-linter.sh and asserts on stdout (DRIFT_DECLARED_VS_PROSE
section) for the expected finding presence/absence.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest


REAL_REPO = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
LINTER = os.path.join(REAL_REPO, ".claude", "scripts", "verify-linter.sh")
LIB_DIR = os.path.join(REAL_REPO, ".claude", "scripts", "lib")


def _build(tmpdir, skill, state_id, registry_value, state_md_body):
    """Construct a tmpdir mini-repo around a single state file."""
    os.makedirs(os.path.join(tmpdir, ".claude/scripts"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, ".claude/patterns"), exist_ok=True)
    skill_dir = os.path.join(tmpdir, ".claude/skills", skill)
    os.makedirs(skill_dir, exist_ok=True)

    shutil.copy(LINTER, os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"))
    shutil.copytree(LIB_DIR, os.path.join(tmpdir, ".claude/scripts/lib"), dirs_exist_ok=True)

    with open(os.path.join(tmpdir, ".claude/patterns/state-registry.json"), "w") as f:
        json.dump({skill: {state_id: registry_value}}, f)
    with open(os.path.join(tmpdir, ".claude/patterns/template-coherence-rules.json"), "w") as f:
        json.dump({"rules": []}, f)
    with open(os.path.join(skill_dir, f"state-{state_id}-test.md"), "w") as f:
        f.write(state_md_body)


def _run(tmpdir):
    result = subprocess.run(
        ["bash", os.path.join(tmpdir, ".claude/scripts/verify-linter.sh")],
        capture_output=True,
        text=True,
        cwd=tmpdir,
    )
    return result.returncode, result.stdout


# ----- CHECK-X1 forward early-exit detector -----

class TestX1ForwardEarlyExit(unittest.TestCase):

    def test_x1_fires_when_actions_have_terminal_prose_but_no_declaration(self):
        """ACTIONS prose 'If no remaining findings ... advance state to TERMINAL'
        without registry's allows_early_exit_when -> X1 finding."""
        state_md = """\
# STATE 1

**ACTIONS:**

If no errors remain, advance state to TERMINAL and skill ends.

**VERIFY:**
```bash
true
```
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _build(tmpdir, "demo_skill", "1", {"verify": "true"}, state_md)
            rc, stdout = _run(tmpdir)
        self.assertIn("ACTIONS contain early-exit TERMINAL prose", stdout)
        self.assertIn("demo_skill:1", stdout)

    def test_x1_silent_when_declaration_present(self):
        """Same prose, but registry declares allows_early_exit_when -> no X1 finding."""
        state_md = """\
# STATE 1

**ACTIONS:**

If no errors remain, advance state to TERMINAL and skill ends.

**VERIFY:**
```bash
true
```
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _build(
                tmpdir,
                "demo_skill",
                "1",
                {"verify": "true", "allows_early_exit_when": "zero_findings"},
                state_md,
            )
            rc, stdout = _run(tmpdir)
        self.assertNotIn("early-exit TERMINAL prose", stdout)


# ----- CHECK-X2 baseline-parity detector -----

class TestX2BaselineParity(unittest.TestCase):

    def test_x2_fires_when_baseline_outcome_prose_lacks_declaration(self):
        """ACTIONS prose 'final_errors <= baseline' without verify_semantics -> X2 finding."""
        state_md = """\
# STATE 1

**ACTIONS:**

After fixes, ensure final_errors <= baseline before advancing.

**VERIFY:**
```bash
true
```
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _build(tmpdir, "demo_skill", "1", {"verify": "true"}, state_md)
            rc, stdout = _run(tmpdir)
        self.assertIn("ACTIONS contain baseline/parity comparison", stdout)
        self.assertIn("demo_skill:1", stdout)

    def test_x2_silent_when_declaration_present(self):
        """Same prose, but registry declares verify_semantics -> no X2 finding."""
        state_md = """\
# STATE 1

**ACTIONS:**

After fixes, ensure final_errors <= baseline before advancing.

**VERIFY:**
```bash
[ "$final_errors" -le "$baseline" ]
```
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _build(
                tmpdir,
                "demo_skill",
                "1",
                {"verify": "[ \"$final_errors\" -le \"$baseline\" ]", "verify_semantics": "no_regression_from_baseline"},
                state_md,
            )
            rc, stdout = _run(tmpdir)
        self.assertNotIn("baseline/parity comparison", stdout)


# ----- check_declared_drift -----

class TestDeclaredDrift(unittest.TestCase):

    def test_declared_exit_drifts_from_actions(self):
        """Registry declares allows_early_exit_when=zero_findings but ACTIONS lacks
        any matching synonym phrase -> drift_declared finding."""
        state_md = """\
# STATE 1

**ACTIONS:**

Run the build and emit the report.

**VERIFY:**
```bash
true
```
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _build(
                tmpdir,
                "demo_skill",
                "1",
                {"verify": "true", "allows_early_exit_when": "zero_findings"},
                state_md,
            )
            rc, stdout = _run(tmpdir)
        self.assertIn("DRIFT_DECLARED_VS_PROSE", stdout)
        self.assertIn("zero_findings", stdout)
        self.assertIn("demo_skill:1", stdout)

    def test_declared_exit_aligned_with_actions_passes(self):
        """Registry declares allows_early_exit_when=zero_findings AND ACTIONS contains
        a synonym phrase ('zero findings') -> no drift_declared finding."""
        state_md = """\
# STATE 1

**ACTIONS:**

If there are zero findings remaining, exit early.

**VERIFY:**
```bash
true
```
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _build(
                tmpdir,
                "demo_skill",
                "1",
                {"verify": "true", "allows_early_exit_when": "zero_findings"},
                state_md,
            )
            rc, stdout = _run(tmpdir)
        self.assertNotIn("zero_findings", stdout)


if __name__ == "__main__":
    unittest.main()
