#!/usr/bin/env python3
"""Validate every pending retrospective candidate has a disposition.

Issue context: #1276 — soft retrospective filing has failed 5 times.
This validator is the hard-block gate: every candidate from
.runs/retrospective-pending-findings.json must be EITHER:
  (a) filed as a real GitHub issue (entry in .runs/retrospective-filed-findings.json), OR
  (b) explicitly suppressed in .runs/retrospective-result.json with
      reason from a closed enum

Closed suppression enum (round-2 critic Concern 3):
  - not-template-rooted
  - duplicate-of-#NNNN
  - env-issue-out-of-scope
  - already-tracked-in-#NNNN
  - defer-with-followup-#NNNN

The defer-with-followup-#NNNN value REQUIRES a tracking issue number,
making deferral observable rather than silent.

Invoked by lifecycle-finalize.sh as a hard-block gate. MODE controlled by
RETROSPECTIVE_COMPLETENESS_MODE env var:
  warn (default during rollout): exit 0 + WARN log
  deny (post-rollout): exit 1 on incomplete, blocking finalize

Schema-version backwards compat: when the active run's schema_version
gating returns < 2 (old runs from before this PR's merge cutoff),
this validator skips with a WARN.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.schema_version_gate import required_schema_version  # type: ignore

PENDING_PATH = ".runs/retrospective-pending-findings.json"
FILED_PATH = ".runs/retrospective-filed-findings.json"
RESULT_PATH = ".runs/retrospective-result.json"

VALID_SUPPRESSION_REASONS = {
    "not-template-rooted",
    "env-issue-out-of-scope",
}
# Reasons that must reference an issue number — pattern <reason-prefix>-#NNNN
ISSUE_REF_REASON_PATTERNS = {
    "duplicate-of-#": re.compile(r"^duplicate-of-#\d+$"),
    "already-tracked-in-#": re.compile(r"^already-tracked-in-#\d+$"),
    "defer-with-followup-#": re.compile(r"^defer-with-followup-#\d+$"),
}


def _active_run_id() -> str:
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
        ts = d.get("timestamp") or ""
        if ts >= best_ts:
            best = d
            best_ts = ts
    return (best or {}).get("run_id", "")


def _is_valid_suppression_reason(reason: str) -> bool:
    if reason in VALID_SUPPRESSION_REASONS:
        return True
    for prefix, pattern in ISSUE_REF_REASON_PATTERNS.items():
        if reason.startswith(prefix) and pattern.match(reason):
            return True
    return False


def _mode() -> str:
    # #1393 (a) phase-2 shipped deny default. Resolution moved to shared
    # prose_gate_mode helper (#1449/#1431/#1433): PROSE_GATES_TOLERANT >
    # PROSE_GATE_RETRO_SUPPRESSIONS_CONFIRMATION_MODE > snapshot > registry
    # > prior_default="deny". prior_default preserves the #1393 phase-2 decision.
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
    from prose_gate_mode import resolve
    return resolve("retro-suppressions-confirmation", prior_default="deny")


def main() -> int:
    mode = _mode()

    rid = _active_run_id()
    required_v = required_schema_version(rid) if rid else 1
    if required_v < 2:
        print(
            f"validate-retrospective-completeness: SKIP (run_id={rid!r} "
            f"pre-cutoff; required schema_version={required_v})"
        )
        return 0

    if not os.path.isfile(PENDING_PATH):
        # #1393 (a) phase-3: SKIP → FAIL on missing pending-findings.json.
        # The pre-check in check-observation-artifacts.sh now rejects this
        # state upstream when MODE=deny (the new default), so this path is
        # structurally unreachable in normal flow. Promoting SKIP → FAIL
        # removes dead code AND defends against future callers that invoke
        # the validator directly without going through check-observation-artifacts.sh.
        msg = (
            f"validate-retrospective-completeness: FAIL (no {PENDING_PATH}; "
            "enumerate-pending-retrospective-findings.py was not run during "
            "Step 5a — silent-skip class #1385)"
        )
        print(msg, file=sys.stderr)
        return 0 if mode == "warn" else 1

    try:
        pending_doc = json.load(open(PENDING_PATH))
    except Exception as e:
        msg = f"BLOCK: cannot parse {PENDING_PATH}: {e}"
        print(msg, file=sys.stderr)
        return 0 if mode == "warn" else 1
    pending = pending_doc.get("candidates") or []
    if not pending:
        print("validate-retrospective-completeness: OK (0 pending candidates)")
        return 0

    pending_ids = {c.get("candidate_id") for c in pending if c.get("candidate_id")}

    # Collect filed candidate_ids
    filed_ids: set[str] = set()
    if os.path.isfile(FILED_PATH):
        try:
            filed_doc = json.load(open(FILED_PATH))
            for entry in filed_doc.get("filed") or []:
                cid = entry.get("candidate_id")
                if cid:
                    filed_ids.add(cid)
        except Exception:
            pass

    # Collect suppressed candidate_ids + validate enum
    suppressed_ids: set[str] = set()
    suppression_errors: list[str] = []
    if os.path.isfile(RESULT_PATH):
        try:
            result_doc = json.load(open(RESULT_PATH))
            for s in result_doc.get("suppressions") or []:
                cid = s.get("candidate_id")
                reason = s.get("reason") or ""
                if not cid:
                    suppression_errors.append(
                        f"suppression entry missing candidate_id: {s!r}"
                    )
                    continue
                if not _is_valid_suppression_reason(reason):
                    suppression_errors.append(
                        f"candidate {cid}: reason {reason!r} not in closed enum "
                        f"({sorted(VALID_SUPPRESSION_REASONS) + sorted(ISSUE_REF_REASON_PATTERNS)})"
                    )
                    continue
                suppressed_ids.add(cid)
        except Exception as e:
            suppression_errors.append(f"cannot parse {RESULT_PATH}: {e}")

    # Prose-gate retro-suppressions-confirmation: validate findings_filed[]
    # entries' confirmation_evidence (min_length:40). Additive — does not
    # change existing suppression handling. See .claude/patterns/prose-gates.json
    # gate_id=retro-suppressions-confirmation.
    CONFIRMATION_MIN_LENGTH = 40
    findings_filed_ids: set[str] = set()
    findings_filed_errors: list[str] = []
    result_doc_for_ff: dict = {}
    if os.path.isfile(RESULT_PATH):
        try:
            result_doc_for_ff = json.load(open(RESULT_PATH))
        except Exception:
            result_doc_for_ff = {}
    for ff in result_doc_for_ff.get("findings_filed") or []:
        cid = ff.get("candidate_id")
        if not cid:
            findings_filed_errors.append(
                f"findings_filed entry missing candidate_id: {ff!r}"
            )
            continue
        conf = ff.get("confirmation_evidence") or ""
        if not isinstance(conf, str) or len(conf) < CONFIRMATION_MIN_LENGTH:
            findings_filed_errors.append(
                f"findings_filed candidate_id={cid}: confirmation_evidence "
                f"must be string >={CONFIRMATION_MIN_LENGTH} chars "
                f"(got len={len(conf) if isinstance(conf, str) else 'non-string'})"
            )
            continue
        findings_filed_ids.add(cid)
    # Soft additive check on suppression confirmation_evidence — only flags
    # entries whose `confirmation_evidence` (or legacy `justification`) is
    # shorter than the threshold. Existing closed-enum check above is
    # unchanged.
    for s in result_doc_for_ff.get("suppressions") or []:
        cid = s.get("candidate_id")
        if not cid or cid not in suppressed_ids:
            continue
        conf = s.get("confirmation_evidence") or s.get("justification") or ""
        if len(conf) < CONFIRMATION_MIN_LENGTH:
            suppression_errors.append(
                f"suppression candidate_id={cid}: confirmation_evidence "
                f"(or legacy justification) must be >={CONFIRMATION_MIN_LENGTH} "
                f"chars (got len={len(conf)})"
            )

    disposed_ids = filed_ids | suppressed_ids | findings_filed_ids
    missing_ids = pending_ids - disposed_ids

    if not missing_ids and not suppression_errors and not findings_filed_errors:
        print(
            f"validate-retrospective-completeness: OK ({len(pending_ids)} pending, "
            f"{len(filed_ids)} filed, {len(suppressed_ids)} suppressed, "
            f"{len(findings_filed_ids)} findings_filed)"
        )
        return 0

    # Failure path
    print(
        f"validate-retrospective-completeness: FAIL "
        f"(missing dispositions: {len(missing_ids)}, "
        f"suppression errors: {len(suppression_errors)}, "
        f"findings_filed errors: {len(findings_filed_errors)})",
        file=sys.stderr,
    )
    if missing_ids:
        for cid in sorted(missing_ids):
            cand = next((c for c in pending if c.get("candidate_id") == cid), {})
            print(
                f"  MISSING DISPOSITION: candidate {cid} "
                f"(kind={cand.get('kind')}, key={cand.get('key')!r})",
                file=sys.stderr,
            )
        print(
            "\nFile each missing candidate via:\n"
            "  python3 .claude/scripts/file-retrospective-finding.py \\\n"
            "    --candidate-id <id> --title \"<title>\" --body \"<body>\"\n"
            "OR add a suppression to .runs/retrospective-result.json:\n"
            '  "suppressions": [{"candidate_id": "<id>", "reason": "<enum>", "justification": "..."}]',
            file=sys.stderr,
        )
    if suppression_errors:
        for e in suppression_errors:
            print(f"  SUPPRESSION ERROR: {e}", file=sys.stderr)
    if findings_filed_errors:
        for e in findings_filed_errors:
            print(f"  FINDINGS_FILED ERROR: {e}", file=sys.stderr)

    if mode == "warn":
        print("\n[MODE=warn] not blocking finalize", file=sys.stderr)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
