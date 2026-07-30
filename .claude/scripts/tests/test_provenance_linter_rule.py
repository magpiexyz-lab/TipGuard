#!/usr/bin/env python3
"""test_provenance_linter_rule.py — coherence rule self-test.

Validates:
- check_provenance_aware_runs_read fires on naked .runs/ reads with positive read pattern
- skips when scope= or runs_reader.* marker present
- skips when pragma `# coherence-allow: provenance-blind-read` present
- skips docstring interiors (triple-quote toggle)
- skips test directories (legitimately exercise .runs/ I/O)
- skips files in allowlist
- check_cross_run_channel_exemption_pairing fires when a channel path is in STALE_ARTIFACTS
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
RUNNER = ROOT / ".claude/scripts/lib/linter/runner.py"
VERIFY_LINTER = ROOT / ".claude/scripts/verify-linter.sh"


def run_linter_with_fixture(fixture_root: Path) -> str:
    """Invoke runner.py with VL_REPO_ROOT pointing at a fixture tree."""
    env = os.environ.copy()
    env["VL_REPO_ROOT"] = str(fixture_root)
    env["VL_RULES_PATH"] = str(fixture_root / ".claude/patterns/template-coherence-rules.json")
    env["CLAUDE_PROJECT_DIR"] = str(fixture_root)
    cli = ROOT / ".claude/scripts/lib/linter/cli.py"
    proc = subprocess.run(
        ["python3", str(cli)],
        capture_output=True, text=True, env=env, timeout=30,
    )
    return proc.stdout + proc.stderr


class ProvenanceAwareReadsRuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_linter_"))
        # Minimal repo skeleton
        (self.tmp / ".claude/scripts").mkdir(parents=True)
        (self.tmp / ".claude/hooks").mkdir(parents=True)
        (self.tmp / ".claude/patterns").mkdir(parents=True)
        (self.tmp / ".claude/scripts/lib/linter").mkdir(parents=True)
        # Copy the linter
        shutil.copy(RUNNER, self.tmp / ".claude/scripts/lib/linter/runner.py")
        # Create __init__.py files
        (self.tmp / ".claude/scripts/lib/__init__.py").touch()
        (self.tmp / ".claude/scripts/lib/linter/__init__.py").touch()
        # Minimal coherence-rule-schema.json
        (self.tmp / ".claude/patterns/coherence-rule-schema.json").write_text(json.dumps({
            "$schema": "http://json-schema.org/draft-07/schema#",
            "definitions": {"severity": {"enum": ["block", "warn"]}}
        }))
        # Minimal state-registry.json (required by runner.py entry point)
        (self.tmp / ".claude/patterns/state-registry.json").write_text(json.dumps({}))
        # Minimal skills dir
        (self.tmp / ".claude/skills").mkdir(parents=True, exist_ok=True)
        # Allowlist (empty)
        (self.tmp / ".claude/patterns/provenance-blind-allowlist.json").write_text(
            json.dumps({"allowed": []})
        )
        # cross-run-channels (empty channels for non-pairing tests)
        (self.tmp / ".claude/patterns/cross-run-channels.json").write_text(
            json.dumps({"channels": {}})
        )
        # lifecycle-init shell (empty STALE_ARTIFACTS by default)
        (self.tmp / ".claude/scripts/lifecycle-init.sh").write_text(
            "#!/bin/bash\nSTALE_ARTIFACTS=()\n"
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _rules(self, *rules) -> None:
        (self.tmp / ".claude/patterns/template-coherence-rules.json").write_text(
            json.dumps({"rules": list(rules)})
        )

    def _provenance_rule(self):
        return {
            "id": "provenance_aware_runs_read",
            "type": "provenance_aware_runs_read",
            "severity": "warn",
            "scan_glob": ".claude/scripts/**/*.py,.claude/hooks/**/*.sh",
            "allowlist_path": ".claude/patterns/provenance-blind-allowlist.json",
            "pragma": "# coherence-allow: provenance-blind-read",
        }

    def test_naked_open_runs_jsonl_flagged(self):
        (self.tmp / ".claude/scripts/bad.py").write_text(
            "import json\n"
            "with open('.runs/fix-ledger.jsonl') as fh:\n"
            "    pass\n"
        )
        self._rules(self._provenance_rule())
        out = run_linter_with_fixture(self.tmp)
        self.assertIn("provenance-blind .runs/ read", out)
        self.assertIn("bad.py", out)

    def test_with_runs_reader_marker_clean(self):
        (self.tmp / ".claude/scripts/good.py").write_text(
            "import json\n"
            "from runs_reader import read_jsonl\n"
            "r = read_jsonl('.runs/fix-ledger.jsonl', scope='current-run')\n"
        )
        self._rules(self._provenance_rule())
        out = run_linter_with_fixture(self.tmp)
        self.assertNotIn("good.py", out)

    def test_pragma_suppresses(self):
        (self.tmp / ".claude/scripts/legacy.py").write_text(
            "import json\n"
            "with open('.runs/fix-ledger.jsonl') as fh:  # coherence-allow: provenance-blind-read\n"
            "    pass\n"
        )
        self._rules(self._provenance_rule())
        out = run_linter_with_fixture(self.tmp)
        self.assertNotIn("legacy.py", out)

    def test_docstring_mention_skipped(self):
        # The mention is inside a docstring AND has no read pattern, so
        # it's doubly safe. Validate the docstring skip logic specifically.
        (self.tmp / ".claude/scripts/doc.py").write_text(
            '"""\n'
            "Module that demonstrates open('.runs/fix-ledger.jsonl') as fh:\n"
            '"""\n'
            "import json\n"
        )
        self._rules(self._provenance_rule())
        out = run_linter_with_fixture(self.tmp)
        self.assertNotIn("doc.py", out)

    def test_tests_directory_excluded(self):
        (self.tmp / ".claude/scripts/tests").mkdir()
        (self.tmp / ".claude/scripts/tests/test_x.py").write_text(
            "with open('.runs/fix-ledger.jsonl') as fh:\n"
            "    pass\n"
        )
        self._rules(self._provenance_rule())
        out = run_linter_with_fixture(self.tmp)
        self.assertNotIn("test_x.py", out)

    def test_allowlist_suppresses(self):
        (self.tmp / ".claude/patterns/provenance-blind-allowlist.json").write_text(
            json.dumps({"allowed": [".claude/scripts/old.py"]})
        )
        (self.tmp / ".claude/scripts/old.py").write_text(
            "with open('.runs/fix-ledger.jsonl') as fh:\n"
            "    pass\n"
        )
        self._rules(self._provenance_rule())
        out = run_linter_with_fixture(self.tmp)
        self.assertNotIn("old.py: provenance-blind", out)


class CrossRunChannelPairingRuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_pairing_"))
        (self.tmp / ".claude/scripts/lib/linter").mkdir(parents=True)
        (self.tmp / ".claude/hooks").mkdir(parents=True)
        (self.tmp / ".claude/patterns").mkdir(parents=True)
        shutil.copy(RUNNER, self.tmp / ".claude/scripts/lib/linter/runner.py")
        (self.tmp / ".claude/scripts/lib/__init__.py").touch()
        (self.tmp / ".claude/scripts/lib/linter/__init__.py").touch()
        (self.tmp / ".claude/patterns/coherence-rule-schema.json").write_text(json.dumps({
            "$schema": "http://json-schema.org/draft-07/schema#",
            "definitions": {"severity": {"enum": ["block", "warn"]}}
        }))
        (self.tmp / ".claude/patterns/state-registry.json").write_text(json.dumps({}))
        (self.tmp / ".claude/skills").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _rule(self):
        return {
            "id": "cross_run_channel_exemption_pairing",
            "type": "cross_run_channel_exemption_pairing",
            "severity": "warn",
        }

    def test_path_in_stale_artifacts_fires_without_opt_in(self):
        (self.tmp / ".claude/patterns/cross-run-channels.json").write_text(json.dumps({
            "channels": {
                "test-log": {"paths": [".runs/test-log.jsonl"]}
            }
        }))
        (self.tmp / ".claude/scripts/lifecycle-init.sh").write_text(
            "STALE_ARTIFACTS=(\n"
            '  ".runs/test-log.jsonl"\n'
            ")\n"
        )
        (self.tmp / ".claude/patterns/template-coherence-rules.json").write_text(
            json.dumps({"rules": [self._rule()]})
        )
        out = run_linter_with_fixture(self.tmp)
        self.assertIn("test-log.jsonl", out)
        self.assertIn("STALE_ARTIFACTS", out)

    def test_transient_cross_state_opt_in_suppresses(self):
        (self.tmp / ".claude/patterns/cross-run-channels.json").write_text(json.dumps({
            "channels": {
                "test-log": {
                    "paths": [".runs/test-log.jsonl"],
                    "transient_cross_state": True,
                }
            }
        }))
        (self.tmp / ".claude/scripts/lifecycle-init.sh").write_text(
            "STALE_ARTIFACTS=(\n"
            '  ".runs/test-log.jsonl"\n'
            ")\n"
        )
        (self.tmp / ".claude/patterns/template-coherence-rules.json").write_text(
            json.dumps({"rules": [self._rule()]})
        )
        out = run_linter_with_fixture(self.tmp)
        self.assertNotIn("provenance-blind", out)

    def test_path_not_in_stale_artifacts_passes(self):
        (self.tmp / ".claude/patterns/cross-run-channels.json").write_text(json.dumps({
            "channels": {
                "test-log": {"paths": [".runs/test-log.jsonl"]}
            }
        }))
        (self.tmp / ".claude/scripts/lifecycle-init.sh").write_text(
            "STALE_ARTIFACTS=(\n"
            '  ".runs/observe-result.json"\n'
            ")\n"
        )
        (self.tmp / ".claude/patterns/template-coherence-rules.json").write_text(
            json.dumps({"rules": [self._rule()]})
        )
        out = run_linter_with_fixture(self.tmp)
        self.assertNotIn("test-log", out)


if __name__ == "__main__":
    unittest.main()
