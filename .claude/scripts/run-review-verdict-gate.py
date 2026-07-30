#!/usr/bin/env python3
"""run-review-verdict-gate.py — executable extraction of
.claude/patterns/review-verdict-gate.md's enforce_review_verdict procedure.

Invoked by states (verify state-2, state-3c) after a reviewer agent's
trace lands. Walks the trace's review_method fields (top-level or in
per_*_reviews arrays), enforces the per-agent policy table, and writes a
review_method_gate_evaluated: true sentinel that downstream VERIFY
commands assert.

Idempotent: re-invocation on a trace that already has the sentinel is a
no-op. Safe to run unconditionally from state ACTIONS.

Usage:
  python3 .claude/scripts/run-review-verdict-gate.py <trace_path> <agent_name>

Exit codes:
  0 — sentinel written (with or without corrections), or trace already
      had sentinel (no-op).
  1 — trace path missing or unparsable.
  2 — invalid arguments.
"""
from __future__ import annotations

import json
import os
import sys
from urllib.parse import urlparse


# SHARED:AUTH_PATHS — canonical set, must match
# .claude/patterns/render-review-detection.md and
# .claude/patterns/review-verdict-gate.md. Drift enforced by
# .claude/scripts/tests/test_auth_paths_drift.py.
AUTH_PATHS = {"/login", "/signup", "/auth/callback", "/auth/reset-password"}


# Per-agent policy. Keys: (agent, review_method, final_path_bucket).
# final_path_bucket: "auth" if final_path ∈ AUTH_PATHS, "non-auth" otherwise,
# or "any" for policies that don't depend on path.
POLICY = {
    # ux-journeyer: per_step_reviews
    ("ux-journeyer", "rendered-authed", "any"): {"per_step_status": "pass"},
    ("ux-journeyer", "rendered-demo", "any"): {"per_step_status": "pass"},
    ("ux-journeyer", "source-only", "auth"): {"per_step_status": "dead-end-auth"},
    ("ux-journeyer", "source-only", "non-auth"): {"per_step_status": "dead-end"},
    ("ux-journeyer", "unknown", "any"): {"per_step_status": "error"},
    ("ux-journeyer", "prereq-unmet", "any"): {
        "per_step_status": "blocked",
        "top_level_verdict": "blocked",
    },

    # behavior-verifier: per_behavior_reviews
    ("behavior-verifier", "rendered-authed", "any"): {"per_item_verdict": "PASS"},
    ("behavior-verifier", "rendered-demo", "any"): {"per_item_verdict": "PASS"},
    ("behavior-verifier", "source-only", "auth"): {"per_item_verdict": "FAIL"},
    ("behavior-verifier", "source-only", "non-auth"): {"per_item_verdict": "DEGRADED"},
    ("behavior-verifier", "unknown", "any"): {"per_item_verdict": "FAIL"},
    ("behavior-verifier", "prereq-unmet", "any"): {"per_item_verdict": "SKIPPED"},

    # accessibility-scanner: per_page_reviews — current contract is
    # "skip page", enforced inside accessibility-scanner.md procedure.
    # The gate here only asserts the sentinel is written; no verdict
    # rewrite is performed (existing skip contract is unchanged).
}


def bucket_final_path(review_evidence: dict | None) -> str:
    if not review_evidence:
        return "any"
    final_url = review_evidence.get("final_url")
    if not final_url:
        return "any"
    try:
        path = urlparse(final_url).path
    except Exception:
        return "any"
    return "auth" if path in AUTH_PATHS else "non-auth"


def lookup_policy(agent: str, review_method: str, review_evidence: dict | None) -> dict | None:
    bucket = bucket_final_path(review_evidence)
    for key in [(agent, review_method, bucket), (agent, review_method, "any")]:
        if key in POLICY:
            return POLICY[key]
    return None


def enforce_review_verdict(trace_path: str, agent: str) -> dict:
    if not os.path.exists(trace_path):
        return {"corrections_applied": 0, "skipped_reason": "trace-missing"}

    with open(trace_path) as f:
        try:
            trace = json.load(f)
        except json.JSONDecodeError as e:
            return {"corrections_applied": 0, "skipped_reason": f"json-decode-error: {e}"}

    # Idempotency guard
    if trace.get("review_method_gate_evaluated") is True:
        return {"corrections_applied": 0, "skipped_reason": "already-evaluated"}

    corrections: list[dict] = []

    # Walk fan-out arrays in fixed order
    array_keys = ["per_step_reviews", "per_behavior_reviews", "per_page_reviews"]
    for array_key in array_keys:
        entries = trace.get(array_key)
        if not isinstance(entries, list):
            continue
        for i, entry in enumerate(entries):
            rm = entry.get("review_method")
            if not rm:
                # Forward-compat: entries without review_method pass through
                continue
            policy = lookup_policy(agent, rm, entry.get("review_evidence") or {})
            if not policy:
                continue

            # Per-item verdict (behavior-verifier)
            if "per_item_verdict" in policy:
                required = policy["per_item_verdict"]
                emitted = entry.get("verdict")
                if emitted and emitted != required:
                    corrections.append({
                        "location": f"{array_key}[{i}]",
                        "review_method": rm,
                        "original_verdict": emitted,
                        "corrected_to": required,
                    })
                    entry["verdict"] = required
                elif not emitted:
                    entry["verdict"] = required

            # Per-step status (ux-journeyer)
            if "per_step_status" in policy:
                required = policy["per_step_status"]
                emitted = entry.get("status")
                if emitted and emitted != required:
                    corrections.append({
                        "location": f"{array_key}[{i}]",
                        "review_method": rm,
                        "original_status": emitted,
                        "corrected_to": required,
                    })
                    entry["status"] = required
                elif not emitted:
                    entry["status"] = required

            # Top-level verdict (e.g., prereq-unmet → blocked)
            if "top_level_verdict" in policy:
                required_top = policy["top_level_verdict"]
                emitted_top = trace.get("verdict")
                if emitted_top and emitted_top != required_top:
                    corrections.append({
                        "location": "top-level",
                        "review_method": rm,
                        "original_verdict": emitted_top,
                        "corrected_to": required_top,
                    })
                    trace["verdict"] = required_top

    trace["review_method_gate_evaluated"] = True
    if corrections:
        existing = trace.get("review_method_gate_corrections") or []
        trace["review_method_gate_corrections"] = existing + corrections

    with open(trace_path, "w") as f:
        json.dump(trace, f, indent=2)

    return {"corrections_applied": len(corrections)}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            "usage: python3 run-review-verdict-gate.py <trace_path> <agent_name>",
            file=sys.stderr,
        )
        sys.exit(2)
    result = enforce_review_verdict(sys.argv[1], sys.argv[2])
    print(json.dumps(result))
    if result.get("skipped_reason") == "trace-missing":
        sys.exit(1)
