#!/usr/bin/env python3
"""Layer 3: Adaptive LLM Audit Sampling Decision.

Part of Three-Layer Compliance Architecture.
Determines whether to trigger a deep LLM semantic audit based on
anomaly count, Q-score, and adaptive sampling rate.

Usage:
    python3 .claude/scripts/audit-sample.py --anomaly-count <N> --q-score <float>
    python3 .claude/scripts/audit-sample.py --anomaly-count <N> --q-score <float> --force

State file: .runs/audit-sample-state.json (created on first invocation)

Output: JSON to stdout:
    {"trigger": true, "reason": "anomaly_detected|low_q_score|random_sample|forced"}
    {"trigger": false, "reason": "clean_run", "current_rate": 0.05}
"""
import argparse
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone

try:
    _project = subprocess.check_output(
        ['git', 'rev-parse', '--show-toplevel'],
        stderr=subprocess.DEVNULL
    ).decode().strip()
except Exception:
    _project = os.environ.get("CLAUDE_PROJECT_DIR", ".")
RUNS_DIR = _project + "/.runs"
STATE_FILE = os.path.join(RUNS_DIR, "audit-sample-state.json")

DEFAULT_STATE = {
    "consecutive_clean": 0,
    "current_rate": 0.10,
    "last_anomaly_run": None,
    "cooldown_remaining": 0,
}


def load_state():
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        # Ensure all fields exist (forward compat)
        for k, v in DEFAULT_STATE.items():
            state.setdefault(k, v)
        return state
    except Exception:
        return dict(DEFAULT_STATE)


def save_state(state):
    os.makedirs(RUNS_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def should_trigger(anomaly_count, q_score, force, run_id):
    state = load_state()

    if force:
        save_state(state)
        return True, "forced"

    if anomaly_count > 0:
        state["consecutive_clean"] = 0
        state["current_rate"] = 0.50
        state["cooldown_remaining"] = 10
        state["last_anomaly_run"] = run_id
        save_state(state)
        return True, "anomaly_detected"

    if q_score < 0.5:
        save_state(state)
        return True, "low_q_score"

    # Decay cooldown
    if state["cooldown_remaining"] > 0:
        state["cooldown_remaining"] -= 1
        if state["cooldown_remaining"] == 0:
            state["current_rate"] = 0.10

    # Consecutive clean decay
    state["consecutive_clean"] += 1
    if state["consecutive_clean"] >= 50:
        state["current_rate"] = min(state["current_rate"], 0.02)
    elif state["consecutive_clean"] >= 20:
        state["current_rate"] = min(state["current_rate"], 0.05)

    # Random sample
    if random.random() < state["current_rate"]:
        save_state(state)
        return True, "random_sample"

    save_state(state)
    return False, "clean_run"


def main():
    parser = argparse.ArgumentParser(description="Layer 3: Adaptive LLM audit sampling")
    parser.add_argument("--anomaly-count", type=int, required=True,
                        help="Number of anomalies from compliance-audit.py")
    parser.add_argument("--q-score", type=float, required=True,
                        help="Q-score from write-q-score.py")
    parser.add_argument("--run-id", default="",
                        help="Run ID for tracking")
    parser.add_argument("--force", action="store_true",
                        help="Force trigger regardless of sampling")
    args = parser.parse_args()

    trigger, reason = should_trigger(
        args.anomaly_count, args.q_score, args.force, args.run_id
    )

    state = load_state()
    result = {
        "trigger": trigger,
        "reason": reason,
        "current_rate": state["current_rate"],
        "consecutive_clean": state["consecutive_clean"],
    }

    print(json.dumps(result))

    # Phase A (prose-gate observation-phase-step5c-anomaly-audit): write
    # .runs/audit-sample-result.json unconditionally so anomaly-audit-evidence.py
    # can validate at state-99 epilogue. Triggered or not, the artifact must exist.
    result_artifact = {
        "triggered": trigger,
        "audit_outcome": reason,
        "anomaly_count_observed": args.anomaly_count,
        "q_score": args.q_score,
        "current_rate": state["current_rate"],
        "consecutive_clean": state["consecutive_clean"],
    }
    try:
        subprocess.run(
            [
                "bash", ".claude/scripts/lib/write-gate-artifact.sh",
                "--path", ".runs/audit-sample-result.json",
                "--payload", json.dumps(result_artifact),
                "--skill", os.environ.get("SKILL_KEY", "observe"),
            ],
            check=False,
        )
    except Exception:
        # Best-effort; epilogue validator catches missing artifact.
        pass


if __name__ == "__main__":
    main()
