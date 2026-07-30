#!/usr/bin/env python3
"""Validate .runs/user-approval-evidence.json for bootstrap state-6 gate.

Invoked by `state-completion-gate.sh` when `advance-state.sh bootstrap 6`
runs. The artifact must exist and carry:

- approval_source: "AskUserQuestion" | "direct-user-message"
- quoted_user_reply: string, min_length=8
- timestamp: ISO 8601, within 60 seconds of now

Exit 0 on pass; exit 1 on violation (writes to .runs/lead-deviation-log.jsonl).

Closes prose-gate `bootstrap-state-6-user-approval` (.claude/patterns/prose-gates.json).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

ARTIFACT_PATH = ".runs/user-approval-evidence.json"
DEVIATION_LOG_PATH = ".runs/lead-deviation-log.jsonl"
GATE_ID = "bootstrap-state-6-user-approval"
MODE_ENV_VAR = "USER_APPROVAL_EVIDENCE_MODE"
VALID_SOURCES = {"AskUserQuestion", "direct-user-message"}
MIN_REPLY_LEN = 8
MAX_TIMESTAMP_AGE_SEC = 60


def _active_run_id() -> str:
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
    return (best or {}).get("run_id", "")


def _log_deviation(violations: list[str]) -> None:
    """Append deviation entry via shared atomic appender. On exception →
    write-failures.jsonl (observer-visible). Closes #1431."""
    entry = {
        "timestamp": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": _active_run_id(),
        "skill": "bootstrap",
        "state_id": "6",
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

    violations: list[str] = []

    if not os.path.isfile(ARTIFACT_PATH):
        violations.append(f"{ARTIFACT_PATH} missing — bootstrap state-6 "
                          "requires explicit user-approval evidence")
    else:
        try:
            d = json.load(open(ARTIFACT_PATH))
        except Exception as e:
            violations.append(f"{ARTIFACT_PATH} unparseable: {e}")
            d = None

        if d is not None:
            src = d.get("approval_source")
            if src not in VALID_SOURCES:
                violations.append(f"approval_source={src!r} not in {sorted(VALID_SOURCES)}")

            reply = d.get("quoted_user_reply") or ""
            if not isinstance(reply, str) or len(reply) < MIN_REPLY_LEN:
                violations.append(
                    f"quoted_user_reply must be string ≥{MIN_REPLY_LEN} chars "
                    f"(got len={len(reply) if isinstance(reply, str) else 'non-string'})"
                )

            ts_raw = d.get("timestamp") or ""
            try:
                ts = _dt.datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=_dt.timezone.utc)
                age = (_dt.datetime.now(_dt.timezone.utc) - ts).total_seconds()
                if age > MAX_TIMESTAMP_AGE_SEC:
                    violations.append(
                        f"timestamp stale (>{MAX_TIMESTAMP_AGE_SEC}s old): age={age:.0f}s"
                    )
            except Exception as e:
                violations.append(f"timestamp parse failed: {e}")

    if violations:
        for v in violations:
            tag = "BLOCK" if mode == "deny" else "WARN"
            print(f"{tag}: {v}", file=sys.stderr)
        _log_deviation(violations)
        return 1 if mode == "deny" else 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
