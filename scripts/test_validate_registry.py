"""Tests for state-registry.json structural validation."""
import json
import os
import re
import pytest

REGISTRY_PATH = os.path.join(
    os.path.dirname(__file__), "..", ".claude", "patterns", "state-registry.json"
)


def load_registry():
    with open(REGISTRY_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Registry top-level structure
# ---------------------------------------------------------------------------


class TestRegistryStructure:
    def test_is_valid_json(self):
        reg = load_registry()
        assert isinstance(reg, dict)

    def test_skill_sections_are_dicts(self):
        reg = load_registry()
        for key, val in reg.items():
            assert isinstance(val, dict), f"Top-level key '{key}' must be a dict"


# ---------------------------------------------------------------------------
# State entry format validation (string or object)
# ---------------------------------------------------------------------------


class TestStateEntryFormats:
    def test_all_entries_are_string_or_object(self):
        reg = load_registry()
        skip_sections = {"trace_schemas", "skill_owned_artifacts", "epilogue_artifacts"}
        for skill, states in reg.items():
            if skill in skip_sections:
                continue
            for state_id, entry in states.items():
                assert isinstance(entry, (str, dict)), (
                    f"{skill}.{state_id}: entry must be str or dict, "
                    f"got {type(entry).__name__}"
                )

    def test_object_entries_have_verify_key(self):
        reg = load_registry()
        skip_sections = {"trace_schemas", "skill_owned_artifacts", "epilogue_artifacts"}
        for skill, states in reg.items():
            if skill in skip_sections:
                continue
            for state_id, entry in states.items():
                if isinstance(entry, dict):
                    assert "verify" in entry, (
                        f"{skill}.{state_id}: object entry must have 'verify' key"
                    )

    def test_object_entries_verify_is_string(self):
        reg = load_registry()
        skip_sections = {"trace_schemas", "skill_owned_artifacts", "epilogue_artifacts"}
        for skill, states in reg.items():
            if skill in skip_sections:
                continue
            for state_id, entry in states.items():
                if isinstance(entry, dict):
                    assert isinstance(entry["verify"], str), (
                        f"{skill}.{state_id}: 'verify' must be a string"
                    )

    def test_object_entries_calls_is_list(self):
        reg = load_registry()
        skip_sections = {"trace_schemas", "skill_owned_artifacts", "epilogue_artifacts"}
        for skill, states in reg.items():
            if skill in skip_sections:
                continue
            for state_id, entry in states.items():
                if isinstance(entry, dict) and "calls" in entry:
                    assert isinstance(entry["calls"], list), (
                        f"{skill}.{state_id}: 'calls' must be a list"
                    )

    def test_calls_entries_have_required_keys(self):
        reg = load_registry()
        skip_sections = {"trace_schemas", "skill_owned_artifacts", "epilogue_artifacts"}
        for skill, states in reg.items():
            if skill in skip_sections:
                continue
            for state_id, entry in states.items():
                if isinstance(entry, dict) and "calls" in entry:
                    for i, call in enumerate(entry["calls"]):
                        assert isinstance(call, dict), (
                            f"{skill}.{state_id}.calls[{i}]: must be a dict"
                        )
                        assert "path" in call, (
                            f"{skill}.{state_id}.calls[{i}]: must have 'path'"
                        )
                        assert "artifact" in call, (
                            f"{skill}.{state_id}.calls[{i}]: must have 'artifact'"
                        )


# ---------------------------------------------------------------------------
# Current registry baseline
# ---------------------------------------------------------------------------

# Object-format entries that have been intentionally upgraded.
#
# Two upgrade waves:
#   Wave A (pre-#1162): {verify, calls} or {verify, allows_early_exit_when, ...}
#     for richer per-state metadata (multi-call states, exit conditions).
#   Wave B (#1162): {verify, artifact, lifecycle: durable | transient-cross-skill |
#     transient-intra-skill} declaring artifact lifecycle so lifecycle-finalize.sh
#     can skip transient-intra-skill VERIFY rerun and lifecycle-next.sh can block
#     resume on missing-durable-artifact. Migration-driven (deterministic via
#     migrate-state-registry-lifecycle.py).
KNOWN_OBJECT_ENTRIES = {
    # Wave A entries
    ("change", "2"),
    ("change", "3"),
    ("change", "6"),
    ("review", "2b"),
    ("resolve", "7"),  # #1043 sibling fix: allows_early_exit_when=all_fixes_rejected
    ("verify", "7b"),
    # Wave B entries (#1162) — the verify skill
    ("verify", "0"),
    ("verify", "2"),
    ("verify", "3a"),
    ("verify", "3b"),
    ("verify", "3c"),
    ("verify", "3d"),
    ("verify", "4"),
    ("verify", "7a"),
    # Wave B entries — bootstrap
    ("bootstrap", "3a"),
    ("bootstrap", "10"),
    ("bootstrap", "11"),
    ("bootstrap", "12"),
    ("bootstrap", "13c"),
    ("bootstrap", "14a"),
    ("bootstrap", "18"),
    ("bootstrap", "19b"),
    # Wave B entries — change
    ("change", "7"),
    ("change", "8"),
    ("change", "9"),
    ("change", "10"),
    ("change", "11a"),
    ("change", "11b"),
    ("change", "12"),
    # Wave B entries — review (2e/4 retroactively migrated; 2f/6 newly added)
    ("review", "2e"),  # #928 fix: allows_early_exit_when=no_fixes
    ("review", "2f"),
    ("review", "4"),   # #928 fix: verify_semantics=no_regression_from_baseline
    ("review", "6"),
    # Wave B entries — resolve
    ("resolve", "10"),
    ("resolve", "11"),
    # #1339 — opt-in deferred VERIFY for chained writer + advance-state.
    # state.8 + state.8b carry defer_verify_when_writer in object form so the
    # state-completion-gate hook can decompose chains and skip sync VERIFY
    # when a sibling write-gate-artifact.sh writes the listed path.
    ("resolve", "8"),
    ("resolve", "8b"),
    # Wave B entries — distribute
    ("distribute", "3a"),
    ("distribute", "5"),
    # Wave B entries — other skills
    ("iterate-check", "c3"),
    ("observe", "1"),
    ("ads-ready", "0"),
    ("ads-ready", "1"),
    # #1331 — solve.1 migrated from string to object form (verify+artifact+lifecycle)
    # to declare .runs/solve-challenge.json + transient-cross-skill lifecycle so
    # artifact-transience-solve coherence rule is satisfied and the new
    # solve-challenge.json artifact is wiped by lifecycle-init.sh.
    ("solve", "1"),
    ("solve", "2"),
    ("upgrade", "3"),
    # Shared epilogue state-99 entries — every skill's 99 is a transient-cross-skill
    # object entry sharing the same VERIFY (artifact: observation-enforcement.json).
    ("verify", "99"),
    ("bootstrap", "99"),
    ("change", "99"),
    ("review", "99"),
    ("distribute", "99"),
    ("resolve", "99"),
    ("solve", "99"),
    ("spec", "99"),
    ("upgrade", "99"),
    ("deploy", "99"),
    ("teardown", "99"),
    ("rollback", "99"),
    ("iterate-check", "99"),
    ("iterate-cross", "99"),
    ("iterate-cross-phase2", "99"),
    ("iterate", "99"),
    ("retro", "99"),
    ("observe", "99"),
    ("audit", "99"),
    ("ads-ready", "99"),
}

# State IDs that refer to shared state files in .claude/patterns/ rather than
# a per-skill file under .claude/skills/<skill>/. State 99 is the shared
# terminal epilogue state (see state-99-epilogue.md + #1043 fix).
SHARED_TERMINAL_STATE_IDS = {"99"}


class TestRegistryBaseline:
    def test_entry_count(self):
        """Confirm total entry count hasn't changed unexpectedly."""
        reg = load_registry()
        count = 0
        for skill, states in reg.items():
            if skill in {"trace_schemas", "skill_owned_artifacts", "epilogue_artifacts"}:
                continue
            count += len(states)
        assert count >= 100, f"Expected ~147 state entries, found {count}"

    def test_known_object_entries_are_objects(self):
        """Entries listed in KNOWN_OBJECT_ENTRIES must be object format."""
        reg = load_registry()
        for skill, state_id in KNOWN_OBJECT_ENTRIES:
            entry = reg[skill][state_id]
            assert isinstance(entry, dict), (
                f"{skill}.{state_id}: expected object format"
            )

    def test_non_listed_entries_are_strings(self):
        """Entries NOT in KNOWN_OBJECT_ENTRIES must still be strings."""
        reg = load_registry()
        skip_sections = {"trace_schemas", "skill_owned_artifacts", "epilogue_artifacts"}
        for skill, states in reg.items():
            if skill in skip_sections:
                continue
            for state_id, entry in states.items():
                if (skill, state_id) in KNOWN_OBJECT_ENTRIES:
                    continue
                assert isinstance(entry, str), (
                    f"{skill}.{state_id}: unexpected object entry — "
                    f"add to KNOWN_OBJECT_ENTRIES if intentional"
                )


# ---------------------------------------------------------------------------
# State ordering (keys should be in ascending order within each skill)
# ---------------------------------------------------------------------------


def _state_sort_key(state_id):
    """Sort key for state IDs: numeric first, then alpha suffixes.
    The shared terminal epilogue state ("99") always sorts LAST so it can
    coexist with alpha-prefixed state ids (iterate-check uses c0, c1, ...;
    iterate-cross uses x0, x1, ...)."""
    if state_id in SHARED_TERMINAL_STATE_IDS:
        return (float('inf'), "")
    m = re.match(r"^(\d+)(.*)$", state_id)
    if m:
        return (int(m.group(1)), m.group(2))
    return (999, state_id)


class TestStateOrdering:
    def test_state_keys_in_ascending_order(self):
        reg = load_registry()
        skip_sections = {"trace_schemas", "skill_owned_artifacts", "epilogue_artifacts"}
        for skill, states in reg.items():
            if skill in skip_sections:
                continue
            keys = list(states.keys())
            sorted_keys = sorted(keys, key=_state_sort_key)
            assert keys == sorted_keys, (
                f"{skill}: state keys out of order: {keys} vs expected {sorted_keys}"
            )


# ---------------------------------------------------------------------------
# Bidirectional file <-> registry sync validation
# ---------------------------------------------------------------------------

SKILLS_DIR = os.path.join(
    os.path.dirname(__file__), "..", ".claude", "skills"
)


def _discover_state_files():
    """Find all state-*.md files under .claude/skills/*/."""
    import glob
    return sorted(glob.glob(os.path.join(SKILLS_DIR, "*", "state-*.md")))


def _extract_advance_state_calls(filepath):
    """Parse advance-state.sh <skill> <state> from a state file.

    Uses the skill name from the call, NOT the directory name.
    Handles multi-mode: iterate/state-c0-*.md -> iterate-check.c0
    """
    results = []
    with open(filepath) as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            m = re.search(
                r'(?:bash\s+\S*/|\./)advance-state\.sh\s+([a-z][a-z0-9_-]*)\s+([a-z0-9_]+)',
                stripped,
            )
            if m:
                results.append((m.group(1), m.group(2)))
    return results


def test_extract_advance_state_calls_accepts_digit_mode_skill(tmp_path):
    state_file = tmp_path / "state-x5-pay-intent-verdict.md"
    state_file.write_text(
        "```bash\n"
        "bash .claude/scripts/advance-state.sh iterate-cross-phase2 x5\n"
        "```\n"
    )
    assert _extract_advance_state_calls(str(state_file)) == [
        ("iterate-cross-phase2", "x5")
    ]


class TestForwardSync:
    """Every state file on disk must have a matching registry entry."""

    def test_every_state_file_has_registry_entry(self):
        reg = load_registry()
        missing = []
        for f in _discover_state_files():
            for skill, state_id in _extract_advance_state_calls(f):
                if skill not in reg or state_id not in reg.get(skill, {}):
                    missing.append(
                        f"{skill}.{state_id} (from {os.path.basename(f)})"
                    )
        assert not missing, (
            f"{len(missing)} unregistered entries:\n"
            + "\n".join(f"  {m}" for m in missing)
        )

    def test_every_state_file_has_advance_state_call(self):
        no_call = []
        for f in _discover_state_files():
            if not _extract_advance_state_calls(f):
                no_call.append(os.path.relpath(f))
        assert not no_call, (
            f"{len(no_call)} state files lack advance-state.sh call:\n"
            + "\n".join(f"  {f}" for f in no_call)
        )


class TestReverseSync:
    """Every registry entry must have a corresponding state file."""

    def test_every_registry_entry_has_state_file(self):
        reg = load_registry()
        skip = {"trace_schemas", "skill_owned_artifacts", "epilogue_artifacts"}

        # Discover shared terminal state files under .claude/patterns/
        import glob as _glob
        patterns_dir = os.path.join(
            os.path.dirname(__file__), "..", ".claude", "patterns"
        )
        shared_state_ids_present = set()
        for path in _glob.glob(os.path.join(patterns_dir, "state-*.md")):
            m = re.match(r"state-([0-9a-z]+)-.*\.md$", os.path.basename(path))
            if m and m.group(1) in SHARED_TERMINAL_STATE_IDS:
                shared_state_ids_present.add(m.group(1))

        file_map = {}
        for f in _discover_state_files():
            for skill, state_id in _extract_advance_state_calls(f):
                file_map[(skill, state_id)] = f
        missing = []
        for skill, states in reg.items():
            if skill in skip:
                continue
            for state_id in states:
                # Shared terminal states are dispatched from .claude/patterns/
                # via the find_state_file fallback in lifecycle-next.sh
                if state_id in shared_state_ids_present:
                    continue
                if (skill, state_id) not in file_map:
                    missing.append(f"{skill}.{state_id}")
        assert not missing, (
            f"{len(missing)} orphan registry entries:\n"
            + "\n".join(f"  {m}" for m in missing)
        )


class TestPostconditionSyntax:
    """Verify postcondition commands are syntactically valid."""

    def test_python_commands_parse(self):
        import ast
        reg = load_registry()
        skip = {"trace_schemas", "skill_owned_artifacts", "epilogue_artifacts"}
        errors = []
        for skill, states in reg.items():
            if skill in skip:
                continue
            for state_id, entry in states.items():
                cmd = (
                    entry.get("verify", entry)
                    if isinstance(entry, dict)
                    else entry
                )
                if not isinstance(cmd, str):
                    continue
                for m in re.finditer(
                    r'python3 -c "(.*?)"(?:\s|$|\|)', cmd, re.DOTALL
                ):
                    code = m.group(1).replace('\\"', '"')
                    try:
                        ast.parse(code)
                    except SyntaxError as e:
                        errors.append(f"{skill}.{state_id}: {e}")
        assert not errors, (
            f"{len(errors)} syntax errors:\n" + "\n".join(errors)
        )

    def test_object_entries_structure(self):
        reg = load_registry()
        skip = {"trace_schemas", "skill_owned_artifacts", "epilogue_artifacts"}
        errors = []
        for skill, states in reg.items():
            if skill in skip:
                continue
            for state_id, entry in states.items():
                if not isinstance(entry, dict):
                    continue
                if "verify" not in entry:
                    errors.append(f"{skill}.{state_id}: missing 'verify'")
                elif not isinstance(entry["verify"], str):
                    errors.append(f"{skill}.{state_id}: 'verify' not string")
                if "calls" in entry and not isinstance(entry["calls"], list):
                    errors.append(f"{skill}.{state_id}: 'calls' not list")
        assert not errors, "\n".join(errors)


# ---------------------------------------------------------------------------
# Verify-linter integration (VERIFY-POSTCONDITIONS drift detection)
# ---------------------------------------------------------------------------


class TestVerifyLinterClean:
    """verify-linter.sh must report 0 uncovered, 0 diverged, 0 unjustified_true."""

    def test_verify_linter_passes(self):
        import subprocess

        repo_root = os.path.join(os.path.dirname(__file__), "..")
        linter = os.path.join(repo_root, ".claude", "scripts", "verify-linter.sh")
        result = subprocess.run(
            ["bash", linter],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        assert result.returncode == 0, (
            f"verify-linter.sh failed (exit {result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )
        assert "0 uncovered" in result.stdout, f"Expected 0 uncovered:\n{result.stdout}"
        assert "0 diverged" in result.stdout, f"Expected 0 diverged:\n{result.stdout}"
        assert "0 unjustified_true" in result.stdout, (
            f"Expected 0 unjustified_true:\n{result.stdout}"
        )
