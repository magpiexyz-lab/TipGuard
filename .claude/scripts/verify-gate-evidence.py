#!/usr/bin/env python3
"""GECR CLI — invoke gate-evidence rules or run a coverage audit.

Usage:
    python3 .claude/scripts/verify-gate-evidence.py --rule-id <id>
    python3 .claude/scripts/verify-gate-evidence.py --rule-id all
    python3 .claude/scripts/verify-gate-evidence.py --audit

Exit codes:
    0 — PASS (no failures, or all failures in MODE=warn)
    1 — BLOCK (deny mode + failures present)
    2 — Infrastructure error (schema invalid, evidence source unparseable)

Audit mode enumerates structural-shape gate-keeper checks via grep and reports
checks WITHOUT a corresponding rule entry in gate-evidence-rules.json. Output
is JSON written to stdout for capture by Step 13 (companion issue body).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))

from gate_evidence_runner import (  # type: ignore
    load_rules,
    run_rule,
    format_failure,
)


GATE_KEEPER_PATH = ".claude/agents/gate-keeper.md"
CHECK_OBSERVATION_PATH = ".claude/scripts/check-observation-artifacts.sh"
AUDIT_TRIGGER_PATTERN = r"test -f|test -d|grep -E.*href|grep -c "


def _git_commit_sha() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
        return out.decode().strip()
    except Exception:
        return "(unknown)"


def _audit() -> int:
    """Enumerate structural-shape gate-keeper checks and classify coverage.

    Each finding is classified into one of three coverage states:
      - `rule`        — covered by a GECR rule (rule's `gate_id` appears in
                        the line text). True coverage.
      - `annotation`  — listed under `evidence_check_intentionally_structural`
                        in gate-evidence-rules.json. Deferred — needs triage
                        per the rationale recorded in the annotation.
      - `uncovered`   — neither. Hard regression risk; the linter rule
                        `gate_verdict_evidence_coverage` warns/blocks on these.

    Companion-issue input (Plan Step 13): the `findings_by_coverage_state.annotation`
    set is the canonical "needs triage" list.

    Writes JSON report to stdout. Exit 0 always (audit is read-only).
    """
    findings: list[dict] = []
    trigger_re = re.compile(AUDIT_TRIGGER_PATTERN)
    commit_sha = _git_commit_sha()

    # Load rules + annotation registry. Both contribute coverage signal.
    try:
        rules_doc_raw = json.load(open(
            os.path.join(os.path.dirname(_HERE), "patterns", "gate-evidence-rules.json")
        ))
    except (OSError, json.JSONDecodeError):
        rules_doc_raw = {}
    rules = rules_doc_raw.get("rules", []) or []
    covered_gate_ids = {r.get("gate_id", "") for r in rules if r.get("gate_id")}

    # Parse annotation registry — accepts both string entries and
    # {check_id, justification} object entries (per schema oneOf).
    annotated_check_ids: set[str] = set()
    for entry in rules_doc_raw.get("evidence_check_intentionally_structural", []) or []:
        if isinstance(entry, str):
            annotated_check_ids.add(entry)
        elif isinstance(entry, dict):
            cid = entry.get("check_id")
            if isinstance(cid, str):
                annotated_check_ids.add(cid)

    for path in (GATE_KEEPER_PATH, CHECK_OBSERVATION_PATH):
        if not os.path.isfile(path):
            continue
        try:
            with open(path) as fh:
                for lineno, line in enumerate(fh, start=1):
                    if not trigger_re.search(line):
                        continue
                    check_id = f"{path}:{lineno}"
                    covered_by_rule = any(
                        gid and gid in line for gid in covered_gate_ids
                    )
                    covered_by_annotation = check_id in annotated_check_ids
                    if covered_by_rule:
                        coverage_state = "rule"
                    elif covered_by_annotation:
                        coverage_state = "annotation"
                    else:
                        coverage_state = "uncovered"
                    findings.append({
                        "file": path,
                        "line": lineno,
                        "check_id": check_id,
                        "text": line.rstrip()[:200],
                        "covered_by_rule": covered_by_rule,
                        "covered_by_annotation": covered_by_annotation,
                        "coverage_state": coverage_state,
                    })
        except OSError:
            continue

    by_file: dict[str, int] = {}
    by_coverage_state: dict[str, list[dict]] = {
        "rule": [], "annotation": [], "uncovered": []
    }
    for f in findings:
        by_file[f["file"]] = by_file.get(f["file"], 0) + 1
        by_coverage_state[f["coverage_state"]].append({
            "check_id": f["check_id"],
            "text": f["text"],
        })

    report = {
        "audit_commit_sha": commit_sha,
        "audited_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "audit_method": (
            f"grep -nE '{AUDIT_TRIGGER_PATTERN}' on {GATE_KEEPER_PATH} and "
            f"{CHECK_OBSERVATION_PATH}"
        ),
        "total_findings": len(findings),
        "findings_by_file": by_file,
        "summary_by_coverage_state": {
            k: len(v) for k, v in by_coverage_state.items()
        },
        "findings_by_coverage_state": by_coverage_state,
        "covered_gate_ids": sorted(covered_gate_ids),
        "annotated_check_ids": sorted(annotated_check_ids),
        "findings": findings,
    }
    print(json.dumps(report, indent=2))
    return 0


def _run_one(rule_id: str) -> int:
    """Run a single rule by id (or all rules if rule_id == 'all')."""
    try:
        rules = load_rules()
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2

    if rule_id != "all":
        rules = [r for r in rules if r.get("id") == rule_id]
        if not rules:
            sys.stderr.write(f"verify-gate-evidence: rule not found: {rule_id!r}\n")
            sys.stderr.write(f"  Available rules: {[r.get('id') for r in load_rules()]}\n")
            return 0  # not-found is not an error — useful for soak-mode skipping

    overall_failed = False
    for rule in rules:
        rid = rule.get("id", "<unknown>")
        mode, failures = run_rule(rule)
        if mode == "skip":
            sys.stderr.write(f"verify-gate-evidence: SKIP {rid!r} (pre-cutoff)\n")
            continue
        if not failures:
            sys.stderr.write(f"verify-gate-evidence: PASS {rid!r}\n")
            continue
        sys.stderr.write(
            f"verify-gate-evidence: {('BLOCK' if mode == 'deny' else 'WARN')} "
            f"{rid!r} ({len(failures)} failures, mode={mode})\n"
        )
        for f in failures:
            sys.stderr.write(f"  {format_failure(rule, f)}\n")
        if mode == "deny":
            overall_failed = True

    return 1 if overall_failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GECR — verify gate evidence cross-reference rules"
    )
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--rule-id", help="Rule id to run (or 'all')")
    g.add_argument("--audit", action="store_true", help="Run coverage audit")
    parser.add_argument("--gate-id", help="Optional gate-id (for audit logging)")
    parser.add_argument("--check-num", type=int, help="Optional check number (for audit logging)")

    args = parser.parse_args()
    if args.audit:
        return _audit()
    return _run_one(args.rule_id)


if __name__ == "__main__":
    sys.exit(main())
