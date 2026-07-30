"""Dossier verification helper (Issue #1415).

Single source of truth for asserting that solve-reasoning Phase 1a Prior-Failure
Dossier was actually built before solve-trace.json is accepted. Called from both
verify-recurrence-guard.py (--require-dossier flag) and verify-change-solve.py
(inline import) so all three callers (resolve.5, solve.1, change.3) use the
same contract.

Public surface:
    assert_dossier_loaded(trace, *, problem_type, divergence_files_evidence) -> None
    DossierVerifyError
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

DOSSIER_PATH = ".runs/prior-failure-dossier.json"


class DossierVerifyError(AssertionError):
    """Raised when the dossier contract is violated."""


def _load_dossier(path: str = DOSSIER_PATH) -> dict:
    if not os.path.isfile(path):
        raise DossierVerifyError(
            f"prior-failure-dossier.json missing at {path}. "
            "Phase 1a (Prior-Failure Dossier construction) was skipped. "
            "See solve-reasoning.md Phase 1a + the Step 0 bash in the active state file."
        )
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise DossierVerifyError(f"{path} not parseable as JSON: {exc}")


def assert_dossier_loaded(
    trace: dict,
    *,
    problem_type: str | None,
    divergence_files_evidence: Iterable[str] = (),
) -> None:
    """Assert dossier contract when problem_type=defect; no-op otherwise.

    Contract:
      (a) .runs/prior-failure-dossier.json exists and parses
      (b) prior_failure_response is a list in solve-trace.json (empty allowed)
      (c) dossier._meta.divergence_files is non-empty when caller's
          divergence_files_evidence is non-empty (closes empty-input bypass)
      (d) when dossier.phase_1a is non-empty,
          len(prior_failure_response) >= len(phase_1a)
    """
    if problem_type != "defect":
        return

    dossier = _load_dossier()
    phase_1a = dossier.get("phase_1a")
    if not isinstance(phase_1a, list):
        raise DossierVerifyError(
            "prior-failure-dossier.json has no phase_1a list — corrupted dossier"
        )

    meta = dossier.get("_meta") or {}
    meta_files = meta.get("divergence_files") or []
    evidence = [f for f in (divergence_files_evidence or []) if f]
    if evidence and not meta_files:
        raise DossierVerifyError(
            f"dossier._meta.divergence_files is empty but caller listed "
            f"{len(evidence)} divergence file(s). Phase 1a was invoked with "
            "empty input — the dossier is vacuous. Pass the caller's "
            "divergence files into dossier_builder.build_dossier."
        )

    response = trace.get("prior_failure_response")
    if not isinstance(response, list):
        raise DossierVerifyError(
            "solve-trace.json.prior_failure_response missing or not a list. "
            "Phase 4b must emit prior_failure_response (empty list when "
            "dossier was empty) — see solve-reasoning.md Phase 4b."
        )

    # Git-sentinel entries (prior_run_id starts with "git:") are advisory —
    # surfaced from git history when the ledger is empty (#1437 fix). The
    # designer SHOULD consult them via `git show <sha>` but is not required
    # to enumerate one prior_failure_response per. Only ledger-derived
    # entries (real prior run_ids) count toward the response-floor.
    ledger_entries = [
        e for e in phase_1a
        if not str(e.get("prior_run_id", "")).startswith("git:")
    ]
    if ledger_entries and len(response) < len(ledger_entries):
        raise DossierVerifyError(
            f"prior_failure_response has {len(response)} entries but dossier "
            f"phase_1a has {len(ledger_entries)} LEDGER entries "
            f"(git-sentinel entries are advisory and excluded). Phase 4b "
            "contract requires >=1 response per ledger entry citing a "
            "concrete_delta_step_or_guard."
        )


__all__ = ["assert_dossier_loaded", "DossierVerifyError", "DOSSIER_PATH"]
