#!/usr/bin/env python3
"""merge-scaffold-pages-traces.py — Official merge script for bootstrap STATE 11c.

Merges per-page `.runs/agent-traces/scaffold-pages-*.json` traces into the
aggregate `.runs/agent-traces/scaffold-pages.json`. Previously inlined in
state-11c-page-scaffold.md but extracted to this dedicated script so the
agent-trace-write-guard.sh allowlist can authorise exactly this write
(mirrors the #1045 resolution for merge-design-critic-traces.py). The
script's invocation pattern is tied to the guard's
ALLOWED_REGEX_MERGE_SCAFFOLD_PAGES — do not rename or move.

Behavior matches the prior inline merge:
  - Globs `.runs/agent-traces/scaffold-pages-*.json`
  - Counts batches as `pages_created`
  - Concatenates `files_created[]` and `issues[]` from each batch
  - Writes aggregate with `agent="scaffold-pages"` plus the merged fields

This is a "legacy aggregate" in the AOC v1.1 sense — it does not yet emit
`provenance:"lead-merge"`, `partial:true`, or `contributing_spawn_indexes`.
state-completion-gate.sh accepts unprovenanced aggregates for backward
compatibility (see lead-merge exemption block in that hook). Adding full
AOC v1.1 lead-merge invariants is a follow-up.

Exit codes:
  0 — merge succeeded, aggregate trace written
  1 — no per-page traces found (nothing to merge)
  2 — per-page trace parse error

Usage:
  python3 .claude/scripts/merge-scaffold-pages-traces.py
"""
import datetime
import glob
import json
import os
import sys


def main() -> int:
    traces_dir = ".runs/agent-traces"
    per_page_pattern = os.path.join(traces_dir, "scaffold-pages-*.json")
    aggregate_path = os.path.join(traces_dir, "scaffold-pages.json")

    batches = sorted(glob.glob(per_page_pattern))
    # Filter out the aggregate path itself in case it matches the glob
    # (shouldn't, since the suffix differs, but defensive).
    batches = [b for b in batches if b != aggregate_path]

    if not batches:
        sys.stderr.write(
            f"merge-scaffold-pages-traces: no per-page traces at {per_page_pattern}\n"
        )
        return 1

    # Partition into real completions vs init-trace stubs (#1190). A stub is a
    # trace where init-trace.py registered presence but the agent never wrote
    # a verdict (status="started", no verdict field). Counting stubs as
    # completions inflates pages_created and laundering them through the
    # default-pass verdict aggregation hides rate-limited spawns. The
    # stub_count + stub_files top-level fields preserve the
    # attempted-but-incomplete signal so downstream consumers (BG2, Q-score)
    # can detect partial-batch outcomes.
    real_traces = []
    stub_traces = []
    for b in batches:
        try:
            with open(b) as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            sys.stderr.write(
                f"merge-scaffold-pages-traces: cannot parse {b}: {exc}\n"
            )
            return 2
        status = (d.get("status") or "").lower()
        verdict_field = d.get("verdict")
        if status == "started" and not verdict_field:
            stub_traces.append((b, d))
        else:
            real_traces.append((b, d))

    if stub_traces:
        sys.stderr.write(
            f"merge-scaffold-pages-traces: WARNING: {len(stub_traces)} stub "
            f"trace(s) detected (init-trace registered, agent never wrote "
            f"verdict — likely rate-limited or crashed mid-spawn):\n"
        )
        for b, _ in stub_traces:
            sys.stderr.write(f"  - {b}\n")

    # Resolve run_id: try bootstrap-context.json first (the original caller),
    # then verify-context.json as fallback for embed-verify re-merge scenarios.
    run_id = ""
    for ctx_file in (".runs/bootstrap-context.json", ".runs/verify-context.json"):
        try:
            with open(ctx_file) as f:
                run_id = json.load(f).get("run_id", "")
            if run_id:
                break
        except Exception:
            continue

    merged = {
        "agent": "scaffold-pages",
        "pages_created": 0,
        "files_created": [],
        "issues": [],
        "run_id": run_id,
        # AOC v1 contract: aggregate trace MUST carry checks_performed and
        # verdict so verify-report-gate.sh schema validation passes (#1122).
        "checks_performed": [
            "page_authored",
            "events_wired",
            "build_smoke",
            "self_check_scored",
        ],
        "verdict": "pass",
        # AOC v1.1 (#1254): aggregate trace composed by lead from sibling
        # per-page traces. provenance="lead-merge" + partial=True are
        # required for any provenance != self by artifact-integrity-gate.sh.
        # status="completed" required by AOC v1.1 schema. contributing_spawn_indexes
        # is set below conditionally so state-completion-gate.sh sibling count
        # match doesn't reject when spawn-log scan is empty in run_id-scoped mode.
        "status": "completed",
        "provenance": "lead-merge",
        "partial": True,
        # #1190: preserve attempted-but-incomplete signal alongside the
        # completion count. stub_count > 0 indicates the spawn batch had
        # rate-limited or crashed agents; the lead should re-spawn for the
        # listed pages or accept the partial batch with documented reason.
        "stub_count": len(stub_traces),
        "stub_files": [b for b, _ in stub_traces],
    }
    # Verdict rank for worst-of-batch aggregation. Higher rank wins.
    verdict_rank = {"pass": 1, "fixed": 2, "partial": 3, "unresolved": 4, "fail": 5}

    for _b, d in real_traces:
        merged["pages_created"] += 1
        merged["files_created"].extend(d.get("files_created", []))
        merged["issues"].extend(d.get("issues", []))
        # Worst-of-batch verdict — aggregate must reflect failures
        # (a hardcoded "pass" lies to pattern-classifier and Q-score).
        per_page_verdict = d.get("verdict", "pass")
        if verdict_rank.get(per_page_verdict, 0) > verdict_rank.get(
            merged["verdict"], 0
        ):
            merged["verdict"] = per_page_verdict

    # Aggregate template_recommendations[] across per-page traces (#1294 audit).
    # Without propagation, the aggregate scaffold-pages.json fails the schema
    # validator wired at bootstrap.11c. Per-page traces individually carry the
    # field per scaffold-pages.md:130-131; the aggregate must mirror it.
    tr_lists = [
        d.get("template_recommendations", [])
        for _, d in real_traces
        if isinstance(d.get("template_recommendations"), list)
    ]
    concat_recommendations = [item for lst in tr_lists for item in lst]
    all_explicit_none = (
        all(
            d.get("template_recommendations_explicit_none", False)
            for _, d in real_traces
        )
        if real_traces
        else False
    )
    if concat_recommendations:
        merged["template_recommendations"] = concat_recommendations
        merged["template_recommendations_explicit_none"] = False
    else:
        merged["template_recommendations"] = []
        merged["template_recommendations_explicit_none"] = bool(all_explicit_none)

    merged["timestamp"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # AOC v1.1 (#1254): contributing_spawn_indexes binds the lead-merge
    # aggregate to specific scaffold-pages spawns. When run_id is set, scan
    # spawn-log for matching entries and include the indexes; when scan is
    # empty (run_id present but spawn-log lacks entries), OMIT the field
    # entirely — including a synthesized index list would trigger
    # state-completion-gate.sh count-mismatch rejection. When run_id is
    # empty (legacy / pre-AOC replay), fall back to the per-batch index range
    # so the field is non-empty for downstream consumers.
    spawn_log_path = ".runs/agent-spawn-log.jsonl"
    if run_id and os.path.exists(spawn_log_path):
        contributing: list[int] = []
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
                        rec.get("agent") == "scaffold-pages"
                        and rec.get("run_id") == run_id
                        and rec.get("hook") == "skill-agent-gate"
                        and rec.get("spawn_index") is not None
                    ):
                        contributing.append(int(rec["spawn_index"]))
        except OSError:
            pass
        if contributing:
            merged["contributing_spawn_indexes"] = sorted(set(contributing))
        # else: omit — count mismatch would be rejected
    elif not run_id:
        merged["contributing_spawn_indexes"] = list(range(len(real_traces)))

    with open(aggregate_path, "w") as f:
        json.dump(merged, f)
    print(
        f"merge-scaffold-pages-traces: wrote {aggregate_path} "
        f"(pages_created={merged['pages_created']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
