#!/usr/bin/env python3
"""Behavioral tests for AOC v1 coherence rules R1/R2/R3.

Validates that verify-linter.sh dispatches correctly to the three new rule
types introduced by agent-output-contract.md:

- R1 verdict_vocab_consistency — catches agent files that emit verdicts
  outside the registry's allowed_verdicts for that agent, and
  evaluate-hard-gate-predicates.py predicates that reference non-registry
  verdict literals.
- R2 ledger_ownership — catches writes to gated paths (.runs/fix-ledger.jsonl,
  .runs/fix-log.md) from files outside the allowed_writers list.
- R3 consumer_coverage — catches consumer files that do not reference the
  canonical source (.runs/fix-ledger.jsonl).

Also verifies the --strict-aoc CLI flag makes these rules blocking even
when --warn-only is set.

Run via: python3 .claude/scripts/tests/test_aoc_coherence_rules.py
Or via:  bash .claude/scripts/tests/run-all.sh
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


REAL_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LINTER = os.path.join(REAL_REPO, ".claude", "scripts", "verify-linter.sh")
LIB_DIR = os.path.join(REAL_REPO, ".claude", "scripts", "lib")


def _setup_repo(tmpdir, rules, files):
    """Create a minimal repo skeleton scanned by verify-linter.sh.

    rules: dict written as template-coherence-rules.json
    files: {relpath: content} to write before the linter runs
    """
    os.makedirs(os.path.join(tmpdir, ".claude/scripts"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, ".claude/patterns"), exist_ok=True)
    shutil.copy(LINTER, os.path.join(tmpdir, ".claude/scripts/verify-linter.sh"))
    # Copy lib/ alongside the linter so the upcoming Python-package refactor
    # (which puts business logic under .claude/scripts/lib/linter/) doesn't
    # break this fixture. Idempotent today: linter is still self-contained.
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

MINIMAL_REGISTRY = {
    "verdict_agents_schema": {
        "demo-agent": {
            "allowed_verdicts": ["pass", "fail"],
            "allowed_results": ["clean", "fixed"],
        }
    }
}


MINIMAL_PREDICATES = """\
#!/usr/bin/env python3
# Stub predicate file — refs only registry verdicts.
# t.get('verdict') == 'pass'
# t.get('verdict') in ('pass', 'fail')
"""


# --- R1 verdict_vocab_consistency ------------------------------------------


class TestR1VerdictVocab(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _base_rule(self):
        return {
            "rules": [{
                "id": "aoc-verdict-vocab-consistency",
                "type": "verdict_vocab_consistency",
                "severity": "block",
                "registry_path": ".claude/patterns/agent-registry.json",
                "agent_files_glob": ".claude/agents/*.md",
                "predicate_file": ".claude/scripts/evaluate-hard-gate-predicates.py",
            }]
        }

    def test_compliant_agent_passes(self):
        """Agent emitting registry-declared verdict has no findings."""
        files = {
            ".claude/patterns/agent-registry.json": json.dumps(MINIMAL_REGISTRY),
            ".claude/scripts/evaluate-hard-gate-predicates.py": MINIMAL_PREDICATES,
            ".claude/agents/demo-agent.md": (
                "# Demo Agent\n\n"
                '`"verdict": "pass"` is valid.\n'
                '`"verdict": "fail"` also valid.\n'
            ),
        }
        _setup_repo(self.tmpdir, self._base_rule(), files)
        rc, out, _ = _run_linter(self.tmpdir, "--strict-aoc")
        self.assertEqual(rc, 0, f"expected clean, got:\n{out}")

    def test_pre_aoc_legacy_verdict_is_blocked(self):
        """Agent emitting pre-AOC legacy verdict (e.g. 'all fixed') triggers R1."""
        files = {
            ".claude/patterns/agent-registry.json": json.dumps(MINIMAL_REGISTRY),
            ".claude/scripts/evaluate-hard-gate-predicates.py": MINIMAL_PREDICATES,
            ".claude/agents/demo-agent.md": (
                "# Demo Agent\n\n"
                '`"verdict": "all fixed"` is the legacy drift we want to catch.\n'
            ),
        }
        _setup_repo(self.tmpdir, self._base_rule(), files)
        rc, out, _ = _run_linter(self.tmpdir, "--strict-aoc")
        self.assertEqual(rc, 1, f"expected blocking, got clean:\n{out}")
        self.assertIn("aoc-verdict-vocab-consistency", out)
        self.assertIn("all fixed", out)

    def test_predicate_references_non_registry_verdict_is_blocked(self):
        """evaluate-hard-gate-predicates.py referencing a verdict literal not in registry triggers R1."""
        files = {
            ".claude/patterns/agent-registry.json": json.dumps(MINIMAL_REGISTRY),
            ".claude/scripts/evaluate-hard-gate-predicates.py": (
                '#!/usr/bin/env python3\n'
                "# Stub\n"
                "# t.get('verdict') == 'weirdo'\n"
            ),
            ".claude/agents/demo-agent.md": '# Demo\n',
        }
        _setup_repo(self.tmpdir, self._base_rule(), files)
        rc, out, _ = _run_linter(self.tmpdir, "--strict-aoc")
        self.assertEqual(rc, 1, f"expected blocking, got:\n{out}")
        self.assertIn("weirdo", out)


# --- R2 ledger_ownership ---------------------------------------------------


class TestR2LedgerOwnership(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _base_rule(self):
        return {
            "rules": [{
                "id": "aoc-fix-ledger-ownership",
                "type": "ledger_ownership",
                "severity": "block",
                "allowed_writers": [
                    ".claude/scripts/write-fix-ledger.py",
                    ".claude/scripts/render-fix-log.py",
                ],
                "gated_paths": [
                    ".runs/fix-ledger.jsonl",
                    ".runs/fix-log.md",
                ],
            }]
        }

    def test_no_writes_passes(self):
        """Template files that only READ gated paths (cat/json.load) pass."""
        files = {
            ".claude/agents/reader.md": (
                "# Reader\n\n"
                "Run `wc -l .runs/fix-ledger.jsonl` to count fixes.\n"
                "Read `.runs/fix-log.md` for human-readable summary.\n"
            ),
            ".claude/scripts/write-fix-ledger.py": "#!/usr/bin/env python3\nopen('.runs/fix-ledger.jsonl', 'w')\n",
            ".claude/scripts/render-fix-log.py": "#!/usr/bin/env python3\nopen('.runs/fix-log.md', 'w')\n",
        }
        _setup_repo(self.tmpdir, self._base_rule(), files)
        rc, out, _ = _run_linter(self.tmpdir, "--strict-aoc")
        self.assertEqual(rc, 0, f"expected clean, got:\n{out}")

    def test_unauthorized_shell_write_is_blocked(self):
        """Unauthorized `echo >> .runs/fix-log.md` triggers R2."""
        files = {
            ".claude/agents/bad-writer.md": (
                "# Bad\n\n"
                "```bash\n"
                "echo 'Fix (bad): test.ts — manual' >> .runs/fix-log.md\n"
                "```\n"
            ),
            ".claude/scripts/write-fix-ledger.py": "#!/usr/bin/env python3\n",
            ".claude/scripts/render-fix-log.py": "#!/usr/bin/env python3\n",
        }
        _setup_repo(self.tmpdir, self._base_rule(), files)
        rc, out, _ = _run_linter(self.tmpdir, "--strict-aoc")
        self.assertEqual(rc, 1, f"expected blocking, got:\n{out}")
        self.assertIn("aoc-fix-ledger-ownership", out)
        self.assertIn("bad-writer.md", out)

    def test_unauthorized_python_write_is_blocked(self):
        """Unauthorized `open('.runs/fix-ledger.jsonl', 'a')` triggers R2."""
        files = {
            ".claude/scripts/bad-writer.py": (
                "open('.runs/fix-ledger.jsonl', 'a').write('spoof\\n')\n"
            ),
            ".claude/scripts/write-fix-ledger.py": "#!/usr/bin/env python3\n",
            ".claude/scripts/render-fix-log.py": "#!/usr/bin/env python3\n",
        }
        _setup_repo(self.tmpdir, self._base_rule(), files)
        rc, out, _ = _run_linter(self.tmpdir, "--strict-aoc")
        self.assertEqual(rc, 1, f"expected blocking, got:\n{out}")
        self.assertIn("bad-writer.py", out)


# --- R3 consumer_coverage --------------------------------------------------


class TestR3ConsumerCoverage(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _base_rule(self):
        return {
            "rules": [{
                "id": "aoc-consumer-coverage",
                "type": "consumer_coverage",
                "severity": "block",
                "canonical_source": ".runs/fix-ledger.jsonl",
                "consumers": [".claude/hooks/demo-consumer.sh"],
            }]
        }

    def test_consumer_referencing_ledger_passes(self):
        files = {
            ".claude/hooks/demo-consumer.sh": (
                "#!/usr/bin/env bash\n"
                "wc -l .runs/fix-ledger.jsonl\n"
            )
        }
        _setup_repo(self.tmpdir, self._base_rule(), files)
        rc, out, _ = _run_linter(self.tmpdir, "--strict-aoc")
        self.assertEqual(rc, 0, f"expected clean, got:\n{out}")

    def test_consumer_missing_ledger_reference_is_blocked(self):
        files = {
            ".claude/hooks/demo-consumer.sh": (
                "#!/usr/bin/env bash\n"
                "# Reads only the prose fix-log.md; ledger reference absent.\n"
                "cat .runs/fix-log.md | wc -l\n"
            )
        }
        _setup_repo(self.tmpdir, self._base_rule(), files)
        rc, out, _ = _run_linter(self.tmpdir, "--strict-aoc")
        self.assertEqual(rc, 1, f"expected blocking, got:\n{out}")
        self.assertIn("aoc-consumer-coverage", out)


# --- Flag matrix: --strict-aoc x --warn-only ------------------------------


class TestStrictAocFlagMatrix(unittest.TestCase):
    """--strict-aoc must override --warn-only for AOC rule-type findings."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _setup_with_violation(self):
        rules = {"rules": [{
            "id": "aoc-fix-ledger-ownership",
            "type": "ledger_ownership",
            "severity": "block",
            "allowed_writers": [".claude/scripts/write-fix-ledger.py"],
            "gated_paths": [".runs/fix-ledger.jsonl"],
        }]}
        files = {
            ".claude/scripts/write-fix-ledger.py": "#!/usr/bin/env python3\n",
            ".claude/agents/bad.md": "```bash\necho x >> .runs/fix-ledger.jsonl\n```\n",
        }
        _setup_repo(self.tmpdir, rules, files)

    def test_no_flags_blocks(self):
        self._setup_with_violation()
        rc, _, _ = _run_linter(self.tmpdir)
        self.assertEqual(rc, 1)

    def test_warn_only_alone_does_not_block(self):
        self._setup_with_violation()
        rc, _, _ = _run_linter(self.tmpdir, "--warn-only")
        self.assertEqual(rc, 0)

    def test_warn_only_plus_strict_aoc_blocks(self):
        """--strict-aoc overrides --warn-only for R2."""
        self._setup_with_violation()
        rc, out, _ = _run_linter(self.tmpdir, "--warn-only", "--strict-aoc")
        self.assertEqual(rc, 1, f"expected blocking, got:\n{out}")

    def test_strict_aoc_alone_blocks(self):
        self._setup_with_violation()
        rc, _, _ = _run_linter(self.tmpdir, "--strict-aoc")
        self.assertEqual(rc, 1)


# --- write-fix-ledger.py dedup (Gap 1 fix) --------------------------------


class TestWriteFixLedgerDedup(unittest.TestCase):
    """Verifies the AOC v1 FLS v1 consolidator does NOT double-count lead-merge
    aggregate fixes. design-critic writes per-page sub-traces (design-critic-
    landing.json, design-critic-pricing.json) whose fixes are concatenated
    into the merged design-critic.json by merge-design-critic-traces.py.
    Without dedup, the ledger would have 2 rows per fix."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.traces = os.path.join(self.tmpdir, ".runs", "agent-traces")
        os.makedirs(self.traces, exist_ok=True)
        # Mirror the registry (only lead_merge_aggregate_agents is read).
        os.makedirs(os.path.join(self.tmpdir, ".claude", "patterns"), exist_ok=True)
        with open(os.path.join(self.tmpdir, ".claude/patterns/agent-registry.json"), "w") as f:
            json.dump({
                "lead_merge_aggregate_agents": [
                    "design-critic", "scaffold-pages", "scaffold-images",
                    "implementer", "visual-implementer"
                ]
            }, f)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_trace(self, name, fixes):
        path = os.path.join(self.traces, f"{name}.json")
        trace = {
            "agent": name.split("-")[0] + "-" + name.split("-")[1] if "-" in name else name,
            "run_id": "t1",
            "timestamp": "2026-04-23T12:00:00Z",
            "fixes": fixes,
        }
        # Override: for design-critic and sub-traces, the trace's `agent` field
        # is always the base name (not per-page).
        trace["agent"] = "design-critic"
        with open(path, "w") as f:
            json.dump(trace, f)

    def _run_consolidator(self):
        result = subprocess.run(
            ["python3", os.path.join(REAL_REPO, ".claude/scripts/write-fix-ledger.py"),
             "--run-id", "t1"],
            capture_output=True, text=True, cwd=self.tmpdir
        )
        return result.returncode, result.stdout, result.stderr

    def _ledger_rows(self):
        ledger = os.path.join(self.tmpdir, ".runs/fix-ledger.jsonl")
        if not os.path.isfile(ledger):
            return []
        return [json.loads(l) for l in open(ledger) if l.strip()]

    def test_submerged_traces_skipped_when_aggregate_present(self):
        """5 per-page fixes + aggregate of 5 → 5 ledger rows (not 10)."""
        self._write_trace("design-critic-landing", [
            {"file": "hero.tsx", "symptom": "low contrast", "fix": "bg-slate-900"},
            {"file": "cta.tsx", "symptom": "weak CTA", "fix": "larger button"},
        ])
        self._write_trace("design-critic-pricing", [
            {"file": "tier.tsx", "symptom": "cramped", "fix": "added padding"},
            {"file": "table.tsx", "symptom": "alignment", "fix": "right-aligned prices"},
            {"file": "faq.tsx", "symptom": "spacing", "fix": "increased margin"},
        ])
        # Merged aggregate concatenates all 5 fixes.
        self._write_trace("design-critic", [
            {"file": "hero.tsx", "symptom": "low contrast", "fix": "bg-slate-900"},
            {"file": "cta.tsx", "symptom": "weak CTA", "fix": "larger button"},
            {"file": "tier.tsx", "symptom": "cramped", "fix": "added padding"},
            {"file": "table.tsx", "symptom": "alignment", "fix": "right-aligned prices"},
            {"file": "faq.tsx", "symptom": "spacing", "fix": "increased margin"},
        ])
        rc, out, err = self._run_consolidator()
        self.assertEqual(rc, 0, f"consolidator failed: {err}")
        rows = self._ledger_rows()
        self.assertEqual(len(rows), 5, f"expected 5 (aggregate only), got {len(rows)}: "
                         f"ledger double-counted sub-trace fixes")
        # Every row should have batch_id == "design-critic" (the aggregate).
        for r in rows:
            self.assertEqual(r["batch_id"], "design-critic",
                             f"row should originate from aggregate: {r}")

    def test_sub_traces_emit_rows_when_aggregate_absent(self):
        """If only sub-traces exist (no merge yet), sub-trace rows are included.
        This prevents a failed merge step from silently dropping all fixes."""
        self._write_trace("design-critic-landing", [
            {"file": "hero.tsx", "symptom": "low contrast", "fix": "bg-slate-900"},
        ])
        # No merged design-critic.json.
        rc, out, err = self._run_consolidator()
        self.assertEqual(rc, 0, f"consolidator failed: {err}")
        rows = self._ledger_rows()
        self.assertEqual(len(rows), 1, f"expected 1 row, got {len(rows)}")
        self.assertEqual(rows[0]["batch_id"], "design-critic-landing")

    def test_non_aggregate_agent_unaffected_by_dedup(self):
        """security-fixer is not a lead_merge_aggregate_agent; its fixes
        always go into the ledger directly."""
        path = os.path.join(self.traces, "security-fixer.json")
        with open(path, "w") as f:
            json.dump({
                "agent": "security-fixer", "run_id": "t1",
                "timestamp": "2026-04-23T12:00:00Z",
                "fixes": [
                    {"file": "a.ts", "symptom": "missing auth", "fix": "added middleware"},
                    {"file": "b.ts", "symptom": "leak", "fix": "redacted"},
                ],
            }, f)
        rc, out, err = self._run_consolidator()
        self.assertEqual(rc, 0)
        rows = self._ledger_rows()
        self.assertEqual(len(rows), 2)


# --- E1.1-E1.6: Stage B validator_integration_required -----------------------


class TestStageBValidatorIntegrationRequired(unittest.TestCase):
    """#1295 PR1 Stage B: per-validator executable-context enforcement."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _stage_b_rule(self, ip):
        return {
            "rules": [{
                "id": "test-stage-b",
                "type": "validator_integration_required",
                "severity": "block",
                "description": "test",
                "validators": [".claude/scripts/validate-testval.py"],
                "integration_points": [ip],
            }]
        }

    # E1.1: happy — validator referenced via `verify` key in JSON
    def test_e1_1_referenced_via_verify_key_passes(self):
        registry = {"state1": {"verify": "python3 validate-testval.py"}}
        files = {
            ".claude/scripts/validate-testval.py": "#!/usr/bin/env python3\n",
            ".claude/patterns/fake-registry.json": json.dumps(registry),
        }
        ip = {
            "path": ".claude/patterns/fake-registry.json",
            "executable_keys": ["verify"],
            "state_value_executable": False,
        }
        _setup_repo(self.tmpdir, self._stage_b_rule(ip), files)
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertEqual(rc, 0, f"E1.1 expected pass, got:\n{out}")

    # E1.2: happy — validator referenced via bare-string state value (state-name regex)
    def test_e1_2_referenced_via_state_name_regex_passes(self):
        registry = {"11b": "python3 validate-testval.py"}
        files = {
            ".claude/scripts/validate-testval.py": "#!/usr/bin/env python3\n",
            ".claude/patterns/fake-registry.json": json.dumps(registry),
        }
        ip = {
            "path": ".claude/patterns/fake-registry.json",
            "executable_keys": [],
            "state_value_executable": True,
        }
        _setup_repo(self.tmpdir, self._stage_b_rule(ip), files)
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertEqual(rc, 0, f"E1.2 expected pass, got:\n{out}")

    # E1.3: NEGATIVE — validator referenced ONLY in `description` field (HC-PR1-1)
    def test_e1_3_description_field_not_executable_fails(self):
        registry = {"state1": {"description": "uses validate-testval.py to check things"}}
        files = {
            ".claude/scripts/validate-testval.py": "#!/usr/bin/env python3\n",
            ".claude/patterns/fake-registry.json": json.dumps(registry),
        }
        ip = {
            "path": ".claude/patterns/fake-registry.json",
            "executable_keys": ["verify"],
            "state_value_executable": True,
        }
        _setup_repo(self.tmpdir, self._stage_b_rule(ip), files)
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertEqual(rc, 1, f"E1.3 expected failure (description not executable), got clean:\n{out}")
        self.assertIn("test-stage-b", out)

    # E1.4: NEGATIVE — validator referenced only in .sh comment line
    def test_e1_4_sh_comment_not_executable_fails(self):
        sh_content = "#!/usr/bin/env bash\n# validate-testval.py is mentioned here\necho done\n"
        files = {
            ".claude/scripts/validate-testval.py": "#!/usr/bin/env python3\n",
            ".claude/scripts/fake-hook.sh": sh_content,
        }
        _setup_repo(self.tmpdir, self._stage_b_rule(".claude/scripts/fake-hook.sh"), files)
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertEqual(rc, 1, f"E1.4 expected failure (.sh comment not executable), got clean:\n{out}")
        self.assertIn("test-stage-b", out)

    # E1.5: NEGATIVE — validator referenced only in .md prose (outside code fence)
    def test_e1_5_md_prose_not_executable_fails(self):
        md_content = "## Section\n\nvalidate-testval.py is mentioned here but outside code block.\n"
        files = {
            ".claude/scripts/validate-testval.py": "#!/usr/bin/env python3\n",
            ".claude/patterns/fake-doc.md": md_content,
        }
        _setup_repo(self.tmpdir, self._stage_b_rule(".claude/patterns/fake-doc.md"), files)
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertEqual(rc, 1, f"E1.5 expected failure (.md prose not executable), got clean:\n{out}")
        self.assertIn("test-stage-b", out)

    # E1.6: NEGATIVE — validator referenced only inside calls[].path (parent_key resets to `path`)
    def test_e1_6_calls_path_not_executable_fails(self):
        registry = {"state1": {"calls": [{"path": "validate-testval.py", "artifact": "foo.json"}]}}
        files = {
            ".claude/scripts/validate-testval.py": "#!/usr/bin/env python3\n",
            ".claude/patterns/fake-registry.json": json.dumps(registry),
        }
        ip = {
            "path": ".claude/patterns/fake-registry.json",
            "executable_keys": ["verify"],
            "state_value_executable": True,
        }
        _setup_repo(self.tmpdir, self._stage_b_rule(ip), files)
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertEqual(rc, 1, f"E1.6 expected failure (calls[].path not executable), got clean:\n{out}")
        self.assertIn("test-stage-b", out)


# --- E1.7-E1.12: Stage C validator_inventory_completeness --------------------


class TestStageCValidatorInventoryCompleteness(unittest.TestCase):
    """#1295 PR1 Stage C: meta-rule for validator inventory drift."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _stage_b_rule(self, validators_b):
        return {
            "id": "test-stage-b",
            "type": "validator_integration_required",
            "severity": "block",
            "description": "test",
            "validators": validators_b,
            "integration_points": [".claude/scripts/fake-lifecycle.sh"],
        }

    def _stage_c_rule(self, skip=None):
        rule = {
            "id": "test-stage-c",
            "type": "validator_inventory_completeness",
            "severity": "block",
            "description": "test",
            "discovery_glob": [".claude/scripts/validate-*.py"],
        }
        if skip is not None:
            rule["skip_validators"] = skip
        return rule

    def _setup(self, validators_b, validators_on_disk, skip=None):
        """Write Stage B + Stage C rules and files.

        validators_b: list of relative paths for Stage B validators[]
        validators_on_disk: {relpath: content} for each on-disk validator
        Stage B integration_point is fake-lifecycle.sh with non-comment refs.
        """
        sh_lines = ["#!/usr/bin/env bash"]
        for v in validators_b:
            sh_lines.append(f"python3 {os.path.basename(v)}")
        files = {".claude/scripts/fake-lifecycle.sh": "\n".join(sh_lines) + "\n"}
        files.update(validators_on_disk)
        rules = {"rules": [self._stage_b_rule(validators_b), self._stage_c_rule(skip)]}
        _setup_repo(self.tmpdir, rules, files)

    # E1.7: happy — all on-disk validators covered by Stage B validators[]
    def test_e1_7_all_covered_passes(self):
        v = ".claude/scripts/validate-main.py"
        self._setup(
            validators_b=[v],
            validators_on_disk={v: "#!/usr/bin/env python3\n"},
        )
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertEqual(rc, 0, f"E1.7 expected pass, got:\n{out}")

    # E1.8: NEGATIVE — skip_validators with bad category
    def test_e1_8_bad_skip_category_fails(self):
        v_main = ".claude/scripts/validate-main.py"
        v_other = ".claude/scripts/validate-other.py"
        self._setup(
            validators_b=[v_main],
            validators_on_disk={
                v_main: "#!/usr/bin/env python3\n",
                v_other: "#!/usr/bin/env python3\n",
            },
            skip={v_other: {"category": "bad-category", "justification": "test reason"}},
        )
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertEqual(rc, 1, f"E1.8 expected failure (bad category), got clean:\n{out}")
        self.assertIn("test-stage-c", out)

    # E1.9: NEGATIVE — skip_validators with empty justification
    def test_e1_9_empty_justification_fails(self):
        v_main = ".claude/scripts/validate-main.py"
        v_other = ".claude/scripts/validate-other.py"
        self._setup(
            validators_b=[v_main],
            validators_on_disk={
                v_main: "#!/usr/bin/env python3\n",
                v_other: "#!/usr/bin/env python3\n",
            },
            skip={v_other: {"category": "build-time", "justification": ""}},
        )
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertEqual(rc, 1, f"E1.9 expected failure (empty justification), got clean:\n{out}")
        self.assertIn("test-stage-c", out)

    # E1.10: NEGATIVE — magic-header inside docstring does NOT exempt (tokenize-COMMENT-only)
    def test_e1_10_magic_header_in_docstring_not_exempt_fails(self):
        v_main = ".claude/scripts/validate-main.py"
        v_other = ".claude/scripts/validate-other.py"
        # The magic header appears inside a string literal (docstring), NOT as a COMMENT token.
        # tokenize.tokenize will produce a STRING token for the docstring, not COMMENT.
        docstring_with_magic = (
            '#!/usr/bin/env python3\n'
            '"""\n'
            'Example usage:\n'
            '    # validator-class: cli-tool\n'
            '"""\n'
            'import sys\n'
        )
        self._setup(
            validators_b=[v_main],
            validators_on_disk={
                v_main: "#!/usr/bin/env python3\n",
                v_other: docstring_with_magic,
            },
        )
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertEqual(rc, 1, f"E1.10 expected failure (docstring magic header not exempt), got clean:\n{out}")
        self.assertIn("test-stage-c", out)

    # E1.11: happy — magic-header on line 2 as real COMMENT token exempts the validator
    def test_e1_11_real_comment_magic_header_passes(self):
        v_main = ".claude/scripts/validate-main.py"
        v_other = ".claude/scripts/validate-other.py"
        real_magic = "#!/usr/bin/env python3\n# validator-class: build-time\n\"\"\"description.\"\"\"\n"
        self._setup(
            validators_b=[v_main],
            validators_on_disk={
                v_main: "#!/usr/bin/env python3\n",
                v_other: real_magic,
            },
        )
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertEqual(rc, 0, f"E1.11 expected pass, got:\n{out}")

    # E1.12: happy — skip_validators with valid category + non-empty justification
    def test_e1_12_valid_skip_validators_passes(self):
        v_main = ".claude/scripts/validate-main.py"
        v_other = ".claude/scripts/validate-other.py"
        self._setup(
            validators_b=[v_main],
            validators_on_disk={
                v_main: "#!/usr/bin/env python3\n",
                v_other: "#!/usr/bin/env python3\n",
            },
            skip={v_other: {"category": "build-time", "justification": "Run by /spec; not a lifecycle gate."}},
        )
        rc, out, _ = _run_linter(self.tmpdir)
        self.assertEqual(rc, 0, f"E1.12 expected pass, got:\n{out}")


class TestMustContainSectionSourceCodeLiteral(unittest.TestCase):
    """#1447 Rule A — pin the source-code-literal use of must_contain_section.

    must_contain_section is canonically used for markdown section headings
    (`required_section: "## Production Observability"`). Issue #1447 Rule A
    repurposes it to assert a code literal (`'force-dynamic'`) appears in
    scaffolded page.tsx files. The semantic is mechanically correct (runner.py
    documents required_section as literal substring), but the rule name's
    "section" framing makes the source-code-literal use non-obvious. This test
    class pins the use-case so future rule-engine refactors preserve substring
    matching even outside markdown contexts.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _rule(self):
        return {
            "rules": [{
                "id": "test-seg-auth-force-dynamic",
                "type": "must_contain_section",
                "severity": "block",
                "applies_to_glob": "src/app/**/[[]*[]]/**/page.tsx",
                "required_section": "'force-dynamic'",
                "trigger_pattern_any": [
                    "from\\s+['\"]@/lib/auth['\"]"
                ],
                "description": "test fixture for #1447 Rule A — escaped brackets [[]*[]] match literal [seg] dirs; ** on both sides catches [seg] anywhere in the path"
            }]
        }

    def test_page_with_force_dynamic_passes(self):
        """A [seg] page that imports auth AND declares force-dynamic does not trigger."""
        files = {
            "src/app/items/[id]/page.tsx": (
                "import { requireRole } from '@/lib/auth';\n"
                "export const dynamic = 'force-dynamic';\n"
                "export default function P() { return null; }\n"
            ),
        }
        _setup_repo(self.tmpdir, self._rule(), files)
        rc, out, _ = _run_linter(self.tmpdir, "--strict-aoc")
        self.assertEqual(rc, 0, f"expected clean (force-dynamic present), got:\n{out}")

    def test_page_missing_force_dynamic_is_blocked(self):
        """A [seg] page that imports auth but lacks 'force-dynamic' literal is blocked."""
        files = {
            "src/app/projects/[slug]/page.tsx": (
                "import { requireRole } from '@/lib/auth';\n"
                "export default function P() { return null; }\n"
            ),
        }
        _setup_repo(self.tmpdir, self._rule(), files)
        rc, out, _ = _run_linter(self.tmpdir, "--strict-aoc")
        self.assertEqual(rc, 1, f"expected block (force-dynamic missing), got clean:\n{out}")
        self.assertIn("src/app/projects/[slug]/page.tsx", out)
        self.assertIn("'force-dynamic'", out)

    def test_page_without_auth_import_is_not_triggered(self):
        """A [seg] page without auth imports does not trigger the rule even without force-dynamic."""
        files = {
            "src/app/public/[id]/page.tsx": (
                "export default function P() { return null; }\n"
            ),
        }
        _setup_repo(self.tmpdir, self._rule(), files)
        rc, out, _ = _run_linter(self.tmpdir, "--strict-aoc")
        self.assertEqual(rc, 0, f"expected clean (no auth import → no trigger), got:\n{out}")

    def test_non_dynamic_page_not_in_scope(self):
        """A non-[seg] page (e.g., src/app/items/page.tsx) is outside applies_to_glob."""
        files = {
            "src/app/items/page.tsx": (
                "import { requireRole } from '@/lib/auth';\n"
                "export default function P() { return null; }\n"
            ),
        }
        _setup_repo(self.tmpdir, self._rule(), files)
        rc, out, _ = _run_linter(self.tmpdir, "--strict-aoc")
        self.assertEqual(rc, 0, f"expected clean (non-dynamic page out of scope), got:\n{out}")

    def test_edit_subpage_under_seg_is_in_scope(self):
        """Issue #1447 follow-up: a page UNDER a [seg] directory (e.g.,
        src/app/items/[id]/edit/page.tsx) is in scope. [seg] is the
        grandparent, not the immediate parent. Without ** on both sides
        of [[]*[]] in the glob, this case is silently missed."""
        files = {
            "src/app/items/[id]/edit/page.tsx": (
                "import { requireRole } from '@/lib/auth';\n"
                "export default function P() { return null; }\n"
            ),
        }
        _setup_repo(self.tmpdir, self._rule(), files)
        rc, out, _ = _run_linter(self.tmpdir, "--strict-aoc")
        self.assertEqual(rc, 1, f"expected block (force-dynamic missing on edit subpage), got clean:\n{out}")
        self.assertIn("src/app/items/[id]/edit/page.tsx", out)

    def test_descendant_of_seg_is_in_scope(self):
        """Issue #1447 follow-up: a page whose ancestor is a [seg] but the
        page itself is not directly under the [seg] (e.g.,
        src/app/[orgId]/projects/page.tsx — auth-gated within an org
        context) is in scope."""
        files = {
            "src/app/[orgId]/projects/page.tsx": (
                "import { requireRole } from '@/lib/auth';\n"
                "export default function P() { return null; }\n"
            ),
        }
        _setup_repo(self.tmpdir, self._rule(), files)
        rc, out, _ = _run_linter(self.tmpdir, "--strict-aoc")
        self.assertEqual(rc, 1, f"expected block (descendant of [seg] missing force-dynamic), got clean:\n{out}")
        self.assertIn("src/app/[orgId]/projects/page.tsx", out)


if __name__ == "__main__":
    unittest.main()
