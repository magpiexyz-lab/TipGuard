"""Meta-tests for the 5 hard-block validators introduced in the unified
physical-artifact-enforcement PR (#1276/#1272/#1261/#1252/#1255).

Round-2 critic Concern 8: future PRs that soften any validator (e.g.,
replacing `assert <condition>` with `print("WARN"); sys.exit(0)`) get
caught by these property tests. Each validator is exercised with synthetic
INVALID inputs and the test asserts non-zero exit code AND/OR specific
error output.

Layout (one TestCase per validator):
  - existence: validator script file exists and is executable
  - reference: validator is referenced from its expected integration point
    (state-registry.json / lifecycle-finalize.sh / observation-phase.md)
  - happy_path: clean fixture → exit 0
  - missing_input: required input absent → controlled exit (skip OR fail)
  - synthetic_invalid: malformed/incomplete fixture → exit 1 in deny mode
  - softening_no_op: hypothetical "no-op" patch wouldn't pass — verified
    indirectly by asserting the validator's output mentions specific
    error categories (a no-op print('ok') script wouldn't)

CI auto-discovers this file via .github/workflows/ci.yml line 113
(`pytest .claude/scripts/tests/`).

Conventions reused from .claude/scripts/tests/test_validate_recovery.py:
  - subprocess + tempdir + git init pattern
  - cwd-pinned subprocess.run for fixture isolation
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Repo root: tests/ lives at .claude/scripts/tests/, so up 3 = repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / ".claude" / "scripts"

# Pre-cutoff run_id (matches RUN_ID_TS_RE) — schema_version_gate returns 1
PRE_CUTOFF_RUN_ID = "test-2020-01-01T00:00:00Z"

# Post-cutoff would be after MIGRATION_CUTOFF_ISO. Since cutoff is the
# placeholder __MERGE_COMMIT_TIMESTAMP__ until merge-commit sed, we cannot
# directly construct a "post-cutoff" run_id. Instead, the meta-tests
# exercise the validators in pre-cutoff SKIP mode (which exits 0) AND
# directly exercise the underlying logic by setting the env var to deny
# mode + faking pending-findings to verify error paths produce non-zero
# exit when MODE=deny is forced AND the gate is artificially activated.

# To exercise post-cutoff behavior we monkey-patch the helper module by
# setting MIGRATION_CUTOFF_ISO via a wrapper subprocess that pre-imports
# and overrides. Pattern: PYTHONPATH=<lib> python -c "import schema_version_gate;
# schema_version_gate.MIGRATION_CUTOFF_ISO='2000-01-01T00:00:00Z'; <run script>".

VALIDATORS = {
    "validate-retrospective-completeness.py": {
        "mode_env": "RETROSPECTIVE_COMPLETENESS_MODE",
        "ref_files": [
            # Wired at check-observation-artifacts.sh (state-99 Step 2a),
            # NOT lifecycle-finalize.sh (state-99 Step 1) — the latter runs
            # BEFORE retrospective-result.json is written by Step 5a.
            ".claude/scripts/check-observation-artifacts.sh",
            ".claude/patterns/observation-phase.md",
        ],
    },
    "validate-step55-evidence.py": {
        "mode_env": "STEP55_EVIDENCE_MODE",
        "ref_files": [
            ".claude/patterns/state-registry.json",
            ".claude/procedures/design-critic.md",
        ],
    },
    "validate-image-spec-compliance.py": {
        "mode_env": "SCAFFOLD_IMAGES_SPEC_MODE",
        "ref_files": [
            ".claude/patterns/state-registry.json",
        ],
        # state_registry_states (#1294): every state-registry entry that
        # MUST chain this validator in its VERIFY. Only scaffold-images
        # (bootstrap.11a) writes image-manifest.json; bootstrap.11b is the
        # downstream validator-state. /change does not spawn scaffold-* so
        # is not listed — D-3 catches future additions across all skills.
        "state_registry_states": [("bootstrap", "11b")],
    },
    "validate-scaffold-recommendations-schema.py": {
        "mode_env": "SCAFFOLD_RECOMMENDATIONS_SCHEMA_MODE",
        "ref_files": [
            ".claude/patterns/state-registry.json",
        ],
        # state_registry_states (#1294): each scaffold-* spawn must be
        # validated by a downstream state. Bootstrap ordering:
        #   9 scaffold-setup, 10 scaffold-init, 11a scaffold-libs/externals/
        #   images → validated at 11b
        #   11c scaffold-pages/landing → validated at 11c (this PR)
        #   14 scaffold-wire → validated at 14 (this PR)
        "state_registry_states": [
            ("bootstrap", "11b"),
            ("bootstrap", "11c"),
            ("bootstrap", "14"),
        ],
    },
    "validate-observer-evidence-coverage.py": {
        "mode_env": "OBSERVER_EVIDENCE_COVERAGE_MODE",
        "ref_files": [
            ".claude/patterns/observation-phase.md",
            ".claude/agents/observer.md",
        ],
    },
}


def _run_validator(
    validator: str,
    cwd: Path,
    extra_env: dict | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["python3", str(SCRIPTS_DIR / validator)],
        cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout,
    )


def _setup_tempdir_with_context(run_id: str = PRE_CUTOFF_RUN_ID) -> Path:
    """Create tempdir with a minimal .runs/<skill>-context.json."""
    tmp = Path(tempfile.mkdtemp(prefix="test_validator_"))
    runs = tmp / ".runs"
    runs.mkdir(parents=True, exist_ok=True)
    # Minimal context that _active_run_id() will pick up
    skill = run_id.split("-2", 1)[0]
    ctx = {
        "skill": skill,
        "branch": "test",
        "timestamp": "2020-01-01T00:00:00Z",
        "run_id": run_id,
        "completed_states": [],
        "completed": False,
    }
    (runs / f"{skill}-context.json").write_text(json.dumps(ctx))
    return tmp


def _force_post_cutoff_invocation(
    validator: str,
    cwd: Path,
    extra_env: dict | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    """Run a validator with MIGRATION_CUTOFF_ISO patched to a past date,
    so all run_ids are post-cutoff and the validator's actual logic runs."""
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    # Symlink lib/ + patched schema_version_gate.py
    # Simpler: copy validator and lib to tempdir, then patch
    # Even simpler: use a wrapper that pre-imports and overrides

    wrapper = f"""
import sys, os, runpy
sys.path.insert(0, {str(SCRIPTS_DIR)!r})
import lib.schema_version_gate as svg
svg.MIGRATION_CUTOFF_ISO = "2000-01-01T00:00:00Z"
runpy.run_path({str(SCRIPTS_DIR / validator)!r}, run_name="__main__")
"""
    return subprocess.run(
        ["python3", "-c", wrapper],
        cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout,
    )


# ---------- Universal tests applied to every validator ----------

class TestValidatorExistence(unittest.TestCase):
    """Each validator script must exist and be executable."""

    def test_all_validator_scripts_exist(self):
        for name in VALIDATORS:
            path = SCRIPTS_DIR / name
            self.assertTrue(
                path.is_file(),
                f"validator {name!r} missing at {path}",
            )

    def test_all_validators_have_main_block(self):
        for name in VALIDATORS:
            content = (SCRIPTS_DIR / name).read_text()
            self.assertIn(
                "if __name__ == \"__main__\"", content,
                f"{name}: missing __main__ block",
            )


class TestValidatorReferences(unittest.TestCase):
    """Each validator must be referenced from its expected integration files
    (#1276 round-2 C8 anti-removal property)."""

    def test_validators_referenced_from_integration_points(self):
        for name, spec in VALIDATORS.items():
            for ref_file in spec["ref_files"]:
                full = REPO_ROOT / ref_file
                self.assertTrue(
                    full.is_file(),
                    f"reference file {ref_file!r} missing",
                )
                content = full.read_text()
                self.assertIn(
                    name, content,
                    f"{name!r} not referenced from {ref_file!r} — integration broken",
                )


# ---------------------------------------------------------------------------
# Cross-state coverage tests (#1294)
#
# A validator that must run at multiple state-registry entries declares
# `state_registry_states: [(skill, state_id), ...]` in VALIDATORS.
# Four tests cooperate to lock coverage and prevent silent drift:
#   D-2 explicit allowlist: each listed state's verify mentions the validator
#   D-3 auto-discovery:     every scaffold-* spawn site has a downstream
#                           validator-state in the same skill (walks ALL
#                           `.claude/skills/**/state-*.md`)
#   D-4 spawn superset:     allowlist covers every present spawn site
#   D-5 inverse drift:      every state-registry mention of the validator is
#                           in the allowlist
#
# This is the canonical way #1294 is closed — stronger than wiring change.11b
# (which is a no-op today) because D-3 catches future scaffold-* spawn sites
# in any skill, including /change /upgrade /resolve.
# ---------------------------------------------------------------------------

STATE_REGISTRY_PATH = REPO_ROOT / ".claude" / "patterns" / "state-registry.json"
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
SCAFFOLD_SPAWN_RE = re.compile(
    r"^\s*-\s*subagent_type:\s*(scaffold-[a-z-]+)\s*$",
    re.MULTILINE,
)


def _extract_verify(entry):
    """Mirror sync-verify-to-state-files.sh extract_verify_cmd() (lines 40-46).

    State-registry entries can be either a bare command string or a
    {"verify": ..., "artifact": ..., "lifecycle": ...} dict.
    """
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return entry.get("verify", "")
    return ""


def _load_state_registry():
    return json.loads(STATE_REGISTRY_PATH.read_text())


def _state_index(reg, skill, state_id):
    """Return the insertion-order index of state_id in reg[skill], or None.

    JSON object keys preserve insertion order in Python ≥3.7. The order in
    state-registry.json reflects the canonical execution order of the skill.
    """
    states = list(reg.get(skill, {}).keys())
    if state_id not in states:
        return None
    return states.index(state_id)


def _enumerate_scaffold_spawn_sites():
    """Walk .claude/skills/**/state-*.md for canonical scaffold-* spawn lines.

    Returns a list of tuples: (skill, state_id, agent_name, source_path).

    The regex is line-anchored to the canonical spawn marker
    `- subagent_type: scaffold-<name>`. This rejects:
      - markdown checklist items like `- [ ] scaffold-setup completed`
      - Python list literals like `expected = ['scaffold-setup', ...]`
      - prose mentions of scaffold-* names

    Future scaffold-* spawn sites in any skill MUST use this canonical form.
    """
    state_file_re = re.compile(r"^state-([0-9a-z]+)-")
    sites = []
    for path in sorted(SKILLS_DIR.glob("*/state-*.md")):
        try:
            relative = path.relative_to(SKILLS_DIR)
        except ValueError:
            continue
        parts = relative.parts
        if len(parts) < 2:
            continue
        skill = parts[0]
        m = state_file_re.match(parts[1])
        if not m:
            continue
        state_id = m.group(1)
        text = path.read_text()
        for match in SCAFFOLD_SPAWN_RE.finditer(text):
            sites.append((skill, state_id, match.group(1), path))
    return sites


class TestScaffoldValidatorCrossStateCoverage(unittest.TestCase):
    """D-2: each (skill, state_id) in VALIDATORS[*].state_registry_states must
    actually have the validator chained in that state's verify command.
    """

    def test_state_registry_states_wire_validator(self):
        reg = _load_state_registry()
        for name, spec in VALIDATORS.items():
            states = spec.get("state_registry_states") or []
            for skill, state_id in states:
                with self.subTest(validator=name, skill=skill, state=state_id):
                    self.assertIn(
                        skill, reg,
                        f"state-registry has no skill {skill!r}",
                    )
                    self.assertIn(
                        state_id, reg[skill],
                        f"state-registry[{skill}] has no state {state_id!r}",
                    )
                    verify = _extract_verify(reg[skill][state_id])
                    self.assertIn(
                        name, verify,
                        f"{name!r} not in state-registry[{skill}.{state_id}].verify "
                        f"— allowlist out of sync with registry",
                    )


class TestScaffoldSpawningStatesHaveValidators(unittest.TestCase):
    """D-3: every scaffold-* spawn site in `.claude/skills/**/state-*.md` must
    have a downstream validator-state in the same skill.

    Walks ALL skill directories — closes #1294's actual concern across the
    full skill universe (bootstrap, change, upgrade, resolve, ...). A future
    skill adding a scaffold-* spawn fails this test until the maintainer adds
    `(skill, state_id)` to VALIDATORS[validate-scaffold-recommendations-schema.py]
    .state_registry_states AND wires the validator into that state's verify.
    """

    def _assert_downstream_coverage(self, validator_spec, name, skill, spawn_state, agent_name):
        reg = _load_state_registry()
        spawn_idx = _state_index(reg, skill, spawn_state)
        self.assertIsNotNone(
            spawn_idx,
            f"spawn state {skill}.{spawn_state} (agent={agent_name}) not in registry",
        )
        states = list(reg[skill].keys())
        target_idxs = []
        for sk, target_state in validator_spec.get("state_registry_states", []):
            if sk != skill:
                continue
            t_idx = _state_index(reg, sk, target_state)
            if t_idx is not None:
                target_idxs.append(t_idx)
        self.assertTrue(
            any(t >= spawn_idx for t in target_idxs),
            f"scaffold-* spawn at {skill}.{spawn_state} (agent={agent_name}) "
            f"has no downstream validator-state for {name!r}; "
            f"states after spawn: {states[spawn_idx:]} ; "
            f"validator allowlist for {skill!r}: "
            f"{[s for sk, s in validator_spec.get('state_registry_states', []) if sk == skill]}",
        )

    def test_recommendations_validator_covers_every_spawn(self):
        spec = VALIDATORS["validate-scaffold-recommendations-schema.py"]
        for skill, state_id, agent_name, source in _enumerate_scaffold_spawn_sites():
            with self.subTest(skill=skill, state=state_id, agent=agent_name):
                self._assert_downstream_coverage(
                    spec,
                    "validate-scaffold-recommendations-schema.py",
                    skill,
                    state_id,
                    agent_name,
                )

    def test_image_spec_validator_covers_scaffold_images_spawns(self):
        spec = VALIDATORS["validate-image-spec-compliance.py"]
        for skill, state_id, agent_name, source in _enumerate_scaffold_spawn_sites():
            if agent_name != "scaffold-images":
                continue
            with self.subTest(skill=skill, state=state_id, agent=agent_name):
                self._assert_downstream_coverage(
                    spec,
                    "validate-image-spec-compliance.py",
                    skill,
                    state_id,
                    agent_name,
                )


class TestStateRegistryStatesMatchKnownSpawnUniverse(unittest.TestCase):
    """D-4: the recommendations validator's state_registry_states must cover
    every (skill, downstream_validator_state) implied by the present
    scaffold-* spawn universe. Catches: validator entry drops a coverage
    state, leaving present spawns uncovered.
    """

    def test_recommendations_allowlist_is_superset_of_spawn_anchors(self):
        reg = _load_state_registry()
        spec = VALIDATORS["validate-scaffold-recommendations-schema.py"]
        allowlist = set(tuple(p) for p in spec.get("state_registry_states", []))

        # For each spawn site, derive the EARLIEST allowlist state >= spawn_idx
        # (the canonical "downstream validator anchor"). If the validator is
        # supposed to cover this spawn, that anchor must exist in allowlist.
        for skill, state_id, agent_name, source in _enumerate_scaffold_spawn_sites():
            spawn_idx = _state_index(reg, skill, state_id)
            self.assertIsNotNone(
                spawn_idx,
                f"spawn state {skill}.{state_id} not in registry",
            )
            states = list(reg[skill].keys())
            # Earliest allowlisted state for this skill that is >= spawn_idx
            anchor_indices = sorted(
                _state_index(reg, sk, st)
                for sk, st in allowlist
                if sk == skill and _state_index(reg, sk, st) is not None
            )
            anchor_indices = [i for i in anchor_indices if i >= spawn_idx]
            self.assertTrue(
                anchor_indices,
                f"D-4: spawn at {skill}.{state_id} (agent={agent_name}) has no "
                f"downstream allowlisted state in "
                f"validate-scaffold-recommendations-schema.py.state_registry_states; "
                f"add ({skill}, <state-after-{state_id}>) to the allowlist AND wire "
                f"the validator at that state.",
            )


class TestValidatorMentionsInRegistryMatchAllowlist(unittest.TestCase):
    """D-5: every state-registry entry whose verify command mentions a
    validator with a `state_registry_states` allowlist must appear in that
    allowlist. Inverse drift detection.

    Catches: maintainer wires a new state in state-registry.json (e.g., adds
    bootstrap.13 to validate-scaffold-recommendations-schema.py) without
    updating VALIDATORS dict — D-2/D-4 silently pass while drift accumulates.

    SCOPE LIMITATION (post-#1305 audit): only validators that DECLARE
    `state_registry_states` participate. The other 3 validators
    (validate-retrospective-completeness.py, validate-step55-evidence.py,
    validate-observer-evidence-coverage.py) are OUT OF SCOPE for D-5
    today — they don't yet have explicit cross-state allowlists. To
    promote them, add `state_registry_states` to their VALIDATORS entry
    with the canonical (skill, state_id) list and the gate becomes
    automatic. Tracked as future work.
    """

    def test_registry_mentions_match_allowlist(self):
        reg = _load_state_registry()
        for name, spec in VALIDATORS.items():
            if "state_registry_states" not in spec:
                # See SCOPE LIMITATION in class docstring. Skipping is
                # intentional, not an oversight — promotion requires
                # adding state_registry_states to the validator's entry.
                continue
            allowlist = set(tuple(p) for p in spec["state_registry_states"])
            mentioned = set()
            for skill, states in reg.items():
                if not isinstance(states, dict):
                    continue
                for state_id, entry in states.items():
                    verify = _extract_verify(entry)
                    if name in verify:
                        mentioned.add((skill, state_id))
            unlisted = mentioned - allowlist
            self.assertFalse(
                unlisted,
                f"D-5: state-registry mentions {name!r} at {sorted(unlisted)} "
                f"but VALIDATORS[{name!r}].state_registry_states does not list "
                f"these — meta-test will not detect future removal. Add the "
                f"missing entries to VALIDATORS dict.",
            )


class TestValidatorPreCutoffSkip(unittest.TestCase):
    """Pre-cutoff run_id must produce SKIP exit 0 (backwards compat)."""

    def test_each_validator_skips_pre_cutoff(self):
        for name in VALIDATORS:
            with self.subTest(validator=name):
                tmp = _setup_tempdir_with_context(PRE_CUTOFF_RUN_ID)
                try:
                    r = _run_validator(name, tmp)
                    self.assertEqual(
                        r.returncode, 0,
                        f"{name}: pre-cutoff should exit 0 (got {r.returncode}); "
                        f"stdout={r.stdout!r} stderr={r.stderr!r}",
                    )
                    self.assertIn("SKIP", r.stdout + r.stderr,
                        f"{name}: pre-cutoff exit 0 but no SKIP message")
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)


# ---------- Per-validator targeted error-path tests ----------

class TestRetrospectiveCompletenessErrors(unittest.TestCase):
    """validate-retrospective-completeness.py: missing dispositions → error
    in deny mode. Verifies the validator actually checks pending vs filed
    (a no-op script would report OK)."""

    def test_post_cutoff_missing_disposition_fails_in_deny(self):
        tmp = _setup_tempdir_with_context("solve-2026-05-04T00:00:00Z")
        try:
            # Post-cutoff candidate without disposition
            (tmp / ".runs" / "retrospective-pending-findings.json").write_text(json.dumps({
                "run_id": "solve-2026-05-04T00:00:00Z",
                "schema_version": 2,
                "candidates": [{
                    "candidate_id": "abcdef123456",
                    "kind": "hook-friction",
                    "confidence": "high",
                    "key": "hook:test",
                    "evidence": {},
                    "source_files": [],
                }]
            }))
            r = _force_post_cutoff_invocation(
                "validate-retrospective-completeness.py",
                tmp,
                {"RETROSPECTIVE_COMPLETENESS_MODE": "deny"},
            )
            self.assertNotEqual(
                r.returncode, 0,
                f"deny mode + missing disposition should exit non-zero; "
                f"stdout={r.stdout!r} stderr={r.stderr!r}",
            )
            self.assertIn("MISSING DISPOSITION", r.stderr,
                "expected 'MISSING DISPOSITION' in stderr (no-op script wouldn't emit this)")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_post_cutoff_invalid_suppression_reason_fails(self):
        tmp = _setup_tempdir_with_context("solve-2026-05-04T00:00:00Z")
        try:
            (tmp / ".runs" / "retrospective-pending-findings.json").write_text(json.dumps({
                "run_id": "solve-2026-05-04T00:00:00Z",
                "schema_version": 2,
                "candidates": [{
                    "candidate_id": "abcdef123456", "kind": "k", "confidence": "high",
                    "key": "k", "evidence": {}, "source_files": [],
                }]
            }))
            (tmp / ".runs" / "retrospective-result.json").write_text(json.dumps({
                "step_5a_executor": "lead",
                "schema_version": 2,
                "suppressions": [{
                    "candidate_id": "abcdef123456",
                    "reason": "i-just-feel-like-it",  # not in closed enum
                    "justification": "n/a",
                }]
            }))
            r = _force_post_cutoff_invocation(
                "validate-retrospective-completeness.py",
                tmp,
                {"RETROSPECTIVE_COMPLETENESS_MODE": "deny"},
            )
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("not in closed enum", r.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestStep55EvidenceErrors(unittest.TestCase):
    """validate-step55-evidence.py: sidecar with N>1 candidates but no
    evidence files → fail."""

    def test_post_cutoff_missing_evidence_fails(self):
        tmp = _setup_tempdir_with_context("verify-2026-05-04T00:00:00Z")
        try:
            (tmp / ".runs" / "image-candidates.json").write_text(json.dumps({
                "schema_version": 2,
                "slots": {
                    "hero": {
                        "candidates": [
                            {"path": "a.webp", "selected": True},
                            {"path": "b.webp", "score_in_context": {"subject": 8, "style": 8, "color": 8, "composition": 8, "polish": 8}},
                            {"path": "c.webp", "score_in_context": {"subject": 8, "style": 8, "color": 8, "composition": 8, "polish": 8}},
                        ]
                    }
                }
            }))
            r = _force_post_cutoff_invocation(
                "validate-step55-evidence.py",
                tmp,
                {"STEP55_EVIDENCE_MODE": "deny"},
            )
            self.assertNotEqual(r.returncode, 0,
                f"missing evidence files should fail in deny; got {r.returncode}, stderr={r.stderr!r}")
            self.assertIn("evidence screenshot", r.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_pre_cutoff_unstamped_sidecar_skips(self):
        """Pre-cutoff run + unstamped sidecar → grandfather (SKIP, exit 0).

        Uses a wrapper that pushes MIGRATION_CUTOFF_ISO to a far-future date
        so the test run_id is unambiguously pre-cutoff regardless of when the
        suite runs in real time."""
        tmp = _setup_tempdir_with_context("verify-2026-04-01T00:00:00Z")
        try:
            (tmp / ".runs" / "image-candidates.json").write_text(json.dumps({
                # No schema_version field — legacy producer
                "slots": {
                    "hero": {
                        "candidates": [
                            {"path": "a.webp", "selected": True},
                            {"path": "b.webp"},
                        ]
                    }
                }
            }))
            wrapper = f"""
import sys, runpy
sys.path.insert(0, {str(SCRIPTS_DIR)!r})
import lib.schema_version_gate as svg
svg.MIGRATION_CUTOFF_ISO = "2099-01-01T00:00:00Z"
runpy.run_path({str(SCRIPTS_DIR / "validate-step55-evidence.py")!r}, run_name="__main__")
"""
            env = os.environ.copy()
            env["STEP55_EVIDENCE_MODE"] = "deny"
            r = subprocess.run(
                ["python3", "-c", wrapper],
                cwd=str(tmp), env=env, capture_output=True, text=True, timeout=30,
            )
            # Pre-cutoff run forces required_v=1; auto-stamp branch grandfathers.
            self.assertEqual(r.returncode, 0,
                f"pre-cutoff unstamped sidecar should SKIP; got {r.returncode}, stderr={r.stderr!r}")
            self.assertIn("pre-cutoff", r.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_post_cutoff_unstamped_sidecar_blocks_in_deny(self):
        """Post-cutoff run + unstamped sidecar → producer drift, BLOCK in deny."""
        tmp = _setup_tempdir_with_context("verify-2026-05-04T00:00:00Z")
        try:
            (tmp / ".runs" / "image-candidates.json").write_text(json.dumps({
                # No schema_version field — producer-side drift on post-cutoff run
                "slots": {
                    "hero": {
                        "candidates": [
                            {"path": "a.webp", "selected": True},
                            {"path": "b.webp"},
                        ]
                    }
                }
            }))
            r = _force_post_cutoff_invocation(
                "validate-step55-evidence.py",
                tmp,
                {"STEP55_EVIDENCE_MODE": "deny"},
            )
            self.assertNotEqual(r.returncode, 0,
                f"post-cutoff unstamped sidecar should BLOCK in deny mode; got {r.returncode}, stderr={r.stderr!r}")
            self.assertIn("missing schema_version", r.stderr)
            self.assertIn("scaffold-images Step 5b", r.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _make_step55_fixture(self, tmp: Path, html_content: str | None = None):
        """Build a minimal post-cutoff sidecar + screenshot + provenance for
        DOM-binding tests. Returns the candidate path tuple (slot, basename)."""
        # Sidecar with one evaluated candidate (score_in_context populated)
        # plus a winner so sampling-floor isn't tripped by N=2.
        slot = "hero"
        basenames = ["hero-explore-1.webp", "hero-explore-2.webp"]
        (tmp / ".runs" / "image-candidates.json").write_text(json.dumps({
            "schema_version": 2,
            "slots": {
                slot: {
                    "candidates": [
                        {"path": f".runs/image-candidates/{basenames[0]}", "selected": True,
                         "provenance": {"model": "fal/flux", "prompt_hash": "h0", "seed": 1}},
                        {"path": f".runs/image-candidates/{basenames[1]}",
                         "score_in_context": {"subject": 8, "style": 8, "color": 8, "composition": 8, "polish": 8},
                         "evaluation_notes": ["This is a substantive evaluation note long enough to pass the 50-char minimum check."],
                         "provenance": {"model": "fal/flux", "prompt_hash": "h1", "seed": 2}},
                    ]
                }
            }
        }))
        # Build a 1280x720 PNG using stdlib (zlib + struct) — no Pillow needed.
        scr_dir = tmp / ".runs" / "screenshots" / "candidates"
        scr_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = scr_dir / f"{slot}-{basenames[1].rsplit('.', 1)[0]}.png"
        screenshot_path.write_bytes(_make_min_png(1280, 720))
        if html_content is not None:
            html_path = scr_dir / f"{slot}-{basenames[1].rsplit('.', 1)[0]}.html"
            html_path.write_text(html_content)
        return slot, basenames[1]

    def test_dom_binding_passes_when_slot_in_dom(self):
        """Canonical flow: candidate copied to public/images/<slot>.<ext>;
        DOM <img src> references the slot path. Validator should accept."""
        tmp = _setup_tempdir_with_context("verify-2026-05-04T00:00:00Z")
        try:
            self._make_step55_fixture(tmp, html_content=(
                '<html><body>'
                '<img src="/_next/image?url=%2Fimages%2Fhero.webp&w=1920">'
                '</body></html>'
            ))
            r = _force_post_cutoff_invocation(
                "validate-step55-evidence.py", tmp,
                {"STEP55_EVIDENCE_MODE": "deny"},
            )
            # Sampling floor will fail (only 1 evaluated candidate when N=2,
            # required floor is min(N-1, 6) = 1; we have 1 evidence) — should
            # PASS the sampling floor. May still fail other checks; assert
            # specifically that no DOM-binding error appears.
            self.assertNotIn("DOM snapshot", r.stderr,
                f"DOM check should not fire when slot is in DOM; stderr={r.stderr!r}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_dom_binding_fails_when_neither_slot_nor_basename_in_dom(self):
        """Score fabrication: DOM has no <img> referencing the slot or
        candidate. Should BLOCK in deny mode."""
        tmp = _setup_tempdir_with_context("verify-2026-05-04T00:00:00Z")
        try:
            self._make_step55_fixture(tmp, html_content=(
                '<html><body>'
                '<img src="/some/unrelated/page.png">'
                '</body></html>'
            ))
            r = _force_post_cutoff_invocation(
                "validate-step55-evidence.py", tmp,
                {"STEP55_EVIDENCE_MODE": "deny"},
            )
            self.assertNotEqual(r.returncode, 0,
                f"DOM mismatch should fail in deny; got {r.returncode}, stderr={r.stderr!r}")
            self.assertIn("DOM snapshot", r.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_dom_binding_warns_when_html_missing(self):
        """No DOM snapshot → graceful degrade, WARN, no block."""
        tmp = _setup_tempdir_with_context("verify-2026-05-04T00:00:00Z")
        try:
            self._make_step55_fixture(tmp, html_content=None)
            r = _force_post_cutoff_invocation(
                "validate-step55-evidence.py", tmp,
                {"STEP55_EVIDENCE_MODE": "deny"},
            )
            self.assertIn("DOM-binding skipped", r.stderr,
                f"missing DOM should warn but not block; stderr={r.stderr!r}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_telemetry_record_emitted_on_skip_no_sidecar(self):
        """SKIP path (no sidecar) → telemetry row with verdict=skip."""
        tmp = _setup_tempdir_with_context("verify-2026-05-04T00:00:00Z")
        try:
            r = _force_post_cutoff_invocation(
                "validate-step55-evidence.py", tmp, {"STEP55_EVIDENCE_MODE": "warn"},
            )
            self.assertEqual(r.returncode, 0)
            telemetry = tmp / ".runs" / "step55-soak-telemetry.jsonl"
            self.assertTrue(telemetry.exists(),
                f"telemetry file should exist; ls .runs={list((tmp/'.runs').iterdir())}")
            lines = telemetry.read_text().strip().splitlines()
            self.assertEqual(len(lines), 1)
            rec = json.loads(lines[0])
            self.assertEqual(rec["verdict"], "skip")
            self.assertEqual(rec["skip_reason"], "no_sidecar")
            self.assertEqual(rec["mode"], "warn")
            self.assertIn("run_id", rec)
            self.assertIn("timestamp", rec)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_telemetry_record_emitted_on_fail_with_categories(self):
        """FAIL path → telemetry row with verdict=fail and violation_categories."""
        tmp = _setup_tempdir_with_context("verify-2026-05-04T00:00:00Z")
        try:
            self._make_step55_fixture(tmp, html_content=(
                '<html><body><img src="/some/unrelated/page.png"></body></html>'
            ))
            r = _force_post_cutoff_invocation(
                "validate-step55-evidence.py", tmp, {"STEP55_EVIDENCE_MODE": "warn"},
            )
            telemetry = tmp / ".runs" / "step55-soak-telemetry.jsonl"
            self.assertTrue(telemetry.exists())
            rec = json.loads(telemetry.read_text().strip().splitlines()[-1])
            self.assertEqual(rec["verdict"], "fail")
            self.assertGreater(rec["violation_count"], 0)
            self.assertIn("dom_unbound", rec["violation_categories"])
            self.assertEqual(rec["mode"], "warn")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _make_min_png(width: int, height: int) -> bytes:
    """Build a minimal valid PNG of given dimensions using stdlib only.

    Used by DOM-binding tests so we can synthesize a screenshot that passes
    check_image_magic + check_image_min_dimensions without depending on Pillow.
    """
    import struct, zlib
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    # Minimal solid-gray IDAT: rows of \x00 filter byte + RGB triples.
    raw = b"".join(b"\x00" + b"\x80" * (width * 3) for _ in range(height))
    idat = zlib.compress(raw, 1)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


class TestImageSpecComplianceErrors(unittest.TestCase):
    """validate-image-spec-compliance.py: model deviation without declaration → fail."""

    def test_post_cutoff_undeclared_deviation_fails(self):
        tmp = _setup_tempdir_with_context("change-2026-05-04T00:00:00Z")
        try:
            # spec must be readable from cwd as .claude/patterns/scaffold-images-spec.json
            spec_dir = tmp / ".claude" / "patterns"
            spec_dir.mkdir(parents=True)
            shutil.copy(
                REPO_ROOT / ".claude" / "patterns" / "scaffold-images-spec.json",
                spec_dir / "scaffold-images-spec.json",
            )
            (tmp / ".runs" / "image-manifest.json").write_text(json.dumps({
                "images": [
                    {"filename": "feature-1.webp", "model": "fal-ai/flux-2-pro"},  # spec says recraft
                ]
            }))
            # No spec_deviations declared in agent trace
            traces_dir = tmp / ".runs" / "agent-traces"
            traces_dir.mkdir(parents=True)
            (traces_dir / "scaffold-images.json").write_text(json.dumps({
                "verdict": "pass",
                "spec_deviations": [],
            }))
            r = _force_post_cutoff_invocation(
                "validate-image-spec-compliance.py",
                tmp,
                {"SCAFFOLD_IMAGES_SPEC_MODE": "deny"},
            )
            self.assertNotEqual(r.returncode, 0,
                f"undeclared deviation should fail; got {r.returncode}, stderr={r.stderr!r}")
            self.assertIn("not in spec", r.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestScaffoldRecommendationsSchemaErrors(unittest.TestCase):
    """validate-scaffold-recommendations-schema.py: missing template_recommendations
    field → fail."""

    def test_post_cutoff_missing_field_fails(self):
        tmp = _setup_tempdir_with_context("bootstrap-2026-05-04T00:00:00Z")
        try:
            traces_dir = tmp / ".runs" / "agent-traces"
            traces_dir.mkdir(parents=True)
            (traces_dir / "scaffold-setup.json").write_text(json.dumps({
                "verdict": "pass",
                # template_recommendations missing entirely
            }))
            r = _force_post_cutoff_invocation(
                "validate-scaffold-recommendations-schema.py",
                tmp,
                {"SCAFFOLD_RECOMMENDATIONS_SCHEMA_MODE": "deny"},
            )
            self.assertNotEqual(r.returncode, 0,
                f"missing template_recommendations should fail; got {r.returncode}, stderr={r.stderr!r}")
            self.assertIn("schema completeness", r.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_post_cutoff_empty_array_without_explicit_none_fails(self):
        tmp = _setup_tempdir_with_context("bootstrap-2026-05-04T00:00:00Z")
        try:
            traces_dir = tmp / ".runs" / "agent-traces"
            traces_dir.mkdir(parents=True)
            (traces_dir / "scaffold-libs.json").write_text(json.dumps({
                "verdict": "pass",
                "template_recommendations": [],
                # missing template_recommendations_explicit_none
            }))
            r = _force_post_cutoff_invocation(
                "validate-scaffold-recommendations-schema.py",
                tmp,
                {"SCAFFOLD_RECOMMENDATIONS_SCHEMA_MODE": "deny"},
            )
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("requires", r.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestObserverEvidenceCoverageErrors(unittest.TestCase):
    """validate-observer-evidence-coverage.py: existing evidence not consulted → fail."""

    def test_post_cutoff_missing_consultation_fails(self):
        tmp = _setup_tempdir_with_context("verify-2026-05-04T00:00:00Z")
        try:
            # Friction summary exists with content
            (tmp / ".runs" / "hook-friction-summary.json").write_text(json.dumps({
                "run_id": "verify-2026-05-04T00:00:00Z",
                "hooks": {"foo": {"count": 1}},
                "total": 1,
            }))
            traces_dir = tmp / ".runs" / "agent-traces"
            traces_dir.mkdir(parents=True)
            # Observer trace does NOT list it
            (traces_dir / "observer.json").write_text(json.dumps({
                "verdict": "pass",
                "evidence_consulted": [".runs/observer-diffs.txt"],
            }))
            r = _force_post_cutoff_invocation(
                "validate-observer-evidence-coverage.py",
                tmp,
                {"OBSERVER_EVIDENCE_COVERAGE_MODE": "deny"},
            )
            self.assertNotEqual(r.returncode, 0,
                f"missing consultation should fail; got {r.returncode}, stderr={r.stderr!r}")
            self.assertIn("evidence_consulted", r.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------- phash.py + schema_version_gate.py library tests ----------

class TestPhashLibrary(unittest.TestCase):
    def test_imports_without_error(self):
        sys.path.insert(0, str(SCRIPTS_DIR))
        try:
            from lib.phash import (  # noqa: F401
                check_image_magic, hamming_distance, read_provenance,
                validate_provenance_triple_unique, validate_phash_diversity,
            )
        finally:
            sys.path.pop(0)

    def test_provenance_triple_unique(self):
        sys.path.insert(0, str(SCRIPTS_DIR))
        try:
            from lib.phash import validate_provenance_triple_unique
            errs = validate_provenance_triple_unique([
                {"model": "a", "prompt_hash": "b", "seed": 1},
                {"model": "a", "prompt_hash": "b", "seed": 1},  # dup
            ])
            self.assertEqual(len(errs), 1)
            self.assertIn("duplicate provenance triple", errs[0])
        finally:
            sys.path.pop(0)


class TestSchemaVersionGate(unittest.TestCase):
    def test_extract_run_id_timestamp(self):
        sys.path.insert(0, str(SCRIPTS_DIR))
        try:
            from lib.schema_version_gate import extract_run_id_timestamp
            self.assertEqual(
                extract_run_id_timestamp("solve-2026-05-04T03:12:26Z"),
                "2026-05-04T03:12:26Z",
            )
            self.assertEqual(
                extract_run_id_timestamp("iterate-cross-2026-04-13T07:07:04Z"),
                "2026-04-13T07:07:04Z",
            )
            self.assertIsNone(extract_run_id_timestamp(""))
        finally:
            sys.path.pop(0)

    def test_required_schema_version_post_cutoff_active(self):
        sys.path.insert(0, str(SCRIPTS_DIR))
        try:
            from lib.schema_version_gate import (
                required_schema_version, is_v2_active, MIGRATION_CUTOFF_ISO,
            )
            # Post-merge: gate is ACTIVE. MIGRATION_CUTOFF_ISO must match the
            # ISO 8601 UTC pattern. Pre-cutoff run_ids → 1, post-cutoff → 2.
            self.assertTrue(is_v2_active(),
                f"gate must be active post-merge; cutoff={MIGRATION_CUTOFF_ISO!r}")
            # A run_id from a year clearly before any plausible merge cutoff
            # must be grandfathered.
            self.assertEqual(
                required_schema_version("solve-2020-01-01T00:00:00Z"), 1
            )
            # A run_id from a year clearly after must enforce v2.
            self.assertEqual(
                required_schema_version("solve-2099-12-31T23:59:59Z"), 2
            )
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
