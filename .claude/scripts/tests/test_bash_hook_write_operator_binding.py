#!/usr/bin/env python3
"""test_bash_hook_write_operator_binding.py — class-level prevention test.

Validates the bash_hook_write_operator_binding rule (template-coherence-
rules.json). Issue #1236: 7 historical sibling defects (#1023, #1045, #1064,
#1123, #1185, #1223, #1230) where bash hooks used unbound co-occurrence regex
without binding the write operator to the protected path target. The rule
verifies (a) every entry in write-guard-hooks.json points at an existing
hook with the protected_path_regex literal in source and every declared
write_operator referenced, and (b) no unregistered .sh in scan_glob contains
the historical anti-pattern shapes.

Each test isolates by copying .claude/ to a tempdir, mutating the manifest
and/or hook fixtures there, and running the linter via cli.py.

Run: python3 .claude/scripts/tests/test_bash_hook_write_operator_binding.py
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


class TestBashHookWriteOperatorBinding(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_bhwob_"))
        shutil.copytree(ROOT / ".claude", self.tmp / ".claude", dirs_exist_ok=True)
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_linter(self) -> tuple[int, str, str]:
        env = os.environ.copy()
        env["VL_REPO_ROOT"] = str(self.tmp)
        env["VL_RULES_PATH"] = str(self.tmp / ".claude/patterns/template-coherence-rules.json")
        env["VL_JSON_OUT"] = "1"
        env["VL_WARN_ONLY"] = "1"
        proc = subprocess.run(
            ["python3", str(self.tmp / ".claude/scripts/lib/linter/cli.py")],
            capture_output=True, text=True, env=env, timeout=60,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def _findings(self) -> list[str]:
        rc, stdout, stderr = self._run_linter()
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            self.fail(f"linter did not return JSON: rc={rc} stdout={stdout!r} stderr={stderr!r}")
        return [f for f in data.get("cross_file_contradiction", [])
                if "bash-hook-write-operator-binding" in f]

    def _write_manifest(self, entries: list):
        manifest = {"write_guards": entries}
        (self.tmp / ".claude/patterns/write-guard-hooks.json").write_text(
            json.dumps(manifest, indent=2)
        )

    def _write_hook(self, name: str, content: str):
        hook_path = self.tmp / ".claude/hooks" / name
        hook_path.write_text(content)
        hook_path.chmod(0o755)

    def _delete_hook(self, name: str):
        (self.tmp / ".claude/hooks" / name).unlink(missing_ok=True)

    # ---- Manifest verification (Phase 1) ----

    def test_default_repo_state_passes(self):
        """The committed manifest + hooks should produce zero findings after
        the dd parity fix landed in commit C."""
        findings = self._findings()
        self.assertEqual(findings, [], f"unexpected default-state findings: {findings}")

    def test_manifest_entry_pointing_at_nonexistent_hook_fires(self):
        self._write_manifest([
            {
                "hook": ".claude/hooks/does-not-exist.sh",
                "protected_path_regex": "phantom-path",
                "write_operators": [">", ">>"],
            }
        ])
        findings = self._findings()
        self.assertTrue(
            any("does-not-exist.sh" in f and "manifest entry points at nonexistent file" in f
                for f in findings),
            f"expected nonexistent-hook finding, got: {findings}",
        )

    def test_manifest_protected_path_absent_from_hook_fires(self):
        # Inject a hook that does NOT contain the declared protected_path_regex
        self._write_hook("test-bogus-guard.sh", "#!/usr/bin/env bash\nexit 0\n")
        self._write_manifest([
            {
                "hook": ".claude/hooks/test-bogus-guard.sh",
                "protected_path_regex": "this-string-not-in-source",
                "write_operators": [">"],
            }
        ])
        findings = self._findings()
        self.assertTrue(
            any("test-bogus-guard.sh" in f
                and "protected_path_regex literal" in f
                and "not found in source" in f
                for f in findings),
            f"expected protected_path-absent finding, got: {findings}",
        )

    def test_manifest_write_operator_missing_fires(self):
        # Hook source contains `tee|cp|mv` but manifest declares `dd` too.
        # Word-boundary check should detect that `dd` is not actually used as
        # a token (only as a substring of unrelated identifiers if at all).
        self._write_hook(
            "test-no-dd-guard.sh",
            "#!/usr/bin/env bash\n"
            "# protected: special-target/foo\n"
            "if echo $C | awk '/special-target/ && /(tee|cp|mv)/'; then exit 1; fi\n",
        )
        self._write_manifest([
            {
                "hook": ".claude/hooks/test-no-dd-guard.sh",
                "protected_path_regex": "special-target",
                "write_operators": ["tee", "cp", "mv", "dd"],
            }
        ])
        findings = self._findings()
        self.assertTrue(
            any("test-no-dd-guard.sh" in f and "'dd'" in f and "missing" in f for f in findings),
            f"expected missing-dd finding, got: {findings}",
        )

    # ---- Anti-pattern scan (Phase 2) ----

    def test_unregistered_grep_with_dotstar_fires(self):
        """Shape A: grep -qE '<op>.*<path>' — historical #1230 shape."""
        self._write_hook(
            "test-ap-shape-a.sh",
            "#!/usr/bin/env bash\n"
            "if echo \"$NORM\" | grep -qE '(>|>>|tee|cp|mv|dd).*phantom-path-name'; then\n"
            "  exit 1\n"
            "fi\n",
        )
        findings = self._findings()
        self.assertTrue(
            any("test-ap-shape-a.sh" in f and "anti-pattern 'grep-with-.*'" in f
                and "not registered" in f
                for f in findings),
            f"expected anti-pattern shape A finding, got: {findings}",
        )

    def test_unregistered_awk_co_occurrence_fires(self):
        """Shape B: awk '/<path>/ && /(<op>)/' — original co-occurrence."""
        self._write_hook(
            "test-ap-shape-b.sh",
            "#!/usr/bin/env bash\n"
            "if echo $C | awk '/phantom-path/ && /(>|>>|tee|cp|mv|dd)/'; then exit 1; fi\n",
        )
        findings = self._findings()
        self.assertTrue(
            any("test-ap-shape-b.sh" in f for f in findings),
            f"expected anti-pattern shape B finding, got: {findings}",
        )

    def test_pragma_allow_suppresses_anti_pattern(self):
        """`# coherence-allow: unbound-fastpath` suppresses an anti-pattern
        match within ±200 chars (legitimate fast-path filter case)."""
        self._write_hook(
            "test-pragma-fastpath.sh",
            "#!/usr/bin/env bash\n"
            "# Fast-path glob: cheap pre-filter before downstream bound check.\n"
            "# coherence-allow: unbound-fastpath\n"
            "if echo \"$NORM\" | grep -qE '(>|>>|tee|cp|mv|dd).*phantom-path'; then\n"
            "  : # downstream bound-target check would go here\n"
            "fi\n",
        )
        findings = self._findings()
        self.assertFalse(
            any("test-pragma-fastpath.sh" in f for f in findings),
            f"pragma should suppress anti-pattern finding, got: {findings}",
        )

    def test_verbatim_1230_pre_fix_shape_fires(self):
        """Pin: the pre-#1230 buggy line in trace-write-guard.sh (commit
        before 528ccd4) is the canonical instance the rule must catch. If a
        future detector refactor weakens grep_body_re or body_write_op_re,
        this test fails — preventing silent regression of the rule's
        coverage of historical defects.

        Verbatim from `git show 528ccd4^:.claude/hooks/trace-write-guard.sh`
        (line 38). Hook is intentionally unregistered in the manifest so
        the Phase 2 anti-pattern scan fires."""
        self._write_hook(
            "test-1230-verbatim.sh",
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "COMMAND=\"$1\"\n"
            "case \"$COMMAND\" in\n"
            "  *agent-spawn-log*) ;;\n"
            "  *) exit 0 ;;\n"
            "esac\n"
            "NORM=$(printf '%s' \"$COMMAND\" | sed -E 's/[0-9]*>+&[0-9]+//g')\n"
            # ↓ verbatim pre-#1230 buggy regex
            "if echo \"$NORM\" | grep -qE '(>|>>|[[:space:]]tee[[:space:]]|[[:space:]]cp[[:space:]]|[[:space:]]mv[[:space:]]|[[:space:]]dd[[:space:]]).*agent-spawn-log'; then\n"
            "  echo 'deny' >&2\n"
            "  exit 2\n"
            "fi\n",
        )
        findings = self._findings()
        self.assertTrue(
            any("test-1230-verbatim.sh" in f and "anti-pattern 'grep-with-.*'" in f
                and "not registered" in f
                for f in findings),
            f"detector must catch the verbatim #1230 pre-fix regex, got: {findings}",
        )

    def test_registered_hook_with_post_fix_shape_passes(self):
        """The 4 committed write-guard hooks (after the dd parity fix) use the
        canonical bound-target shape; no anti-pattern findings should fire on
        them."""
        findings = self._findings()
        # All four registered hooks should be clean.
        for hook in [
            ".claude/hooks/agent-trace-write-guard.sh",
            ".claude/hooks/trace-write-guard.sh",
            ".claude/hooks/fix-ledger-write-guard.sh",
            ".claude/hooks/bootstrap-phase-a-write-guard.sh",
        ]:
            self.assertFalse(
                any(hook in f and "anti-pattern" in f for f in findings),
                f"{hook} should not fire anti-pattern findings: got {findings}",
            )

    def test_clean_unrelated_hook_does_not_fire(self):
        """A hook that does no write-guard work and contains none of the
        anti-pattern shapes should not fire."""
        self._write_hook(
            "test-unrelated.sh",
            "#!/usr/bin/env bash\nset -euo pipefail\necho 'hello'\nexit 0\n",
        )
        findings = self._findings()
        self.assertFalse(
            any("test-unrelated.sh" in f for f in findings),
            f"unrelated hook should not fire, got: {findings}",
        )

    # ---- Canonicalization enforcement (Phase 3, #1298) ----

    def test_phase3_canonicalize_before_match_passes(self):
        """Phase 3: hook calls canonicalize_bash_command.py before any
        regex match. No raw $COMMAND references after canonicalize line.
        Should produce 0 findings."""
        self._write_manifest([
            {
                "hook": ".claude/hooks/test-canon-ok.sh",
                "protected_path_regex": "test-protected/",
                "write_operators": [">", ">>"],
            }
        ])
        self._write_hook(
            "test-canon-ok.sh",
            "#!/usr/bin/env bash\n"
            "COMMAND=\"$1\"\n"
            "case \"$COMMAND\" in *test-protected/*) ;; *) exit 0 ;; esac\n"
            "COMMAND_CANONICAL=$(printf '%s' \"$COMMAND\" | python3 .claude/scripts/lib/canonicalize_bash_command.py)\n"
            "case \"$COMMAND_CANONICAL\" in *test-protected/*) ;; *) exit 0 ;; esac\n"
            "if echo \"$COMMAND_CANONICAL\" | awk '/(>|>>) test-protected\\//'; then\n"
            "  echo deny >&2; exit 2\n"
            "fi\n",
        )
        findings = self._findings()
        self.assertFalse(
            any("test-canon-ok.sh" in f and "#1298" in f for f in findings),
            f"hook with canonicalize before match should pass Phase 3, got: {findings}",
        )

    def test_phase3_missing_canonicalize_fires(self):
        """Phase 3: registered hook with NO canonicalize_bash_command call
        must fire 'missing canonicalize' finding."""
        self._write_manifest([
            {
                "hook": ".claude/hooks/test-no-canon.sh",
                "protected_path_regex": "test-protected/",
                "write_operators": [">", ">>"],
            }
        ])
        self._write_hook(
            "test-no-canon.sh",
            "#!/usr/bin/env bash\n"
            "COMMAND=\"$1\"\n"
            "case \"$COMMAND\" in *test-protected/*) ;; *) exit 0 ;; esac\n"
            # No canonicalize call — directly matches on $COMMAND.
            "if echo \"$COMMAND\" | awk '/(>|>>) test-protected\\//'; then\n"
            "  echo deny >&2; exit 2\n"
            "fi\n",
        )
        findings = self._findings()
        self.assertTrue(
            any("test-no-canon.sh" in f and "missing canonicalize_bash_command.py" in f
                and "#1298" in f
                for f in findings),
            f"expected missing-canonicalize finding, got: {findings}",
        )

    def test_phase3_raw_command_after_canonicalize_without_pragma_fires(self):
        """Phase 3: hook canonicalizes but later uses raw "$COMMAND" without
        the pragma — must fire."""
        self._write_manifest([
            {
                "hook": ".claude/hooks/test-raw-no-pragma.sh",
                "protected_path_regex": "test-protected/",
                "write_operators": [">", ">>"],
            }
        ])
        self._write_hook(
            "test-raw-no-pragma.sh",
            "#!/usr/bin/env bash\n"
            "COMMAND=\"$1\"\n"
            "case \"$COMMAND\" in *test-protected/*) ;; *) exit 0 ;; esac\n"
            "COMMAND_CANONICAL=$(printf '%s' \"$COMMAND\" | python3 .claude/scripts/lib/canonicalize_bash_command.py)\n"
            "case \"$COMMAND_CANONICAL\" in *test-protected/*) ;; *) exit 0 ;; esac\n"
            # Raw $COMMAND reference after canonicalize, no pragma — Phase 3 fires.
            "if echo \"$COMMAND\" | awk '/(>|>>) test-protected\\//'; then\n"
            "  echo deny >&2; exit 2\n"
            "fi\n",
        )
        findings = self._findings()
        self.assertTrue(
            any("test-raw-no-pragma.sh" in f and "raw \"$COMMAND\" reference" in f
                and "#1298" in f
                for f in findings),
            f"expected raw-without-pragma finding, got: {findings}",
        )

    def test_phase3_raw_command_after_canonicalize_with_pragma_passes(self):
        """Phase 3: hook canonicalizes and later uses raw "$COMMAND" but with
        the pragma within ±5 lines — must NOT fire."""
        self._write_manifest([
            {
                "hook": ".claude/hooks/test-raw-with-pragma.sh",
                "protected_path_regex": "test-protected/",
                "write_operators": [">", ">>"],
            }
        ])
        self._write_hook(
            "test-raw-with-pragma.sh",
            "#!/usr/bin/env bash\n"
            "COMMAND=\"$1\"\n"
            "case \"$COMMAND\" in *test-protected/*) ;; *) exit 0 ;; esac\n"
            "COMMAND_CANONICAL=$(printf '%s' \"$COMMAND\" | python3 .claude/scripts/lib/canonicalize_bash_command.py)\n"
            "case \"$COMMAND_CANONICAL\" in *test-protected/*) ;; *) exit 0 ;; esac\n"
            "# coherence-allow: raw-command — heredoc-fed python attack detection\n"
            "if echo \"$COMMAND\" | grep -qE 'open\\(.*test-protected/'; then\n"
            "  echo deny >&2; exit 2\n"
            "fi\n",
        )
        findings = self._findings()
        self.assertFalse(
            any("test-raw-with-pragma.sh" in f and "raw \"$COMMAND\"" in f for f in findings),
            f"hook with pragma should pass Phase 3, got: {findings}",
        )


if __name__ == "__main__":
    unittest.main()
