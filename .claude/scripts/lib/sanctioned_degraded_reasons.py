"""Shared sanctioned-degraded-reasons allowlist.

Sources: #1265 (review_method gate carve-out), #1042 (demo-mode-fixture-short-circuit),
#1061 (empty-boundary-fast-path), #1196 (redirect-source-only opt-in via S2).

Both `.claude/scripts/merge-design-critic-traces.py` (review_method carve-out at
the source-only/unknown verdict gate) AND the GECR `recovery_skip_extraction`
matcher in `.claude/scripts/lib/gate_evidence_runner.py` import from here so
the suppression list cannot drift between the two integration points.

Adding a new reason: append here, document the source PR/issue in the
`.claude/agents/design-critic.md` Rendered-Review Contract or equivalent
sanctioned-skip section, and update the corresponding tests
(`test_merge_design_critic_*`, `test_recovery_skip_matcher.py`).
"""

SANCTIONED_DEGRADED_REASONS = frozenset({
    "demo-mode-fixture-short-circuit",  # #1042 — design-critic Sub-branch S1
    "redirect-source-only",             # #1196 — design-critic Sub-branch S2 opt-in
    "empty-boundary-fast-path",         # #1061 — state-3a empty-boundary fast-path
})

__all__ = ["SANCTIONED_DEGRADED_REASONS"]
