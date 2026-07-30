#!/usr/bin/env python3
"""check-design-critic-sanctioned.py — detect sanctioned design-critic aggregate.

The merged `.runs/agent-traces/design-critic.json` aggregate has
`provenance="lead-merge"` and may carry `verdict="unresolved"` even when
every contributing per-page sibling is in a sanctioned shape:

  - `provenance == "self"` with normal verdict (regular page review), OR
  - `provenance == "self-degraded"` AND `recovery_validated == true` AND
    `degraded_reason in {"demo-mode-fixture-short-circuit",
                         "empty-boundary-fast-path"}`.

In that case the aggregate verdict is conservatively pulled to "unresolved"
by the worst-verdict pick in `merge-design-critic-traces.py`, but the actual
work is fully accounted for by sanctioned per-page paths. The state-7b
cross-validation gate (`state-registry.json` verify[7b] +
`state-7b-compute-qscore.md` L143) consults this script to decide whether
to require `hard_gate_failure: true`.

Inputs:
  argv[1]: path to design-critic.json aggregate

Exit codes:
  0 — sanctioned (state-7b VERIFY may exempt aggregate from hard_gate_failure)
  1 — not sanctioned (genuine failure — hard_gate_failure required)

The aggregate-level `provenance` MUST be `"lead-merge"` and the per-page
provenance maps MUST be present and non-empty for sanction to be granted —
this avoids accidental sanction of incomplete merges or pre-AOC-v1 traces.
"""
import json
import sys

SANCTIONED_REASONS = {
    "demo-mode-fixture-short-circuit",  # #1042 Sub-branch S1
    "empty-boundary-fast-path",         # #1061 fast-path
}


def is_sanctioned(trace: dict) -> bool:
    if trace.get("provenance") != "lead-merge":
        return False
    ppp = trace.get("per_page_provenance") or {}
    ppr = trace.get("per_page_recovery_validated") or {}
    ppd = trace.get("per_page_degraded_reason") or {}
    if not ppp:
        return False
    for page, prov in ppp.items():
        if prov == "self-degraded":
            if not ppr.get(page, False):
                return False
            if ppd.get(page) not in SANCTIONED_REASONS:
                return False
        elif prov != "self":
            return False
    return True


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("usage: check-design-critic-sanctioned.py <path-to-design-critic.json>\n")
        return 1
    try:
        with open(sys.argv[1]) as f:
            trace = json.load(f)
    except Exception as exc:
        sys.stderr.write(f"check-design-critic-sanctioned: cannot read trace: {exc}\n")
        return 1
    return 0 if is_sanctioned(trace) else 1


if __name__ == "__main__":
    sys.exit(main())
