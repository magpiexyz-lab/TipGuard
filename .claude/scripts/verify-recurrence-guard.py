#!/usr/bin/env python3
"""verify-recurrence-guard.py — RMG v2 Phase A.

Standalone verifier callable from state-registry.json VERIFY blocks.

Reads `.runs/solve-trace.json`, asserts the structural fields required by all
three callers, and — when `prevention_analysis.recurrence_risk != "none"` —
parses `prevention_analysis.recurrence_guard` via
`.claude/scripts/lib/recurrence_guard_parser.py`. Tolerant mode is honored
(legacy free-text guards become `kind="legacy_freetext"` and pass; this is
intentional during the soak window).

Optional flags:
  --require-prevention    assert prevention_analysis is present (resolve)
  --require-phase-3-gaps  assert phase_3_gaps is present and non-empty in full mode (solve)
  --require-run-id        assert solve-trace run_id matches a sibling context.json
  --require-falsification assert prevention_analysis.falsification is present and
                          parses under recurrence_guard_parser.parse_falsification
                          when problem_type=defect. Strict: missing or invalid
                          falsification returns exit 1 immediately.
  --require-dossier       assert .runs/prior-failure-dossier.json exists and
                          solve-trace.json.prior_failure_response is populated
                          when problem_type=defect. Closes the Phase 1a coverage
                          gap (Issue #1415). For --skill resolve, divergence
                          evidence is sourced from .runs/resolve-reproduction.json.
  --context-path PATH     explicit context json (default: auto-detect by skill)
  --skill {resolve,solve,change}  influences default context-path
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".claude" / "scripts" / "lib"))

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

REQUIRED_TRACE_FIELDS = (
    "mode",
    "problem_decomposition",
    "constraint_enumeration",
    "solution_design",
    "self_check",
    "output",
)


def _load(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def _default_context_path(skill: str) -> str:
    return f".runs/{skill}-context.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-prevention", action="store_true")
    parser.add_argument("--require-phase-3-gaps", action="store_true")
    parser.add_argument("--require-run-id", action="store_true")
    parser.add_argument("--require-falsification", action="store_true")
    parser.add_argument("--require-dossier", action="store_true")
    parser.add_argument("--context-path")
    parser.add_argument("--skill", choices=("resolve", "solve", "change"))
    args = parser.parse_args(argv)

    trace_path = ".runs/solve-trace.json"
    if not os.path.isfile(trace_path):
        print(f"VERIFY FAIL: {trace_path} missing", file=sys.stderr)
        return 1

    trace = _load(trace_path)
    if trace.get("mode") not in ("light", "full"):
        print(f"VERIFY FAIL: mode={trace.get('mode')!r} (must be light or full)", file=sys.stderr)
        return 1

    missing = [k for k in REQUIRED_TRACE_FIELDS if not trace.get(k)]
    if missing:
        print(f"VERIFY FAIL: solve-trace.json empty fields: {missing}", file=sys.stderr)
        return 1

    if args.require_phase_3_gaps:
        if "phase_3_gaps" not in trace:
            print("VERIFY FAIL: phase_3_gaps field missing", file=sys.stderr)
            return 1
        if trace["mode"] == "full" and not trace.get("phase_3_gaps"):
            print("VERIFY FAIL: phase_3_gaps empty in full mode", file=sys.stderr)
            return 1

    if args.require_run_id:
        ctx_path = args.context_path or (
            _default_context_path(args.skill) if args.skill else None
        )
        if not ctx_path or not os.path.isfile(ctx_path):
            print(f"VERIFY FAIL: context json {ctx_path!r} missing", file=sys.stderr)
            return 1
        ctx = _load(ctx_path)
        if trace.get("run_id") != ctx.get("run_id"):
            print(
                f"VERIFY FAIL: run_id mismatch trace={trace.get('run_id')!r} "
                f"context={ctx.get('run_id')!r}",
                file=sys.stderr,
            )
            return 1

    pa = trace.get("prevention_analysis")
    if args.require_prevention:
        if pa is None:
            print("VERIFY FAIL: prevention_analysis required", file=sys.stderr)
            return 1
        if not isinstance(pa, dict):
            print("VERIFY FAIL: prevention_analysis must be a dict", file=sys.stderr)
            return 1
        for field in ("root_cause_addressed", "recurrence_risk", "scope"):
            if field not in pa:
                print(
                    f"VERIFY FAIL: prevention_analysis missing {field}",
                    file=sys.stderr,
                )
                return 1

    if isinstance(pa, dict):
        risk = pa.get("recurrence_risk")
        if risk and risk not in ("none", "guarded", "unguarded"):
            print(
                f"VERIFY FAIL: recurrence_risk invalid: {risk!r}",
                file=sys.stderr,
            )
            return 1
        if risk and risk != "none":
            guard = pa.get("recurrence_guard")
            if guard is None:
                print(
                    "VERIFY FAIL: recurrence_guard required when "
                    "recurrence_risk != 'none' (RMG v2)",
                    file=sys.stderr,
                )
                return 1
            try:
                parse(guard)
            except RecurrenceGuardParseError as exc:
                print(
                    f"VERIFY FAIL: recurrence_guard rejected by RMG v2 parser: "
                    f"{exc} (raw={getattr(exc, 'raw_value', guard)!r})",
                    file=sys.stderr,
                )
                return 1

    # Falsification Gate (sibling of recurrence_guard inside prevention_analysis).
    # Fires only when problem_type=defect to keep non-defect runs unaffected.
    if args.require_falsification and isinstance(pa, dict):
        if pa.get("problem_type") == "defect":
            falsi = pa.get("falsification")
            if falsi is None:
                print(
                    "VERIFY FAIL: prevention_analysis.falsification required "
                    "when problem_type=defect (Falsification Gate). See "
                    ".claude/patterns/solve-reasoning.md 'Falsification Schema'.",
                    file=sys.stderr,
                )
                return 1
            try:
                parse_falsification(falsi)
            except FalsificationParseError as exc:
                print(
                    f"VERIFY FAIL: falsification rejected: {exc} "
                    f"(raw={getattr(exc, 'raw_value', falsi)!r})",
                    file=sys.stderr,
                )
                return 1

    # Dossier Gate (Issue #1415): assert .runs/prior-failure-dossier.json
    # exists and solve-trace.json.prior_failure_response is populated when
    # problem_type=defect. Closes the Phase 1a verify-coverage asymmetry.
    if args.require_dossier and isinstance(pa, dict):
        evidence: list[str] = []
        if args.skill == "resolve":
            repro_path = ".runs/resolve-reproduction.json"
            if os.path.isfile(repro_path):
                try:
                    repro = _load(repro_path)
                    # divergence_point is the string "<file>:<line>" per
                    # state-3-reproduce.md schema — split on first ':'.
                    evidence = sorted({
                        (r.get("divergence_point", "") or "").split(":", 1)[0]
                        for r in repro.get("reproductions", [])
                        if r.get("divergence_point")
                    } - {""})
                except (OSError, json.JSONDecodeError, AttributeError):
                    pass
        try:
            assert_dossier_loaded(
                trace,
                problem_type=pa.get("problem_type"),
                divergence_files_evidence=evidence,
            )
        except DossierVerifyError as exc:
            print(f"VERIFY FAIL: {exc}", file=sys.stderr)
            return 1

        # OARC #1468/#1456 — semantic-match consultation gate. For every
        # phase_1a entry where the dossier set
        # `designer_consultation_attestation_required: true` (semantic-match
        # heuristic: ≥2 content-token overlap with the canonicalized symptom
        # AND ≥1 file overlap), `solve-trace.json.prior_failure_consultation`
        # MUST have a matching entry with `consulted_via != "skipped"` OR a
        # `skip_justification` of ≥40 chars. Default is warn-only;
        # CONSULTATION_DENY in {"1", "deny"} promotes to a hard block
        # (Phase C cutover per .claude/patterns/gecr-cutover-criteria.json).
        dossier_path = ".runs/prior-failure-dossier.json"
        if (os.path.isfile(dossier_path)
                and pa.get("problem_type") == "defect"):
            try:
                dossier = _load(dossier_path)
            except (OSError, json.JSONDecodeError):
                dossier = {}
            required_prior_run_ids = [
                e.get("prior_run_id")
                for e in (dossier.get("phase_1a") or [])
                if isinstance(e, dict)
                and e.get("designer_consultation_attestation_required") is True
                and e.get("prior_run_id")
            ]
            if required_prior_run_ids:
                consultations = trace.get("prior_failure_consultation") or []
                consulted_index: dict[str, dict] = {}
                if isinstance(consultations, list):
                    for c in consultations:
                        if isinstance(c, dict) and c.get("prior_run_id"):
                            consulted_index[c["prior_run_id"]] = c
                missing: list[str] = []
                weak: list[str] = []
                for pid in required_prior_run_ids:
                    entry = consulted_index.get(pid)
                    if entry is None:
                        missing.append(pid)
                        continue
                    via = entry.get("consulted_via", "")
                    if via == "skipped":
                        justification = entry.get("skip_justification") or ""
                        if not isinstance(justification, str) or len(justification.strip()) < 40:
                            weak.append(pid)
                if missing or weak:
                    msg_parts = []
                    if missing:
                        msg_parts.append(
                            f"missing consultation entries for: {missing}"
                        )
                    if weak:
                        msg_parts.append(
                            f"skipped consultations with weak justification (<40 chars): {weak}"
                        )
                    full_msg = (
                        "OARC #1468/#1456 — semantic-match dossier entries require "
                        "prior_failure_consultation. " + "; ".join(msg_parts)
                        + ". Each entry must carry `consulted_via != \"skipped\"` "
                        "OR `skip_justification` ≥40 chars. See "
                        "`.claude/agents/solve-critic.md` vector 4 amendment."
                    )
                    # Soak/deny mode: CONSULTATION_DENY in {"1", "deny"}
                    # promotes the gate to a hard block (Phase C cutover per
                    # .claude/patterns/gecr-cutover-criteria.json; "deny"
                    # accepted because the gecr-cutover-overdue linter message
                    # historically suggested that spelling). Default during
                    # soak: warn-only — surface the gap without blocking PR
                    # merge so designers see the contract before enforcement.
                    if os.environ.get("CONSULTATION_DENY", "") in ("1", "deny"):
                        print(f"VERIFY FAIL: {full_msg}", file=sys.stderr)
                        return 1
                    print(f"VERIFY WARN: {full_msg}", file=sys.stderr)

    # #1331 runtime guard: when /solve full-mode runs round 2, the orchestrator
    # must have archived round-1 to the sidecar. Read solve-critic.json.round
    # directly as the signal channel — when round == 2, the archive at
    # .runs/solve-critic-round1.json must exist with round=1 + non-empty
    # concerns[]. This mirrors the resolve/change guards in
    # verify-resolve-challenge.py and verify-change-solve.py.
    if args.skill == "solve":
        sc_path = ".runs/agent-traces/solve-critic.json"
        if os.path.exists(sc_path):
            try:
                sc = _load(sc_path)
            except Exception:
                sc = {}
            if sc.get("round") == 2:
                archive_path = ".runs/solve-critic-round1.json"
                if not os.path.exists(archive_path):
                    print(
                        f"VERIFY FAIL: solve-critic.json has round=2 but round-1 "
                        f"archive missing at {archive_path} — orchestrator must "
                        "archive solve-critic.json to this sidecar BEFORE spawning "
                        "round 2 (see solve-reasoning.md Phase 5 / "
                        "solve/state-1-execute.md)",
                        file=sys.stderr,
                    )
                    return 1
                try:
                    archive = _load(archive_path)
                except Exception as exc:
                    print(
                        f"VERIFY FAIL: {archive_path} not parseable as JSON: {exc}",
                        file=sys.stderr,
                    )
                    return 1
                if archive.get("round") != 1:
                    print(
                        f"VERIFY FAIL: {archive_path} has round={archive.get('round')!r}, "
                        "expected 1 — sidecar should be the archived round-1 trace",
                        file=sys.stderr,
                    )
                    return 1
                arc_concerns = archive.get("concerns") or []
                if not (isinstance(arc_concerns, list) and len(arc_concerns) > 0):
                    print(
                        f"VERIFY FAIL: {archive_path} has no concerns[] — round-2 "
                        "vector 5 cannot fire without round-1 concern_ids",
                        file=sys.stderr,
                    )
                    return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
