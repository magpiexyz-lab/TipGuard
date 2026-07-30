#!/usr/bin/env python3
"""merge-landing-critic-traces.py — Pre-aggregator for the landing-critic split (#1468).

Reads `landing-sections-critic.json` and `landing-images-critic.json` from
`.runs/agent-traces/` and aggregates them into the canonical
`design-critic-landing.json` so the outer `merge-design-critic-traces.py`
treats landing as a single per-page sibling (same shape as non-landing
`design-critic-<page>.json` traces).

Field ownership table (closes round-2 critic concern 2e082f2e941f from
the originating /solve --defect run):

  sections-critic provides:
    min_score, verdict, result, sections_below_8, weakest_page,
    pre_existing_debt, fixes_applied (section), unresolved_sections,
    image_issues_for_landing (observation channel to images-critic),
    review_method, review_evidence

  images-critic provides:
    candidates_tried, new_candidates_generated, unresolved_images,
    image_scores, image_fixes, images_evaluated

  Aggregator computes:
    pages_reviewed = 1
    page = "landing"
    provenance = "lead-merge"
    partial = sections.partial OR images.partial
    degraded_reason = "; ".join(filter(None, [sections.degraded_reason, images.degraded_reason]))
    recovery_validated = False  (Stage-1c stamps later)
    contributing_spawn_indexes = sorted spawn-log indexes for both agents
    fixes = sections.fixes + images.fixes
    workarounds = sections.workarounds + images.workarounds (deduped)
    template_gap_observed = sections.template_gap_observed + images.template_gap_observed (deduped)
    checks_performed = sections.checks_performed + images.checks_performed (deduped)

The invocation pattern is tied to the
`ALLOWED_REGEX_MERGE_LANDING_CRITIC` allowlist in
`.claude/hooks/agent-trace-write-guard.sh` — do not rename or move.

Exit codes:
  0 — merge succeeded, aggregate trace written
  1 — one or both sub-traces absent (lead must investigate)
  2 — sub-trace parse error

Usage:
  python3 .claude/scripts/merge-landing-critic-traces.py
"""
import datetime
import json
import os
import sys


def _load_trace(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _is_sparse(trace: dict | None) -> bool:
    """Return True when a trace is sparse (init-stub survived). The aggregator
    surfaces this as a friction signal rather than silently zero-filling.

    Matches the `sparse-trace` candidate kind emitted by
    `enumerate-pending-retrospective-findings.py._candidates_from_sparse_traces`
    (Step 2 of the OARC PR)."""
    if not isinstance(trace, dict):
        return True
    if trace.get("status") == "started" and trace.get("verdict") is None:
        return True
    return False


def main() -> int:
    traces_dir = ".runs/agent-traces"
    sections_path = os.path.join(traces_dir, "landing-sections-critic.json")
    images_path = os.path.join(traces_dir, "landing-images-critic.json")
    aggregate_path = os.path.join(traces_dir, "design-critic-landing.json")

    sections = _load_trace(sections_path)
    images = _load_trace(images_path)

    if sections is None and images is None:
        sys.stderr.write(
            "merge-landing-critic-traces: neither landing-sections-critic.json nor "
            "landing-images-critic.json present; nothing to merge.\n"
        )
        return 1
    if sections is None or images is None:
        missing = "landing-sections-critic.json" if sections is None else "landing-images-critic.json"
        sys.stderr.write(
            f"merge-landing-critic-traces: {missing} is missing — landing critic split "
            "requires BOTH sub-traces. Lead must investigate (one of the two agents "
            "did not complete its spawn cycle).\n"
        )
        return 1

    sections_sparse = _is_sparse(sections)
    images_sparse = _is_sparse(images)
    if sections_sparse or images_sparse:
        which = []
        if sections_sparse:
            which.append("landing-sections-critic")
        if images_sparse:
            which.append("landing-images-critic")
        sys.stderr.write(
            f"merge-landing-critic-traces: WARN — sparse sub-trace(s) detected: "
            f"{', '.join(which)}. Aggregate will reflect available fields only; "
            "the OARC enumerator (sparse-trace-pairing rule) will emit candidate(s) "
            "for the lead to file or suppress.\n"
        )

    # Read run_id from active context (verify-context.json). Mirrors the
    # #1257 convention in merge-design-consistency-checker-traces.py — the
    # merger runs only during /verify and reads the single fixed context
    # (no cross-skill ambiguity to filter by provenance).
    run_id = ""
    try:
        with open(".runs/verify-context.json") as f:  # coherence-allow: provenance-blind-read — fixed verify-context, no cross-skill ambiguity (#1257 merger convention)
            run_id = json.load(f).get("run_id", "")
    except Exception:
        pass

    # ── Field ownership table ──
    # Sections-critic owns the section/layout fields.
    s_get = sections.get if not sections_sparse else (lambda k, d=None: d)
    i_get = images.get if not images_sparse else (lambda k, d=None: d)

    min_score = s_get("min_score")
    sections_below_8 = s_get("sections_below_8")
    weakest_page = s_get("weakest_page", "landing")
    pre_existing_debt = s_get("pre_existing_debt") or []
    unresolved_sections = s_get("unresolved_sections")
    section_review_method = s_get("review_method")
    section_review_evidence = s_get("review_evidence") or {}
    image_issues_for_landing = s_get("image_issues_for_landing") or []

    # Images-critic owns the image fields.
    candidates_tried = i_get("candidates_tried")
    new_candidates_generated = i_get("new_candidates_generated")
    unresolved_images = i_get("unresolved_images") or []
    image_scores = i_get("image_scores") or []
    image_fixes = i_get("image_fixes")
    images_evaluated = i_get("images_evaluated")
    # images-critic's review_method takes precedence for image-context evaluation
    image_review_method = i_get("review_method")

    # ── Verdict aggregation ──
    # If either sub-verdict is "unresolved" → aggregate unresolved.
    # If either is "fail" → fail.
    # Else → pass.
    section_verdict = s_get("verdict")
    image_verdict = i_get("verdict")
    if "unresolved" in (section_verdict, image_verdict):
        verdict = "unresolved"
        result = None
    elif "fail" in (section_verdict, image_verdict):
        verdict = "fail"
        result = "partial"
    else:
        verdict = "pass"
        # result: clean if both clean, else partial/fixed per worst
        section_result = s_get("result", "clean")
        image_result = i_get("result", "clean")
        if "partial" in (section_result, image_result):
            result = "partial"
        elif "fixed" in (section_result, image_result):
            result = "fixed"
        else:
            result = "clean"

    # ── partial / degraded_reason aggregation ──
    section_partial = bool(s_get("partial"))
    image_partial = bool(i_get("partial"))
    partial = section_partial or image_partial or sections_sparse or images_sparse
    reasons: list[str] = []
    if s_get("degraded_reason"):
        reasons.append(f"sections:{s_get('degraded_reason')}")
    if i_get("degraded_reason"):
        reasons.append(f"images:{i_get('degraded_reason')}")
    if sections_sparse:
        reasons.append("sections:sparse-trace")
    if images_sparse:
        reasons.append("images:sparse-trace")
    degraded_reason = "; ".join(reasons) if reasons else None

    # ── Sanctioned-skip propagation (closes state-registry.json line 22 #1129 check) ──
    # The legacy landing_sd check reads `design-critic-landing.json.provenance == "self-degraded"
    # AND recovery_validated is True` to grant a Step 5.5 confirmation pass. When the
    # images-critic sub-trace is a sanctioned legitimate skip (empty-boundary-fast-path,
    # demo-mode-fixture-short-circuit, redirect-source-only) AND has been recovery-validated
    # by Stage-1c BEFORE the merger runs, we propagate the self-degraded semantic to the
    # aggregate so the legacy check still accepts the skip without manual override.
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
    try:
        from sanctioned_degraded_reasons import SANCTIONED_DEGRADED_REASONS
    except ImportError:
        SANCTIONED_DEGRADED_REASONS = frozenset()
    images_prov = i_get("provenance")
    images_dr = i_get("degraded_reason")
    images_rv = bool(i_get("recovery_validated"))
    propagate_sanctioned_skip = (
        images_prov in ("self-degraded", "recovery", "lead-on-behalf")
        and images_dr in SANCTIONED_DEGRADED_REASONS
        and images_rv is True
    )

    # ── checks_performed (deduped) ──
    checks = []
    for src in (s_get("checks_performed") or [], i_get("checks_performed") or []):
        if isinstance(src, list):
            for c in src:
                if c not in checks:
                    checks.append(c)

    # ── fixes (concatenated, sections first) ──
    fixes: list = []
    for src in (s_get("fixes") or [], i_get("fixes") or []):
        if isinstance(src, list):
            fixes.extend(src)

    # ── AOC v1.3 fields (deduped) ──
    workarounds: list = []
    template_gap_observed: list = []
    seen_w: set = set()
    seen_t: set = set()
    for trace in (sections if not sections_sparse else {}, images if not images_sparse else {}):
        for entry in (trace.get("workarounds") or []) if isinstance(trace, dict) else []:
            key = json.dumps(entry, sort_keys=True) if isinstance(entry, dict) else str(entry)
            if key not in seen_w:
                workarounds.append(entry)
                seen_w.add(key)
        for entry in (trace.get("template_gap_observed") or []) if isinstance(trace, dict) else []:
            key = json.dumps(entry, sort_keys=True) if isinstance(entry, dict) else str(entry)
            if key not in seen_t:
                template_gap_observed.append(entry)
                seen_t.add(key)

    # ── contributing_spawn_indexes from spawn-log ──
    contributing: list[int] = []
    spawn_log = ".runs/agent-spawn-log.jsonl"
    if os.path.isfile(spawn_log) and run_id:
        try:
            with open(spawn_log) as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if (
                        rec.get("agent") in ("landing-sections-critic", "landing-images-critic")
                        and rec.get("run_id") == run_id
                        and rec.get("hook") == "skill-agent-gate"
                        and rec.get("spawn_index") is not None
                    ):
                        contributing.append(int(rec["spawn_index"]))
        except OSError:
            pass

    # ── review_method: take section's (image agent inherits); concatenate
    # review_evidence dicts ──
    review_method = section_review_method or image_review_method or "unknown"

    # ── Build aggregate trace per AOC v1.1 lead-merge contract ──
    # Default provenance = lead-merge (aggregate_ok predicate accepts it).
    # When the images-critic sub-trace is a sanctioned skip with recovery_validated,
    # propagate self-degraded + recovery_validated:True to satisfy validated_fallback
    # AND the legacy state-registry.json line 22 landing_sd check.
    aggregate_provenance = "self-degraded" if propagate_sanctioned_skip else "lead-merge"
    aggregate_recovery_validated = True if propagate_sanctioned_skip else False
    merged = {
        "agent": "design-critic",  # outer merger keys on agent name
        "verdict": verdict,
        "result": result,
        "status": "completed",
        "provenance": aggregate_provenance,
        "partial": partial,
        "checks_performed": checks,
        "pages_reviewed": 1,
        "page": "landing",
        "weakest_page": weakest_page,
        "min_score": min_score,
        "sections_below_8": sections_below_8,
        "fixes_applied": len(fixes),
        "unresolved_sections": unresolved_sections,
        "pre_existing_debt": pre_existing_debt,
        "image_issues_for_landing": image_issues_for_landing,
        "candidates_tried": candidates_tried,
        "new_candidates_generated": new_candidates_generated,
        "unresolved_images": unresolved_images,
        "image_scores": image_scores,
        "image_fixes": image_fixes,
        "images_evaluated": images_evaluated,
        "review_method": review_method,
        "review_evidence": section_review_evidence,
        "fixes": fixes,
        "workarounds": workarounds,
        "template_gap_observed": template_gap_observed,
        "recovery_validated": aggregate_recovery_validated,
        "contributing_spawn_indexes": sorted(set(contributing)),
        "sub_traces": ["landing-sections-critic.json", "landing-images-critic.json"],
        "run_id": run_id,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if degraded_reason:
        merged["degraded_reason"] = degraded_reason

    # Write directly (sanctioned via agent-trace-write-guard.sh allowlist).
    with open(aggregate_path, "w") as f:
        json.dump(merged, f)
    print(
        f"merge-landing-critic-traces: wrote {aggregate_path} "
        f"(verdict={verdict}, partial={partial}, "
        f"min_score={min_score}, candidates_tried={candidates_tried}, "
        f"image_fixes={image_fixes})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
