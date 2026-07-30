#!/usr/bin/env python3
"""merge-design-critic-traces.py — Official merge script for verify STATE 3b.

Merges per-page `.runs/agent-traces/design-critic-*.json` traces into the
aggregate `.runs/agent-traces/design-critic.json`. Previously inlined in
state-3b-quality-gate.md but extracted to this dedicated script so the
agent-trace-write-guard.sh allowlist can authorise exactly this write
(issue #1045). The script's invocation pattern is tied to the guard's
ALLOWED_REGEX_MERGE_DESIGN_CRITIC — do not rename or move.

Preserves every field the inline merge produced, including:
  - pages_reviewed, min_score, min_score_all, verdict
  - checks_performed, sections_below_8, fixes_applied, unresolved_sections
  - per_page_review_methods, per_page_review_evidence
  - review_method_gate_corrections (tight gate auto-corrections)
  - pre_existing_debt, fixes
  - shared_fixes_applied (Stage 1c shared-component verdict upgrade)
  - timestamp, run_id

Exit codes:
  0 — merge succeeded, aggregate trace written
  1 — no per-page traces found (nothing to merge)
  2 — per-page trace parse error

Usage:
  python3 .claude/scripts/merge-design-critic-traces.py
"""
import datetime
import glob
import json
import os
import sys

# Import the shared sanctioned-skip list from `.claude/scripts/lib/`.
# #1265 centralised the list here; the import indirection in slice 0 of the
# OARC PR makes both this merger AND the GECR `recovery_skip_extraction`
# matcher (`gate_evidence_runner.py`) reference the same source of truth,
# preventing the "N+1 sanctioned reason will repeat the defect" class. The
# carve-out at line ~190 of the loop body and the validated_fallback skip
# both read this constant. Adding a new reason: edit
# `.claude/scripts/lib/sanctioned_degraded_reasons.py` and document in
# `.claude/agents/design-critic.md` Rendered-Review Contract.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from sanctioned_degraded_reasons import SANCTIONED_DEGRADED_REASONS  # noqa: E402

# #1265: provenance values whose self-degraded-or-recovery state is
# acceptable as a sibling-class exception in worst-wins aggregation
# when accompanied by recovery_validated=True. Mirrors the
# validated_fallback predicate in
# .claude/scripts/evaluate-hard-gate-predicates.py — the two artifacts
# must stay coherent (a sibling that satisfies the hard-gate predicate
# also must not pull down the merged verdict).
_VALIDATED_FALLBACK_PROVENANCES = frozenset({
    "self-degraded",
    "recovery",
    "lead-on-behalf",
})


def _coalesce(value, default):
    # `dict.get(k, default)` returns `default` only when k is absent;
    # an explicit JSON `null` returns None. `min(int, None)` and
    # `int + None` then crash. Use this helper anywhere a numeric
    # default must apply to BOTH absent-key and explicit-null cases.
    # Critically: distinct from `value or default`, which also coerces
    # legitimate 0 to default (procedures/design-critic.md uses
    # min_score=0 as the empty-boundary sentinel).
    return default if value is None else value


def main() -> int:
    traces_dir = ".runs/agent-traces"
    per_page_pattern = os.path.join(traces_dir, "design-critic-*.json")
    # #1274 / round-2 critic C12: dedupe by page_key; keep latest epoch per
    # page so post-fix re-evaluations supersede stale OLD traces. Both
    # consumers (this merger AND aggregate_ok in evaluate-hard-gate-predicates)
    # call the same helper to stay consistent.
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
    from design_critic_trace_selector import select_latest_per_page_traces  # noqa: E402
    batches = select_latest_per_page_traces(traces_dir, "design-critic")

    if not batches:
        sys.stderr.write(
            f"merge-design-critic-traces: no per-page traces at {per_page_pattern}\n"
        )
        return 1

    run_id = ""
    try:
        with open(".runs/verify-context.json") as f:
            run_id = json.load(f).get("run_id", "")
    except Exception:
        pass

    merged = {
        "agent": "design-critic",
        "pages_reviewed": 0,
        "min_score": 10,
        "verdict": "pass",
        "checks_performed": [],
        "pages": len(batches),
        "consistency_fixes": 0,
        "sections_below_8": 0,
        "fixes_applied": 0,
        "unresolved_sections": 0,
        "min_score_all": 10,
        "pre_existing_debt": [],
        "fixes": [],
        "per_page_review_methods": {},
        "per_page_review_evidence": [],
        "run_id": run_id,
    }
    worst_verdicts = {"unresolved": 3, "fixed": 2, "pass": 1}
    shared_base = os.path.join(traces_dir, "design-critic-shared.json")
    aggregate_path = os.path.join(traces_dir, "design-critic.json")

    # Track per-page latest trace metadata so the fix-ledger crediting
    # block below can suppress double-counting (#1274 round-2 critic Q5).
    # Keyed by page_key. Only set when the latest trace satisfies the
    # post-fix precedence rule (epoch > 0 AND unresolved_sections == 0).
    post_fix_resolved_pages: set[str] = set()

    for b in batches:
        # The selector helper already excludes design-critic-shared.json
        # and the design-critic.json aggregate; no further skips needed.
        try:
            with open(b) as f:
                d = json.load(f)
        except Exception as exc:
            sys.stderr.write(f"merge-design-critic-traces: cannot parse {b}: {exc}\n")
            return 2

        # Sparse-trace tolerance (Step 5a of OARC PR #1468/#1456): when a
        # sub-trace is an init-stub that survived (status=started + no verdict
        # field), skip it from aggregation with a warning. The OARC enumerator
        # (`enumerate-pending-retrospective-findings.py._candidates_from_sparse_traces`)
        # will emit a sparse-trace candidate row for the lead to file/suppress
        # — no need to crash here or silently zero-fill fields.
        if d.get("status") == "started" and d.get("verdict") is None:
            sys.stderr.write(
                f"merge-design-critic-traces: WARN — sparse sub-trace at {b} "
                f"(status=started, no verdict). Skipping from aggregation; OARC "
                f"sparse-trace-pairing rule will require paired observation.\n"
            )
            continue

        merged["pages_reviewed"] += _coalesce(d.get("pages_reviewed"), 1)
        merged["min_score"] = min(merged["min_score"], _coalesce(d.get("min_score"), 10))
        merged["min_score_all"] = min(merged["min_score_all"], _coalesce(d.get("min_score_all"), 10))
        merged["checks_performed"].extend(d.get("checks_performed", []))
        merged["sections_below_8"] += _coalesce(d.get("sections_below_8"), 0)
        merged["fixes_applied"] += _coalesce(d.get("fixes_applied"), 0)
        merged["unresolved_sections"] += _coalesce(d.get("unresolved_sections"), 0)

        # render-review-detection aggregation (render-review-detection.md)
        page_key = (
            d.get("page")
            or d.get("weakest_page")
            or os.path.basename(b).replace("design-critic-", "").replace(".json", "")
        )
        # #1274: post-fix precedence — when the latest trace for this page
        # is an --epoch>0 re-evaluation AND its unresolved_sections is 0,
        # the page is authoritatively resolved by visual re-validation.
        # The fix-ledger crediting block below MUST NOT additionally
        # decrement unresolved_sections for this page (would over-credit).
        try:
            _trace_epoch = int(d.get("epoch") or 0)
        except (TypeError, ValueError):
            _trace_epoch = 0
        if _trace_epoch > 0 and _coalesce(d.get("unresolved_sections"), 0) == 0:
            post_fix_resolved_pages.add(page_key)
        rm = d.get("review_method")
        prov_here = d.get("provenance", "self")
        degraded_reason = d.get("degraded_reason", "")
        if rm:
            merged["per_page_review_methods"][page_key] = rm
            merged["per_page_review_evidence"].append(
                {"page": page_key, **(d.get("review_evidence") or {})}
            )
            # Invariant enforcement (tight gate): source-only/unknown MUST be
            # unresolved. When an agent emits a non-unresolved verdict on a
            # degraded render, self-heal the in-memory trace AND log so the
            # agent bug surfaces.
            #
            # #1042 Session C carve-out: a self-degraded trace with
            # degraded_reason="demo-mode-fixture-short-circuit" is the
            # sanctioned DEMO_MODE fixture short-circuit path — it already
            # emits verdict=unresolved (from write-degraded-trace.py
            # --verdict unresolved), so the self-heal would be a no-op.
            # Skip the self-heal write entirely for this path so the
            # audit log is not polluted with phantom "corrections".
            original_verdict = d.get("verdict", "")
            if (
                rm in ("source-only", "unknown")
                and original_verdict.lower() != "unresolved"
                and not (
                    prov_here == "self-degraded"
                    and degraded_reason in SANCTIONED_DEGRADED_REASONS
                )
            ):
                print(
                    "WARN: [" + page_key + "] review_method=" + rm
                    + " but verdict=" + original_verdict
                    + "; forcing verdict=unresolved per Rendered-Review Contract"
                )
                d["verdict"] = "unresolved"
                merged.setdefault("review_method_gate_corrections", []).append(
                    {"page": page_key, "review_method": rm, "original_verdict": original_verdict}
                )
            if (
                prov_here == "self-degraded"
                and degraded_reason == "demo-mode-fixture-short-circuit"
            ):
                merged.setdefault("demo_mode_short_circuit_pages", []).append(page_key)
            if (
                prov_here == "self-degraded"
                and degraded_reason == "empty-boundary-fast-path"
            ):
                merged.setdefault("empty_boundary_fast_path_pages", []).append(page_key)

        debt = d.get("pre_existing_debt", [])
        if isinstance(debt, list):
            merged["pre_existing_debt"].extend(debt)
        page_fixes = d.get("fixes", [])
        if isinstance(page_fixes, list):
            merged["fixes"].extend(page_fixes)

        # Per-page provenance propagation for the aggregate_ok predicate
        # (evaluate-hard-gate-predicates.py). The predicate re-reads per-page trace files
        # directly so this aggregate view is informational, but it helps
        # downstream consumers (q-score, PR body) reason about which pages
        # landed in which bucket without re-globbing. (#1042)
        merged.setdefault("per_page_provenance", {})[page_key] = prov_here
        merged.setdefault("per_page_recovery_validated", {})[page_key] = bool(
            d.get("recovery_validated", False)
        )
        srv = d.get("source_review_verdict")
        if srv is not None:
            merged.setdefault("per_page_source_review_verdict", {})[page_key] = srv
        if degraded_reason:
            merged.setdefault("per_page_degraded_reason", {})[page_key] = degraded_reason

        # #1265: skip validated_fallback siblings in worst-wins so an unresolved
        # sibling that satisfies the hard-gate validated_fallback predicate
        # does not pull down the aggregate verdict (cascade-blocking downstream
        # fixers via false-positive design-ux-merge.json verdict=fail). Track
        # them in `validated_fallback_pages` for downstream observability.
        # When ALL effective siblings are validated_fallback, the loop leaves
        # merged["verdict"] at "pass" — aggregate_ok validates per-sibling
        # independently so this is consistent with the hard-gate contract,
        # but we mark `all_validated_fallback=True` after the loop so consumers
        # (state-7b Q-score, verify-report) can distinguish "all-pass" from
        # "all-validated-fallback-pass."
        recovery_validated = bool(d.get("recovery_validated", False))
        is_validated_fallback = (
            prov_here in _VALIDATED_FALLBACK_PROVENANCES
            and recovery_validated
        )
        if is_validated_fallback:
            merged.setdefault("validated_fallback_pages", []).append(page_key)
        else:
            bv = d.get("verdict", "pass").lower()
            if worst_verdicts.get(bv, 0) > worst_verdicts.get(merged["verdict"], 0):
                merged["verdict"] = bv
                merged["weakest_page"] = d.get("weakest_page", d.get("page", ""))
        if d.get("retry_attempted"):
            merged["retry_attempted"] = True

    # #1265: when ALL effective siblings (excluding shared/aggregate) are
    # validated_fallback, mark the aggregate so downstream consumers can
    # distinguish "all-pass" from "all-validated-fallback-pass." Verdict
    # stays "pass" — aggregate_ok validates per-sibling, so this is the
    # contract-correct shape.
    effective_siblings = [
        b for b in batches if b not in (shared_base, aggregate_path)
    ]
    validated_fallback_pages = merged.get("validated_fallback_pages") or []
    if effective_siblings and len(validated_fallback_pages) == len(effective_siblings):
        merged["all_validated_fallback"] = True

    # #1274: Lead-applied shared-fix credit at merge time.
    # When the lead applies shared-component fixes during state-3a Stage 1b
    # (logged via write-fix-ledger.py --lead-fix), per-page design-critic
    # traces are immutable post-write and still record the pre-fix
    # `unresolved_shared` count. Consult fix-ledger.jsonl to credit those
    # lead-applied fixes against the aggregate's unresolved_sections.
    #
    # Filter notes:
    #   - provenance is filtered by the LITERAL string 'lead' (not 'lead-fix';
    #     write-fix-ledger.py:373 writes literal 'lead' for --lead-fix mode)
    #     plus 'lead-on-behalf' for the case where lead transcribed an
    #     agent's reported aggregate fix.
    #   - run_id filter prevents cross-run pollution per #1267 hardening.
    #   - per-page traces remain immutable; only the merged aggregate is
    #     corrected. The audit trail lives in merged["lead_fix_corrections"].
    ledger_path = ".runs/fix-ledger.jsonl"
    lead_fixed_files: set[str] = set()
    if os.path.exists(ledger_path):
        with open(ledger_path) as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line:
                    continue
                try:
                    _e = json.loads(_line)
                except Exception:
                    continue
                if not run_id or _e.get("run_id") != run_id:
                    continue
                if _e.get("provenance") in ("lead", "lead-on-behalf"):
                    _fp = _e.get("file")
                    if _fp:
                        lead_fixed_files.add(_fp)

    lead_fix_corrections: list = []
    if lead_fixed_files:
        for batch in batches:
            # `batches` already excludes shared and aggregate via the helper.
            try:
                with open(batch) as _f:
                    _d = json.load(_f)
            except Exception:
                continue
            for _si in _d.get("shared_issues", []) or []:
                if _si.get("file") in lead_fixed_files:
                    page_key = (
                        _d.get("page")
                        or _d.get("weakest_page")
                        or os.path.basename(batch)
                        .replace("design-critic-", "")
                        .replace(".json", "")
                    )
                    # #1274 post-fix precedence: when the latest trace for
                    # this page is a re-evaluation that already shows
                    # unresolved_sections=0, the visual re-validation is
                    # authoritative — do NOT additionally credit the same
                    # lead-fix or unresolved_sections will go negative.
                    if page_key in post_fix_resolved_pages:
                        continue
                    lead_fix_corrections.append({
                        "page": page_key,
                        "file": _si["file"],
                        "section": _si.get("section"),
                    })
        if lead_fix_corrections:
            merged["lead_fix_corrections"] = lead_fix_corrections
            creditable = len(lead_fix_corrections)
            merged["unresolved_sections"] = max(
                0, merged.get("unresolved_sections", 0) - creditable
            )
            if merged["verdict"] == "unresolved" and merged["unresolved_sections"] == 0:
                merged["verdict"] = "fixed"

    # Stage 1c shared-component verdict upgrade
    if os.path.exists(shared_base):
        try:
            with open(shared_base) as f:
                shared = json.load(f)
        except Exception as exc:
            sys.stderr.write(f"merge-design-critic-traces: cannot parse shared trace: {exc}\n")
            return 2
        shared_v = shared.get("verdict", "").lower()
        shared_fixes = shared.get("fixes_applied", 0)
        merged["shared_fixes_applied"] = shared_fixes
        # If only unresolved issues were shared-component, and shared agent fixed them:
        if merged["verdict"] == "unresolved" and shared_v in ("pass", "fixed"):
            if shared_fixes > 0 and merged["unresolved_sections"] <= shared_fixes:
                merged["verdict"] = "fixed"
                merged["unresolved_sections"] = 0

    merged["timestamp"] = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    # AOC v1 lead-merge aggregate contract (#1042 Session C). The aggregate
    # `design-critic.json` is composed from per-page sibling traces, so it
    # carries provenance="lead-merge" + partial=true (required by
    # artifact-integrity-gate.sh:144-147 for any provenance != self). The
    # aggregate_ok hard-gate predicate keys on `contributing_spawn_indexes`
    # being a non-empty list (and verifies each sibling independently).
    # AOC v1.1 (#1254): status="completed" is required by the schema for
    # downstream consumers that filter on trace.status.
    merged["status"] = "completed"
    merged["provenance"] = "lead-merge"
    merged["partial"] = True
    # contributing_spawn_indexes semantics (state-completion-gate.sh:261-283):
    # count must equal the number of `hook: skill-agent-gate` entries for
    # this base in the current run_id. Match that filter exactly — if we
    # count any entries written by other hooks (or by older log formats),
    # the gate will report "aggregate claims N spawns but spawn-log has M".
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
                        rec.get("agent") == "design-critic"
                        and rec.get("run_id") == run_id
                        and rec.get("hook") == "skill-agent-gate"
                        and rec.get("spawn_index") is not None
                    ):
                        contributing.append(int(rec["spawn_index"]))
        except OSError:
            pass
    if not contributing:
        # Spawn log absent / run_id unresolvable / pre-AOC run — fall back
        # to the per-batch index so the aggregate still has a non-empty
        # list. Each contributing sibling trace is still verified by the
        # aggregate_ok predicate. In a well-formed AOC v1 run the spawn
        # log is always present, so this fallback only fires in
        # integration tests and legacy replays.
        contributing = list(range(len([
            b for b in batches
            if b not in (shared_base, aggregate_path)
        ])))
    merged["contributing_spawn_indexes"] = sorted(set(contributing))

    with open(aggregate_path, "w") as f:
        json.dump(merged, f)
    print(f"merge-design-critic-traces: wrote {aggregate_path} (pages={merged['pages']}, verdict={merged['verdict']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
