#!/usr/bin/env python3
"""VERIFY script for change state 3: validate solve-trace.json and change-challenge.json.

Checks:
- solve_depth matches the complexity formula
- solve-trace.json has all required fields
- change-challenge.json exists with valid structure
- Full mode requires critic_rounds > 0
- RMG v2: when preliminary_type=Fix and recurrence_risk != 'none',
  recurrence_guard parses via .claude/scripts/lib/recurrence_guard_parser.py
- When change-challenge.json critic_rounds == 2, the round-1 archive at
  .runs/solve-critic-round1.json exists and is parseable JSON containing
  round=1 + non-empty concerns[] (#1331: vector 5 needs round-1 concerns;
  without the archive the round-2 cross-check has no input source).
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
from recurrence_guard_parser import (  # noqa: E402
    FalsificationParseError,
    RecurrenceGuardParseError,
    parse,
    parse_falsification,
)
from dossier_verify import (  # noqa: E402
    DossierVerifyError,
    assert_dossier_loaded,
)

ctx = json.load(open(".runs/change-context.json"))
sd = ctx.get("solve_depth")
assert sd in ("light", "full"), "solve_depth=%s" % sd

pt = ctx.get("preliminary_type", "")
aa = ctx.get("affected_areas", 0)
assert not (
    pt in ("Feature", "Upgrade") and isinstance(aa, int) and aa >= 3 and sd != "full"
), "Formula requires full (type=%s,areas=%s) but got %s" % (pt, aa, sd)

st = json.load(open(".runs/solve-trace.json"))
required = [
    "mode",
    "problem_decomposition",
    "constraint_enumeration",
    "solution_design",
    "self_check",
    "output",
]
missing = [k for k in required if k not in st]
assert not missing, "solve-trace.json missing: %s" % missing

# Prevention analysis: required when preliminary_type is Fix
pt = ctx.get("preliminary_type", "")
pa = st.get("prevention_analysis")
if pt == "Fix":
    assert pa is not None, "prevention_analysis required when preliminary_type=Fix"
    assert isinstance(pa, dict), "prevention_analysis must be a dict"
    for field in ("root_cause_addressed", "recurrence_risk", "scope"):
        assert field in pa, "prevention_analysis missing %s" % field
    assert pa["recurrence_risk"] in ("none", "guarded", "unguarded"), (
        "recurrence_risk invalid: %s" % pa["recurrence_risk"]
    )
    if pa["recurrence_risk"] != "none":
        guard = pa.get("recurrence_guard")
        assert guard is not None, (
            "recurrence_guard required when recurrence_risk != 'none' (RMG v2)"
        )
        try:
            parse(guard)
        except RecurrenceGuardParseError as exc:
            raise AssertionError(
                "recurrence_guard fails RMG v2 parser: %s (raw=%r)"
                % (exc, getattr(exc, "raw_value", guard))
            )

    # Falsification Gate — /change Fix branch sets problem_type=defect inside
    # prevention_analysis via solve-reasoning Phase 4.
    if pa.get("problem_type") == "defect":
        falsi = pa.get("falsification")
        assert falsi is not None, (
            "prevention_analysis.falsification required when "
            "problem_type=defect (Falsification Gate)"
        )
        try:
            parse_falsification(falsi)
        except FalsificationParseError as exc:
            raise AssertionError(
                "falsification fails parser: %s (raw=%r)"
                % (exc, getattr(exc, "raw_value", falsi))
            )

        # Dossier Gate (Issue #1415): /change Fix path must build the
        # Prior-Failure Dossier and emit prior_failure_response. Evidence
        # comes from exploration-trace.json (NOT change-context.json — the
        # latter only carries affected_areas count).
        expl_path = ".runs/exploration-trace.json"
        evidence: list[str] = []
        if os.path.isfile(expl_path):
            try:
                evidence = sorted(
                    json.load(open(expl_path)).get("affected_files", [])
                )
            except (OSError, json.JSONDecodeError):
                pass
        try:
            assert_dossier_loaded(
                st,
                problem_type=pa.get("problem_type"),
                divergence_files_evidence=evidence,
            )
        except DossierVerifyError as exc:
            raise AssertionError(str(exc))

cc = json.load(open(".runs/change-challenge.json"))
assert isinstance(cc.get("critic_rounds"), int), "critic_rounds missing or not int"
assert isinstance(cc.get("concerns"), list), "concerns missing or not list"
assert not (sd == "full" and cc["critic_rounds"] == 0), "full mode but critic_rounds=0"
ta = cc.get("round_1_type_a_count", 0)
assert not (ta > 0 and cc["critic_rounds"] < 2), (
    "round_1_type_a_count=%d but critic_rounds=%d — round 2 required when TYPE A > 0"
    % (ta, cc["critic_rounds"])
)

# #1331 runtime guard: when round 2 ran, the round-1 archive MUST exist with
# parseable JSON containing round=1 concerns. Without it, vector 5
# (within-run-round1-concern-unaddressed) has no input source — silently
# bypassed by any future change that adds round-2 spawning without archival.
if cc["critic_rounds"] == 2:
    archive_path = ".runs/solve-critic-round1.json"
    assert os.path.exists(archive_path), (
        f"critic_rounds=2 but round-1 archive missing at {archive_path} — "
        "the orchestrator must archive solve-critic.json to this sidecar BEFORE "
        "spawning round 2 (see solve-reasoning.md Phase 5 / state-3-solve-reasoning.md)"
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
