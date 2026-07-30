#!/usr/bin/env python3
"""Consolidate agent trace fixes[] arrays into .runs/fix-ledger.jsonl.

AOC v1 FLS v1 consolidator. One authoritative per-fix ledger replaces the
prose-count drift between .runs/fix-log.md and agent trace fixes[].

AOC v1.1 (PR3) extends the script with a `--lead-fix` mode that writes a
single ledger row for an in-flight orchestrator fix. This closes #1064 D2
(no sanctioned lead-orchestrator fix-entry path) and #1067 Case C
(lead-fix has no per-row provenance).

Contract:
  - One JSON object per line.
  - Fields per AOC v1 FLS v1: fix_id, agent, source_trace, run_id, file,
    symptom, fix, timestamp, batch_id, batch_size.
  - AOC v1.1: per-row `provenance` field (agent | lead | lead-on-behalf)
    and optional `severity` (fix | warn).
  - fix_id = <source_trace_basename>:<run_id>:<fix_array_index> for agent fixes
    (run_id qualifier added in #1267 to defend against cross-run collisions
    when run N and run N+1 both produce identical (basename, idx) pairs from
    different agent spawns). When trace_run_id is empty (legacy traces or
    contexts missing run_id), falls back to legacy <basename>:<idx> form
    for backward compatibility — those rows can still collide cross-run, but
    modern traces always carry run_id from active context so the collision
    surface shrinks to legacy data only.
    fix_id = lead-<skill>:<run_id>:<monotonic-counter> for --lead-fix.
  - batch_id = source_trace_basename for agent fixes; per-invocation
    timestamp for --lead-fix (each invocation is its own batch).
  - batch_size = len(trace.fixes) for agent fixes; 1 for --lead-fix.
  - Atomic write: tempfile + os.rename (POSIX-atomic).
  - Idempotent: existing fix_ids are skipped (consolidate mode);
    --lead-fix uses a monotonic counter persisted in
    .runs/<skill>-context.json.lead_fix_counter so repeat invocations
    each get a fresh fix_id.

Granularity gate (AOC v1.1):
  - Reject rows with empty/null `file` (defends against #1048-class
    summary entries like "fixed N issues").
  - Reject --lead-fix rows whose `symptom` matches a summary pattern
    (^(fixed|all|N) ).

Invocation:
  Consolidate (default): run unconditionally at every state-completion-gate
  advance; idempotency makes repeat runs cheap.
  Lead-fix: invoke once per in-flight orchestrator correction.

Usage:
    python3 .claude/scripts/write-fix-ledger.py [--run-id <id>]
    python3 .claude/scripts/write-fix-ledger.py --dry-run
    python3 .claude/scripts/write-fix-ledger.py --lead-fix \\
        --skill <skill> \\
        --fix-json '{"file":"...","symptom":"...","fix":"..."}' \\
        [--severity warn]

Exit 0 if ledger successfully written or up-to-date; exit non-zero on
fatal error (e.g., write failure, granularity gate violation).
"""
import argparse
import glob
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone


LEDGER_PATH = ".runs/fix-ledger.jsonl"
TRACES_DIR = ".runs/agent-traces"
AGENT_REGISTRY = ".claude/patterns/agent-registry.json"

# AOC v1.1 granularity gate: reject summary-pattern symptoms (#1048 class).
# Matches "fixed 19 issues", "all critical resolved", "N tests passed", etc.
SUMMARY_SYMPTOM_PATTERNS = [
    re.compile(r"^\s*fixed\s+\d+\b", re.IGNORECASE),
    re.compile(r"^\s*all\s+\w+\s+(fixed|resolved|done|pass)", re.IGNORECASE),
    re.compile(r"^\s*\d+\s+(issues?|fixes|tests|warnings|fails?)\b", re.IGNORECASE),
]


def _is_summary_symptom(symptom):
    if not isinstance(symptom, str):
        return False
    return any(p.search(symptom) for p in SUMMARY_SYMPTOM_PATTERNS)


def _load_lead_merge_aggregate_agents():
    """Return the list of agents with sub-trace merging semantics.
    Used to dedupe ledger rows: when <agent>.json exists alongside
    <agent>-*.json, only <agent>.json is authoritative (post-merge).
    Falls back to a hard-coded list if the registry is unreadable."""
    try:
        with open(AGENT_REGISTRY) as f:
            reg = json.load(f)
        agents = reg.get("lead_merge_aggregate_agents")
        if isinstance(agents, list) and agents:
            return list(agents)
    except (OSError, json.JSONDecodeError):
        pass
    return [
        "design-critic",
        "scaffold-pages",
        "scaffold-images",
        "implementer",
        "visual-implementer",
    ]


def load_existing_ledger(path=LEDGER_PATH):
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path) as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError:
                # Preserve malformed lines by ignoring — they will be
                # overwritten on next full write. Do not silently drop
                # valid rows.
                continue
    return rows


def agent_name_from_trace(trace, trace_path):
    name = trace.get("agent")
    if name:
        return name
    return os.path.basename(trace_path).replace(".json", "")


def _should_skip_as_submerged(trace_path, aggregate_agents, all_paths):
    """AOC v1 FLS v1 dedup: for each lead_merge_aggregate_agent, if the
    aggregate `<agent>.json` exists, sub-traces `<agent>-*.json` are
    intermediate and MUST NOT emit ledger rows (their fixes are already
    concatenated into the aggregate's fixes[] by merge-<agent>-traces.py).
    Without this skip, every per-page fix doubles: once in the sub-trace
    row and once in the aggregate row.

    Generic 2-level aggregation (#1468 landing-critic split): when an
    aggregate trace declares a `sub_traces` field (a list of filenames),
    those sub-traces are ALSO skipped if the aggregate is itself absorbed
    by a higher-level aggregate. Example chain:

      landing-{sections,images}-critic.json → design-critic-landing.json
        → design-critic.json

    landing-sections-critic.json and landing-images-critic.json do not match
    the design-critic- prefix, but design-critic-landing.json lists them in
    `sub_traces`. This generic check walks all aggregates' sub_traces lists.
    """
    basename = os.path.basename(trace_path).replace(".json", "")
    filename = os.path.basename(trace_path)
    # Pass 1: direct prefix match against registered aggregate agents.
    for agent in aggregate_agents:
        if basename.startswith(agent + "-"):
            aggregate_path = os.path.join(TRACES_DIR, agent + ".json")
            if aggregate_path in all_paths:
                return True
    # Pass 2: sub_traces field on any aggregate that is itself absorbed.
    # Read each aggregate trace's sub_traces field and check if filename matches.
    for agent in aggregate_agents:
        aggregate_path = os.path.join(TRACES_DIR, agent + ".json")
        if aggregate_path not in all_paths:
            continue
        # Walk every <agent>-*.json sibling — they may themselves declare
        # sub_traces that include `filename` (chained aggregation).
        for path in all_paths:
            sib_base = os.path.basename(path)
            if not (sib_base == agent + ".json" or sib_base.startswith(agent + "-")):
                continue
            try:
                sib = json.load(open(path))
            except (OSError, json.JSONDecodeError):
                continue
            sub_traces = sib.get("sub_traces") or []
            if isinstance(sub_traces, list) and filename in sub_traces:
                return True
    return False


def _row_provenance_from_trace(trace):
    """AOC v1.1: derive per-row provenance from the trace's provenance field.
    Mapping: trace `self`/`self-degraded`/`recovery`/`lead-merge` → row `agent`
    (the fix is attributed to the source agent). Trace `lead-on-behalf` → row
    `lead-on-behalf` (lead transcribed but agent did the work). lead-fix
    rows are written via --lead-fix mode, not consolidate mode."""
    trace_prov = trace.get("provenance")
    if trace_prov == "lead-on-behalf":
        return "lead-on-behalf"
    return "agent"


def collect_rows(existing_ids, caller_run_id):
    """Walk trace directory, extract fixes[] from each trace, yield FLS v1
    records for fix_ids not yet in the ledger.

    Dedup: skip sub-traces of lead_merge_aggregate_agents when the aggregate
    trace is present. Prevents double-counting per-page fixes that are
    concatenated into the merged aggregate's fixes[] array.

    Granularity gate (AOC v1.1): reject rows where `file` is null/empty.
    Drops legacy summary entries like {"fixes": [{"symptom": "fixed N issues"}]}
    that #1048 documented as the root cause of fix-count drift.
    """
    aggregate_agents = _load_lead_merge_aggregate_agents()
    all_paths = set(glob.glob(os.path.join(TRACES_DIR, "*.json")))
    new_rows = []
    skipped_no_file = 0
    for trace_path in sorted(all_paths):
        if _should_skip_as_submerged(trace_path, aggregate_agents, all_paths):
            continue
        try:
            trace = json.load(open(trace_path))
        except Exception:
            continue
        fixes = trace.get("fixes", [])
        if not isinstance(fixes, list) or not fixes:
            continue
        basename = os.path.basename(trace_path).replace(".json", "")
        agent = agent_name_from_trace(trace, trace_path)
        trace_run_id = trace.get("run_id") or caller_run_id or ""
        ts = trace.get("timestamp") or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        row_provenance = _row_provenance_from_trace(trace)
        batch_size = len(fixes)
        for idx, fix in enumerate(fixes):
            # #1267: include run_id in fix_id to prevent cross-run collision
            # (run N's design-critic:0 silently dedup'd run N+1's design-critic:0,
            # dropping new fixes). Empty trace_run_id falls back to the legacy
            # 2-part form so pre-#1267 ledger rows stay addressable.
            fix_id = (
                f"{basename}:{trace_run_id}:{idx}"
                if trace_run_id
                else f"{basename}:{idx}"
            )
            if fix_id in existing_ids:
                continue
            # Accept loose shapes in the source fixes[] array: {file, symptom, fix}
            # is canonical but some agents write {file, desc, action} etc.
            file_val = None
            symptom_val = None
            fix_val = None
            if isinstance(fix, dict):
                file_val = fix.get("file") or fix.get("path")
                symptom_val = fix.get("symptom") or fix.get("desc") or fix.get("description")
                fix_val = fix.get("fix") or fix.get("action") or fix.get("change")
            elif isinstance(fix, str):
                fix_val = fix
            # AOC v1.1 granularity gate: drop fixes without a file. Logs to
            # stderr for diagnosis; the trace itself is preserved for audit.
            if not file_val:
                skipped_no_file += 1
                sys.stderr.write(
                    f"write-fix-ledger: skipping {fix_id} from {basename} "
                    f"(no file field — granularity gate AOC v1.1)\n"
                )
                continue
            row = {
                "fix_id": fix_id,
                "agent": agent,
                "source_trace": trace_path,
                "run_id": trace_run_id,
                "file": file_val,
                "symptom": symptom_val,
                "fix": fix_val,
                "timestamp": ts,
                "batch_id": basename,
                "batch_size": batch_size,
                "provenance": row_provenance,
            }
            # EARC slice 1: preserve lead_transcribed flag from agent traces.
            # When a fixer-class agent crashed and the lead recorded fixes
            # via write-recovery-trace.sh --fixes-json, the per-entry
            # lead_transcribed:true flag distinguishes "agent's own claim"
            # from "lead's recovery-evidence claim" so pattern-classifier
            # can route the row to the lead-transcribed sub-class.
            if isinstance(fix, dict) and fix.get("lead_transcribed") is True:
                row["lead_transcribed"] = True
            new_rows.append(row)
    if skipped_no_file:
        sys.stderr.write(
            f"write-fix-ledger: granularity gate dropped {skipped_no_file} fix(es) "
            "without a file field. See agent-output-contract.md FLS v1.\n"
        )
    return new_rows


def atomic_write(rows, path=LEDGER_PATH):
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".fix-ledger-", suffix=".jsonl.tmp", dir=parent
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            for row in rows:
                f.write(json.dumps(row, sort_keys=True) + "\n")
        os.rename(tmp_path, path)  # POSIX-atomic
    except Exception:
        if os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def _bump_lead_fix_counter(skill):
    """AOC v1.1: monotonic counter for lead-fix rows, persisted in the
    skill's context.json. Returns the new counter value (post-increment).
    Falls back to a timestamp-based unique value if context.json is missing
    or unwritable, so concurrent invocations still get distinct fix_ids.
    """
    ctx_path = f".runs/{skill}-context.json"
    if not os.path.isfile(ctx_path):
        # Fallback: timestamp-microsecond suffix avoids collisions even
        # without persistent state. Returns a string.
        return f"ts{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"
    try:
        with open(ctx_path) as f:
            ctx = json.load(f)
    except (OSError, json.JSONDecodeError):
        return f"ts{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"
    counter = ctx.get("lead_fix_counter")
    if not isinstance(counter, int):
        counter = 0
    counter += 1
    ctx["lead_fix_counter"] = counter
    # Atomic write of context.json (mirrors lifecycle-finalize.sh pattern)
    fd, tmp = tempfile.mkstemp(prefix=".ctx-", dir=os.path.dirname(ctx_path) or ".")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(ctx, f, indent=2)
        os.rename(tmp, ctx_path)
    except Exception:
        if os.path.isfile(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        # Don't fail the whole invocation just because counter persistence
        # broke — fall back to timestamp suffix.
        return f"ts{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"
    return counter


def _resolve_run_id_for_skill(skill):
    """Look up run_id from .runs/<skill>-context.json. Empty string if missing."""
    ctx_path = f".runs/{skill}-context.json"
    if not os.path.isfile(ctx_path):
        return ""
    try:
        with open(ctx_path) as f:
            return json.load(f).get("run_id", "") or ""
    except (OSError, json.JSONDecodeError):
        return ""


def _validate_lead_fix(fix, severity):
    """AOC v1.1 granularity gate for --lead-fix.
    Returns (file, symptom, fix_text) or raises ValueError on rejection."""
    if not isinstance(fix, dict):
        raise ValueError("--fix-json must decode to a JSON object")
    file_val = fix.get("file") or fix.get("path")
    symptom_val = fix.get("symptom") or fix.get("desc") or fix.get("description")
    fix_val = fix.get("fix") or fix.get("action") or fix.get("change")
    # Granularity gate: reject all-empty rows and summary-pattern symptoms.
    if not file_val:
        raise ValueError(
            "granularity gate: --lead-fix requires a non-empty `file` "
            "(AOC v1.1 — defends against #1048 summary entries)"
        )
    if severity != "warn" and _is_summary_symptom(symptom_val):
        raise ValueError(
            f"granularity gate: --lead-fix symptom {symptom_val!r} matches a "
            "summary pattern (e.g., 'fixed N issues'). Provide one row per "
            "specific fix, or pass --severity warn for batch warnings."
        )
    return file_val, symptom_val, fix_val


def write_lead_fix_row(skill, fix_dict, severity, ledger_path=LEDGER_PATH):
    """AOC v1.1 lead-fix path. Append one row to fix-ledger.jsonl with
    provenance:"lead", agent:"lead-<skill>", source_trace:"lead", and a
    monotonic fix_id. Returns the new row dict."""
    file_val, symptom_val, fix_val = _validate_lead_fix(fix_dict, severity)
    run_id = _resolve_run_id_for_skill(skill)
    counter = _bump_lead_fix_counter(skill)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fix_id = f"lead-{skill}:{run_id or 'no-run'}:{counter}"
    row = {
        "fix_id": fix_id,
        "agent": f"lead-{skill}",
        "source_trace": "lead",
        "run_id": run_id,
        "file": file_val,
        "symptom": symptom_val,
        "fix": fix_val,
        "timestamp": ts,
        "batch_id": ts,        # per-invocation timestamp (each call is its own batch)
        "batch_size": 1,
        "provenance": "lead",
    }
    if severity == "warn":
        row["severity"] = "warn"
    # Append-only: load existing, add row, atomic-rewrite.
    existing = load_existing_ledger(ledger_path)
    existing_ids = {r.get("fix_id") for r in existing if isinstance(r, dict)}
    if fix_id in existing_ids:
        sys.stderr.write(
            f"write-fix-ledger: lead-fix row {fix_id} already in ledger (skipping)\n"
        )
        return row
    atomic_write(existing + [row], ledger_path)
    return row


def write_template_edit_row(skill, file_val, before_hash, after_hash,
                            agent="lead-template-edit",
                            ledger_path=LEDGER_PATH):
    """Append a template-edit row to fix-ledger.jsonl (#1128 Layer 3).

    Bypasses summary-pattern check (template-edits have no symptom narrative).
    Uses provenance:'lead' since Phase 1 only fires for lead-attributed edits
    (covered-by-agent-trace cases skip ledger write at scanner level)."""
    if not file_val:
        raise ValueError("--template-edit requires --file <path>")
    run_id = _resolve_run_id_for_skill(skill)
    counter = _bump_lead_fix_counter(skill)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fix_id = f"lead-{skill}:{run_id or 'no-run'}:{counter}"
    row = {
        "fix_id": fix_id,
        "agent": agent,
        "source_trace": "lead-template-edit",
        "run_id": run_id,
        "file": file_val,
        "symptom": None,
        "fix": None,
        "timestamp": ts,
        "batch_id": ts,
        "batch_size": 1,
        "provenance": "lead",
        "entry_type": "template-edit",
        "before_hash": before_hash,
        "after_hash": after_hash,
        "severity": "warn",
    }
    existing = load_existing_ledger(ledger_path)
    existing_ids = {r.get("fix_id") for r in existing if isinstance(r, dict)}
    if fix_id in existing_ids:
        sys.stderr.write(
            f"write-fix-ledger: template-edit row {fix_id} already in ledger (skipping)\n"
        )
        return row
    atomic_write(existing + [row], ledger_path)
    return row


def main():
    ap = argparse.ArgumentParser(
        description="Consolidate agent trace fixes[] into fix-ledger.jsonl"
    )
    ap.add_argument("--run-id", default=None,
                    help="Fallback run_id when source trace lacks one")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show counts without writing")
    # AOC v1.1 lead-fix mode (#1064 D2 / #1067 Case C)
    ap.add_argument("--lead-fix", action="store_true",
                    help="Write a single lead-orchestrator fix row (AOC v1.1). "
                         "Required: --skill, --fix-json. Optional: --severity warn.")
    ap.add_argument("--skill", default=None,
                    help="Active skill name for --lead-fix (e.g., verify, change). "
                         "Used to resolve run_id from .runs/<skill>-context.json and "
                         "to attribute the row as agent='lead-<skill>'.")
    ap.add_argument("--fix-json", default=None,
                    help="JSON object for --lead-fix: {\"file\":\"...\","
                         "\"symptom\":\"...\",\"fix\":\"...\"}. file is required "
                         "(granularity gate).")
    ap.add_argument("--severity", choices=("fix", "warn"), default="fix",
                    help="--lead-fix only: 'fix' (default) or 'warn' (e.g., for "
                         "STATE 5 e2e-config WARN migration).")
    # AOC v1.1 template-edit mode (#1128 Layer 3)
    ap.add_argument("--template-edit", action="store_true",
                    help="Write a single template-edit row (#1128). Required: "
                         "--skill, --file. Optional: --before-hash, --after-hash, "
                         "--agent (default: lead-template-edit). Bypasses the "
                         "summary-pattern check (template-edits have no symptom).")
    ap.add_argument("--file", default=None,
                    help="Template file path for --template-edit "
                         "(e.g., .claude/scripts/foo.py).")
    ap.add_argument("--before-hash", default=None,
                    help="--template-edit only: pre-edit content hash "
                         "(8-char prefix preferred).")
    ap.add_argument("--after-hash", default=None,
                    help="--template-edit only: post-edit content hash.")
    ap.add_argument("--agent", default="lead-template-edit",
                    help="--template-edit only: attribution string "
                         "(default: lead-template-edit).")
    args = ap.parse_args()

    # ---- AOC v1.1 lead-fix mode ----
    if args.lead_fix:
        if not args.skill:
            sys.stderr.write("ERROR: --lead-fix requires --skill <skill>\n")
            return 2
        if not args.fix_json:
            sys.stderr.write("ERROR: --lead-fix requires --fix-json '<...>'\n")
            return 2
        try:
            fix_dict = json.loads(args.fix_json)
        except json.JSONDecodeError as exc:
            sys.stderr.write(f"ERROR: --fix-json invalid JSON: {exc}\n")
            return 2
        try:
            row = write_lead_fix_row(args.skill, fix_dict, args.severity)
        except ValueError as exc:
            sys.stderr.write(f"ERROR: {exc}\n")
            return 2
        print(
            f"write-fix-ledger: lead-fix wrote {row['fix_id']} "
            f"(agent={row['agent']}, file={row['file']}, severity={row.get('severity', 'fix')})"
        )
        return 0

    # ---- AOC v1.1 template-edit mode (#1128) ----
    if args.template_edit:
        if not args.skill:
            sys.stderr.write("ERROR: --template-edit requires --skill <skill>\n")
            return 2
        if not args.file:
            sys.stderr.write("ERROR: --template-edit requires --file <path>\n")
            return 2
        try:
            row = write_template_edit_row(
                args.skill, args.file, args.before_hash, args.after_hash,
                agent=args.agent,
            )
        except ValueError as exc:
            sys.stderr.write(f"ERROR: {exc}\n")
            return 2
        print(
            f"write-fix-ledger: template-edit wrote {row['fix_id']} "
            f"(agent={row['agent']}, file={row['file']})"
        )
        return 0

    # ---- Default consolidate mode ----
    if not os.path.isdir(TRACES_DIR):
        # Nothing to consolidate. Ensure the file exists for presence checks,
        # but NEVER truncate an existing ledger — --lead-fix rows written
        # before consolidation (agentless skills have no traces dir) must
        # survive, matching the up-to-date branch below.
        existing = load_existing_ledger()
        if not args.dry_run and not os.path.isfile(LEDGER_PATH):
            atomic_write([])
        print(
            f"write-fix-ledger: no traces dir, nothing to consolidate "
            f"({len(existing)} existing rows preserved)"
        )
        return 0

    existing = load_existing_ledger()
    existing_ids = {r.get("fix_id") for r in existing if isinstance(r, dict)}
    new_rows = collect_rows(existing_ids, args.run_id)

    total = len(existing) + len(new_rows)
    if args.dry_run:
        print(f"write-fix-ledger (dry-run): existing={len(existing)} "
              f"new={len(new_rows)} total={total}")
        return 0

    if new_rows:
        atomic_write(existing + new_rows)
        print(f"write-fix-ledger: added {len(new_rows)} rows (total {total})")
    else:
        # Up-to-date; still ensure file exists (empty is valid).
        if not os.path.isfile(LEDGER_PATH):
            atomic_write([])
        print(f"write-fix-ledger: up-to-date ({total} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
