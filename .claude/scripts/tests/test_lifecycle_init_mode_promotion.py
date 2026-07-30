#!/usr/bin/env python3
"""test_lifecycle_init_mode_promotion.py — verify per-mode config promotion.

Covers the `PROMOTABLE_MODE_KEYS` block in lifecycle-init.sh:

  1. Promotes mode-level flag when active mode declares it.
  2. Does not promote when active mode omits the flag.
  3. Top-level survives when mode omits the flag.
  4. Mode-level explicit `false` overrides top-level `true`.
  5. Non-promotable keys (states, trigger) stay nested.
  6. Skill without `modes:` block — no crash, no spurious root keys.
  7. End-to-end: promoted flag actually causes validate-experiment.py to be
     skipped (mode with flag → exit 0; mode without → exit 1 from failing
     validator). Locks the user-facing contract, not just the manifest shape.

Run: python3 .claude/scripts/tests/test_lifecycle_init_mode_promotion.py
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
INIT_SCRIPT = ROOT / ".claude/scripts/lifecycle-init.sh"


class TestModePromotion(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_lc_init_mp_"))
        (self.tmp / ".runs").mkdir()
        (self.tmp / "experiment").mkdir()
        # Minimal valid experiment.yaml so the validation gate (when not
        # skipped) is exercised without aborting init for an unrelated reason.
        (self.tmp / "experiment" / "experiment.yaml").write_text(
            "name: test-fixture\nstatus: draft\n"
        )
        (self.tmp / ".claude").mkdir()
        (self.tmp / ".claude" / "skills").mkdir()
        (self.tmp / ".claude" / "scripts").mkdir()
        # Stub init-context.sh that lifecycle-init.sh calls — make it a no-op.
        (self.tmp / ".claude" / "scripts" / "init-context.sh").write_text(
            "#!/usr/bin/env bash\nexit 0\n"
        )
        os.chmod(self.tmp / ".claude" / "scripts" / "init-context.sh", 0o755)
        # Stub other scripts lifecycle-init may invoke (orphan cleanup, etc).
        for stub in ("stop-transient-services.sh", "update-context-branch.sh"):
            p = self.tmp / ".claude" / "scripts" / stub
            p.write_text("#!/usr/bin/env bash\nexit 0\n")
            os.chmod(p, 0o755)
        # Stub the in-worktree helper to return "true" so branch creation is
        # skipped by lifecycle-init.sh's worktree guard.
        lib = self.tmp / ".claude" / "scripts" / "lib"
        lib.mkdir()
        (lib / "in-worktree.sh").write_text(
            "#!/usr/bin/env bash\necho true\n"
        )
        os.chmod(lib / "in-worktree.sh", 0o755)
        # Stub migrate-legacy-traces.py to a no-op.
        (self.tmp / ".claude" / "scripts" / "migrate-legacy-traces.py").write_text(
            "#!/usr/bin/env python3\nimport sys; sys.exit(0)\n"
        )
        os.chmod(self.tmp / ".claude" / "scripts" / "migrate-legacy-traces.py", 0o755)
        # No validate-experiment.py in tmp tree → validation gate skips per
        # lifecycle-init.sh:414 (`-f "$VALIDATE_SCRIPT"` test); we are testing
        # the promotion logic, not validation execution.

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_skill(self, name: str, body: str):
        d = self.tmp / ".claude" / "skills" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "skill.yaml").write_text(body)

    def _run(self, skill: str, extra: str = "") -> subprocess.CompletedProcess:
        # Run the real lifecycle-init.sh from project root, but pointed at the
        # tmp tree via cwd. CLAUDE_PROJECT_DIR drives PROJECT_DIR resolution.
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        env["BRANCH_CHECKOUT_PROPAGATION_GATE_SKIP"] = "1"
        # Init a tmp git repo so `git rev-parse --show-toplevel` works.
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "--allow-empty", "-qm", "init"],
            cwd=self.tmp, check=True,
        )
        args = ["bash", str(INIT_SCRIPT), skill]
        if extra:
            args.append(extra)
        return subprocess.run(
            args, capture_output=True, text=True, env=env, cwd=str(self.tmp),
            timeout=30,
        )

    def _manifest(self, skill: str) -> dict:
        return json.loads((self.tmp / ".runs" / f"{skill}-lifecycle.json").read_text())

    # ---- Cases ----

    def test_1_promotes_when_mode_declares(self):
        self._write_skill("iter1", """\
modes:
  default:
    states: ["0","99"]
  cross:
    trigger: "--cross"
    states: ["x0","99"]
    skip_experiment_validation: true
""")
        proc = self._run("iter1", '{"mode":"cross"}')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        m = self._manifest("iter1")
        self.assertEqual(m.get("active_mode"), "cross")
        self.assertIs(m.get("skip_experiment_validation"), True)
        # modes subtree must remain intact
        self.assertEqual(m["modes"]["cross"]["states"], ["x0", "99"])
        self.assertIs(m["modes"]["cross"]["skip_experiment_validation"], True)

    def test_2_no_promote_when_mode_omits(self):
        self._write_skill("iter2", """\
modes:
  default:
    states: ["0","99"]
  cross:
    trigger: "--cross"
    states: ["x0","99"]
    skip_experiment_validation: true
""")
        proc = self._run("iter2", '{"mode":"default"}')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        m = self._manifest("iter2")
        self.assertEqual(m.get("active_mode"), "default")
        # default mode has no override, no top-level → key absent at root
        self.assertNotIn("skip_experiment_validation", m)

    def test_3_top_level_survives_when_mode_omits(self):
        self._write_skill("iter3", """\
skip_experiment_validation: true
modes:
  default:
    states: ["0","99"]
  alt:
    trigger: "--alt"
    states: ["a0","99"]
""")
        proc = self._run("iter3", '{"mode":"alt"}')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        m = self._manifest("iter3")
        self.assertEqual(m.get("active_mode"), "alt")
        # top-level was true, mode omits → root keeps true
        self.assertIs(m.get("skip_experiment_validation"), True)

    def test_4_mode_false_overrides_top_true(self):
        self._write_skill("iter4", """\
skip_experiment_validation: true
modes:
  strict:
    trigger: "--strict"
    states: ["s0","99"]
    skip_experiment_validation: false
""")
        proc = self._run("iter4", '{"mode":"strict"}')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        m = self._manifest("iter4")
        self.assertEqual(m.get("active_mode"), "strict")
        # mode explicit false MUST override top-level true (precedence rule)
        self.assertIs(m.get("skip_experiment_validation"), False)

    def test_5_non_promotable_keys_stay_nested(self):
        self._write_skill("iter5", """\
modes:
  cross:
    trigger: "--cross"
    states: ["x0","99"]
    skip_experiment_validation: true
""")
        proc = self._run("iter5", '{"mode":"cross"}')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        m = self._manifest("iter5")
        # states + trigger MUST NOT be promoted to root — they have different
        # semantics under modes[<mode>] (consumed by lifecycle-next.sh:99-103)
        self.assertNotIn("trigger", m)
        # Root `states` may exist only if skill declares it top-level; this
        # skill doesn't, so it must be absent.
        self.assertNotIn("states", m)

    def test_6_no_modes_block_works(self):
        self._write_skill("flat6", """\
skip_experiment_validation: true
states: ["0","1","99"]
""")
        proc = self._run("flat6")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        m = self._manifest("flat6")
        # Skill without modes: promotion branch skipped; top-level still respected
        self.assertNotIn("active_mode", m)
        self.assertIs(m.get("skip_experiment_validation"), True)
        self.assertEqual(m.get("states"), ["0", "1", "99"])

    def test_7_end_to_end_validate_skipped_iff_promoted(self):
        """Integration: install a stub validate-experiment.py that ALWAYS
        fails. With the flag promoted, init must still exit 0. Without it,
        init must exit 1. This locks the user-facing contract that
        promotion actually causes the validation gate to skip — not just
        that the manifest field is set.
        """
        # Install always-failing validate-experiment.py at the path
        # lifecycle-init.sh looks: $PROJECT_DIR/scripts/validate-experiment.py
        scripts_dir = self.tmp / "scripts"
        scripts_dir.mkdir()
        validator = scripts_dir / "validate-experiment.py"
        validator.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "print('Error: stub validator always fails', file=sys.stderr)\n"
            "sys.exit(1)\n"
        )
        os.chmod(validator, 0o755)

        self._write_skill("iter7", """\
modes:
  default:
    states: ["0","99"]
  cross:
    trigger: "--cross"
    states: ["x0","99"]
    skip_experiment_validation: true
""")
        # Cross mode → promotion fires → validator NOT invoked → exit 0
        proc_cross = self._run("iter7", '{"mode":"cross"}')
        self.assertEqual(
            proc_cross.returncode, 0,
            f"cross mode should skip validator, got exit {proc_cross.returncode}\n"
            f"stderr: {proc_cross.stderr}",
        )

        # Default mode → no promotion → validator runs → fails → exit 1
        proc_default = self._run("iter7", '{"mode":"default"}')
        self.assertEqual(
            proc_default.returncode, 1,
            f"default mode should fail at validator, got exit {proc_default.returncode}\n"
            f"stderr: {proc_default.stderr}",
        )
        self.assertIn("experiment.yaml validation failed", proc_default.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
