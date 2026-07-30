#!/usr/bin/env python3
"""Parity tests for verify-linter.sh.

Two layers of regression protection for the upcoming verify-linter.sh
refactor (heredoc -> .claude/scripts/lib/linter/ Python package):

1. **TestRealRepoBaseline** — runs verify-linter.sh against the actual
   repo and asserts the JSON output equals the frozen baselines in
   fixtures/linter_baseline/. Catches breakage of the whole-repo path.

2. **TestSyntheticFixtures** — for each fixture under
   fixtures/linter_synthetic/<name>/, builds a mini-repo by copying
   verify-linter.sh + lib/, layering the fixture's `files/` tree, then
   running verify-linter.sh and asserting stdout equals
   `expected_default.txt` (or `expected_strict.txt` when present).
   Catches per-handler breakage with known-bad inputs.

3. **test_aoc_tag_invariant** — for any finding whose rule_type belongs
   to STRICT_AOC_TYPES, the rendered string MUST contain the
   `(rule_type/severity)` tag. Locks the AOC partitioning contract that
   `_is_aoc_finding` substring-matching depends on (verify-linter.sh
   L1532-1535).

Run: python3 .claude/scripts/tests/test_linter_parity.py
Or:  bash .claude/scripts/tests/run-all.sh
"""
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
BASELINE_DIR = os.path.join(
    REAL_REPO, ".claude", "scripts", "tests", "fixtures", "linter_baseline"
)
SYNTHETIC_DIR = os.path.join(
    REAL_REPO, ".claude", "scripts", "tests", "fixtures", "linter_synthetic"
)

STRICT_AOC_TYPES = {
    "verdict_vocab_consistency",
    "ledger_ownership",
    "consumer_coverage",
    "frontmatter_artifact_consistency",
    "hook_bypass_manifest_completeness",
    "hook_silent_skip_friction_pairing",
}


def _run_real_repo(*flags) -> tuple[int, str]:
    """Run linter against the real repo (no tmpdir copy)."""
    result = subprocess.run(
        ["bash", LINTER, *flags],
        capture_output=True,
        text=True,
        cwd=REAL_REPO,
    )
    return result.returncode, result.stdout


def _install_linter(tmpdir: str) -> None:
    """Copy verify-linter.sh + lib/ into tmpdir under .claude/scripts/."""
    os.makedirs(os.path.join(tmpdir, ".claude/scripts"), exist_ok=True)
    shutil.copy(LINTER, os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"))
    if os.path.isdir(LIB_DIR):
        shutil.copytree(
            LIB_DIR,
            os.path.join(tmpdir, ".claude/scripts/lib"),
            dirs_exist_ok=True,
        )


def _setup_fixture_repo(tmpdir: str, fixture_dir: str) -> None:
    """Build a mini-repo at tmpdir from a fixture directory.

    Layout requirement:
      <fixture_dir>/rules.json     — written to .claude/patterns/template-coherence-rules.json
      <fixture_dir>/files/         — overlay merged into tmpdir (optional)
      <fixture_dir>/registry.json  — written to .claude/patterns/state-registry.json (optional; defaults to {})
    """
    _install_linter(tmpdir)
    os.makedirs(os.path.join(tmpdir, ".claude/patterns"), exist_ok=True)

    rules_path = os.path.join(fixture_dir, "rules.json")
    with open(rules_path) as f:
        rules = json.load(f)
    with open(
        os.path.join(tmpdir, ".claude/patterns/template-coherence-rules.json"), "w"
    ) as f:
        json.dump(rules, f)

    registry_path = os.path.join(fixture_dir, "registry.json")
    if os.path.exists(registry_path):
        shutil.copy(
            registry_path,
            os.path.join(tmpdir, ".claude/patterns/state-registry.json"),
        )
    else:
        with open(
            os.path.join(tmpdir, ".claude/patterns/state-registry.json"), "w"
        ) as f:
            json.dump({}, f)

    files_dir = os.path.join(fixture_dir, "files")
    if os.path.isdir(files_dir):
        for root, _dirs, names in os.walk(files_dir):
            rel = os.path.relpath(root, files_dir)
            dest_root = tmpdir if rel == "." else os.path.join(tmpdir, rel)
            os.makedirs(dest_root, exist_ok=True)
            for name in names:
                shutil.copy(os.path.join(root, name), os.path.join(dest_root, name))


def _run_in_tmpdir(tmpdir: str, *flags) -> tuple[int, str]:
    result = subprocess.run(
        ["bash", os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"), *flags],
        capture_output=True,
        text=True,
        cwd=tmpdir,
    )
    return result.returncode, result.stdout


def _normalize_json_payload(text: str) -> dict:
    """Parse JSON output and sort each list for set-equivalence comparison."""
    data = json.loads(text)
    for key in ("uncovered", "diverged", "unjustified_true", "drift_declared", "cross_file_contradiction"):
        if isinstance(data.get(key), list):
            data[key] = sorted(data[key])
    return data


class TestRealRepoBaseline(unittest.TestCase):
    """Lock the all-zero whole-repo summary as a sanity check."""

    def _assert_matches_baseline(self, mode: str, *flags) -> None:
        rc, stdout = _run_real_repo("--json", *flags)
        self.assertIn(rc, (0, 1), f"{mode}: unexpected exit {rc}; stdout={stdout!r}")
        baseline_path = os.path.join(BASELINE_DIR, f"baseline_{mode}.json")
        with open(baseline_path) as f:
            baseline = _normalize_json_payload(f.read())
        actual = _normalize_json_payload(stdout)
        self.assertEqual(actual, baseline, f"{mode}: drifted from baseline")

    def test_default_baseline(self):
        self._assert_matches_baseline("default")

    def test_strict_aoc_baseline(self):
        self._assert_matches_baseline("strict", "--strict-aoc")

    def test_warn_only_baseline(self):
        self._assert_matches_baseline("warn", "--warn-only")


class TestSyntheticFixtures(unittest.TestCase):
    """Run each linter_synthetic/<name>/ fixture and check stdout shape."""

    def _run_fixture(self, name: str, *flags) -> tuple[int, str]:
        fixture_dir = os.path.join(SYNTHETIC_DIR, name)
        self.assertTrue(os.path.isdir(fixture_dir), f"missing fixture dir: {fixture_dir}")
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_fixture_repo(tmpdir, fixture_dir)
            return _run_in_tmpdir(tmpdir, *flags)

    def test_field_role_map_violation_emits_finding(self):
        """A consumer referencing the field WITHOUT canonical_function should be flagged."""
        rc, stdout = self._run_fixture("field_role_map_violation")
        self.assertIn("CROSS_FILE_CONTRADICTION", stdout)
        self.assertIn("fixture-fr-violation", stdout)

    def test_consumer_coverage_miss_emits_finding(self):
        """A consumer referencing only the legacy source must be flagged by consumer_coverage."""
        rc, stdout = self._run_fixture("consumer_coverage_miss")
        self.assertIn("CROSS_FILE_CONTRADICTION", stdout)
        self.assertIn("fixture-cc-miss", stdout)

    def test_discover_consumers_drift_emits_warn(self):
        """File matching consumption_patterns but absent from authoritative consumers
        list should produce a discover_consumers WARN finding (closes zero-coverage gap)."""
        rc, stdout = self._run_fixture("discover_consumers_drift")
        self.assertIn("CROSS_FILE_CONTRADICTION", stdout)
        self.assertIn("fixture-dc-drift", stdout)
        self.assertIn("undeclared-consumer.md", stdout)
        # Declared consumer must NOT be flagged — it's already in the authoritative list.
        flagged_lines = [l for l in stdout.splitlines() if "undeclared" not in l and ".md" in l]
        self.assertNotIn("declared-consumer.md", "\n".join(flagged_lines))

    def test_clean_no_findings_emits_zero(self):
        """Empty rules list should leave cross_file empty."""
        rc, stdout = self._run_fixture("clean_no_findings", "--json")
        payload = json.loads(stdout)
        self.assertEqual(payload["summary"]["cross_file_contradiction"], 0)

    # --- #1339: state_defer_verify_pairing -----------------------------

    def test_state_defer_verify_pairing_violation_emits_finding(self):
        """A state with defer_verify_when_writer in registry whose state
        file ACTIONS lacks the matching write-gate-artifact.sh invocation
        should be flagged. Without the invocation, the chain-aware gate
        skip would never have a sibling writer to defer to."""
        rc, stdout = self._run_fixture("state_defer_verify_pairing_violation")
        self.assertIn("CROSS_FILE_CONTRADICTION", stdout)
        self.assertIn("fixture-sdv-violation", stdout)
        # The handler must reference both the skill.state coordinate and
        # the missing invocation requirement.
        self.assertIn("test.5", stdout)

    def test_state_defer_verify_pairing_clean_no_findings(self):
        """A state with defer_verify_when_writer AND a matching
        write-gate-artifact.sh --path invocation in ACTIONS should NOT
        be flagged."""
        rc, stdout = self._run_fixture(
            "state_defer_verify_pairing_clean", "--json"
        )
        payload = json.loads(stdout)
        self.assertEqual(payload["summary"]["cross_file_contradiction"], 0)

    # --- #1328: branch_checkout_propagation_pairing --------------------

    def test_branch_checkout_propagation_violation_emits_finding(self):
        """A markdown fenced bash block with `git checkout -b` but no
        sibling `update-context-branch.sh` should be flagged. This is
        the recurrence vector #1328 closes."""
        rc, stdout = self._run_fixture("branch_checkout_propagation_violation")
        self.assertIn("CROSS_FILE_CONTRADICTION", stdout)
        self.assertIn("fixture-bcp-violation", stdout)
        self.assertIn("git checkout -b", stdout)

    def test_branch_checkout_propagation_clean_no_findings(self):
        """A bundled chain (`echo > sentinel && OLD=$(...) && git
        checkout -b X && bash update-context-branch.sh "$OLD"`) should
        NOT be flagged — pairing is structurally satisfied."""
        rc, stdout = self._run_fixture(
            "branch_checkout_propagation_clean", "--json"
        )
        payload = json.loads(stdout)
        self.assertEqual(payload["summary"]["cross_file_contradiction"], 0)

    # --- #1349 + #1350: hook_bypass_manifest_completeness ---------------

    def test_hook_bypass_manifest_completeness_violation_emits_finding(self):
        """An exemption entry missing the required `category` field should
        be flagged. The manifest entries[i] coordinate appears in the
        finding. Closes #1349 silent-fail-open class for canonical-writer
        exemptions."""
        rc, stdout = self._run_fixture("hook_bypass_manifest_completeness_violation")
        self.assertIn("CROSS_FILE_CONTRADICTION", stdout)
        self.assertIn("fixture-hbmc-violation", stdout)
        self.assertIn("category", stdout)

    def test_hook_bypass_manifest_completeness_clean_no_findings(self):
        """An exemption entry with all required fields populated AND
        category in valid_categories should NOT be flagged."""
        rc, stdout = self._run_fixture(
            "hook_bypass_manifest_completeness_clean", "--json"
        )
        payload = json.loads(stdout)
        self.assertEqual(payload["summary"]["cross_file_contradiction"], 0)

    # --- #1349 + #1350: hook_silent_skip_friction_pairing ---------------

    def test_hook_silent_skip_friction_pairing_violation_emits_finding(self):
        """A bare `exit 0` with no preceding friction call within the
        lookback window AND no `# friction-skip:` pragma on this or the
        directly preceding line should be flagged. Closes the silent-bypass
        class introduced by #1349/#1350 (defensive exit 0 without audit).

        Regression: also asserts `[[ X ]] && exit 0` and `[[ X ]] || exit 0`
        chain forms are flagged. The original regex required \\b before
        &&/|| which silently failed when the preceding char was non-word
        (e.g., `]` or space) — see #1349/#1350 follow-up.
        """
        rc, stdout = self._run_fixture("hook_silent_skip_friction_pairing_violation")
        self.assertIn("CROSS_FILE_CONTRADICTION", stdout)
        self.assertIn("fixture-hssfp-violation", stdout)
        self.assertIn("synthetic-hook.sh", stdout)
        self.assertIn("unfrictioned silent skip", stdout)
        # Regex regression: && and || chain forms must each be flagged.
        self.assertIn("&& exit 0", stdout)
        self.assertIn("|| exit 0", stdout)

    def test_hook_silent_skip_friction_pairing_clean_no_findings(self):
        """`exit 0` paired with EITHER (a) `_write_hook_friction` within
        the lookback window OR (b) `# friction-skip:` pragma on the same
        or directly preceding line should NOT be flagged."""
        rc, stdout = self._run_fixture(
            "hook_silent_skip_friction_pairing_clean", "--json"
        )
        payload = json.loads(stdout)
        self.assertEqual(payload["summary"]["cross_file_contradiction"], 0)


class TestAOCTagInvariant(unittest.TestCase):
    """Strict-AOC handlers must produce findings with the (rule_type/severity) tag.

    This locks the contract that _is_aoc_finding (verify-linter.sh L1532-1535)
    relies on for exit-code partitioning under --strict-aoc.
    """

    def test_strict_aoc_handler_findings_carry_tag(self):
        """consumer_coverage is one of STRICT_AOC_TYPES; its fixture must produce a tagged finding."""
        fixture_dir = os.path.join(SYNTHETIC_DIR, "consumer_coverage_miss")
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_fixture_repo(tmpdir, fixture_dir)
            rc, stdout = _run_in_tmpdir(tmpdir)
        # The finding line for consumer_coverage MUST contain "(consumer_coverage/"
        self.assertIn(
            "(consumer_coverage/",
            stdout,
            f"consumer_coverage finding missing AOC tag — _is_aoc_finding partitioning would break.\nstdout:\n{stdout}",
        )


if __name__ == "__main__":
    unittest.main()
