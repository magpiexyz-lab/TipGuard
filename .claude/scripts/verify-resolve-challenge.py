#!/usr/bin/env python3
"""VERIFY script for resolve state 5d: validate resolve-challenge.json schema.

Checks:
- challenges array is non-empty
- Each entry has agent_label, final_label (valid values)
- override_reason required when labels differ
- critic_rounds and round_1_type_a_count consistency
- Adversarial trace exists (resolve-challenger or solve-critic)
- When critic_rounds == 2, the round-1 archive at .runs/solve-critic-round1.json
  exists and is parseable JSON containing round=1 + non-empty concerns[]
  (#1331: vector 5 needs round-1 concerns; without the archive the round-2
  cross-check has no input source).
"""
import json
import os
import sys

d = json.load(open(".runs/resolve-challenge.json"))
cs = d.get("challenges", [])
assert isinstance(cs, list) and len(cs) > 0, "challenges empty"

valid_labels = ("sound", "challenged", "needs-revision")
for i, c in enumerate(cs):
    assert "agent_label" in c, f"challenges[{i}] missing agent_label"
    assert "final_label" in c, f"challenges[{i}] missing final_label"
    assert c["agent_label"] in valid_labels, f"challenges[{i}] invalid agent_label: {c['agent_label']}"
    assert c["final_label"] in valid_labels, f"challenges[{i}] invalid final_label: {c['final_label']}"
    if c["agent_label"] != c["final_label"]:
        reason = c.get("override_reason", "").strip()
        assert reason, f"challenges[{i}] override_reason required when labels differ"

cr = d.get("critic_rounds")
ta = d.get("round_1_type_a_count", 0)
assert cr is not None, "critic_rounds missing"
assert not (ta > 0 and cr < 2), (
    "round_1_type_a_count=%d but critic_rounds=%d — round 2 required when TYPE A > 0" % (ta, cr)
)

assert os.path.exists(".runs/agent-traces/resolve-challenger.json") or os.path.exists(
    ".runs/agent-traces/solve-critic.json"
), "adversarial trace missing (resolve-challenger.json or solve-critic.json)"

# #1331 runtime guard: when round 2 ran, the round-1 archive MUST exist with
# parseable JSON containing round=1 concerns. Without it, vector 5
# (within-run-round1-concern-unaddressed) has no input source — silently
# bypassed by any future change that adds round-2 spawning without archival.
if cr == 2:
    archive_path = ".runs/solve-critic-round1.json"
    assert os.path.exists(archive_path), (
        f"critic_rounds=2 but round-1 archive missing at {archive_path} — "
        "the orchestrator must archive solve-critic.json to this sidecar BEFORE "
        "spawning round 2 (see solve-reasoning.md Phase 5 / state-5d-adversarial-challenge.md)"
    )
    try:
        archive = json.load(open(archive_path))
    except Exception as e:
        raise AssertionError(f"{archive_path} not parseable as JSON: {e}")
    assert archive.get("round") == 1, (
        f"{archive_path} has round={archive.get('round')!r}, expected 1 — "
        "the sidecar should be the archived round-1 trace, not a copy of round-2"
    )
    arc_concerns = archive.get("concerns") or []
    assert isinstance(arc_concerns, list) and len(arc_concerns) > 0, (
        f"{archive_path} has no concerns[] — round-2 vector 5 cannot fire without "
        "round-1 concern_ids to cross-check"
    )
