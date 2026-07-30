#!/usr/bin/env bash
# artifact-integrity-gate.sh — Claude Code PreToolUse hook for Write/Edit.
# Layer 1 of Three-Layer Compliance Architecture.
# Validates JSON schema on agent trace and gate verdict writes.
# Fail-open on parse errors — never blocks on malformed JSON.

set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

FILE_PATH=$(read_payload_field "tool_input.file_path")

# Block direct writes to hook-managed spawn-log
case "$FILE_PATH" in
  *agent-spawn-log.jsonl)
    deny "Artifact integrity gate: agent-spawn-log.jsonl is hook-managed. Cannot be written directly." ;;
esac

# Only fire for agent-traces/*.json and gate-verdicts/*.json
case "$FILE_PATH" in
  *agent-traces/*.json|*gate-verdicts/*.json) ;;
  *) exit 0 ;;
esac

# Skip if no active skill context (normal conversation)
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
shopt -s nullglob
CTX_FILES=("$PROJECT_DIR"/.runs/*-context.json)
shopt -u nullglob
if [[ ${#CTX_FILES[@]} -eq 0 ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

extract_write_content

if [[ -z "$CONTENT" ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# Export file path for Python to classify artifact type
export _ARTIFACT_PATH="$FILE_PATH"

VALIDATION=$(echo "$CONTENT" | python3 -c '
import json, sys, os, re

content = sys.stdin.read().strip()
file_path = os.environ.get("_ARTIFACT_PATH", "")

try:
    d = json.loads(content)
except (json.JSONDecodeError, ValueError):
    print("PARSE_ERROR")
    # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
    sys.exit(0)

if not isinstance(d, dict):
    print("PARSE_ERROR")
    # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
    sys.exit(0)

errors = []

# --- Classify artifact type ---

is_gate_verdict = "gate-verdicts/" in file_path
is_agent_trace = "agent-traces/" in file_path

if is_gate_verdict:
    # Gate verdict schema: gate, verdict, branch, timestamp, checks
    for field in ("gate", "verdict", "branch", "timestamp"):
        if field not in d or not isinstance(d[field], str) or not d[field]:
            errors.append(f"gate verdict missing or empty: {field}")
    if "checks" not in d or not isinstance(d.get("checks"), list):
        errors.append("gate verdict missing checks array")

elif is_agent_trace:
    # Skip full validation for init traces (status: started)
    if d.get("status") == "started":
        for field in ("agent", "status", "timestamp"):
            if field not in d or not isinstance(d[field], str) or not d[field]:
                errors.append(f"init trace missing or empty: {field}")
        if errors:
            print("FAIL:" + "; ".join(errors))
        else:
            print("OK")
        # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
        sys.exit(0)

    # Determine agent category from filename
    basename = os.path.basename(file_path).replace(".json", "")

    # Scaffold and implementer agents — minimal schema (status-based)
    scaffold_prefixes = ("scaffold-", "implementer-", "visual-implementer-")
    is_scaffold = any(basename.startswith(p) for p in scaffold_prefixes)

    # Verdict agents — read from registry
    _reg_path = os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", "."), ".claude/patterns/agent-registry.json")
    try:
        verdict_agents = set(json.load(open(_reg_path)).get("verdict_agents", []))
    except Exception:
        verdict_agents = set()
    # Match by prefix for per-page traces like design-critic-landing
    is_verdict_agent = basename in verdict_agents or any(
        basename.startswith(va + "-") for va in verdict_agents
    )

    if is_scaffold:
        for field in ("agent", "status"):
            if field not in d or not isinstance(d[field], str) or not d[field]:
                errors.append(f"scaffold trace missing or empty: {field}")

    elif is_verdict_agent:
        # Required: agent, timestamp, verdict, checks_performed
        for field in ("agent", "timestamp"):
            if field not in d or not isinstance(d[field], str) or not d[field]:
                errors.append(f"agent trace missing or empty: {field}")

        if "verdict" not in d:
            errors.append("agent trace missing verdict field")
        elif not isinstance(d["verdict"], str):
            errors.append("agent trace verdict must be a string")

        if "checks_performed" not in d:
            errors.append("agent trace missing checks_performed array")
        elif not isinstance(d["checks_performed"], list):
            errors.append("agent trace checks_performed must be an array")
        elif len(d["checks_performed"]) == 0:
            # Allow empty checks_performed when the trace represents a marker
            # rather than direct agent execution. lead-on-behalf is excluded
            # because the lead transcribed the agents reported checks.
            prov = d.get("provenance")
            empty_ok = ("recovery", "self-degraded", "lead-merge", "lead-synthesized", "lead-fix", "lead-orchestrated", "lead-skipped")
            if not d.get("recovery") and prov not in empty_ok:
                errors.append("agent trace checks_performed is empty (set recovery: true or use provenance: self-degraded/recovery/lead-synthesized/lead-fix if exhausted)")

        # run_id: warn but do not block (backward compat)
        if "run_id" not in d or not d.get("run_id"):
            sys.stderr.write("WARNING: agent trace has empty run_id — trace freshness cannot be verified\n")

        # --- Per-provenance schema validation (AOC v1.1: agent-trace lifecycle contract) ---
        # Legacy traces (no provenance field) are accepted here and will be
        # migrated later by scripts/migrate-legacy-traces.py.
        prov = d.get("provenance")
        if prov is not None:
            valid_prov = {
                "self", "self-degraded", "recovery", "lead-merge",
                "lead-on-behalf", "lead-synthesized", "lead-fix",
                # AOC v1.2: post-completion lead-orchestrated re-spawn + audit-only fixer-skip.
                "lead-orchestrated", "lead-skipped",
            }
            if prov not in valid_prov:
                errors.append(f"provenance must be one of {sorted(valid_prov)}; got {prov!r}")
            else:
                # partial flag must be true when provenance != self
                if prov != "self":
                    if not d.get("partial"):
                        errors.append(f"provenance={prov} requires partial:true")
                # self-degraded and recovery both need degraded_reason
                if prov in ("self-degraded", "recovery"):
                    if not d.get("degraded_reason"):
                        errors.append(f"provenance={prov} requires degraded_reason (short cause string)")
                # recovery traces must set the legacy mirror
                if prov == "recovery" and d.get("recovery") is not True:
                    errors.append("provenance=recovery requires recovery:true (legacy mirror)")
                # lead-merge must have contributing_spawn_indexes array
                if prov == "lead-merge":
                    csi = d.get("contributing_spawn_indexes")
                    if not isinstance(csi, list) or len(csi) == 0:
                        errors.append("provenance=lead-merge requires contributing_spawn_indexes (non-empty integer array)")
                    elif not all(isinstance(i, int) for i in csi):
                        errors.append("contributing_spawn_indexes must be integers")
                # AOC v1.1 lead-* provenance fields
                # lead-on-behalf: agent succeeded, lead transcribed; need source attestation
                if prov == "lead-on-behalf":
                    if not d.get("source"):
                        errors.append("provenance=lead-on-behalf requires source (canonical values: agent-returned-text, agent-tool-output)")
                # lead-synthesized: agent never spawned, lead writes consistency marker
                if prov == "lead-synthesized":
                    if not d.get("coverage_provider"):
                        errors.append("provenance=lead-synthesized requires coverage_provider (artifact path or identifier proving coverage)")
                    # Synthesized markers should not claim per-fix changes
                    fixes = d.get("fixes")
                    if isinstance(fixes, list) and len(fixes) > 0:
                        errors.append("provenance=lead-synthesized must not claim fixes — use lead-fix or lead-on-behalf instead")
                # lead-fix: lead self-applied fix in-flight
                if prov == "lead-fix":
                    if d.get("lead_attestation") is not True:
                        errors.append("provenance=lead-fix requires lead_attestation:true")
                # AOC v1.2: lead-orchestrated requires explicit-identity attestation.
                # The agent ran successfully but resolve_active_identity returned
                # empty (post-completion). Lead supplied source_run_id+source_skill;
                # spawn-log presence enforced upstream by the writer R3 validation.
                if prov == "lead-orchestrated":
                    if d.get("lead_attestation") is not True:
                        errors.append("provenance=lead-orchestrated requires lead_attestation:true")
                    if not d.get("source_run_id"):
                        errors.append("provenance=lead-orchestrated requires source_run_id (the original run_id this trace is attributed to)")
                    if not d.get("source_skill"):
                        errors.append("provenance=lead-orchestrated requires source_skill (the original skill this trace is attributed to)")
                # AOC v1.2: lead-skipped is audit-only for fixer sanctioned-skip.
                # No predicate accepts verdict=skipped; this is by design — the
                # trace exists for observability, not for granting pass.
                if prov == "lead-skipped":
                    if d.get("lead_attestation") is not True:
                        errors.append("provenance=lead-skipped requires lead_attestation:true")
                    if not d.get("upstream_evidence_path"):
                        errors.append("provenance=lead-skipped requires upstream_evidence_path (path to upstream merge file with fixer_skipped:true)")
                    if not d.get("reason"):
                        errors.append("provenance=lead-skipped requires reason (canonical value: hard_gate_failure)")
                    if not isinstance(d.get("unresolved_critical"), int):
                        errors.append("provenance=lead-skipped requires unresolved_critical:int (writer-computed from upstream merge)")
                # self traces should not claim partial
                if prov == "self" and d.get("partial") is True:
                    errors.append("provenance=self with partial:true is contradictory — use provenance=self-degraded instead")

        # AOC v1.1 (PR3) granularity gate: every fixes[] entry that is a dict
        # MUST have a non-empty file (or path) field. Defends against the
        # #1048 class of summary entries (e.g., {"symptom":"fixed N issues"}
        # with no file). Mirrors write-fix-ledger.py granularity gate at the
        # trace-write layer (defense in depth — earlier rejection).
        # Loose shape: fixes can be dicts or strings; only dicts are checked.
        # Synthesized markers (provenance=lead-synthesized) are already
        # rejected from claiming fixes above; this guard catches everyone else.
        fixes_for_gate = d.get("fixes")
        if isinstance(fixes_for_gate, list):
            for i, fx in enumerate(fixes_for_gate):
                if not isinstance(fx, dict):
                    continue
                file_val = fx.get("file") or fx.get("path")
                if not file_val:
                    errors.append(
                        f"fixes[{i}] missing required file (AOC v1.1 granularity gate; "
                        "summary entries without a specific file are not accepted in trace writes)"
                    )

    else:
        # Unknown agent type — validate minimal fields only
        if "agent" not in d or not isinstance(d.get("agent"), str):
            errors.append("trace missing agent field")

if errors:
    print("FAIL:" + "; ".join(errors))
else:
    print("OK")
' 2>/dev/null || echo "OK")

handle_validation "$VALIDATION" "Artifact integrity gate" "Fix trace/verdict JSON schema before writing."
exit 0
