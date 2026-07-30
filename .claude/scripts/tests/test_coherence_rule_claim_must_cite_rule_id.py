#!/usr/bin/env python3
"""Behavioral tests for #1261 coherence rule: claim_must_cite_existing_rule_id.

Validates that verify-linter.sh dispatches correctly to the new rule type
introduced for catching false coherence-rule claims (e.g., spec.json declaring
"coherence rule pins X" without a corresponding real rule_id).

Test cases (per /solve plan File 4):
1. Trigger phrase 'coherence rule pins them' (line-2 form) WITHOUT citation
   → must fire (positive baseline)
2. Trigger phrase 'coherence linter rule pins all three' (line-7 form) WITHOUT
   citation → must fire (positive baseline; round-1 critic concern 6b7984313ed1)
3. Trigger WITH valid backtick citation matching existing rule (e.g.,
   `golden-path-role-map`) → must NOT fire (negative)
4. Trigger WITH invalid citation (e.g., `nonexistent-rule-foo`) → must fire
   (citation-resolution test; round-2 critic concern 1d996f546321)
5. Legitimate prose mentioning coherence-rule architecture without trigger
   phrasing → must NOT fire
6. Trigger WITH `rule_id: foo` label form citation matching existing rule →
   must NOT fire (label form support)

Run via: python3 .claude/scripts/tests/test_coherence_rule_claim_must_cite_rule_id.py
Or via:  bash .claude/scripts/tests/run-all.sh
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest


REAL_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LINTER = os.path.join(REAL_REPO, ".claude", "scripts", "verify-linter.sh")
LIB_DIR = os.path.join(REAL_REPO, ".claude", "scripts", "lib")


def _setup_repo(tmpdir, rules, files):
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
    for rel, content in files.items():
        full = os.path.join(tmpdir, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(content)


def _run_linter(tmpdir, *extra_args):
    result = subprocess.run(
        ["bash", os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"), *extra_args],
        capture_output=True,
        text=True,
        cwd=tmpdir,
    )
    return result.returncode, result.stdout, result.stderr


# --- Fixtures --------------------------------------------------------------

# Rule template — points at a fake rules-source file with one real rule_id
# (golden-path-role-map). Tests can plant claims that cite or fail to cite
# this id.
def _rule_md(scan_glob=".claude/**/*.md", rules_source_path=None):
    return {
        "id": "test-coherence-rule-claim-md",
        "type": "claim_must_cite_existing_rule_id",
        "severity": "warn",
        "scan_globs": [scan_glob],
        "claim_patterns": [
            "coherence (linter )?rule (pins|binds)\\b"
        ],
        "citation_pattern": "`([a-z][a-z0-9-]+)`|rule_id:\\s*([a-z][a-z0-9-]+)",
        "window_chars": 200,
        "allowed_rule_ids_source": (rules_source_path or ".claude/patterns/test-rules-source.json"),
        # Exclude the rules-source file itself so its own rules[*].id entries
        # don't accidentally match the claim_pattern (the source declares
        # rule definitions, not claims).
        "exclude_globs": [
            ".claude/patterns/test-rules-source.json"
        ]
    }


# Minimal canonical rules source — a single real rule_id we can cite.
RULES_SOURCE = {
    "rules": [
        {"id": "golden-path-role-map", "type": "field_role_map"}
    ]
}


class TestClaimMustCiteExistingRuleId(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Always plant the canonical rules-source so each test can rely on it
        os.makedirs(os.path.join(self.tmpdir, ".claude/patterns"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _setup(self, rule_dict, files):
        # Inject the rules-source into files
        files = dict(files)
        files[".claude/patterns/test-rules-source.json"] = json.dumps(RULES_SOURCE)
        _setup_repo(self.tmpdir, {"rules": [rule_dict]}, files)

    # Test 1: trigger 'coherence rule pins them' WITHOUT citation → fires
    def test_pins_them_without_citation_fires(self):
        files = {
            ".claude/patterns/sample.md": (
                "# Sample\n\n"
                "These three files must be kept in sync (coherence rule pins them).\n"
            )
        }
        self._setup(_rule_md(), files)
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertIn(
            "test-coherence-rule-claim-md",
            out,
            f"expected rule to fire on 'pins them' without citation; got:\n{out}",
        )
        self.assertIn("sample.md", out)

    # Test 2: trigger 'coherence linter rule pins all three' WITHOUT citation → fires
    def test_pins_all_three_without_citation_fires(self):
        files = {
            ".claude/patterns/sample.md": (
                "# Sample\n\n"
                "Update this file FIRST. The coherence linter rule pins all three to match.\n"
            )
        }
        self._setup(_rule_md(), files)
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertIn("test-coherence-rule-claim-md", out)
        self.assertIn("sample.md", out)

    # Test 3: trigger WITH valid backtick citation → does NOT fire
    def test_valid_backtick_citation_passes(self):
        files = {
            ".claude/patterns/sample.md": (
                "# Sample\n\n"
                "These files are coordinated: see `golden-path-role-map` — that "
                "coherence rule pins the consumer set across multiple skills.\n"
            )
        }
        self._setup(_rule_md(), files)
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertNotIn(
            "test-coherence-rule-claim-md",
            out,
            f"rule should NOT fire when valid citation is present; got:\n{out}",
        )

    # Test 4: trigger WITH invalid citation → fires (citation-resolution test)
    def test_invalid_citation_fires(self):
        files = {
            ".claude/patterns/sample.md": (
                "# Sample\n\n"
                "See `nonexistent-rule-foo` — the coherence rule pins X across "
                "files (THIS RULE_ID DOES NOT EXIST in the canonical source).\n"
            )
        }
        self._setup(_rule_md(), files)
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertIn(
            "test-coherence-rule-claim-md",
            out,
            f"rule should fire when citation does not resolve; got:\n{out}",
        )

    # Test 5: legitimate prose without trigger phrasing → does NOT fire
    def test_no_trigger_phrasing_passes(self):
        files = {
            ".claude/patterns/sample.md": (
                "# Sample\n\n"
                "This document discusses coherence-rule architecture in general "
                "terms. There are many types of rules. None of them are claimed "
                "here to enforce any specific cross-file invariant.\n"
            )
        }
        self._setup(_rule_md(), files)
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertNotIn(
            "test-coherence-rule-claim-md",
            out,
            f"rule should NOT fire on legitimate prose without trigger; got:\n{out}",
        )

    # Test 6: trigger WITH `rule_id: foo` label form citation → does NOT fire
    def test_label_form_citation_passes(self):
        files = {
            ".claude/patterns/sample.md": (
                "# Sample\n\n"
                "rule_id: golden-path-role-map — this coherence rule pins the "
                "field across all consumers.\n"
            )
        }
        self._setup(_rule_md(), files)
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertNotIn(
            "test-coherence-rule-claim-md",
            out,
            f"rule should NOT fire with label-form citation; got:\n{out}",
        )


if __name__ == "__main__":
    unittest.main()
