#!/usr/bin/env python3
"""Augment an existing agent trace with whitelisted metadata fields.

Replaces the inline `python -c "...json.dump(d, open(f, 'w'))..."` augmenter
pattern used today by design-critic.md (per-page metadata enrichment) and
similar scaffolding. The inline pattern is blocked by
agent-trace-write-guard.sh's chained-segment check (#1064 D1).

This script is INTENTIONALLY narrow: it only allows adding a small set of
known descriptive fields to a completed trace. It does NOT permit changing
identity (agent / run_id / skill), authorship (provenance / status / verdict),
or correctness markers (partial / recovery_validated / spawn_sha / spawn_index).
This narrow scope was chosen over a generic init-trace.py --update mode to
avoid opening a forgery surface (Round 2 critic concern in solve-trace.json).

Usage:
    python3 .claude/scripts/augment-trace.py \\
        --agent <agent-name> \\
        --augment-spawn-index <N> \\
        --field <key>=<value> [--field <key>=<value> ...] \\
        [--trace-filename <name>.json]

Args:
    --agent              Required. Agent base name (matches spawn-log entry).
    --augment-spawn-index Required. The spawn_index from agent-spawn-log.jsonl
                         that this augmentation belongs to. The script verifies
                         the spawn-log has a matching entry (agent + run_id +
                         spawn_index) before writing. This prevents augmenting
                         traces of agents that were never actually spawned.
    --field key=value    Repeatable. Field/value pairs to merge into the trace.
                         Only keys in ALLOWED_AUGMENT_FIELDS are accepted.
                         Values may be JSON literals (e.g., 'page=landing',
                         'candidates_tried=3', 'pages_reviewed=["a","b"]').
    --trace-filename     Optional. Defaults to "<agent>.json"; per-page traces
                         pass e.g. "design-critic-landing.json".

Idempotent: re-running with the same args produces the same trace. Existing
field values are overwritten (last-writer-wins).

Atomic write: tempfile + os.rename().

Allowed fields (whitelist):
    page                 — design-critic per-page identifier
    candidates_tried     — design-critic per-page candidate count
    image_issues_for_landing — design-critic per-page image issues
    pages_reviewed       — design-critic / accessibility-scanner aggregate
    per_page_reviews     — accessibility-scanner per-page array
    per_step_reviews     — ux-journeyer per-step array
    per_behavior_reviews — behavior-verifier per-behavior array
    review_method        — design-critic / reviewer agents
    review_evidence      — design-critic / reviewer agents
    caveat               — design-critic / ux-journeyer caveat field
    review_method_gate_evaluated  — review-verdict-gate sentinel
    review_method_gate_corrections — review-verdict-gate corrections array
    fixes_evaluated      — observer aggregate count
    files_collected      — build-info-collector count
    inconsistencies      — design-consistency-checker structured findings
    findings             — security-attacker / security-defender structured findings
    inconsistent_count   — count_summary scanner field
    findings_count       — count_summary scanner field
    fails_count          — count_summary scanner field
    warnings_count       — count_summary scanner field
    violations_count     — count_summary scanner field
    type_a_count, type_b_count, type_c_count — solve-critic count fields
    confirmed_count, disputed_count — challenger count fields
    saved, skipped, total — pattern-classifier count fields
    unmatched_given_phrase — behavior-verifier diagnostic

Adding a new allowed field: append to ALLOWED_AUGMENT_FIELDS below.
NEVER add identity / authorship / correctness markers — those go through
the dedicated writers (init-trace.py for status/identity, write-agent-trace.sh
for provenance, validate-recovery.sh for recovery_validated).

Exit codes:
    0 — augmentation written
    1 — input or precondition error (missing args, no spawn-log match, etc.)
    2 — payload / value parse error
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone


# Whitelist of fields callers may set via --field.
# This is the entire forgery defense — keep it short and specific.
ALLOWED_AUGMENT_FIELDS = {
    # design-critic per-page metadata
    "page",
    "candidates_tried",
    "image_issues_for_landing",
    "pages_reviewed",
    # reviewer agent shared fields
    "review_method",
    "review_evidence",
    "caveat",
    "review_method_gate_evaluated",
    "review_method_gate_corrections",
    # accessibility-scanner runtime path
    "per_page_reviews",
    # ux-journeyer
    "per_step_reviews",
    # behavior-verifier
    "per_behavior_reviews",
    "unmatched_given_phrase",
    # observer / build-info-collector
    "fixes_evaluated",
    "files_collected",
    # design-consistency-checker
    "inconsistencies",
    "inconsistent_count",
    # security-attacker / security-defender
    "findings",
    "findings_count",
    "fails_count",
    # performance-reporter
    "warnings_count",
    # accessibility-scanner counts
    "violations_count",
    # solve-critic
    "type_a_count",
    "type_b_count",
    "type_c_count",
    "concerns",
    "round",
    # solve-critic — RMG v2 Phase D + cutover
    "prior_failure_dossier_evaluated",
    # challenger counts
    "confirmed_count",
    "disputed_count",
    "verdicts",
    # pattern-classifier
    "saved",
    "skipped",
    "total",
}

# Fields the script PROTECTS — augment-trace.py refuses to touch these even
# if a future maintainer adds them to ALLOWED_AUGMENT_FIELDS by mistake.
PROTECTED_FIELDS = {
    "agent",
    "status",
    "verdict",
    "result",
    "provenance",
    "partial",
    "run_id",
    "skill",
    "spawn_sha",
    "spawn_index",
    "recovery_validated",
    "recovery",
    "recovery_reason",
    "lead_attestation",
    "degraded_reason",
    "source",
    "coverage_provider",
    "contributing_spawn_indexes",
    "no_fixes_claimed",
    "fixes",
    "checks_performed",
    "timestamp",
}


def parse_field_value(raw: str):
    """Try JSON parse; fall back to literal string."""
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Augment an existing agent trace with whitelisted descriptive fields.",
    )
    parser.add_argument("--agent", required=True, help="agent base name")
    parser.add_argument(
        "--augment-spawn-index",
        type=int,
        default=None,
        help="optional: spawn_index from agent-spawn-log.jsonl. When provided, the script "
             "verifies an entry with this exact spawn_index exists for the agent+run_id. "
             "When omitted, accepts ANY spawn-log entry matching agent+run_id — used when "
             "the agent does not know its specific spawn_index (e.g., per-page parallel "
             "spawns of the same agent in design-critic). Forgery defense: skill-agent-gate "
             "is the only writer of agent-spawn-log.jsonl, so requiring at least one matching "
             "entry proves the Agent tool was actually invoked for this agent in this run.",
    )
    parser.add_argument(
        "--field",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="repeatable; KEY must be in ALLOWED_AUGMENT_FIELDS",
    )
    parser.add_argument(
        "--trace-filename",
        default="",
        help="defaults to <agent>.json; pass e.g. design-critic-landing.json for per-page traces",
    )
    # AOC v1.2: post-completion lead-orchestrated re-spawn override.
    parser.add_argument(
        "--source-run-id", default="",
        help="explicit run_id override for post-completion augmentation (when the inline "
             "scan returns empty because all *-context.json have completed:true). Must be "
             "supplied with --source-skill (R1 xor).",
    )
    parser.add_argument(
        "--source-skill", default="",
        help="explicit skill paired with --source-run-id (AOC v1.2).",
    )
    args = parser.parse_args()

    # AOC v1.2: validate source-identity flags before continuing.
    if args.source_run_id or args.source_skill:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
        from source_identity_validator import validate_source_identity  # noqa: E402
        errs = validate_source_identity(
            args.source_run_id or None,
            args.source_skill or None,
            agent=args.agent,
        )
        if errs:
            for e in errs:
                sys.stderr.write(f"ERROR: augment-trace.py — {e}\n")
            return 1

    if not args.field:
        sys.stderr.write("ERROR: augment-trace.py — at least one --field key=value is required\n")
        return 1

    fields = {}
    for raw in args.field:
        if "=" not in raw:
            sys.stderr.write(f"ERROR: augment-trace.py — --field {raw!r} is not in KEY=VALUE form\n")
            return 1
        key, _, value = raw.partition("=")
        key = key.strip()
        if key in PROTECTED_FIELDS:
            sys.stderr.write(
                f"ERROR: augment-trace.py — field {key!r} is protected and cannot be augmented; "
                "use the dedicated writer (write-agent-trace.sh / init-trace.py / validate-recovery.sh)\n"
            )
            return 1
        if key not in ALLOWED_AUGMENT_FIELDS:
            sys.stderr.write(
                f"ERROR: augment-trace.py — field {key!r} is not in ALLOWED_AUGMENT_FIELDS; "
                "if a new descriptive field is genuinely needed, extend the whitelist in this script\n"
            )
            return 1
        fields[key] = parse_field_value(value)

    # Resolve active identity for spawn-log lookup
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    os.chdir(project_dir)

    # AOC v1.2: when source flags supplied, bypass the inline identity scan
    # (post-completion scenario where all *-context.json have completed:true).
    # Validator already enforced R1-R4 above (including R3 spawn-log presence).
    if args.source_run_id and args.source_skill:
        active_run_id = args.source_run_id
    else:
        # Read active run_id from any non-completed *-context.json (mirrors lib-state.sh)
        import glob

        active_run_id = ""
        best_ts = ""
        for f in glob.glob(".runs/*-context.json"):
            if f.endswith("/epilogue-context.json"):
                continue
            try:
                ctx = json.load(open(f))
            except Exception:
                continue
            if ctx.get("completed") is True:
                continue
            ts = ctx.get("timestamp", "") or ""
            if ts >= best_ts:
                best_ts = ts
                active_run_id = ctx.get("run_id", "")

        if not active_run_id:
            sys.stderr.write(
                "ERROR: augment-trace.py — no active skill context on current branch; cannot resolve run_id\n"
            )
            sys.stderr.write(
                "  Hint: under post-completion conditions, supply --source-run-id and --source-skill (AOC v1.2).\n"
            )
            return 1

    # Spawn-log lookup: must find an entry matching (agent, run_id, spawn_index)
    spawn_log_path = ".runs/agent-spawn-log.jsonl"
    if not os.path.isfile(spawn_log_path):
        sys.stderr.write(
            f"ERROR: augment-trace.py — spawn-log not found at {spawn_log_path}; "
            "cannot validate augmentation provenance\n"
        )
        return 1

    matched = False
    with open(spawn_log_path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if (
                e.get("agent") == args.agent
                and e.get("run_id") == active_run_id
                and e.get("hook") == "skill-agent-gate"
            ):
                # When --augment-spawn-index is supplied, require exact match.
                # When omitted, any entry matching agent+run_id satisfies the
                # forgery check (the agent really was spawned in this run).
                if args.augment_spawn_index is None or e.get("spawn_index") == args.augment_spawn_index:
                    matched = True
                    break

    if not matched:
        idx_clause = (
            f" spawn_index={args.augment_spawn_index}"
            if args.augment_spawn_index is not None else ""
        )
        sys.stderr.write(
            f"ERROR: augment-trace.py — no spawn-log entry for agent={args.agent!r} "
            f"run_id={active_run_id!r}{idx_clause}; "
            "augmentation refused (the agent was never spawned in this run)\n"
        )
        return 1

    # Locate target trace
    out_dir = ".runs/agent-traces"
    out_filename = args.trace_filename or f"{args.agent}.json"
    out_path = os.path.join(out_dir, out_filename)
    if not os.path.isfile(out_path):
        sys.stderr.write(
            f"ERROR: augment-trace.py — target trace {out_path} does not exist; "
            "augment can only enrich existing traces, not create new ones\n"
        )
        return 1

    try:
        trace = json.load(open(out_path))
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"ERROR: augment-trace.py — cannot parse trace {out_path}: {exc}\n")
        return 2

    # Defensive: trace.agent must match (or start with agent for per-page) — the
    # spawn-log already proved the agent really ran in this run.
    trace_agent = trace.get("agent", "")
    if trace_agent != args.agent and not trace_agent.startswith(args.agent + "-"):
        sys.stderr.write(
            f"ERROR: augment-trace.py — trace.agent={trace_agent!r} does not match {args.agent!r}\n"
        )
        return 1

    # Apply augmentation (last-writer-wins on whitelisted fields).
    for k, v in fields.items():
        trace[k] = v

    # Stamp augmentation timestamp for audit; this is itself a whitelisted-style
    # marker, but it's owned by the script (not exposed via --field).
    audit_entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fields": sorted(fields.keys()),
    }
    if args.augment_spawn_index is not None:
        audit_entry["spawn_index"] = args.augment_spawn_index
    existing_audit = trace.get("augmented_at")
    if isinstance(existing_audit, list):
        existing_audit.append(audit_entry)
    else:
        trace["augmented_at"] = [audit_entry]

    # Atomic write
    fd, tmp_path = tempfile.mkstemp(prefix=".augment-trace-", dir=out_dir)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(trace, f, indent=2)
            f.write("\n")
        os.rename(tmp_path, out_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    sys.stderr.write(
        f"augment-trace.py: augmented {out_path} fields={sorted(fields.keys())} "
        f"spawn_index={args.augment_spawn_index}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
