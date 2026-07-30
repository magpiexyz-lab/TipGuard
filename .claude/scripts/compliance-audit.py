#!/usr/bin/env python3
"""Layer 2: Cross-Artifact Semantic Consistency Checks.

Part of Three-Layer Compliance Architecture.
Runs deterministic checks that the existing hook system does NOT perform.

Usage:
    python3 .claude/scripts/compliance-audit.py --skill <name> --run-id <id>

Output: .runs/compliance-audit-result.json
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

try:
    PROJECT_DIR = subprocess.check_output(
        ['git', 'rev-parse', '--show-toplevel'],
        stderr=subprocess.DEVNULL
    ).decode().strip()
except Exception:
    PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR", ".")
RUNS_DIR = os.path.join(PROJECT_DIR, ".runs")
REGISTRY_PATH = os.path.join(PROJECT_DIR, ".claude/patterns/state-registry.json")


def _read_skill_states(skill):
    """Read states list from skill.yaml. Handles both flat `states: [...]`
    and modes-qualified structure (iterate, iterate-check, iterate-cross).

    For mode-qualified skill names like 'iterate-check', read the 'check'
    mode's states list from iterate/skill.yaml. For the plain 'iterate' key,
    collect states from all modes.
    """
    # Mode-qualified skill → read parent yaml, look up specific mode.
    # Plain `iterate` maps to the `default` mode only (modes are invoked
    # separately via their own context files: iterate-check, iterate-cross).
    SKILL_DIR_MAP = {
        "iterate-check": ("iterate", "check"),
        "iterate-cross": ("iterate", "cross"),
        "iterate-cross-phase2": ("iterate", "cross-phase2"),
        "iterate":       ("iterate", "default"),
    }
    mode = None
    if skill in SKILL_DIR_MAP:
        dir_name, mode = SKILL_DIR_MAP[skill]
    else:
        dir_name = skill

    skill_yaml = os.path.join(PROJECT_DIR, ".claude/skills", dir_name, "skill.yaml")
    if not os.path.isfile(skill_yaml):
        return []
    text = open(skill_yaml).read()

    # Flat states list at top level
    flat_match = re.search(r'^states:\s*\[([^\]]+)\]', text, re.MULTILINE)
    if flat_match and mode is None:
        return [s.strip().strip('"').strip("'") for s in flat_match.group(1).split(',') if s.strip()]

    # Modes structure. The regex must tolerate intermediate lines (e.g. a
    # `trigger:` line) between `  <mode>:` and `    states: [...]`.
    # Pattern matches a mode header and any following lines at deeper indent
    # up to the next `  <word>:` sibling or EOF, then extracts the first
    # `states: [...]` found within that block.
    if 'modes:' in text:
        if mode is not None:
            # Block extraction: from `  <mode>:` up to next sibling mode at same indent
            block_pat = (
                r'^  %s:\s*\n'  # header line
                r'((?:^    [^\n]*\n)+)'  # body (indented 4 spaces)
                % re.escape(mode)
            )
            bm = re.search(block_pat, text, re.MULTILINE)
            if bm:
                states_match = re.search(r'states:\s*\[([^\]]+)\]', bm.group(1))
                if states_match:
                    return [s.strip().strip('"').strip("'") for s in states_match.group(1).split(',') if s.strip()]
            return []
        # Plain 'iterate' (no mode): collect all modes' states
        collected = []
        for mode_match in re.finditer(r'^  (\w+):\s*\n((?:^    [^\n]*\n)+)', text, re.MULTILINE):
            body = mode_match.group(2)
            states_match = re.search(r'states:\s*\[([^\]]+)\]', body)
            if states_match:
                collected.extend(s.strip().strip('"').strip("'") for s in states_match.group(1).split(',') if s.strip())
        return collected

    return []


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def iso_to_epoch(ts):
    """Parse ISO 8601 timestamp to epoch seconds."""
    try:
        # Handle both with and without Z suffix
        ts = ts.rstrip("Z") + "+00:00"
        dt = datetime.fromisoformat(ts)
        return dt.timestamp()
    except Exception:
        return None


# --- Check (a): Artifact mtime vs trace timestamp ---
def check_artifact_mtime(skill):
    traces = glob.glob(os.path.join(RUNS_DIR, "agent-traces", "*.json"))
    if not traces:
        return {"name": "artifact_mtime", "result": "skip", "detail": "no agent traces found"}

    violations = []
    for path in traces:
        data = load_json(path)
        if not data or "timestamp" not in data:
            continue
        trace_epoch = iso_to_epoch(data["timestamp"])
        if trace_epoch is None:
            continue
        file_mtime = os.path.getmtime(path)
        delta = abs(file_mtime - trace_epoch)
        if delta > 60:
            violations.append(f"{os.path.basename(path)}: mtime delta {delta:.0f}s")

    if violations:
        return {"name": "artifact_mtime", "result": "fail",
                "detail": f"{len(violations)} trace(s) with suspicious mtime: {'; '.join(violations[:3])}"}
    return {"name": "artifact_mtime", "result": "pass", "detail": f"{len(traces)} traces checked"}


# --- Check (b): Fix-log count matching (AOC v1 FLS v1 authoritative) ---
def check_fix_log_count(skill, run_id):
    # AOC v1: .runs/fix-ledger.jsonl is the authoritative per-fix ledger.
    # The ledger is append-only ACROSS runs by design (registered fix-ledger
    # cross-run channel), while the observer evaluates the current run — so
    # the comparison must count only rows whose run_id matches the active run
    # (same defect class as #1417b / #2009; a whole-file count is a
    # guaranteed false anomaly after the first run that ever recorded a fix,
    # and one false anomaly resets audit-sample's decay ladder). Rows without
    # a run_id are legacy/historical (HC2) and excluded from the count.
    # The former fix-log.md prose fallback is gone: lifecycle-finalize
    # Step 2.5 writes the ledger unconditionally, fix-log.md is a
    # whole-history render that cannot be run-scoped, and the old regex no
    # longer matched the current render format anyway.
    ledger_path = os.path.join(RUNS_DIR, "fix-ledger.jsonl")

    if not run_id:
        return {"name": "fix_log_count", "result": "skip",
                "detail": "run_id unavailable — cannot run-scope the fix count"}
    if not os.path.exists(ledger_path):
        return {"name": "fix_log_count", "result": "skip",
                "detail": "no fix-ledger.jsonl; fix-log.md is a whole-history render and cannot be run-scoped"}

    fix_count = 0
    skipped_missing_runid = 0
    other_run_rows = 0
    try:
        with open(ledger_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rid = row.get("run_id")
                if not rid:
                    skipped_missing_runid += 1
                elif rid == run_id:
                    fix_count += 1
                else:
                    other_run_rows += 1
    except OSError:
        return {"name": "fix_log_count", "result": "skip",
                "detail": "cannot read fix-ledger.jsonl"}

    # Find observer trace fixes_evaluated
    observer_path = os.path.join(RUNS_DIR, "agent-traces", "observer.json")
    observer = load_json(observer_path)
    if not observer or "fixes_evaluated" not in observer:
        return {"name": "fix_log_count", "result": "skip",
                "detail": f"ledger has {fix_count} current-run entries but no observer trace with fixes_evaluated"}
    observer_run_id = observer.get("run_id")
    if observer_run_id and observer_run_id != run_id:
        return {"name": "fix_log_count", "result": "skip",
                "detail": f"stale observer trace (run_id {observer_run_id} != active {run_id})"}

    scope_note = (f" (run-scoped; {other_run_rows} prior-run, "
                  f"{skipped_missing_runid} legacy no-run_id rows excluded)")
    observer_count = observer.get("fixes_evaluated", 0)
    if fix_count != observer_count:
        return {"name": "fix_log_count", "result": "fail",
                "detail": f"ledger has {fix_count} current-run entries but observer.fixes_evaluated={observer_count}{scope_note}"}
    return {"name": "fix_log_count", "result": "pass",
            "detail": f"ledger and observer agree: {fix_count} current-run entries{scope_note}"}


# --- Check (c): Behavior claims ---
def check_behavior_claims(skill):
    # No agent currently writes behaviors_checked — skip until agents are extended
    return {"name": "behavior_claims", "result": "skip",
            "detail": "no agent writes behaviors_checked field yet"}


# --- Check (d): checks_performed completeness ---
def check_checks_completeness(skill):
    registry = load_json(REGISTRY_PATH)
    if not registry:
        return {"name": "checks_completeness", "result": "skip",
                "detail": "cannot read state-registry.json"}

    # Read verify agent specs from skill.yaml (v2) or agent_gates (v1 fallback)
    agent_gates = registry.get("agent_gates", {})
    verify_gates = agent_gates.get("verify", {}) if agent_gates else {}
    traces_dir = os.path.join(RUNS_DIR, "agent-traces")
    if not os.path.isdir(traces_dir):
        return {"name": "checks_completeness", "result": "skip",
                "detail": "no agent-traces directory"}

    violations = []
    checked = 0

    for agent_name, spec in verify_gates.items():
        if agent_name.startswith("_"):
            continue
        required = spec.get("required_checks")
        if not required:
            continue

        # Find matching trace file (exact match or prefix match for per-page traces)
        trace_path = os.path.join(traces_dir, f"{agent_name}.json")
        if not os.path.exists(trace_path):
            # Try prefix match for per-page traces (design-critic-landing.json)
            matches = glob.glob(os.path.join(traces_dir, f"{agent_name}*.json"))
            if not matches:
                continue
            # Check all matching traces
            for match_path in matches:
                data = load_json(match_path)
                if not data:
                    continue
                performed = set(data.get("checks_performed", []))
                missing = set(required) - performed
                if missing:
                    violations.append(f"{os.path.basename(match_path)}: missing {sorted(missing)}")
                checked += 1
            continue

        data = load_json(trace_path)
        if not data:
            continue
        # Skip recovery traces — they legitimately have reduced checks
        if data.get("recovery"):
            checked += 1
            continue
        performed = set(data.get("checks_performed", []))
        missing = set(required) - performed
        if missing:
            violations.append(f"{agent_name}: missing {sorted(missing)}")
        checked += 1

    if checked == 0:
        return {"name": "checks_completeness", "result": "skip",
                "detail": "no agent traces with required_checks found"}
    if violations:
        return {"name": "checks_completeness", "result": "fail",
                "detail": f"{len(violations)} agent(s) with incomplete checks: {'; '.join(violations[:3])}"}
    return {"name": "checks_completeness", "result": "pass",
            "detail": f"{checked} agent traces verified against required_checks"}


# --- Check (e): Gate verdict downstream enforcement ---
def check_gate_enforcement(skill):
    verdicts_dir = os.path.join(RUNS_DIR, "gate-verdicts")
    if not os.path.isdir(verdicts_dir):
        return {"name": "gate_enforcement", "result": "skip",
                "detail": "no gate-verdicts directory"}

    verdict_files = glob.glob(os.path.join(verdicts_dir, "*.json"))
    if not verdict_files:
        return {"name": "gate_enforcement", "result": "skip",
                "detail": "no gate verdict files"}

    blocked_gates = []
    for vf in verdict_files:
        data = load_json(vf)
        if data and data.get("verdict") == "BLOCK":
            blocked_gates.append(os.path.basename(vf).replace(".json", ""))

    if not blocked_gates:
        return {"name": "gate_enforcement", "result": "pass",
                "detail": f"no BLOCK verdicts in {len(verdict_files)} gate files"}

    # If there are BLOCK verdicts, check that no downstream states were completed
    context_path = os.path.join(RUNS_DIR, f"{skill}-context.json")
    context = load_json(context_path)
    if not context:
        return {"name": "gate_enforcement", "result": "skip",
                "detail": f"BLOCK found in {blocked_gates} but no context file"}

    completed = set(str(s) for s in context.get("completed_states", []))
    registry = load_json(REGISTRY_PATH)
    if not registry:
        return {"name": "gate_enforcement", "result": "skip",
                "detail": "cannot read state-registry.json for state ordering"}

    required = _read_skill_states(skill)

    # Any BLOCK should mean the skill stopped — check if it actually completed
    if context.get("completed"):
        return {"name": "gate_enforcement", "result": "fail",
                "detail": f"skill marked completed despite BLOCK verdicts: {blocked_gates}"}

    return {"name": "gate_enforcement", "result": "pass",
            "detail": f"BLOCK verdicts {blocked_gates} respected — skill not marked completed"}


# --- Check (f): Missing required states ---
def check_missing_states(skill):
    context_path = os.path.join(RUNS_DIR, f"{skill}-context.json")
    context = load_json(context_path)
    if not context:
        return {"name": "missing_states", "result": "skip",
                "detail": f"no {skill}-context.json"}

    registry = load_json(REGISTRY_PATH)
    if not registry:
        return {"name": "missing_states", "result": "skip",
                "detail": "cannot read state-registry.json"}

    required = _read_skill_states(skill)
    if not required:
        return {"name": "missing_states", "result": "skip",
                "detail": f"no _required_states defined for {skill}"}

    completed = set(str(s) for s in context.get("completed_states", []))
    skip = set(str(s) for s in context.get("skip_states", []))
    required_set = set(required)
    missing = required_set - completed - skip

    if missing:
        # If exactly 1 state missing and it's the last required state,
        # this is the currently-executing epilogue state (audit runs before
        # advance-state marks it complete). Treat as pass.
        if len(missing) == 1 and str(required[-1]) in missing:
            return {"name": "missing_states", "result": "pass",
                    "detail": f"all pre-epilogue states completed ({len(required)-1}/{len(required)}), "
                              f"epilogue state {sorted(missing)[0]} executing"}
        return {"name": "missing_states", "result": "fail",
                "detail": f"missing states: {sorted(missing)} (completed: {sorted(completed)})"}
    return {"name": "missing_states", "result": "pass",
            "detail": f"all {len(required)} required states completed"}


# --- Condition resolver for trace_schemas conditional fields ---

def _is_webapp(trace_data, context_data):
    """Check if archetype is web-app from context or exploration-trace."""
    if context_data and context_data.get("archetype") == "web-app":
        return True
    et = load_json(os.path.join(RUNS_DIR, "exploration-trace.json"))
    return bool(et and et.get("archetype") == "web-app")


def _security_merge_has_issues():
    """Check if security-merge.json reports actual issues."""
    sm = load_json(os.path.join(RUNS_DIR, "security-merge.json"))
    return bool(sm and sm.get("merged_issues", 0) > 0
                and sm.get("source") != "no-security-agents")


def _has_fixes():
    """Check if fix-log.md has fix entries (consistent with check_b's detection)."""
    path = os.path.join(RUNS_DIR, "fix-log.md")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
    return bool(re.search(r"^\*\*Fix \d+\*\*", content, re.MULTILINE))


CONDITION_RESOLVERS = {
    # Phase 1: existing (upgraded to 3-arg)
    "when_full":            lambda t, c, ctx: t and t.get("mode") == "full",
    "when_light":           lambda t, c, ctx: t and t.get("mode") == "light",
    "when_rounds_gt_1":     lambda t, c, ctx: c and c.get("critic_rounds", 0) > 1,
    # Phase 2: change
    "when_solve_depth_full":    lambda t, c, ctx: ctx and ctx.get("solve_depth") == "full",
    "when_archetype_webapp":    lambda t, c, ctx: _is_webapp(t, ctx),
    # Phase 3: verify
    "when_scope_includes_security":         lambda t, c, ctx: ctx and ctx.get("scope") in ("full", "security"),
    "when_scope_includes_visual_and_webapp": lambda t, c, ctx: (
        ctx and ctx.get("scope") in ("full", "visual") and _is_webapp(t, ctx)
    ),
    "when_security_issues_found":           lambda t, c, ctx: _security_merge_has_issues(),
    "when_fixes_applied":                   lambda t, c, ctx: _has_fixes(),
}


def evaluate_condition(cond_key, trace_data, challenge_data, context_data=None):
    """Evaluate a trace_schemas condition key against actual data."""
    resolver = CONDITION_RESOLVERS.get(cond_key)
    return resolver(trace_data, challenge_data, context_data) if resolver else False


# --- Check (g): Trace schema conformance ---
def check_trace_schema_conformance(skill):
    registry = load_json(REGISTRY_PATH)
    if not registry:
        return {"name": "trace_schema_conformance", "result": "skip",
                "detail": "cannot read state-registry.json"}

    schema = registry.get("trace_schemas", {}).get(skill)
    if not schema:
        return {"name": "trace_schema_conformance", "result": "skip",
                "detail": f"no trace_schemas entry for {skill}"}

    violations = []

    # Load context_file for condition resolution
    context_file = schema.get("context_file")
    context_data = load_json(os.path.join(RUNS_DIR, context_file)) if context_file else None

    # Check trace_file fields
    trace_file = schema.get("trace_file")
    trace_data = None
    if trace_file:
        trace_data = load_json(os.path.join(RUNS_DIR, trace_file))
        if not trace_data:
            violations.append(f"{trace_file} missing or not valid JSON")
        else:
            for field in schema.get("required_fields", {}).get("always", []):
                if not trace_data.get(field):
                    violations.append(f"{trace_file}: {field} missing or empty")
            for cond_key, fields in schema.get("required_fields", {}).items():
                if cond_key == "always":
                    continue
                if evaluate_condition(cond_key, trace_data, None, context_data):
                    for field in fields:
                        if not trace_data.get(field):
                            violations.append(f"{trace_file}: {field} missing or empty (required by {cond_key})")

    # Check challenge_file fields
    challenge_file = schema.get("challenge_file")
    challenge_data = None
    if challenge_file:
        challenge_data = load_json(os.path.join(RUNS_DIR, challenge_file))
        if challenge_data:
            for field in schema.get("challenge_fields", {}).get("always", []):
                if field not in challenge_data:
                    violations.append(f"{challenge_file}: {field} missing")
            for cond_key, fields in schema.get("challenge_fields", {}).items():
                if cond_key == "always":
                    continue
                if evaluate_condition(cond_key, trace_data, challenge_data, context_data):
                    for field in fields:
                        if field not in challenge_data:
                            violations.append(f"{challenge_file}: {field} missing (required by {cond_key})")

    # Check extra_trace_files (e.g., exploration-trace.json for change)
    for extra_file, field_spec in schema.get("extra_trace_files", {}).items():
        extra_data = load_json(os.path.join(RUNS_DIR, extra_file))
        if not extra_data:
            violations.append(f"{extra_file} missing or not valid JSON")
        else:
            for field in field_spec.get("always", []):
                if not extra_data.get(field):
                    violations.append(f"{extra_file}: {field} missing or empty")
            for cond_key, fields in field_spec.items():
                if cond_key == "always":
                    continue
                if evaluate_condition(cond_key, trace_data, challenge_data, context_data):
                    for field in fields:
                        if not extra_data.get(field):
                            violations.append(f"{extra_file}: {field} missing or empty (required by {cond_key})")

    if not trace_file and not challenge_file and not schema.get("extra_trace_files"):
        return {"name": "trace_schema_conformance", "result": "skip",
                "detail": f"no trace/challenge/extra files defined for {skill}"}

    if violations:
        return {"name": "trace_schema_conformance", "result": "fail",
                "detail": f"{len(violations)} violation(s): {'; '.join(violations[:5])}"}
    return {"name": "trace_schema_conformance", "result": "pass",
            "detail": f"trace schema verified for {skill}"}


# --- Check (h): Agent trace coverage ---
def check_agent_trace_coverage(skill):
    registry = load_json(REGISTRY_PATH)
    if not registry:
        return {"name": "agent_trace_coverage", "result": "skip",
                "detail": "cannot read state-registry.json"}

    schema = registry.get("trace_schemas", {}).get(skill)
    if not schema:
        return {"name": "agent_trace_coverage", "result": "skip",
                "detail": f"no trace_schemas entry for {skill}"}

    expected = schema.get("expected_agent_traces", {})
    traces_dir = os.path.join(RUNS_DIR, "agent-traces")

    # Load data for condition resolution
    trace_file = schema.get("trace_file")
    trace_data = load_json(os.path.join(RUNS_DIR, trace_file)) if trace_file else None
    challenge_file = schema.get("challenge_file")
    challenge_data = load_json(os.path.join(RUNS_DIR, challenge_file)) if challenge_file else None
    context_file = schema.get("context_file")
    context_data = load_json(os.path.join(RUNS_DIR, context_file)) if context_file else None

    # Resolve exact agents and glob patterns separately
    required_agents = list(expected.get("always", []))
    required_globs = list(expected.get("always_glob", []))

    for cond_key, agents in expected.items():
        if cond_key in ("always", "always_glob"):
            continue
        if cond_key.endswith("_glob"):
            real_key = cond_key[:-5]  # strip "_glob"
            if evaluate_condition(real_key, trace_data, challenge_data, context_data):
                required_globs.extend(agents)
        else:
            if evaluate_condition(cond_key, trace_data, challenge_data, context_data):
                required_agents.extend(agents)

    if not required_agents and not required_globs:
        return {"name": "agent_trace_coverage", "result": "skip",
                "detail": f"no expected agents for {skill} in current mode"}

    # Check exact agents
    missing = [a for a in required_agents
               if not os.path.exists(os.path.join(traces_dir, f"{a}.json"))]

    # Check glob agents (at least 1 match required per pattern)
    missing_globs = []
    for pattern in required_globs:
        matches = glob.glob(os.path.join(traces_dir, f"{pattern}.json"))
        if not matches:
            missing_globs.append(f"{pattern} (0 matches)")

    all_missing = missing + missing_globs
    total_expected = len(required_agents) + len(required_globs)

    if all_missing:
        return {"name": "agent_trace_coverage", "result": "fail",
                "detail": f"missing agent traces: {all_missing}"}
    return {"name": "agent_trace_coverage", "result": "pass",
            "detail": f"{total_expected} expected agent trace(s) verified"}


# --- Cross-check handlers for check (i) ---

def _check_array_vs_trace_count(check_spec, challenge, traces_dir):
    """Verify challenge array length matches agent trace array length."""
    violations = []
    arr = challenge.get(check_spec["challenge_array"], [])
    trace_name = check_spec["trace"]
    trace_path = os.path.join(traces_dir, f"{trace_name}.json")
    trace = load_json(trace_path)
    if trace:
        trace_arr = trace.get(check_spec["trace_field"], [])
        if len(arr) != len(trace_arr):
            violations.append(
                f"{check_spec['challenge_array']} length ({len(arr)}) != "
                f"{trace_name}.{check_spec['trace_field']} length ({len(trace_arr)})")
    return violations


def _check_glob_status(check_spec, challenge, traces_dir):
    """Verify all glob-matched traces have expected status."""
    violations = []
    pattern = check_spec["trace_glob"]
    matches = glob.glob(os.path.join(traces_dir, f"{pattern}.json"))
    min_count = check_spec.get("min_count", 1)
    if len(matches) < min_count:
        if min_count > 0:
            violations.append(f"{pattern}: found {len(matches)}, need >= {min_count}")
        return violations
    for path in matches:
        data = load_json(path)
        if data:
            actual = data.get(check_spec["status_field"])
            expected = check_spec["expected_status"]
            if actual != expected:
                violations.append(
                    f"{os.path.basename(path)}: {check_spec['status_field']}="
                    f"{actual}, expected {expected}")
    return violations


def _check_all_agents_traced(check_spec, challenge, traces_dir):
    """Verify all agent traces completed (not just started).

    Accepts verdict, checks_performed, or status as completion indicators
    since different agent types use different fields.
    """
    violations = []
    if not os.path.isdir(traces_dir):
        return violations
    for path in glob.glob(os.path.join(traces_dir, "*.json")):
        data = load_json(path)
        if not data or data.get("recovery"):
            continue
        has_completion = (
            "verdict" in data
            or "checks_performed" in data
            or "status" in data
        )
        if not has_completion:
            violations.append(f"{os.path.basename(path)}: started but no completion indicator")
    return violations


CROSS_CHECK_HANDLERS = {
    "array_vs_trace_count": _check_array_vs_trace_count,
    "glob_status_check": _check_glob_status,
    "all_agents_traced": _check_all_agents_traced,
}


# --- Check (i): Cross-artifact count consistency ---
def check_cross_artifact_counts(skill):
    registry = load_json(REGISTRY_PATH)
    if not registry:
        return {"name": "cross_artifact_counts", "result": "skip",
                "detail": "cannot read state-registry.json"}

    schema = registry.get("trace_schemas", {}).get(skill)
    if not schema:
        return {"name": "cross_artifact_counts", "result": "skip",
                "detail": f"no trace_schemas entry for {skill}"}

    violations = []
    traces_dir = os.path.join(RUNS_DIR, "agent-traces")

    # Existing critic cross-check (runs whenever challenge_file has critic_rounds)
    challenge_file = schema.get("challenge_file")
    challenge = load_json(os.path.join(RUNS_DIR, challenge_file)) if challenge_file else None

    if challenge and challenge.get("critic_rounds") is not None:
        critic_path = os.path.join(traces_dir, "solve-critic.json")
        critic = load_json(critic_path)
        if critic:
            trace_round = critic.get("round")
            challenge_rounds = challenge.get("critic_rounds")
            if trace_round is not None and trace_round != challenge_rounds:
                violations.append(
                    f"critic_rounds mismatch: challenge={challenge_rounds}, trace round={trace_round}")

            if trace_round == 1:
                r1_ta = challenge.get("round_1_type_a_count")
                if r1_ta is not None and critic.get("type_a_count") is not None:
                    if r1_ta != critic["type_a_count"]:
                        violations.append(
                            f"round_1_type_a_count mismatch: challenge={r1_ta}, trace={critic['type_a_count']}")
            elif trace_round == 2:
                r2_ta = challenge.get("round_2_type_a_count")
                if r2_ta is not None and critic.get("type_a_count") is not None:
                    if r2_ta != critic["type_a_count"]:
                        violations.append(
                            f"round_2_type_a_count mismatch: challenge={r2_ta}, trace={critic['type_a_count']}")

            concerns = critic.get("concerns", [])
            ta = critic.get("type_a_count", 0)
            tb = critic.get("type_b_count", 0)
            tc = critic.get("type_c_count", 0)
            if len(concerns) != ta + tb + tc:
                violations.append(
                    f"concerns count={len(concerns)} != type_a({ta})+type_b({tb})+type_c({tc})")

    # Dispatch cross_checks from schema
    for check_spec in schema.get("cross_checks", []):
        handler = CROSS_CHECK_HANDLERS.get(check_spec.get("type"))
        if handler:
            violations.extend(handler(check_spec, challenge or {}, traces_dir))

    has_checks = challenge_file or schema.get("cross_checks")
    if not has_checks:
        return {"name": "cross_artifact_counts", "result": "skip",
                "detail": f"no challenge_file or cross_checks for {skill}"}

    if violations:
        return {"name": "cross_artifact_counts", "result": "fail",
                "detail": f"{len(violations)} mismatch(es): {'; '.join(violations)}"}
    return {"name": "cross_artifact_counts", "result": "pass",
            "detail": f"cross-artifact counts consistent for {skill}"}


# --- Check (k): Q2 evidence completeness (closes #1226) ---
def check_q2_evidence_complete(skill, run_id):
    """When hook-friction.jsonl has rows for the current run_id, the Q2
    retrospective MUST have access to its 4th evidence channel:

      1. .runs/hook-friction-summary.json must exist (produced by
         aggregate-hook-friction.py — now invoked by lifecycle-finalize.sh).
      2. retrospective-result.json.process_compliance MUST NOT be a
         literal 'clean' / 'Clean' when friction events for this run exist —
         a clean verdict with friction is suspicious per #1226's symptom.

    Skips when:
      - hook-friction.jsonl is absent or has no rows for current run_id
        (legitimate friction-free run).
      - retrospective-result.json is absent (Step 5a was scope-skipped per
        observation-phase.md scope gate; not this check's responsibility).

    Schema-aware: process_compliance can be a string OR list OR object.
      - string: lower-compare against {'clean', ''}.
      - list: empty list = clean.
      - object: read .verdict subfield (lower-compare).
    """
    name = "q2_evidence_complete"
    friction_path = os.path.join(RUNS_DIR, "hook-friction.jsonl")
    if not os.path.isfile(friction_path) or os.path.getsize(friction_path) == 0:
        return {"name": name, "result": "skip",
                "detail": "no hook-friction.jsonl rows for run"}

    # Filter friction events by run_id — only count rows belonging to current run.
    run_rows = 0
    try:
        with open(friction_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("run_id") == run_id:
                    run_rows += 1
    except Exception as exc:
        return {"name": name, "result": "skip",
                "detail": f"unreadable hook-friction.jsonl: {exc}"}

    if run_rows == 0:
        return {"name": name, "result": "skip",
                "detail": "no hook-friction.jsonl rows for this run_id"}

    failures = []
    summary_path = os.path.join(RUNS_DIR, "hook-friction-summary.json")
    if not os.path.isfile(summary_path):
        failures.append(
            f"hook-friction-summary.json missing despite {run_rows} run-scoped friction event(s) "
            f"— aggregate-hook-friction.py did not run (lifecycle-finalize.sh Step 2.6 first pass; "
            f"observation-phase.md Step 2d tail refresh)"
        )

    retro_path = os.path.join(RUNS_DIR, "retrospective-result.json")
    if os.path.isfile(retro_path):
        retro = load_json(retro_path) or {}
        pc = retro.get("process_compliance")

        def _is_clean(value):
            if isinstance(value, str):
                return value.strip().lower() in ("", "clean")
            if isinstance(value, list):
                return len(value) == 0
            if isinstance(value, dict):
                v = value.get("verdict")
                if isinstance(v, str):
                    return v.strip().lower() in ("", "clean")
                return False
            return False

        if pc is not None and _is_clean(pc):
            failures.append(
                f"retrospective-result.json.process_compliance is 'clean' but {run_rows} "
                f"run-scoped hook-friction event(s) recorded — Q2 retrospective should "
                f"address them (false-clean retrospective per #1226)"
            )

    if failures:
        return {"name": name, "result": "fail",
                "detail": "; ".join(failures)}
    return {"name": name, "result": "pass",
            "detail": f"{run_rows} friction event(s) acknowledged by Q2 evidence channel"}


# --- Check (j): Lead-deliverable compliance (closes #1152) ---
def check_lead_deliverable_compliance(skill):
    """For each artifact in lead-only-artifacts.json that exists at audit-time,
    verify its declared executor field is set to 'lead'. For
    retrospective-result.json specifically, also verify the observation-evidence
    sibling exists (split-deliverable invariant).

    Skips when no lead-only artifact is present (acceptable on the fast-path:
    /solve and other process-scope skills may write neither file when execution
    was friction-free).
    """
    name = "lead_deliverable_compliance"
    manifest_path = os.path.join(REGISTRY_PATH.rsplit("/", 1)[0], "lead-only-artifacts.json")
    if not os.path.isfile(manifest_path):
        return {"name": name, "result": "skip",
                "detail": "lead-only-artifacts.json not present"}
    manifest = load_json(manifest_path)
    if not manifest:
        return {"name": name, "result": "skip",
                "detail": "lead-only-artifacts.json unreadable"}

    failures = []
    checked = 0
    for entry in manifest.get("artifacts", []):
        path = entry.get("path", "")
        executor_field = entry.get("executor_field", "")
        if not path or not executor_field:
            continue
        # Resolve relative to project root (RUNS_DIR is .runs under project)
        if path.startswith(".runs/"):
            full = os.path.join(os.path.dirname(RUNS_DIR), path)
        else:
            full = path
        if not os.path.isfile(full):
            continue
        checked += 1
        try:
            d = json.load(open(full))
        except Exception as e:
            failures.append(f"{path}: unreadable ({e})")
            continue
        v = d.get(executor_field)
        if v != "lead":
            failures.append(f"{path}: {executor_field}={v!r} (must be 'lead')")
            continue
        # Special-case: retrospective-result.json requires observation-evidence sibling
        if path.endswith("retrospective-result.json"):
            sibling = os.path.join(RUNS_DIR, "observation-evidence.json")
            if not os.path.isfile(sibling):
                failures.append(
                    f"{path} present but observation-evidence.json missing "
                    f"(split-deliverable invariant — observer collects evidence, "
                    f"lead writes interpretation)")

    if checked == 0:
        return {"name": name, "result": "skip",
                "detail": "no lead-only artifacts present at audit time"}
    if failures:
        return {"name": name, "result": "fail",
                "detail": "; ".join(failures)}
    return {"name": name, "result": "pass",
            "detail": f"{checked} lead-only artifact(s) verified"}


def main():
    parser = argparse.ArgumentParser(description="Layer 2: Cross-artifact semantic consistency")
    parser.add_argument("--skill", required=True, help="Skill name")
    parser.add_argument("--run-id", required=True, help="Run ID from context")
    args = parser.parse_args()

    checks = [
        check_artifact_mtime(args.skill),
        check_fix_log_count(args.skill, args.run_id),
        check_behavior_claims(args.skill),
        check_checks_completeness(args.skill),
        check_gate_enforcement(args.skill),
        check_missing_states(args.skill),
        check_trace_schema_conformance(args.skill),
        check_agent_trace_coverage(args.skill),
        check_cross_artifact_counts(args.skill),
        check_lead_deliverable_compliance(args.skill),
        check_q2_evidence_complete(args.skill, args.run_id),
    ]

    anomaly_count = sum(1 for c in checks if c["result"] == "fail")
    overall = "fail" if anomaly_count > 0 else "pass"

    result = {
        "skill": args.skill,
        "run_id": args.run_id,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checks": checks,
        "overall": overall,
        "anomaly_count": anomaly_count,
    }

    os.makedirs(RUNS_DIR, exist_ok=True)
    with open(os.path.join(RUNS_DIR, "compliance-audit-result.json"), "w") as f:
        json.dump(result, f, indent=2)
        f.write("\n")

    # Summary to stdout
    passed = sum(1 for c in checks if c["result"] == "pass")
    skipped = sum(1 for c in checks if c["result"] == "skip")
    print(f"Compliance audit: {overall} ({passed} pass, {anomaly_count} fail, {skipped} skip)")

    if anomaly_count > 0:
        for c in checks:
            if c["result"] == "fail":
                print(f"  FAIL: {c['name']} — {c['detail']}", file=sys.stderr)


if __name__ == "__main__":
    main()
