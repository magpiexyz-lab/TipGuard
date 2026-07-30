#!/usr/bin/env python3
"""test_codemod_canonical_writer_audit.py — coverage for PR-A audit script.

Confirms the audit script:
  1. Detects S1-S4 + tee write shapes targeting manifest paths.
  2. Does NOT flag read-only mentions (open(...,'r'), json.load,
     os.path.exists, [ -f path ], backtick prose).
  3. Tags VERIFY-section writes as verify_misplacement (always manual review).
  4. Tags out-of-manifest writes as in_scope=False.
  5. Detects writes inside helper-script .sh and .py files.
  6. Idempotent — re-running produces the same manifest.
  7. --check exits 1 when in-scope findings exist, 0 otherwise.

Run: python3 .claude/scripts/tests/test_codemod_canonical_writer_audit.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".claude/scripts/codemod-canonical-writer-audit.py"


class AuditScriptHarness(unittest.TestCase):
    """Build a minimal synthetic .claude/ tree in a tempdir and run the
    audit script against it. Asserts on the JSON output."""

    @classmethod
    def setUpClass(cls):
        if not SCRIPT.is_file():
            raise RuntimeError(f"audit script missing: {SCRIPT}")

    def _make_tree(
        self,
        files: dict[str, str],
        manifest_paths: list[str] | None = None,
    ) -> Path:
        """Create a tempdir with a fake .claude/ tree.

        files: relative-path → content. Paths starting with '.claude/...' or
               'src/...' are written verbatim; the manifest is auto-generated
               from manifest_paths.
        """
        if manifest_paths is None:
            manifest_paths = [
                ".runs/q-dimensions.json",
                ".runs/change-context.json",
                ".runs/solve-trace.json",
                ".runs/e2e-result.json",
                ".runs/quality-merge.json",
            ]
        tmp = Path(tempfile.mkdtemp(prefix="audit-test-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

        # Generate the manifest fixture.
        manifest_dir = tmp / ".claude/patterns"
        manifest_dir.mkdir(parents=True)
        manifest_path = manifest_dir / "gate-readable-artifacts-canonical.json"
        manifest_path.write_text(json.dumps({
            "artifacts": [{"path": p} for p in manifest_paths],
        }))

        # Copy the actual audit script into the temp tree (preserves the
        # script's `parents[2]` REPO_ROOT calculation).
        target_script = tmp / ".claude/scripts/codemod-canonical-writer-audit.py"
        target_script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(SCRIPT, target_script)

        # Materialize fixture files.
        for rel, content in files.items():
            full = tmp / rel
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(textwrap.dedent(content))

        # .runs/ for output.
        (tmp / ".runs").mkdir(parents=True, exist_ok=True)
        return tmp

    def _run_audit(self, tmp: Path, *extra_args: str) -> tuple[int, dict]:
        """Run audit.py in tmp, return (exit_code, manifest_dict)."""
        proc = subprocess.run(
            [sys.executable, str(tmp / ".claude/scripts/codemod-canonical-writer-audit.py"),
             "--json", *extra_args],
            cwd=tmp, capture_output=True, text=True,
        )
        manifest_path = tmp / ".runs/canonical-writer-migration-manifest.json"
        if manifest_path.exists():
            data = json.loads(manifest_path.read_text())
        else:
            data = {}
        return proc.returncode, data


class TestS1S2S3S4Detection(AuditScriptHarness):

    def test_s2_single_call_detected(self):
        tmp = self._make_tree({
            ".claude/skills/audit/state-2-prioritize.md": """
            **ACTIONS:**
            ```bash
            python3 -c "
            import json
            json.dump({'a': 1}, open('.runs/q-dimensions.json', 'w'))
            "
            ```
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        in_scope = [e for e in m["entries"] if e["in_scope"]]
        self.assertEqual(len(in_scope), 1, m)
        self.assertEqual(in_scope[0]["writer_shape"], "S2")
        self.assertEqual(in_scope[0]["target_path"], ".runs/q-dimensions.json")

    def test_s1_multi_line_detected(self):
        tmp = self._make_tree({
            ".claude/skills/change/state-5.md": """
            **ACTIONS:**
            ```bash
            python3 -c "
            import json
            with open('.runs/change-context.json', 'w') as f:
                json.dump({'classification': 'feature'}, f, indent=2)
            "
            ```
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        in_scope = [e for e in m["entries"] if e["in_scope"]]
        self.assertEqual(len(in_scope), 1)
        self.assertEqual(in_scope[0]["writer_shape"], "S1")

    def test_s3_heredoc_detected(self):
        tmp = self._make_tree({
            ".claude/skills/verify/state-3c.md": """
            **ACTIONS:**
            ```bash
            cat > .runs/quality-merge.json <<'EOF'
            {"verdict":"pass"}
            EOF
            ```
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        in_scope = [e for e in m["entries"] if e["in_scope"]]
        self.assertEqual(len(in_scope), 1)
        self.assertEqual(in_scope[0]["writer_shape"], "S3")

    def test_s4_echo_redirect_detected(self):
        tmp = self._make_tree({
            ".claude/skills/verify/state-5.md": """
            **ACTIONS:**
            ```bash
            echo '{"skipped":true}' > .runs/e2e-result.json
            ```
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        in_scope = [e for e in m["entries"] if e["in_scope"]]
        self.assertEqual(len(in_scope), 1)
        self.assertEqual(in_scope[0]["writer_shape"], "S4")

    def test_tee_detected(self):
        tmp = self._make_tree({
            ".claude/skills/x/state-0.md": """
            **ACTIONS:**
            ```bash
            echo '{"x":1}' | tee .runs/q-dimensions.json
            ```
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        in_scope = [e for e in m["entries"] if e["in_scope"]]
        self.assertEqual(len(in_scope), 1, m)
        self.assertEqual(in_scope[0]["writer_shape"], "TEE")


class TestReadSyntaxAllowlisted(AuditScriptHarness):
    """The ~455-instance false-positive baseline: read-only mentions of
    canonical paths must NOT produce findings."""

    def test_read_open_not_flagged(self):
        tmp = self._make_tree({
            ".claude/skills/x/state-0.md": """
            **ACTIONS:**
            ```bash
            python3 -c "
            import json
            d = json.load(open('.runs/q-dimensions.json', 'r'))
            print(d)
            "
            ```
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        self.assertEqual(len([e for e in m["entries"] if e["in_scope"]]), 0)

    def test_json_load_not_flagged(self):
        tmp = self._make_tree({
            ".claude/skills/x/state-0.md": """
            **ACTIONS:**
            ```bash
            python3 -c "import json; print(json.load(open('.runs/q-dimensions.json')))"
            ```
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        self.assertEqual(len([e for e in m["entries"] if e["in_scope"]]), 0)

    def test_os_path_exists_not_flagged(self):
        tmp = self._make_tree({
            ".claude/skills/x/state-0.md": """
            **POSTCONDITIONS:**
            - `.runs/q-dimensions.json` exists.

            **VERIFY:**
            ```bash
            python3 -c "import os, sys; sys.exit(0 if os.path.exists('.runs/q-dimensions.json') else 1)"
            ```
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        self.assertEqual(len([e for e in m["entries"] if e["in_scope"]]), 0)

    def test_test_dash_f_not_flagged(self):
        tmp = self._make_tree({
            ".claude/skills/x/state-0.md": """
            **VERIFY:**
            ```bash
            test -f .runs/q-dimensions.json && echo OK
            [ -f .runs/q-dimensions.json ] || exit 1
            ```
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        self.assertEqual(len([e for e in m["entries"] if e["in_scope"]]), 0)

    def test_backtick_mention_not_flagged(self):
        tmp = self._make_tree({
            ".claude/skills/x/state-0.md": """
            **ACTIONS:**
            Read `.runs/q-dimensions.json` to inspect dimensions.
            See the `q-dimensions.json` artifact for details.

            **POSTCONDITIONS:**
            - `.runs/q-dimensions.json` exists with three dimensions populated.
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        self.assertEqual(len([e for e in m["entries"] if e["in_scope"]]), 0)


class TestSectionDetection(AuditScriptHarness):

    def test_verify_section_tagged_as_misplacement(self):
        tmp = self._make_tree({
            ".claude/skills/x/state-0.md": """
            **VERIFY:**
            ```bash
            python3 -c "
            import json
            json.dump({'pass':True}, open('.runs/quality-merge.json', 'w'))
            "
            ```
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        in_scope = [e for e in m["entries"] if e["in_scope"]]
        self.assertEqual(len(in_scope), 1)
        self.assertEqual(in_scope[0]["section"], "VERIFY")
        self.assertEqual(in_scope[0]["payload_complexity"], "verify_misplacement")

    def test_postconditions_write_detected(self):
        tmp = self._make_tree({
            ".claude/skills/x/state-1.md": """
            **POSTCONDITIONS:**
            ```bash
            python3 -c "import json; json.dump({'a':1}, open('.runs/q-dimensions.json', 'w'))"
            ```
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        in_scope = [e for e in m["entries"] if e["in_scope"]]
        self.assertEqual(len(in_scope), 1)
        self.assertEqual(in_scope[0]["section"], "POSTCONDITIONS")


class TestComplexityClassification(AuditScriptHarness):

    def test_static_dict_is_mechanical(self):
        tmp = self._make_tree({
            ".claude/skills/x/state-0.md": """
            **ACTIONS:**
            ```bash
            python3 -c "
            import json
            json.dump({'a': 1, 'b': 'static'}, open('.runs/q-dimensions.json', 'w'))
            "
            ```
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        in_scope = [e for e in m["entries"] if e["in_scope"]]
        self.assertEqual(in_scope[0]["payload_complexity"], "mechanical")

    def test_var_interpolation_is_bash_interpolated(self):
        tmp = self._make_tree({
            ".claude/skills/x/state-0.md": """
            **ACTIONS:**
            ```bash
            RUN_ID=$(date +%s)
            python3 -c "
            import json
            json.dump({'run_id': '$RUN_ID', 'a': 1}, open('.runs/q-dimensions.json', 'w'))
            "
            ```
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        in_scope = [e for e in m["entries"] if e["in_scope"]]
        self.assertEqual(in_scope[0]["payload_complexity"], "bash_interpolated")

    def test_if_else_is_conditional(self):
        tmp = self._make_tree({
            ".claude/skills/x/state-0.md": """
            **ACTIONS:**
            ```bash
            python3 -c "
            import json, os
            if os.path.exists('.runs/precondition.json'):
                payload = {'a': 1}
            else:
                payload = {'a': 2}
            json.dump(payload, open('.runs/q-dimensions.json', 'w'))
            "
            ```
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        in_scope = [e for e in m["entries"] if e["in_scope"]]
        self.assertEqual(in_scope[0]["payload_complexity"], "conditional")


class TestScopeFiltering(AuditScriptHarness):

    def test_non_manifest_path_out_of_scope(self):
        tmp = self._make_tree({
            ".claude/skills/x/state-0.md": """
            **ACTIONS:**
            ```bash
            python3 -c "import json; json.dump({}, open('.runs/random.json', 'w'))"
            ```
            """,
        }, manifest_paths=[".runs/q-dimensions.json"])  # random.json not in manifest
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        # 1 finding total, 0 in scope.
        self.assertEqual(m["summary"]["total_findings"], 1)
        self.assertEqual(m["summary"]["in_scope"], 0)
        self.assertEqual(m["summary"]["out_of_scope"], 1)

    def test_append_mode_out_of_scope(self):
        tmp = self._make_tree({
            ".claude/skills/x/state-0.md": """
            **ACTIONS:**
            ```bash
            python3 -c "
            with open('.runs/q-dimensions.json', 'a') as f:
                f.write('{}')
            "
            ```
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        # Append-mode is detected but tagged in_scope=False (path matches but mode='a').
        # Per plan, S6 append-mode is out-of-scope.
        self.assertEqual(m["summary"]["in_scope"], 0)


class TestHelperScripts(AuditScriptHarness):

    def test_python_helper_write_detected(self):
        tmp = self._make_tree({
            ".claude/scripts/some-helper.py": """
            import json
            with open('.runs/q-dimensions.json', 'w') as f:
                json.dump({'a': 1}, f)
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        in_scope = [e for e in m["entries"] if e["in_scope"]]
        self.assertEqual(len(in_scope), 1)
        self.assertEqual(in_scope[0]["file"], ".claude/scripts/some-helper.py")

    def test_shell_helper_write_detected(self):
        tmp = self._make_tree({
            ".claude/scripts/some-helper.sh": """
            #!/usr/bin/env bash
            echo '{"a":1}' > .runs/q-dimensions.json
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        in_scope = [e for e in m["entries"] if e["in_scope"]]
        self.assertEqual(len(in_scope), 1)
        self.assertEqual(in_scope[0]["file"], ".claude/scripts/some-helper.sh")
        self.assertEqual(in_scope[0]["writer_shape"], "S4")


class TestIdempotency(AuditScriptHarness):

    def test_two_runs_produce_same_manifest(self):
        tmp = self._make_tree({
            ".claude/skills/x/state-0.md": """
            **ACTIONS:**
            ```bash
            python3 -c "import json; json.dump({}, open('.runs/q-dimensions.json', 'w'))"
            ```
            """,
        })
        rc1, m1 = self._run_audit(tmp)
        rc2, m2 = self._run_audit(tmp)
        self.assertEqual(rc1, 0)
        self.assertEqual(rc2, 0)
        # Strip generated_at since timestamps differ.
        m1.pop("generated_at", None)
        m2.pop("generated_at", None)
        self.assertEqual(m1, m2)


class TestCheckMode(AuditScriptHarness):

    def test_check_exits_one_when_violations_exist(self):
        tmp = self._make_tree({
            ".claude/skills/x/state-0.md": """
            **ACTIONS:**
            ```bash
            python3 -c "import json; json.dump({}, open('.runs/q-dimensions.json', 'w'))"
            ```
            """,
        })
        rc, _ = self._run_audit(tmp, "--check")
        self.assertEqual(rc, 1)

    def test_check_exits_zero_when_clean(self):
        tmp = self._make_tree({
            ".claude/skills/x/state-0.md": """
            **ACTIONS:**
            ```bash
            bash .claude/scripts/lib/write-gate-artifact.sh \\
              --path .runs/q-dimensions.json --payload "{}"
            ```
            """,
        })
        rc, m = self._run_audit(tmp, "--check")
        self.assertEqual(rc, 0)
        self.assertEqual(m["summary"]["in_scope"], 0)


class TestExclusions(AuditScriptHarness):

    def test_canonical_writer_itself_not_scanned(self):
        # The canonical writer is in EXCLUDE_FILES, so its open(...,'w') is
        # not flagged.
        tmp = self._make_tree({
            ".claude/scripts/lib/write-gate-artifact.sh": """
            #!/usr/bin/env bash
            python3 -c "open('.runs/q-dimensions.json', 'w').write('{}')"
            """,
        })
        rc, m = self._run_audit(tmp)
        self.assertEqual(rc, 0)
        self.assertEqual(m["summary"]["in_scope"], 0)


if __name__ == "__main__":
    unittest.main()
