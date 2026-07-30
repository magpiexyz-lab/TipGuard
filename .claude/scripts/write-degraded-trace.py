#!/usr/bin/env python3
"""Write a self-degraded completion trace when an agent self-detects partial completion.

This is the agent-side counterpart to write-recovery-trace.sh. An agent calls
this helper when it hits a predictable failure mode mid-pipeline (image-limit,
screenshot crash, turn-budget near-exhaustion, tool unavailable) and wants to
report partial results truthfully rather than crashing silently.

Difference from recovery:
  - self-degraded: agent self-reports — provenance=self-degraded (issue #958)
  - recovery: orchestrator reconstructs after agent crashed (issue #963)
  Downstream gates treat both as partial outcomes requiring recovery_validated.

Usage:
    python3 scripts/write-degraded-trace.py <agent-name> \\
        --reason "<specific cause>" \\
        --checks-performed "<check1>,<check2>,..." \\
        [--verdict degraded] \\
        [--fixes-json '[{"file": "...", "type": "..."}]'] \\
        [--extra-json '{"inconsistencies": [...], "findings": [...]}'] \\
        [--trace-filename <name>.json]

Args:
    agent-name         Required. E.g. "design-critic"
    --reason           Required. Short specific cause string.
    --checks-performed Required. Comma-separated list of checks that DID run.
    --verdict          Optional. Defaults to "degraded". Some agents may claim
                       "fail" with partial data.
    --fixes-json       Optional. JSON array of {file, ...} entries the agent
                       claims it actually applied. Enables diff-fix correlation
                       at validate-recovery.sh time.
    --extra-json       Optional. JSON object merged into the written trace
                       BEFORE the atomic write. Allows agents to attach
                       domain-specific evidence (review_method, review_evidence,
                       source_review_verdict, image_issues_for_landing,
                       inconsistencies, findings, etc.) alongside canonical
                       trace fields without re-opening the trace file
                       (which would be blocked by agent-trace-write-guard.sh).
                       Existing canonical keys are NOT overwritten — protected
                       fields (agent, timestamp, status, verdict, provenance,
                       partial, checks_performed, degraded_reason, run_id,
                       skill, spawn_sha, spawn_index, fixes, no_fixes_claimed,
                       recovery_validated, recovery) are not overridable; an
                       attempt to override emits a WARN and drops the key.
                       Example for design-consistency-checker:
                         --extra-json '{"inconsistencies": [{"id":"C4-1",...}]}'
                       Downstream merges (state-3d-quality-fix.md, merge scripts)
                       can read these fields from degraded traces instead of
                       silently dropping them. (Fix #1075.)
    --trace-filename   Optional. Defaults to "<agent-name>.json". Use for
                       per-page traces: "design-critic-landing.json".

Writes: .runs/agent-traces/<trace-filename>
Schema: per agent-trace-protocol.md with provenance=self-degraded, partial=true.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a self-degraded agent trace")
    parser.add_argument("agent", help="agent name")
    parser.add_argument("--reason", required=True, help="short specific cause")
    parser.add_argument("--checks-performed", required=True,
                        help="comma-separated list of checks completed")
    parser.add_argument("--verdict", default="degraded",
                        help="verdict string (default: degraded)")
    parser.add_argument("--fixes-json", default="",
                        help="JSON array of fix entries (optional)")
    parser.add_argument("--extra-json", default="",
                        help="JSON object merged into the written trace; "
                             "agent-specific structured fields are preserved; "
                             "protected fields cannot be overridden")
    parser.add_argument("--trace-filename", default="",
                        help="override output filename")
    parser.add_argument("--spawn-index", type=int, default=None,
                        help="override spawn-log lookup spawn_index for parallel spawns "
                             "of the same agent type (e.g., scaffold-pages-home / "
                             "scaffold-pages-pricing). When omitted, first-match semantics "
                             "are preserved (single-spawn agents).")
    # AOC v1.2: post-completion lead-orchestrated re-spawn.
    parser.add_argument("--source-run-id", default="",
                        help="explicit run_id override for post-completion lead-orchestrated "
                             "re-spawn (when resolve_active_identity returns empty). "
                             "Must be supplied together with --source-skill (R1 xor). "
                             "Stamps provenance=lead-orchestrated.")
    parser.add_argument("--source-skill", default="",
                        help="explicit skill override paired with --source-run-id.")
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
                print(f"ERROR: write-degraded-trace.py — {e}", file=sys.stderr)
            return 1

    if args.spawn_index is not None and args.spawn_index < 0:
        print("ERROR: write-degraded-trace.py — --spawn-index must be a non-negative integer",
              file=sys.stderr)
        return 1

    # AOC v1.2: when source flags supplied, bypass resolve_active_identity
    # (post-completion scenario). Validator already enforced R1-R4 above.
    if args.source_run_id and args.source_skill:
        active_skill = args.source_skill
        active_run_id = args.source_run_id
        provenance = "lead-orchestrated"
    else:
        provenance = "self-degraded"
        # Resolve active identity via the shell helper (single source of truth).
        # We shell out because the helper is in bash.
        try:
            out = subprocess.check_output(
                ["bash", "-c",
                 "source .claude/hooks/lib.sh && resolve_active_identity"],
                text=True, stderr=subprocess.DEVNULL).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            out = ""
        if not out:
            print("ERROR: write-degraded-trace.py — no active skill context on current branch",
                  file=sys.stderr)
            print("  Hint: under post-completion conditions, supply --source-run-id and --source-skill.",
                  file=sys.stderr)
            return 1
        parts = out.split("\t")
        while len(parts) < 4:
            parts.append("")
        active_skill, active_run_id, _active_attr, _ = parts[:4]
        if not active_run_id:
            print("ERROR: write-degraded-trace.py — active context has empty run_id",
                  file=sys.stderr)
            return 1

    # Look up spawn-log entry for this agent in current run_id to inherit spawn_sha.
    # When --spawn-index <N> is supplied: require an exact match on spawn_index too.
    # This disambiguates parallel spawns of the same agent type. Without the override
    # the loop falls back to first-match semantics — preserves single-spawn agents
    # and existing migrated callers.
    spawn_log = ".runs/agent-spawn-log.jsonl"
    spawn_sha = ""
    spawn_index = None
    if os.path.isfile(spawn_log):
        with open(spawn_log) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if not (e.get("agent") == args.agent
                        and e.get("run_id") == active_run_id
                        and e.get("hook") == "skill-agent-gate"):
                    continue
                if args.spawn_index is not None and e.get("spawn_index") != args.spawn_index:
                    continue
                spawn_sha = e.get("head_sha", "")
                spawn_index = e.get("spawn_index")
                break

    # Fail-closed when --spawn-index was supplied but no row matched.
    if args.spawn_index is not None and spawn_index is None:
        print(
            f"ERROR: write-degraded-trace.py — --spawn-index {args.spawn_index} "
            f"requested but no spawn-log row matches "
            f"(agent={args.agent!r}, run_id={active_run_id!r}, hook=skill-agent-gate, "
            f"spawn_index={args.spawn_index}).",
            file=sys.stderr,
        )
        return 1

    # Parse fixes JSON (optional)
    fixes = []
    if args.fixes_json:
        try:
            fixes = json.loads(args.fixes_json)
            if not isinstance(fixes, list):
                print("ERROR: write-degraded-trace.py — --fixes-json must be a JSON array",
                      file=sys.stderr)
                return 1
        except json.JSONDecodeError as exc:
            print(f"ERROR: write-degraded-trace.py — --fixes-json invalid: {exc}",
                  file=sys.stderr)
            return 1

    # Parse extra JSON (optional) — agent-specific structured fields like
    # inconsistencies[], findings[]. Canonical trace keys take precedence; this
    # merge only adds fields not already present. Fix #1075.
    extra = {}
    if args.extra_json:
        try:
            extra = json.loads(args.extra_json)
            if not isinstance(extra, dict):
                print("ERROR: write-degraded-trace.py — --extra-json must be a JSON object",
                      file=sys.stderr)
                return 1
        except json.JSONDecodeError as exc:
            print(f"ERROR: write-degraded-trace.py — --extra-json invalid: {exc}",
                  file=sys.stderr)
            return 1

    checks = [c.strip() for c in args.checks_performed.split(",") if c.strip()]
    if not checks:
        print("ERROR: write-degraded-trace.py — --checks-performed must list at least one check",
              file=sys.stderr)
        return 1

    trace = {
        "agent": args.agent,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "completed",
        "verdict": args.verdict,
        "provenance": provenance,
        "partial": True,
        "checks_performed": checks,
        "degraded_reason": args.reason,
        "fixes": fixes,
        "no_fixes_claimed": len(fixes) == 0,
        "recovery_validated": False,
        "recovery": False,
        "run_id": active_run_id,
        "skill": active_skill,
        "spawn_sha": spawn_sha,
        "spawn_index": spawn_index,
    }
    # AOC v1.2: lead-orchestrated additional required fields.
    if provenance == "lead-orchestrated":
        trace["lead_attestation"] = True
        trace["source_run_id"] = args.source_run_id
        trace["source_skill"] = args.source_skill

    # Merge extra structured fields, preserving canonical keys. Fix #1075.
    for k, v in extra.items():
        if k not in trace:
            trace[k] = v

    os.makedirs(".runs/agent-traces", exist_ok=True)
    filename = args.trace_filename or f"{args.agent}.json"
    target = os.path.join(".runs/agent-traces", filename)
    with open(target, "w") as f:
        json.dump(trace, f, indent=2)
        f.write("\n")

    print(f"Self-degraded trace written: {target} (reason: {args.reason!r})")
    print("Note: recovery_validated:false — validate-recovery.sh will stamp it true "
          "after build+e2e+diff evidence check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
