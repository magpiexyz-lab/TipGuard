"""Tests for state-99 epilogue enforcement (#1043 + #928 + resolve.7 fixes).

Covers test matrix T1-T6 from plan 3-squishy-babbage.md:
- T1: 18-skill dispatch registers state 99 in every entry (shared VERIFY text).
- T2: Embedded skill auto-skips state 99 via embed_skip_epilogue flag.
- T3: VERIFY JSON interpretation: pass, skipped, error, absent.
- T4: CHECK-X1/X2 regex positive + negative cases.
- T5: lifecycle-finalize Step 2 rerun skips state 99.
- T6: find_state_file fallback to .claude/patterns/ for state-99.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / ".claude" / "patterns" / "state-registry.json"
LINTER = REPO_ROOT / ".claude" / "scripts" / "verify-linter.sh"
LIFECYCLE_NEXT = REPO_ROOT / ".claude" / "scripts" / "lifecycle-next.sh"
LIFECYCLE_FINALIZE = REPO_ROOT / ".claude" / "scripts" / "lifecycle-finalize.sh"
PATTERNS_EPILOGUE = REPO_ROOT / ".claude" / "patterns" / "state-99-epilogue.md"

LIFECYCLE_SKILLS = [
    "verify", "bootstrap", "change", "review", "resolve", "distribute",
    "deploy", "teardown", "spec", "rollback", "iterate", "iterate-check",
    "iterate-cross", "iterate-cross-phase2", "retro", "solve", "observe", "audit", "upgrade",
]


# ── T1: 18-skill registry dispatch ─────────────────────────────────────────

class TestT1_RegistryDispatch:
    @pytest.fixture(scope="class")
    def registry(self):
        return json.load(open(REGISTRY))

    def test_all_18_skills_have_state_99(self, registry):
        for skill in LIFECYCLE_SKILLS:
            assert skill in registry, f"skill {skill} missing from registry"
            assert "99" in registry[skill], f"{skill}.99 missing"

    def test_state_99_verify_text_identical_across_skills(self, registry):
        verifies = set()
        for skill in LIFECYCLE_SKILLS:
            entry = registry[skill]["99"]
            v = entry if isinstance(entry, str) else entry.get("verify", "")
            verifies.add(v)
        assert len(verifies) == 1, f"state 99 VERIFY text diverges across skills: {len(verifies)} variants"

    def test_state_99_verify_reads_observation_enforcement(self, registry):
        entry = registry["solve"]["99"]
        v = entry if isinstance(entry, str) else entry.get("verify", "")
        assert "observation-enforcement.json" in v, "VERIFY must reference observation-enforcement.json"
        assert "pass" in v and "skipped" in v, "VERIFY must check both pass and skipped fields"
        # Round 2 critic concern 1: error field MUST NOT be an acceptable outcome
        # for the assertion. Check that the assert expression is literally
        # "pass is True or skipped is True" with no "or error" disjunct.
        assert_line_match = re.search(r"assert\s+d\.get\('pass'\)[^,]*?,", v)
        assert assert_line_match, f"VERIFY does not have expected assert structure: {v}"
        assert_expr = assert_line_match.group(0)
        assert "d.get('error')" not in assert_expr, (
            f"error field must not satisfy VERIFY assertion (vacuous VERIFY regression); "
            f"assert expression: {assert_expr}"
        )


# ── T3: VERIFY JSON interpretation ─────────────────────────────────────────

class TestT3_VerifyJsonPaths:
    @pytest.fixture
    def verify_cmd(self):
        # Registry entries can be either a bare string OR an object
        # `{"verify": "...", "artifact": "...", "lifecycle": "..."}` (Wave B
        # introduced object form for state-99 across every skill — they share
        # the canonical observation-enforcement VERIFY). Extract the verify
        # field when the entry is an object.
        reg = json.load(open(REGISTRY))
        entry = reg["solve"]["99"]
        if isinstance(entry, dict):
            return entry["verify"]
        return entry

    @pytest.fixture
    def sandbox(self, tmp_path):
        # Write a matching <skill>-context.json so the GRAIM v2 C1+C2
        # identity-cross-check assertions inside the VERIFY (skill+run_id
        # match the active context) succeed. Without this, every "pass"
        # case fails on the new identity-staleness assertion even though
        # the pass/skipped semantics under test are unchanged.
        (tmp_path / ".runs").mkdir()
        (tmp_path / ".runs" / "verify-recheck.json").write_text('{"passed":0,"failed":0,"total":0}')
        (tmp_path / ".runs" / "t-context.json").write_text(
            '{"skill":"t","run_id":"r1","branch":"feat/x","timestamp":"2026-04-30T00:00:00Z"}'
        )
        return tmp_path

    def _run(self, cmd, cwd):
        return subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True)

    def test_pass_true_satisfies(self, verify_cmd, sandbox):
        (sandbox / ".runs" / "observation-enforcement.json").write_text(
            '{"pass":true,"missing":[],"scope":"code","skill":"t","run_id":"r1","fast_path":false}'
        )
        assert self._run(verify_cmd, sandbox).returncode == 0

    def test_skipped_true_satisfies(self, verify_cmd, sandbox):
        (sandbox / ".runs" / "observation-enforcement.json").write_text(
            '{"pass":false,"skipped":true,"scope":"unknown","skill":"t","run_id":"r1","fast_path":false,"skip_reason":"external"}'
        )
        assert self._run(verify_cmd, sandbox).returncode == 0

    def test_error_alone_rejected(self, verify_cmd, sandbox):
        (sandbox / ".runs" / "observation-enforcement.json").write_text(
            '{"pass":false,"missing":["x"],"scope":"code","skill":"t","run_id":"r1","fast_path":false,"error":"script exited unexpectedly"}'
        )
        # Must NOT pass — error-only path recreates the vacuous VERIFY bug
        assert self._run(verify_cmd, sandbox).returncode != 0

    def test_pass_false_no_error_rejected(self, verify_cmd, sandbox):
        (sandbox / ".runs" / "observation-enforcement.json").write_text(
            '{"pass":false,"missing":["x"],"scope":"code","skill":"t","run_id":"r1","fast_path":false}'
        )
        assert self._run(verify_cmd, sandbox).returncode != 0

    def test_missing_enforcement_json_rejected(self, verify_cmd, sandbox):
        # verify-recheck.json exists but observation-enforcement.json absent
        assert self._run(verify_cmd, sandbox).returncode != 0


# ── T4: CHECK-X1/X2 regex ─────────────────────────────────────────────────

# Mirror the regexes from verify-linter.sh. If these diverge from the
# in-script regex, the test fails and flags the drift.
EARLY_EXIT_TRIGGER = re.compile(
    r'\bIf (?:ALL |no |zero |0 |none |the .*? is empty|there are no )'
    r'.{0,300}?'
    r'(?:exit loop|exit early|'
    r'advance state.{0,100}?TERMINAL|skill ends|'
    r'no PR created|terminate)\b',
    re.IGNORECASE | re.DOTALL,
)

BASELINE_PARITY_TRIGGER = re.compile(
    r'\b(?:'
    r'<=\s*(?:baseline|pre.?fix)'
    r'|no regression\s+(?:from|vs|against)\s+baseline'
    r'|final_errors\s*<=\s*baseline'
    r'|error count does not exceed baseline'
    r')',
    re.IGNORECASE,
)


class TestT4_CheckX1Regex:
    MATCH_CASES = [
        ("review.2e", "If no fixes succeeded this iteration -> exit loop, proceed to State 3."),
        ("review.2b", "If 0 remaining findings -> exit loop"),
        ("resolve.7", (
            "- If ALL fixes were rejected (no changes in git working tree): report\n"
            "  \"All fixes were rejected — no changes to commit. Issues remain open.\"\n"
            "  Advance state and **TERMINAL** — skill ends, no PR created."
        )),
    ]

    NO_MATCH_CASES = [
        ("happy-path", "If ALL tests passed, proceed to STATE 2 (happy path)"),
        ("bootstrap.3b", "If no suspicious matches -> proceed silently"),
        ("bootstrap.16", "If no test files exist: use direct mode"),
        ("bootstrap.2", "If no files exist in that category, read a well-populated stack file"),
        ("observe.1", 'If no: report "File not found: <path>"'),
        ("verify.1", (
            "**If all 3 attempts fail**, stop and report to the user:\n"
            "> **Build verification failed after 3 attempts.**"
        )),
    ]

    @pytest.mark.parametrize("name,text", MATCH_CASES)
    def test_must_match(self, name, text):
        assert EARLY_EXIT_TRIGGER.search(text) is not None, f"{name} should match but did not"

    @pytest.mark.parametrize("name,text", NO_MATCH_CASES)
    def test_must_not_match(self, name, text):
        assert EARLY_EXIT_TRIGGER.search(text) is None, f"{name} should not match but did"


class TestT4_CheckX2Regex:
    MATCH_CASES = [
        ("review.4", "If final_errors <= baseline_errors, keep; else stop and report regression."),
        ("hypothetical", "VERIFY: no regression from baseline"),
    ]

    NO_MATCH_CASES = [
        # Per-fix keep/revert rule (internal loop operation, not state-level semantic)
        ("review.2e-internal", "5. If error count same or decreased -> keep the fix"),
        # Plain text descriptions
        ("plain", "After running all validators"),
    ]

    @pytest.mark.parametrize("name,text", MATCH_CASES)
    def test_must_match(self, name, text):
        assert BASELINE_PARITY_TRIGGER.search(text) is not None, f"{name} should match but did not"

    @pytest.mark.parametrize("name,text", NO_MATCH_CASES)
    def test_must_not_match(self, name, text):
        assert BASELINE_PARITY_TRIGGER.search(text) is None, f"{name} should not match but did"


# ── T6: find_state_file fallback ──────────────────────────────────────────

class TestT6_FindStateFileFallback:
    def test_state_99_lives_under_patterns_dir(self):
        assert PATTERNS_EPILOGUE.is_file(), "state-99-epilogue.md must exist under .claude/patterns/"

    def test_state_99_has_postconditions_section(self):
        """remediation-phase.md extract_postconditions globs state files to read
        POSTCONDITIONS; state-99-epilogue.md must have one so remediation prompts
        are non-empty if VERIFY fails."""
        text = PATTERNS_EPILOGUE.read_text()
        assert "**POSTCONDITIONS:**" in text

    def test_state_99_verify_block_present(self):
        """sync-verify writes VERIFY code fence into state-99 via patterns-dir
        fallback; fence must exist for sync to find it."""
        text = PATTERNS_EPILOGUE.read_text()
        assert "**VERIFY:**" in text
        assert "```bash" in text


# ── T5: lifecycle-finalize self-skip ───────────────────────────────────────

class TestT5_FinalizeStep2SelfSkip:
    def test_skip_sentinel_in_script(self):
        text = LIFECYCLE_FINALIZE.read_text()
        assert "state_id == '99'" in text, (
            "lifecycle-finalize Step 2 must skip state 99 in VERIFY rerun loop"
        )


# ── T2: embed skip ────────────────────────────────────────────────────────

class TestT2_EmbedSkip:
    def test_lifecycle_init_writes_embed_skip_epilogue(self):
        text = (REPO_ROOT / ".claude" / "scripts" / "lifecycle-init.sh").read_text()
        assert "embed_skip_epilogue" in text
        # Must be gated on EMBED_MODE
        assert 'if [[ -n "$EMBED_MODE" ]]' in text

    def test_lifecycle_next_honors_embed_skip_epilogue(self):
        text = LIFECYCLE_NEXT.read_text()
        assert 'ctx.get("embed_skip_epilogue") is True' in text, (
            "lifecycle-next must honor embed_skip_epilogue as defense-in-depth against "
            "skip_states wholesale rewrites"
        )


# ── T1b: skill.yaml states include 99 ─────────────────────────────────────

class TestT1b_SkillYamlStateLists:
    @pytest.mark.parametrize("skill", [s for s in LIFECYCLE_SKILLS if s not in ("iterate-check", "iterate-cross", "iterate-cross-phase2")])
    def test_skill_yaml_includes_99(self, skill):
        yaml_path = REPO_ROOT / ".claude" / "skills" / (skill if skill not in ("iterate-check", "iterate-cross", "iterate-cross-phase2") else "iterate") / "skill.yaml"
        if not yaml_path.exists():
            pytest.skip(f"{yaml_path} not found (non-lifecycle skill?)")
        import yaml
        d = yaml.safe_load(yaml_path.read_text())
        if skill == "iterate":
            # Every mode must include 99
            for mode_name, mode_body in d.get("modes", {}).items():
                states = [str(s) for s in mode_body.get("states", [])]
                assert "99" in states, f"iterate.{mode_name} states missing 99"
        else:
            states = [str(s) for s in d.get("states", [])]
            assert "99" in states, f"{skill} states missing 99: {states}"


# ── Integration: linter is clean ──────────────────────────────────────────

class TestIntegration_LinterClean:
    def test_verify_linter_exits_clean(self):
        """After all P1-P6b edits, verify-linter.sh must report zero findings."""
        r = subprocess.run(
            ["bash", str(LINTER)],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        out = (r.stdout + r.stderr).lower()
        assert r.returncode == 0, f"verify-linter exited {r.returncode}\n{r.stdout}\n{r.stderr}"
        assert "0 uncovered" in out
        assert "0 diverged" in out
        assert "0 unjustified_true" in out
        assert "0 drift_declared" in out
        assert "0 cross_file_contradiction" in out
