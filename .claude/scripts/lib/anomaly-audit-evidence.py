#!/usr/bin/env python3
"""Validate .runs/audit-sample-result.json exists and is well-formed.

Required fields:
- triggered: bool
- audit_outcome: str (non-empty when triggered==true)
- anomaly_count_observed: int

Invoked from observation-phase.md state-99 epilogue after audit-sample.py runs.
Closes prose-gate `observation-phase-step5c-anomaly-audit`.

Exit 0 / 1; logs to .runs/lead-deviation-log.jsonl on violation.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

ARTIFACT_PATH = ".runs/audit-sample-result.json"
DEVIATION_LOG_PATH = ".runs/lead-deviation-log.jsonl"
GATE_ID = "observation-phase-step5c-anomaly-audit"
MODE_ENV_VAR = "ANOMALY_AUDIT_MODE"


def _active_skill_run() -> tuple[str, str]:
    import glob
    best = None
    best_ts = ""
    for f in glob.glob(".runs/*-context.json"):
        if "epilogue" in f:
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if d.get("completed") is True:
            continue
        ts = d.get("timestamp", "") or ""
        if ts >= best_ts:
            best = d
            best_ts = ts
    if not best:
        return "", ""
    return best.get("skill", ""), best.get("run_id", "")


def _log_deviation(skill: str, run_id: str, violations: list[str]) -> None:
    """Append deviation entry via shared atomic appender. On exception →
    write-failures.jsonl (observer-visible). Closes #1431."""
    entry = {
        "timestamp": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": run_id,
        "skill": skill,
        "state_id": "99",
        "gate_id": GATE_ID,
        "gate_layer": "prose-gates-v1",
        "deviation_type": "manual-write-bypass",
        "evidence": {
            "expected_artifact": ARTIFACT_PATH,
            "violated_fields": violations,
        },
        "auto_filed": False,
    }
    sys.path.insert(0, os.path.dirname(__file__))
    from append_deviation_log import append
    append(entry)


def _resolve_mode(arg_mode: str | None) -> str:
    """Resolve mode: CLI arg overrides; otherwise via shared prose_gate_mode
    helper (PROSE_GATES_TOLERANT > PROSE_GATE_<GATE>_MODE > snapshot > registry
    > prior_default="warn"). Closes #1449/#1431/#1433."""
    if arg_mode:
        return arg_mode
    sys.path.insert(0, os.path.dirname(__file__))
    from prose_gate_mode import resolve
    return resolve(GATE_ID, prior_default="warn")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--mode", choices=["warn", "deny"], default=None,
        help=f"warn=log+exit 0; deny=log+exit 1. Default from ${MODE_ENV_VAR} env var "
             "(Phase A: warn; Phase C: deny).",
    )
    args = ap.parse_args()
    mode = _resolve_mode(args.mode)

    skill, run_id = _active_skill_run()
    violations: list[str] = []

    if not os.path.isfile(ARTIFACT_PATH):
        violations.append(f"{ARTIFACT_PATH} missing — observation-phase Step 5c "
                          "did not invoke audit-sample.py")
    else:
        try:
            d = json.load(open(ARTIFACT_PATH))
        except Exception as e:
            violations.append(f"{ARTIFACT_PATH} unparseable: {e}")
            d = None

        if d is not None:
            if not isinstance(d.get("triggered"), bool):
                violations.append("triggered missing or not bool")
            if not isinstance(d.get("audit_outcome"), str):
                violations.append("audit_outcome missing or not string")
            if d.get("triggered") and not d.get("audit_outcome"):
                violations.append("triggered==true but audit_outcome empty")
            if not isinstance(d.get("anomaly_count_observed"), int):
                violations.append("anomaly_count_observed missing or not int")

    if violations:
        for v in violations:
            tag = "BLOCK" if mode == "deny" else "WARN"
            print(f"{tag}: {v}", file=sys.stderr)
        _log_deviation(skill, run_id, violations)
        return 1 if mode == "deny" else 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
