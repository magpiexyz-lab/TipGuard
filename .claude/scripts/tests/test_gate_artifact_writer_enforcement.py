#!/usr/bin/env python3
"""Meta-test for the gate_artifact_writer_enforcement coherence rule.

Issue #1299 — the rule catches direct writes to gate-readable
.runs/*.json artifacts (declared in
gate-readable-artifacts-canonical.json) from outside the canonical
writer (.claude/scripts/lib/write-gate-artifact.sh).

Test cases (R1-C8 + R2-C1 coverage):
  1. Canonical writer call yields no finding.
  2. with open(target,'w') yields a finding (S1 shape).
  3. with open(target,'r') yields no finding (read suppressor).
  4. json.dump(d, open(target,'w')) yields a finding (S2 shape).
  5. echo > target yields a finding (S4 shape).
  6. cat > target <<EOF yields a finding (S3 shape).
  7. tee target yields a finding.
  8. Helper scripts (.sh/.py) under .claude/scripts/ are scanned.
  9. Read-syntax baseline: open(target,'r'), json.load, os.path.exists,
     [-f path], backtick prose — none produce findings.
 10. State-3b reference pattern (canonical writer call) yields no finding.

Run: python3 .claude/scripts/tests/test_gate_artifact_writer_enforcement.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


REAL_REPO = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
LINTER = os.path.join(REAL_REPO, ".claude", "scripts", "verify-linter.sh")
LIB_DIR = os.path.join(REAL_REPO, ".claude", "scripts", "lib")


def _setup_repo(tmpdir: str, rules: dict, manifest_paths: list, files: dict):
    """Create a minimal repo skeleton scanned by verify-linter.sh."""
    os.makedirs(os.path.join(tmpdir, ".claude/scripts"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, ".claude/patterns"), exist_ok=True)
    shutil.copy(LINTER, os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"))
    if os.path.isdir(LIB_DIR):
        shutil.copytree(
            LIB_DIR,
            os.path.join(tmpdir, ".claude/scripts/lib"),
            dirs_exist_ok=True,
        )
    with open(os.path.join(tmpdir, ".claude/patterns/state-registry.json"), "w") as f:
        json.dump({}, f)
    with open(os.path.join(tmpdir, ".claude/patterns/template-coherence-rules.json"), "w") as f:
        json.dump(rules, f)
    # Synthesize the gate-readable artifacts manifest fixture.
    manifest_data = {"artifacts": [{"path": p} for p in manifest_paths]}
    manifest_path = os.path.join(tmpdir, ".claude/patterns/gate-readable-artifacts-canonical.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest_data, f)
    for rel, content in files.items():
        full = os.path.join(tmpdir, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(content)


def _run_linter(tmpdir: str, *extra_args: str):
    result = subprocess.run(
        ["bash", os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"), *extra_args],
        capture_output=True,
        text=True,
        cwd=tmpdir,
    )
    return result.returncode, result.stdout, result.stderr


def _rule_with_corpus(corpus: list = None) -> dict:
    return {
        "rules": [
            {
                "id": "gate-artifact-writer-enforcement",
                "type": "gate_artifact_writer_enforcement",
                "severity": "warn",
                "manifest_path": ".claude/patterns/gate-readable-artifacts-canonical.json",
                "allowed_writers": [],
                "scan_corpus": corpus or [".claude/skills"],
                "description": "Test fixture rule",
            },
        ],
    }


def _findings_in(stdout: str) -> list[str]:
    """Extract finding lines mentioning the rule id."""
    return [l for l in stdout.splitlines() if "gate-artifact-writer-enforcement" in l]


class GateArtifactEnforcementBase(unittest.TestCase):
    manifest = [".runs/q-dimensions.json", ".runs/change-context.json"]

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="gate-enforce-test-")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestCanonicalWriterAllowed(GateArtifactEnforcementBase):
    def test_canonical_writer_call_yields_no_finding(self):
        _setup_repo(
            self.tmpdir,
            _rule_with_corpus(),
            self.manifest,
            {
                ".claude/skills/audit/state-0.md": (
                    "# STATE 0\n\n"
                    "**ACTIONS:**\n"
                    "```bash\n"
                    "PAYLOAD=$(python3 -c \"import json; print(json.dumps({'a': 1}))\")\n"
                    "bash .claude/scripts/lib/write-gate-artifact.sh \\\n"
                    "  --path .runs/q-dimensions.json \\\n"
                    "  --payload \"$PAYLOAD\" --skill audit\n"
                    "```\n"
                ),
            },
        )
        rc, out, err = _run_linter(self.tmpdir, "--warn-only")
        self.assertEqual(_findings_in(out + err), [], (out, err))

    def test_state_3b_reference_pattern_yields_no_finding(self):
        # The canonical migration target shape from
        # .claude/skills/deploy/state-3b-provision-host.md:64-97
        _setup_repo(
            self.tmpdir,
            _rule_with_corpus(),
            self.manifest,
            {
                ".claude/skills/deploy/state-3b.md": (
                    "**ACTIONS:**\n"
                    "```bash\n"
                    "PAYLOAD=$(python3 -c \"\n"
                    "import json\n"
                    "print(json.dumps({'hosting_created': True, 'canonical_url': '<url>'}))\n"
                    "\")\n"
                    "bash .claude/scripts/lib/write-gate-artifact.sh \\\n"
                    "  --path .runs/q-dimensions.json --payload \"$PAYLOAD\" --skill deploy\n"
                    "```\n"
                ),
            },
        )
        rc, out, err = _run_linter(self.tmpdir, "--warn-only")
        self.assertEqual(_findings_in(out + err), [], (out, err))


class TestS1WithOpen(GateArtifactEnforcementBase):
    def test_with_open_write_yields_finding(self):
        _setup_repo(
            self.tmpdir,
            _rule_with_corpus(),
            self.manifest,
            {
                ".claude/skills/audit/state-0.md": (
                    "**ACTIONS:**\n"
                    "```bash\n"
                    "python3 -c \"\n"
                    "import json\n"
                    "with open('.runs/q-dimensions.json', 'w') as f:\n"
                    "    json.dump({}, f)\n"
                    "\"\n"
                    "```\n"
                ),
            },
        )
        rc, out, err = _run_linter(self.tmpdir, "--warn-only")
        findings = _findings_in(out + err)
        self.assertEqual(len(findings), 1, (out, err))
        self.assertIn(".runs/q-dimensions.json", findings[0])

    def test_with_open_read_yields_no_finding(self):
        _setup_repo(
            self.tmpdir,
            _rule_with_corpus(),
            self.manifest,
            {
                ".claude/skills/audit/state-0.md": (
                    "**ACTIONS:**\n"
                    "```bash\n"
                    "python3 -c \"\n"
                    "import json\n"
                    "with open('.runs/q-dimensions.json', 'r') as f:\n"
                    "    d = json.load(f)\n"
                    "\"\n"
                    "```\n"
                ),
            },
        )
        rc, out, err = _run_linter(self.tmpdir, "--warn-only")
        self.assertEqual(_findings_in(out + err), [], (out, err))


class TestS2JsonDump(GateArtifactEnforcementBase):
    def test_json_dump_open_yields_finding(self):
        _setup_repo(
            self.tmpdir,
            _rule_with_corpus(),
            self.manifest,
            {
                ".claude/skills/audit/state-0.md": (
                    "**ACTIONS:**\n"
                    "```bash\n"
                    "python3 -c \"json.dump({}, open('.runs/change-context.json', 'w'))\"\n"
                    "```\n"
                ),
            },
        )
        rc, out, err = _run_linter(self.tmpdir, "--warn-only")
        findings = _findings_in(out + err)
        self.assertEqual(len(findings), 1, (out, err))
        self.assertIn(".runs/change-context.json", findings[0])

    def test_multiline_payload_with_function_call_yields_finding(self):
        """PR-FIX-S2 regression: the previous S2 regex
        `json\\.dump\\([^()]*?open\\(...)` could not span function calls in
        a multi-line dict payload (e.g. `datetime.now()`). State-99 had
        exactly this shape and was silently missed. The unified matcher
        with negative lookbehind on `with ` catches it."""
        _setup_repo(
            self.tmpdir,
            _rule_with_corpus(),
            self.manifest,
            {
                ".claude/skills/audit/state-0.md": (
                    "**ACTIONS:**\n"
                    "```bash\n"
                    "python3 -c \"\n"
                    "import json, datetime\n"
                    "json.dump({\n"
                    "    'pass': False,\n"
                    "    'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()\n"
                    "}, open('.runs/q-dimensions.json', 'w'), indent=2)\n"
                    "\"\n"
                    "```\n"
                ),
            },
        )
        rc, out, err = _run_linter(self.tmpdir, "--warn-only")
        findings = _findings_in(out + err)
        self.assertEqual(len(findings), 1, (out, err))
        self.assertIn(".runs/q-dimensions.json", findings[0])


class TestS4EchoRedirect(GateArtifactEnforcementBase):
    def test_echo_redirect_yields_finding(self):
        _setup_repo(
            self.tmpdir,
            _rule_with_corpus(),
            self.manifest,
            {
                ".claude/skills/audit/state-0.md": (
                    "**ACTIONS:**\n"
                    "```bash\n"
                    "echo '{\"a\":1}' > .runs/q-dimensions.json\n"
                    "```\n"
                ),
            },
        )
        rc, out, err = _run_linter(self.tmpdir, "--warn-only")
        findings = _findings_in(out + err)
        self.assertEqual(len(findings), 1, (out, err))


class TestS3Heredoc(GateArtifactEnforcementBase):
    def test_cat_heredoc_yields_finding(self):
        _setup_repo(
            self.tmpdir,
            _rule_with_corpus(),
            self.manifest,
            {
                ".claude/skills/audit/state-0.md": (
                    "**ACTIONS:**\n"
                    "```bash\n"
                    "cat > .runs/q-dimensions.json <<EOF\n"
                    "{\"a\":1}\n"
                    "EOF\n"
                    "```\n"
                ),
            },
        )
        rc, out, err = _run_linter(self.tmpdir, "--warn-only")
        findings = _findings_in(out + err)
        self.assertEqual(len(findings), 1, (out, err))


class TestTeeRedirect(GateArtifactEnforcementBase):
    def test_tee_yields_finding(self):
        _setup_repo(
            self.tmpdir,
            _rule_with_corpus(),
            self.manifest,
            {
                ".claude/skills/audit/state-0.md": (
                    "**ACTIONS:**\n"
                    "```bash\n"
                    "echo '{}' | tee .runs/q-dimensions.json\n"
                    "```\n"
                ),
            },
        )
        rc, out, err = _run_linter(self.tmpdir, "--warn-only")
        findings = _findings_in(out + err)
        self.assertEqual(len(findings), 1, (out, err))


class TestHelperScriptCorpus(GateArtifactEnforcementBase):
    def test_helper_script_write_detected(self):
        _setup_repo(
            self.tmpdir,
            _rule_with_corpus(corpus=[".claude/scripts"]),
            self.manifest,
            {
                ".claude/scripts/some-helper.py": (
                    "import json\n"
                    "with open('.runs/q-dimensions.json', 'w') as f:\n"
                    "    json.dump({}, f)\n"
                ),
            },
        )
        rc, out, err = _run_linter(self.tmpdir, "--warn-only")
        findings = _findings_in(out + err)
        self.assertEqual(len(findings), 1, (out, err))


class TestReadSyntaxBaseline(GateArtifactEnforcementBase):
    """The ~455 false-positive baseline: read-only mentions must NOT
    produce findings (R2-C1)."""

    def test_baseline_zero_false_positives(self):
        _setup_repo(
            self.tmpdir,
            _rule_with_corpus(),
            self.manifest,
            {
                ".claude/skills/audit/state-0.md": (
                    "**ACTIONS:**\n"
                    "Read `.runs/q-dimensions.json` and `.runs/change-context.json`.\n"
                    "\n"
                    "```bash\n"
                    "# Read-mode operations:\n"
                    "python3 -c \"open('.runs/q-dimensions.json', 'r')\"\n"
                    "python3 -c \"json.load(open('.runs/change-context.json'))\"\n"
                    "python3 -c \"import os; os.path.exists('.runs/q-dimensions.json')\"\n"
                    "test -f .runs/q-dimensions.json\n"
                    "[ -f .runs/change-context.json ] || exit 1\n"
                    "if [ ! -f .runs/q-dimensions.json ]; then echo 'missing'; fi\n"
                    "```\n"
                    "\n"
                    "**POSTCONDITIONS:**\n"
                    "- `.runs/q-dimensions.json` exists.\n"
                    "- See `.runs/change-context.json` for details.\n"
                ),
            },
        )
        rc, out, err = _run_linter(self.tmpdir, "--warn-only")
        self.assertEqual(_findings_in(out + err), [], (out, err))


class TestAllowedWriters(GateArtifactEnforcementBase):
    def test_allowed_writer_skipped(self):
        _setup_repo(
            self.tmpdir,
            {
                "rules": [
                    {
                        "id": "gate-artifact-writer-enforcement",
                        "type": "gate_artifact_writer_enforcement",
                        "severity": "warn",
                        "manifest_path": ".claude/patterns/gate-readable-artifacts-canonical.json",
                        "allowed_writers": [".claude/skills/audit/state-0.md"],
                        "scan_corpus": [".claude/skills"],
                    },
                ],
            },
            self.manifest,
            {
                ".claude/skills/audit/state-0.md": (
                    "```bash\n"
                    "echo '{}' > .runs/q-dimensions.json\n"
                    "```\n"
                ),
            },
        )
        rc, out, err = _run_linter(self.tmpdir, "--warn-only")
        self.assertEqual(_findings_in(out + err), [], (out, err))


if __name__ == "__main__":
    unittest.main()
