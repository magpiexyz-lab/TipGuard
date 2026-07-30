#!/usr/bin/env python3
"""merge-design-consistency-checker-traces.py — Official merge for verify state-3b page-batched consistency check (#1257).

Mirrors `merge-design-critic-traces.py` exactly:
  * Reads sibling `design-consistency-checker-batch*.json` traces via the
    shared `select_latest_per_page_traces()` helper (parameterized on agent name).
  * Aggregates inconsistencies (deduped by tuple key), pages_reviewed,
    pages_remaining, verdict, severity.
  * Computes `contributing_spawn_indexes` from `.runs/agent-spawn-log.jsonl`
    filtered by run_id + agent + hook=skill-agent-gate (state-completion-gate.sh:261-283 contract).
  * Writes the aggregate `design-consistency-checker.json` with
    `provenance="lead-merge"` so the existing `aggregate_ok` hard-gate
    predicate (`evaluate-hard-gate-predicates.py:131-174`) accepts it.

The invocation pattern is tied to the
`ALLOWED_REGEX_MERGE_DESIGN_CONSISTENCY_CHECKER` allowlist in
`.claude/hooks/agent-trace-write-guard.sh` — do not rename or move.

Exit codes:
  0 — merge succeeded, aggregate trace written
  1 — no per-batch traces found (nothing to merge)
  2 — per-batch trace parse error

Usage:
  python3 .claude/scripts/merge-design-consistency-checker-traces.py
"""
import datetime
import json
import os
import sys

# Severity ranking for max-of aggregation
_SEVERITY_RANK = {"none": 0, "minor": 1, "major": 2}


def main() -> int:
    traces_dir = ".runs/agent-traces"
    aggregate_path = os.path.join(traces_dir, "design-consistency-checker.json")

    # 1. Find sibling per-batch traces via shared helper.
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
    from design_critic_trace_selector import select_latest_per_page_traces  # noqa: E402
    siblings = select_latest_per_page_traces(traces_dir, "design-consistency-checker")

    if not siblings:
        sys.stderr.write(
            "merge-design-consistency-checker-traces: no sibling traces at "
            f"{traces_dir}/design-consistency-checker-*.json\n"
        )
        return 1

    # 2. Read each batch trace.
    batch_data = []
    for path in siblings:
        try:
            with open(path) as f:
                batch_data.append(json.load(f))
        except (OSError, json.JSONDecodeError) as exc:
            sys.stderr.write(
                f"merge-design-consistency-checker-traces: cannot parse {path}: {exc}\n"
            )
            return 2

    # 3. Read run_id from active context (verify-context.json).
    run_id = ""
    try:
        with open(".runs/verify-context.json") as f:
            run_id = json.load(f).get("run_id", "")
    except Exception:
        pass

    # 4. Aggregate inconsistencies (dedupe by tuple key).
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for b in batch_data:
        for inc in (b.get("inconsistencies") or []):
            key = (
                inc.get("check"),
                tuple(sorted(inc.get("pages") or [])),
                inc.get("severity"),
                inc.get("detail"),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(inc)

    # 5. Aggregate scalar fields.
    pages_reviewed_total = 0
    pages_remaining_set: set[str] = set()
    any_partial = False
    severities: list[str] = []
    for b in batch_data:
        # pages_reviewed may be list or count; normalize
        pr = b.get("pages_reviewed")
        if isinstance(pr, list):
            pages_reviewed_total += len(pr)
        elif isinstance(pr, int):
            pages_reviewed_total += pr
        else:
            # fall back to pages_reviewed_count if present
            prc = b.get("pages_reviewed_count")
            if isinstance(prc, int):
                pages_reviewed_total += prc
        rem = b.get("pages_remaining") or []
        if isinstance(rem, list):
            pages_remaining_set.update(rem)
        if b.get("partial"):
            any_partial = True
        sv = b.get("severity")
        if isinstance(sv, str):
            severities.append(sv)

    inconsistent_count = len(deduped)
    verdict = "fail" if inconsistent_count > 0 else "pass"
    severity = "none"
    if severities:
        severity = max(severities, key=lambda s: _SEVERITY_RANK.get(s, 0))

    # 6. Compute contributing_spawn_indexes from agent-spawn-log.jsonl.
    spawn_log_path = ".runs/agent-spawn-log.jsonl"
    contributing: list[int] = []
    if run_id and os.path.exists(spawn_log_path):
        try:
            with open(spawn_log_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if (
                        rec.get("agent") == "design-consistency-checker"
                        and rec.get("run_id") == run_id
                        and rec.get("hook") == "skill-agent-gate"
                        and rec.get("spawn_index") is not None
                    ):
                        contributing.append(int(rec["spawn_index"]))
        except OSError:
            pass
    if not contributing:
        # Fallback for legacy / integration-test runs without a spawn log.
        contributing = list(range(len(siblings)))

    # 7. Build aggregate trace per AOC v1.1 lead-merge contract.
    merged = {
        "agent": "design-consistency-checker",
        "verdict": verdict,
        "result": "count_summary",
        "status": "completed",
        "provenance": "lead-merge",
        "partial": any_partial,
        "checks_performed": [
            "C1_color", "C2_typography", "C3_spacing", "C4_component", "C5_layout",
        ],
        "inconsistencies": deduped,
        "inconsistent_count": inconsistent_count,
        "pages_reviewed": pages_reviewed_total,
        "pages_remaining": sorted(pages_remaining_set),
        "severity": severity,
        "contributing_spawn_indexes": sorted(set(contributing)),
        "coverage_provider": ".runs/consistency-check-prepass.json",
        "run_id": run_id,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    # 8. Write directly (sanctioned via agent-trace-write-guard.sh allowlist).
    with open(aggregate_path, "w") as f:
        json.dump(merged, f)
    print(
        f"merge-design-consistency-checker-traces: wrote {aggregate_path} "
        f"(batches={len(siblings)}, pages={pages_reviewed_total}, verdict={verdict}, "
        f"inconsistent_count={inconsistent_count})"
    )

    # 9. Best-effort telemetry append for multi-batch attestation observability (#1257).
    # Raw-fields record (no precomputed `attesting` flag — helper computes the closure
    # criterion at READ time). Skipped on single-batch path and when run_id is absent
    # (manual / integration-test runs without skill context).
    prepass_p = ".runs/consistency-check-prepass.json"
    prepass_data = None
    if os.path.exists(prepass_p):
        try:
            with open(prepass_p) as pf:
                prepass_data = json.load(pf)
        except (OSError, json.JSONDecodeError):
            prepass_data = None
    partition = prepass_data.get("partition") if prepass_data else None
    partition_size = len(partition) if isinstance(partition, list) else 0
    if partition_size > 1 and run_id:
        record = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "run_id": run_id,
            "provenance": "lead-merge",
            "partition_size": partition_size,
            "contributing_spawn_indexes_count": len(contributing),
            "contributing_spawn_indexes": sorted(set(contributing)),
            "pages_reviewed_total": pages_reviewed_total,
            "verdict": verdict,
            "status": "completed",
        }
        try:
            os.makedirs(".runs", exist_ok=True)
            with open(".runs/consistency-soak-telemetry.jsonl", "a") as tf:
                tf.write(json.dumps(record) + "\n")
        except OSError:
            pass  # telemetry must not break merger
    return 0


if __name__ == "__main__":
    sys.exit(main())
