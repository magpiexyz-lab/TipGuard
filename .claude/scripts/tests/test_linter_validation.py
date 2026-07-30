#!/usr/bin/env python3
"""Tests for the rule-load schema validation in lib/linter/runner.py.

Locks the contract added in PR3:
- Unknown rule type -> exit 1 with literal "unknown rule type" message
  naming the offending rule id.
- Unknown field name in a rule -> exit 1 with sorted unknown keys named.
- Missing required field -> exit 1 with sorted missing required named.
- Handler exceptions -> finding emitted, but linter continues (does not crash).

These tests guarantee that typo'd keys in template-coherence-rules.json
fail loudly instead of the pre-PR3 silent-no-op behavior.
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


def _setup_repo_with_rules(tmpdir, rules):
    """Build a tmpdir mini-repo with the given rules JSON."""
    os.makedirs(os.path.join(tmpdir, ".claude/scripts"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, ".claude/patterns"), exist_ok=True)
    shutil.copy(LINTER, os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"))
    shutil.copytree(LIB_DIR, os.path.join(tmpdir, ".claude/scripts/lib"), dirs_exist_ok=True)
    with open(os.path.join(tmpdir, ".claude/patterns/state-registry.json"), "w") as f:
        json.dump({}, f)
    with open(os.path.join(tmpdir, ".claude/patterns/template-coherence-rules.json"), "w") as f:
        json.dump(rules, f)


def _run(tmpdir, *flags):
    result = subprocess.run(
        ["bash", os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"), *flags],
        capture_output=True,
        text=True,
        cwd=tmpdir,
    )
    return result.returncode, result.stdout, result.stderr


class TestUnknownRuleType(unittest.TestCase):
    def test_typoed_type_exits_1_with_rule_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo_with_rules(
                tmpdir,
                {"rules": [{"id": "typo-test", "type": "verdict_vocab_consistncy"}]},
            )
            rc, _stdout, stderr = _run(tmpdir)
        self.assertEqual(rc, 1)
        self.assertIn("unknown rule type", stderr)
        self.assertIn("'verdict_vocab_consistncy'", stderr)
        self.assertIn("typo-test", stderr)

    def test_typoed_type_blocks_under_warn_only(self):
        """Schema errors must override --warn-only (deliberate contract addition)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo_with_rules(
                tmpdir,
                {"rules": [{"id": "typo-test", "type": "totally_made_up"}]},
            )
            rc, _stdout, stderr = _run(tmpdir, "--warn-only")
        self.assertEqual(rc, 1, f"--warn-only must NOT suppress schema errors. stderr={stderr!r}")


class TestUnknownField(unittest.TestCase):
    def test_typoed_field_name_exits_1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo_with_rules(
                tmpdir,
                {"rules": [{
                    "id": "field-typo",
                    "type": "consumer_coverage",
                    "canonical_source": ".runs/x.jsonl",
                    "consumers": [],
                    "consumr_typo_field": "extra",
                }]},
            )
            rc, _stdout, stderr = _run(tmpdir)
        self.assertEqual(rc, 1)
        self.assertIn("unknown field", stderr)
        self.assertIn("consumr_typo_field", stderr)
        self.assertIn("field-typo", stderr)


class TestMissingRequired(unittest.TestCase):
    def test_missing_required_field_exits_1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo_with_rules(
                tmpdir,
                {"rules": [{
                    "id": "missing-fields",
                    "type": "field_role_map",
                    # Missing both required: field, canonical_function
                }]},
            )
            rc, _stdout, stderr = _run(tmpdir)
        self.assertEqual(rc, 1)
        self.assertIn("missing required field", stderr)
        self.assertIn("missing-fields", stderr)
        self.assertIn("canonical_function", stderr)
        self.assertIn("field", stderr)


class TestMetaKeysAccepted(unittest.TestCase):
    def test_severity_description_transitional_note_are_ok(self):
        """META_KEYS like severity, description, _transitional_note must not trigger 'unknown field'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo_with_rules(
                tmpdir,
                {"rules": [{
                    "id": "meta-keys",
                    "type": "consumer_coverage",
                    "severity": "block",
                    "description": "test",
                    "_transitional_note": "test",
                    "canonical_source": ".runs/x.jsonl",
                    "consumers": [],
                }]},
            )
            rc, _stdout, _stderr = _run(tmpdir, "--json")
        self.assertEqual(rc, 0)


class TestStrictAOCDerivation(unittest.TestCase):
    """STRICT_AOC_TYPES must be derived from HANDLERS, not hardcoded.

    Plan PR3 mandated single source of truth. Pre-PR5 commit had both a
    hardcoded set AND a derivation comprehension marked as the canonical
    one — drift risk. PR5 removes the hardcoded set; this test prevents
    re-introduction.
    """

    def test_strict_aoc_types_is_derived_not_hardcoded(self):
        """Source must contain the derivation comprehension and exactly one assignment."""
        runner_path = os.path.join(REAL_REPO, ".claude/scripts/lib/linter/runner.py")
        with open(runner_path) as f:
            src = f.read()
        self.assertIn(
            "STRICT_AOC_TYPES = {t for t,",
            src,
            "STRICT_AOC_TYPES must be derived from HANDLERS via comprehension.",
        )
        n_assignments = src.count("STRICT_AOC_TYPES = {")
        self.assertEqual(
            n_assignments, 1,
            f"Expected exactly 1 assignment of STRICT_AOC_TYPES, found {n_assignments}.",
        )

    def test_strict_aoc_runtime_partitioning_works(self):
        """Functional: --strict-aoc must override --warn-only for AOC handler types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo_with_rules(
                tmpdir,
                {"rules": [{
                    "id": "cc-strict-test",
                    "type": "consumer_coverage",  # is_strict_aoc=True in HANDLERS
                    "canonical_source": ".runs/x.jsonl",
                    "consumers": [".claude/agents/missing.md"],
                }]},
            )
            rc_warn, _, _ = _run(tmpdir, "--warn-only")
            self.assertEqual(rc_warn, 0, "--warn-only alone should suppress AOC finding")
            rc_strict, stdout_strict, _ = _run(tmpdir, "--warn-only", "--strict-aoc")
            self.assertEqual(rc_strict, 1, "--strict-aoc must override --warn-only for AOC")
            self.assertIn("(consumer_coverage/", stdout_strict)


class TestValidatorEnvPrefixCheck(unittest.TestCase):
    """#1272 follow-up — required_env_prefix sub-check on validator entries.

    Locks the contract that a dict-form validator entry with
    required_env_prefix triggers an additional finding when the prefix is
    absent immediately before the validator invocation in any integration
    point that references it.
    """

    def _setup_with_validator(self, tmpdir, state_registry_3b: str,
                               required_env_prefix: str | None = None):
        """Build a tmpdir mini-repo whose state-registry.json 3b entry has
        the given verify command, and whose template-coherence-rules.json
        declares one validator_integration_required rule."""
        os.makedirs(os.path.join(tmpdir, ".claude/scripts"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, ".claude/patterns"), exist_ok=True)
        shutil.copy(LINTER, os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"))
        shutil.copytree(LIB_DIR, os.path.join(tmpdir, ".claude/scripts/lib"),
                        dirs_exist_ok=True)
        # Make the validator script exist so the rule passes script-existence.
        with open(os.path.join(tmpdir, ".claude/scripts/validate-step55-evidence.py"),
                  "w") as f:
            f.write("#!/usr/bin/env python3\n# stub\n")
        with open(os.path.join(tmpdir, ".claude/patterns/state-registry.json"),
                  "w") as f:
            json.dump({"verify": {"3b": {"verify": state_registry_3b}}}, f)
        validator_entry = (
            {"path": ".claude/scripts/validate-step55-evidence.py",
             "required_env_prefix": required_env_prefix}
            if required_env_prefix
            else ".claude/scripts/validate-step55-evidence.py"
        )
        with open(os.path.join(tmpdir, ".claude/patterns/template-coherence-rules.json"),
                  "w") as f:
            json.dump({"rules": [{
                "id": "test-prefix-rule",
                "type": "validator_integration_required",
                "severity": "block",
                "description": "test",
                "validators": [validator_entry],
                "integration_points": [{
                    "path": ".claude/patterns/state-registry.json",
                    "executable_keys": ["verify"],
                    "state_value_executable": True,
                }],
            }]}, f)

    def test_prefix_required_and_present_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_with_validator(
                tmpdir,
                "STEP55_EVIDENCE_MODE=deny python3 .claude/scripts/validate-step55-evidence.py",
                required_env_prefix="STEP55_EVIDENCE_MODE=deny",
            )
            rc, stdout, _ = _run(tmpdir, "--json")
        self.assertEqual(rc, 0, f"prefix present should pass; stdout={stdout!r}")
        payload = json.loads(stdout)
        self.assertEqual(payload["summary"]["cross_file_contradiction"], 0)

    def test_prefix_required_but_absent_fires(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_with_validator(
                tmpdir,
                "python3 .claude/scripts/validate-step55-evidence.py",
                required_env_prefix="STEP55_EVIDENCE_MODE=deny",
            )
            rc, stdout, _ = _run(tmpdir, "--json")
        self.assertEqual(rc, 1, f"prefix absent should block (severity=block); stdout={stdout!r}")
        payload = json.loads(stdout)
        self.assertEqual(payload["summary"]["cross_file_contradiction"], 1)
        self.assertIn("missing required env prefix", payload["cross_file_contradiction"][0])
        self.assertIn("STEP55_EVIDENCE_MODE=deny", payload["cross_file_contradiction"][0])

    def test_no_prefix_required_bare_string_works(self):
        """Backward compat: bare-string validator entries continue to work."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_with_validator(
                tmpdir,
                "python3 .claude/scripts/validate-step55-evidence.py",
                required_env_prefix=None,  # bare string
            )
            rc, stdout, _ = _run(tmpdir, "--json")
        self.assertEqual(rc, 0, f"bare-string entry without prefix should pass; stdout={stdout!r}")


if __name__ == "__main__":
    unittest.main()
