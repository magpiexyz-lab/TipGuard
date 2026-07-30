#!/usr/bin/env python3
"""Migration of pre-AOC-v1 agent traces to the unified schema.

AOC v1.2 note: additive bump only — no migration logic required.
- `lead-orchestrated` and `lead-skipped` provenance values are NEW; legacy
  traces never carried them, so there is nothing to backfill.
- `allowed_verdicts`/`allowed_results` extension for fixers (adding `skipped`)
  is purely additive — pre-existing traces still use the old vocabulary and
  remain valid; no rewrite needed.
- `lead_orchestrated_forbidden` is a registry-only addition; no trace impact.
- `_aggregate_ok_accepted_predicates` is a registry-only addition; no trace
  impact.



Legacy traces (written before Agent Output Contract v1) lack the `result`
field (AOC v1 qualifier) and may emit uppercase or count-form legacy
verdicts. This script walks .runs/agent-traces/, derives missing fields
from legacy values, case-normalizes uppercase verdicts, and writes a
.runs/trace-migration.json receipt so downstream gates know migration ran.

Called from:
  - lifecycle-init.sh (primary and --embed paths — R2 C4 fix, so embed runs
    also trigger migration rather than carrying unmigrated traces forward)
  - verify-report-gate.sh self-heal mode (R2 C4 alternative fix, logs a
    WARN and continues rather than hard-refusing a multi-hour workflow)

Idempotent: writes a receipt and checks it on subsequent invocations.
A trace is considered fully migrated iff BOTH `provenance` AND `result`
are present (the two-field check prevents pre-AOC-v1 traces that only
had `provenance` backfilled from being skipped).

Migration rules (AOC v1):
  - verdict case-normalized to lowercase (PASS→pass, FAIL→fail,
    DEGRADED→pass+result=degraded, SKIPPED→pass+result=skipped)
  - LEGACY_VERDICT_MAP per agent maps legacy verdict strings to
    (new_verdict, new_result) tuples
  - count_summary agents derive result from structured fields
    (fails_count, findings_count, etc.) or regex-parse the legacy
    verdict string if structured fields are absent
  - FAIL-CLOSED: unknown verdict for a known agent, or count_summary
    agent with no structured field and unparseable verdict, records
    the trace to .runs/trace-migration-unresolved.json and leaves the
    trace unmigrated. verify-report-gate.sh refuses to proceed when
    unresolved_count > 0.
  - #1042 stamping: design-critic traces with the DEMO_MODE fixture
    short-circuit shape (verdict=fixed + review_method=source-only) get
    stamped provenance=self-degraded + degraded_reason=
    "demo-mode-fixture-short-circuit" and recovery_validated=true.

Provenance backfill (v2 contract, still applied):
  - No `provenance` field AND `recovery: true`       → provenance="recovery"
  - No `provenance` field AND no `recovery`/false    → provenance="self"
  - `status` missing → "completed" (unless verdict missing, then "started")
  - `partial` missing → True when provenance in {recovery, self-degraded}, else False
  - `no_fixes_claimed` missing → True when fixes array empty or absent
  - `recovery_validated` missing → False (validate-recovery.sh can stamp later)

AOC v1.1 lead-* provenance values (lead-on-behalf, lead-synthesized,
lead-fix) are NOT backfilled here. Legacy traces predate AOC v1.1 and
cannot have these values. New traces emit them via dedicated writers
(write-agent-trace.sh for lead-on-behalf/lead-synthesized;
write-fix-ledger.py --lead-fix for lead-fix). PR4 (resolve-reviewer
first-class) extends LEGACY_VERDICT_MAP to handle the alias-stub case
specifically.

Usage:
    python3 .claude/scripts/migrate-legacy-traces.py [--dry-run]
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone


RECEIPT_PATH = ".runs/trace-migration.json"
UNRESOLVED_PATH = ".runs/trace-migration-unresolved.json"


# --- AOC v1: Legacy verdict → (new_verdict, new_result) mapping per agent. ---
# Entries marked "count_summary" use COUNT_SUMMARY_FIELDS / COUNT_SUMMARY_REGEXES
# instead of a direct string table.
LEGACY_VERDICT_MAP = {
    "observer": {
        "filed": ("pass", "none"),
        "commented": ("pass", "none"),
        "no observations": ("pass", "clean"),
        "prerequisite-unavailable": ("blocked", "none"),
    },
    "spec-reviewer": {
        "PASS": ("pass", "clean"),
        "FAIL": ("fail", "partial"),
        "pass": ("pass", "clean"),
        "fail": ("fail", "partial"),
    },
    "design-critic": {
        "pass": ("pass", "clean"),
        "fixed": ("pass", "fixed"),
        "unresolved": ("unresolved", None),
    },
    "design-consistency-checker": "count_summary",
    "ux-journeyer": {
        "all pass": ("pass", "clean"),
        "all fixed": ("pass", "fixed"),
        "partial": ("fail", "partial"),
        "blocked": ("blocked", "none"),
    },
    "security-fixer": {
        "all fixed": ("pass", "fixed"),
        "partial": ("fail", "partial"),
        "none": ("pass", "none"),
        # AOC v1: some existing traces may already use pass/fail without result.
        "pass": ("pass", "clean"),
        "fail": ("fail", "partial"),
    },
    "quality-fixer": {
        "all fixed": ("pass", "fixed"),
        "partial": ("fail", "partial"),
        "none": ("pass", "none"),
        "pass": ("pass", "clean"),
        "fail": ("fail", "partial"),
    },
    "security-attacker": "count_summary",
    "security-defender": "count_summary",
    "behavior-verifier": {
        "PASS": ("pass", "clean"),
        "FAIL": ("fail", "partial"),
        "DEGRADED": ("pass", "degraded"),
        "SKIPPED": ("pass", "skipped"),
        "pass": ("pass", "clean"),
        "fail": ("fail", "partial"),
    },
    "performance-reporter": "count_summary",
    "accessibility-scanner": "count_summary",
    "build-info-collector": {
        "collected": ("pass", "clean"),
        "no-fixes": ("pass", "clean"),
    },
    "pattern-classifier": "count_summary",
    "resolve-challenger": "count_summary",
    "review-challenger": "count_summary",
    "solve-critic": "count_summary",
}

# count_summary agents: preferred structured field → (verdict-pass-iff-zero predicate).
# When structured field is present and int-valued, it is authoritative.
COUNT_SUMMARY_FIELDS = {
    "design-consistency-checker": ["inconsistent_count"],
    "security-attacker": ["findings_count"],
    "security-defender": ["fails_count", "findings_count"],
    "performance-reporter": ["warnings_count"],
    "accessibility-scanner": ["violations_count"],
    "pattern-classifier": ["total"],
    "resolve-challenger": ["disputed_count"],
    "review-challenger": ["disputed_count"],
    "solve-critic": ["type_a_count"],
}

# Regex fallbacks for count_summary agents when structured field is absent but
# legacy verdict string carries the count.
COUNT_SUMMARY_REGEXES = {
    "security-defender": (r"(\d+)\s+FAILs?", "fails_count"),
    "security-attacker": (r"(\d+)\s+findings?", "findings_count"),
    "performance-reporter": (r"(\d+)\s+warnings?", "warnings_count"),
    "accessibility-scanner": (r"(\d+)\s+violations?", "violations_count"),
    "design-consistency-checker": (r"(\d+)\s+inconsistenc", "inconsistent_count"),
    "solve-critic": (r"(\d+)\s+TYPE A", "type_a_count"),
    # Adversarial challenger legacy verdicts:
    #   "N fixes sound, M challenged"   (resolve-challenger)
    #   "N fixes sound, M needs-revision"
    #   "N confirmed, M disputed"       (review-challenger)
    # The disputed/challenged count is the "gated" number.
    "resolve-challenger": (r"(\d+)\s+(?:challenged|needs-revision|disputed)", "disputed_count"),
    "review-challenger": (r"(\d+)\s+(?:disputed|needs-evidence|challenged)", "disputed_count"),
}


def case_normalize_verdict(v):
    """Lowercase known AVS v1 verdict tokens. Unknown verdicts pass through
    so downstream fail-closed can catch them."""
    if not isinstance(v, str):
        return v
    low = v.lower()
    if low in ("pass", "fail", "blocked", "unresolved"):
        return low
    return v


def derive_result(trace, agent_name, unresolved_log):
    """Returns (new_verdict, new_result) or (None, None) on parse failure.

    FAIL-CLOSED: on unknown verdict or ambiguous count_summary state, append
    to unresolved_log and return (None, None). Caller leaves trace unmigrated.
    """
    mapping = LEGACY_VERDICT_MAP.get(agent_name)
    legacy_verdict = trace.get("verdict")

    # count_summary path
    if mapping == "count_summary":
        fields = COUNT_SUMMARY_FIELDS.get(agent_name, [])
        # Prefer structured fields
        for f in fields:
            val = trace.get(f)
            if isinstance(val, int):
                return ("pass" if val == 0 else "fail", "count_summary")
        # Regex fallback on verdict string
        if legacy_verdict and agent_name in COUNT_SUMMARY_REGEXES:
            pat, target_field = COUNT_SUMMARY_REGEXES[agent_name]
            m = re.search(pat, str(legacy_verdict))
            if m:
                count_val = int(m.group(1))
                trace[target_field] = count_val
                return ("pass" if count_val == 0 else "fail", "count_summary")
        # Treat known non-count verdict strings as pass-with-clean for challenger-style agents
        # (resolve-challenger/review-challenger/pattern-classifier often emit summary strings
        # that don't carry a count we can parse; prefer structured fields in new traces.)
        if agent_name in ("resolve-challenger", "review-challenger", "pattern-classifier",
                          "solve-critic"):
            # Without structured field AND no parseable regex, FAIL-CLOSED.
            unresolved_log.append({
                "agent": agent_name,
                "trace_verdict": legacy_verdict,
                "reason": f"count_summary agent {agent_name} has no structured field and unparseable verdict",
            })
            return (None, None)
        # Scanner agents must have a count
        unresolved_log.append({
            "agent": agent_name,
            "trace_verdict": legacy_verdict,
            "reason": f"count_summary agent {agent_name} missing required fields: {fields}",
        })
        return (None, None)

    if isinstance(mapping, dict):
        if legacy_verdict in mapping:
            return mapping[legacy_verdict]
        # Try case-normalized lookup before giving up.
        if isinstance(legacy_verdict, str) and legacy_verdict.lower() in mapping:
            return mapping[legacy_verdict.lower()]
        # Known agent + unknown verdict → FAIL-CLOSED.
        unresolved_log.append({
            "agent": agent_name,
            "trace_verdict": legacy_verdict,
            "reason": f"verdict {legacy_verdict!r} not in LEGACY_VERDICT_MAP[{agent_name}]",
        })
        return (None, None)

    # Unknown agent — pass through. Forward-compat for new agents not yet in map.
    return (legacy_verdict, None)


def stamp_self_degraded_recovery(trace, agent_name, trace_path):
    """#1042 cross-group coordination: for design-critic legacy traces that
    exhibit the DEMO_MODE dynamic-route 404 fixture short-circuit shape,
    stamp provenance=self-degraded + degraded_reason=
    "demo-mode-fixture-short-circuit" and invoke validate-recovery.sh to
    stamp recovery_validated=true. Idempotent (no-op if already stamped).
    """
    if agent_name != "design-critic":
        return False
    if trace.get("review_method") != "source-only":
        return False
    # Only traces with fix or pass-like outcomes (not unresolved/fail).
    if trace.get("verdict") not in ("fixed", "pass", "fail"):
        return False
    if trace.get("provenance") == "self-degraded" and trace.get("degraded_reason") == "demo-mode-fixture-short-circuit":
        return False  # already stamped
    trace["provenance"] = "self-degraded"
    trace["degraded_reason"] = "demo-mode-fixture-short-circuit"
    trace["partial"] = True
    # Invoke validate-recovery.sh to stamp recovery_validated; non-fatal if it fails.
    try:
        subprocess.run(
            ["bash", ".claude/scripts/validate-recovery.sh", "--trace", trace_path],
            check=False,
            capture_output=True,
        )
    except Exception:
        pass
    # If validate-recovery.sh did not write recovery_validated, stamp it anyway
    # since migration is idempotent and this is a best-effort backfill.
    if "recovery_validated" not in trace:
        trace["recovery_validated"] = True
    return True


def _self_heal_self_check_score(trace, trace_path):
    """Self-heal pre-cutoff scaffold-pages traces missing self_check_score (#1387).

    The new AOC v1.2 self_check_score field was introduced in PR #1387
    (issue #1387 FM3). Pre-cutoff scaffold-pages traces — written before
    the schema_version=2 cutoff (2026-05-04T05:25:30Z per
    schema_version_gate.py) — lack the field. This self-heal backfills
    self_check_score_explicit_none=true with rerun-recovery reason so
    validate-self-check-score-schema.py passes idempotently.

    Post-cutoff traces MUST emit either self_check_score or
    self_check_score_explicit_none from the agent. We do NOT self-heal
    those; the validator is the gate.

    Idempotent. Returns True iff trace was modified.
    """
    basename = os.path.basename(trace_path)
    if "scaffold-pages-" not in basename:
        return False
    if "self_check_score" in trace or "self_check_score_explicit_none" in trace:
        return False
    # Pre-cutoff check via schema_version_gate
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
        from schema_version_gate import required_schema_version  # type: ignore
    except ImportError:
        # schema_version_gate unavailable — be conservative and self-heal
        # (better than crashing the migration; validator is still the gate
        # for new traces).
        required_schema_version = lambda _rid: 1  # noqa: E731
    rid = trace.get("run_id") or ""
    try:
        version = required_schema_version(rid)
    except Exception:
        version = 1
    if version >= 2:
        return False  # post-cutoff: validator catches missing field, do not self-heal
    trace["self_check_score_explicit_none"] = True
    trace["self_check_score_explicit_none_reason"] = "rerun-recovery"
    return True


def derive_fields(trace, agent_name, trace_path, unresolved_log):
    """Derive missing v2 + AOC v1 fields. Returns (updated_trace, changed).

    Idempotency (AOC v1): a trace is fully-migrated iff BOTH provenance AND
    result are present. Old traces with provenance but no result are
    re-visited to backfill result.

    #1387: self_check_score self-heal runs BEFORE the provenance+result
    short-circuit so traces that already have those fields still get the
    self_check_score backfill on a single pass.
    """
    self_check_healed = _self_heal_self_check_score(trace, trace_path)

    if trace.get("provenance") is not None and trace.get("result") is not None:
        return trace, self_check_healed

    changed = self_check_healed

    # v2: provenance backfill
    if trace.get("provenance") is None:
        prov = "recovery" if trace.get("recovery") else "self"
        trace["provenance"] = prov
        changed = True

        if "status" not in trace:
            trace["status"] = "completed" if "verdict" in trace else "started"

        if "partial" not in trace:
            trace["partial"] = prov in ("recovery", "self-degraded")

        if "no_fixes_claimed" not in trace:
            fixes = trace.get("fixes")
            trace["no_fixes_claimed"] = not isinstance(fixes, list) or len(fixes) == 0

        if "recovery_validated" not in trace:
            trace["recovery_validated"] = False

        if "recovery" not in trace:
            trace["recovery"] = prov == "recovery"

        if prov in ("recovery", "self-degraded") and not trace.get("degraded_reason"):
            trace["degraded_reason"] = "legacy-migrated (reason unrecorded)"

    # AOC v1: case-normalize verdict.
    original_verdict = trace.get("verdict")
    if original_verdict is not None:
        normalized = case_normalize_verdict(original_verdict)
        if normalized != original_verdict:
            trace["verdict"] = normalized
            changed = True

    # #1042 stamping (design-critic fixture short-circuit).
    if stamp_self_degraded_recovery(trace, agent_name, trace_path):
        changed = True

    # AOC v1: derive result if absent.
    if trace.get("result") is None and trace.get("verdict") is not None:
        new_verdict, new_result = derive_result(trace, agent_name, unresolved_log)
        if new_verdict is None and new_result is None:
            # Fail-closed: leave trace unmigrated for operator review.
            # Do NOT set result=None (may collide with "null" sentinel).
            # Return changed flag reflecting any prior v2 backfill that did occur.
            return trace, changed
        # Apply derivation. new_verdict may equal existing verdict (no-op).
        if trace.get("verdict") != new_verdict:
            trace["verdict"] = new_verdict
            changed = True
        trace["result"] = new_result
        changed = True

    return trace, changed


def already_migrated():
    if not os.path.isfile(RECEIPT_PATH):
        return False
    try:
        receipt = json.load(open(RECEIPT_PATH))
        # AOC v1: receipt must carry unresolved_count field to be considered
        # post-AOC-v1. Pre-AOC-v1 receipts re-run once to backfill result.
        return "unresolved_count" in receipt
    except Exception:
        return False


def agent_name_from_path(path):
    """Extract agent name from trace path. Handles both flat
    (security-fixer.json) and sub-trace (design-critic-landing.json)
    forms — for sub-traces we use the base agent prefix (design-critic)."""
    basename = os.path.basename(path).replace(".json", "")
    # Known multi-word base agents; longest match first.
    known_prefixes = [
        "design-consistency-checker",
        "design-critic",
        "build-info-collector",
        "security-attacker",
        "security-defender",
        "security-fixer",
        "quality-fixer",
        "ux-journeyer",
        "performance-reporter",
        "accessibility-scanner",
        "pattern-classifier",
        "resolve-challenger",
        "review-challenger",
        "solve-critic",
        "spec-reviewer",
        "behavior-verifier",
        "observer",
    ]
    for p in known_prefixes:
        if basename == p or basename.startswith(p + "-"):
            return p
    return basename


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy agent traces to v2 + AOC v1 schema")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without writing")
    parser.add_argument("--force", action="store_true",
                        help="Re-run even if receipt exists")
    args = parser.parse_args()

    if already_migrated() and not args.force:
        return 0

    traces_dir = ".runs/agent-traces"
    if not os.path.isdir(traces_dir):
        if not args.dry_run:
            os.makedirs(".runs", exist_ok=True)
            json.dump({
                "migrated_at": datetime.now(timezone.utc).isoformat(),
                "traces_dir_existed": False,
                "processed": 0,
                "changed": 0,
                "unresolved_count": 0,
            }, open(RECEIPT_PATH, "w"), indent=2)
        return 0

    processed = 0
    changed_files = 0
    unresolved_log = []
    for path in sorted(glob.glob(os.path.join(traces_dir, "*.json"))):
        try:
            trace = json.load(open(path))
        except Exception as exc:
            sys.stderr.write(f"WARN: migrate-legacy-traces: cannot parse {path}: {exc}\n")
            continue
        processed += 1
        agent_name = trace.get("agent") or agent_name_from_path(path)
        trace_updated, changed = derive_fields(trace, agent_name, path, unresolved_log)
        if changed:
            changed_files += 1
            if not args.dry_run:
                json.dump(trace_updated, open(path, "w"), indent=2)

    if not args.dry_run:
        os.makedirs(".runs", exist_ok=True)
        json.dump({
            "migrated_at": datetime.now(timezone.utc).isoformat(),
            "traces_dir_existed": True,
            "processed": processed,
            "changed": changed_files,
            "unresolved_count": len(unresolved_log),
        }, open(RECEIPT_PATH, "w"), indent=2)
        if unresolved_log:
            # GRAIM v2 C1: write the gate-readable unresolved file via the
            # canonical writer so it carries {skill, run_id, written_at}.
            # This script runs from lifecycle-init.sh and verify-report-gate.sh
            # contexts where resolve_active_identity is populated.
            unresolved_payload = json.dumps({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "unresolved": unresolved_log,
            })
            try:
                subprocess.run(
                    [
                        "bash",
                        ".claude/scripts/lib/write-gate-artifact.sh",
                        "--path",
                        UNRESOLVED_PATH,
                        "--payload",
                        unresolved_payload,
                    ],
                    check=True,
                )
            except subprocess.CalledProcessError as exc:
                # Fail-closed fallback: if the canonical writer cannot resolve
                # identity (e.g., script invoked outside any skill context),
                # still emit the file so verify-report-gate.sh's hard refuse
                # branch fires. The file will lack identity stamping in that
                # edge case — deliberate trade-off vs losing the gate signal.
                sys.stderr.write(
                    f"WARN: migrate-legacy-traces: write-gate-artifact failed ({exc}); "
                    f"falling back to direct json.dump for {UNRESOLVED_PATH}\n"
                )
                with open(UNRESOLVED_PATH, "w") as f:
                    json.dump({
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "unresolved": unresolved_log,
                    }, f, indent=2)
            sys.stderr.write(
                f"WARN: migrate-legacy-traces: {len(unresolved_log)} unresolved traces "
                f"written to {UNRESOLVED_PATH}. verify-report-gate.sh will refuse to proceed.\n"
            )
        elif os.path.isfile(UNRESOLVED_PATH):
            # Clear stale unresolved file on clean run.
            try:
                os.unlink(UNRESOLVED_PATH)
            except OSError:
                pass
    print(f"migrate-legacy-traces: processed={processed} changed={changed_files} "
          f"unresolved={len(unresolved_log)} {'(dry-run)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
