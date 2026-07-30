"""test_lifecycle_finalize_post_fix_respawn.py — Step 4.7 gate
(closes #1274 — recurrence guard for design-critic post-fix re-spawn
obligation).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
GATE = ROOT / ".claude/scripts/verify-design-critic-post-fix-respawn.py"


def _setup_runs(tmp_path: Path) -> Path:
    runs = tmp_path / ".runs"
    (runs / "agent-traces").mkdir(parents=True)
    return runs


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(GATE), "--project-dir", str(tmp_path)],
        capture_output=True, text=True,
    )


def _verify_context(runs: Path, run_id: str = "verify-1") -> None:
    (runs / "verify-context.json").write_text(json.dumps({
        "skill": "verify", "run_id": run_id, "completed": True,
    }))


def _ledger_lead_fix(runs: Path, run_id: str, file: str) -> None:
    line = json.dumps({
        "run_id": run_id, "provenance": "lead", "file": file,
        "agent": "lead-verify", "fix_id": f"lead-verify:{run_id}:1",
    })
    with (runs / "fix-ledger.jsonl").open("a") as f:
        f.write(line + "\n")


def _per_page_trace(runs: Path, page: str, shared_files: list) -> None:
    (runs / "agent-traces" / f"design-critic-{page}.json").write_text(json.dumps({
        "agent": "design-critic", "page": page,
        "verdict": "unresolved", "result": "partial",
        "status": "completed",
        "shared_issues": [{"file": f} for f in shared_files],
    }))


def _post_fix_trace(runs: Path, page: str, epoch: int, verdict: str = "pass") -> None:
    (runs / "agent-traces" / f"design-critic-{page}--epoch{epoch}.json").write_text(
        json.dumps({
            "agent": "design-critic", "page": page,
            "verdict": verdict, "result": "fixed",
            "status": "completed", "epoch": epoch,
        })
    )


def test_no_obligation_when_no_fix_ledger(tmp_path: Path) -> None:
    _setup_runs(tmp_path)
    rc = _run(tmp_path)
    assert rc.returncode == 0, rc.stderr


def test_no_obligation_when_fix_does_not_match_any_shared_issue(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _verify_context(runs)
    _ledger_lead_fix(runs, "verify-1", "src/components/Header.tsx")
    _per_page_trace(runs, "home", shared_files=["src/components/Footer.tsx"])
    rc = _run(tmp_path)
    assert rc.returncode == 0, rc.stderr


def test_obligation_unmet_blocks(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _verify_context(runs)
    _ledger_lead_fix(runs, "verify-1", "src/components/Header.tsx")
    _per_page_trace(runs, "home", shared_files=["src/components/Header.tsx"])
    rc = _run(tmp_path)
    assert rc.returncode == 1
    assert "no design-critic-home--epoch<N>.json" in rc.stderr


def test_obligation_met_with_pass_verdict(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _verify_context(runs)
    _ledger_lead_fix(runs, "verify-1", "src/components/Header.tsx")
    _per_page_trace(runs, "home", shared_files=["src/components/Header.tsx"])
    _post_fix_trace(runs, "home", epoch=1, verdict="pass")
    rc = _run(tmp_path)
    assert rc.returncode == 0, rc.stderr


def test_obligation_met_with_fixed_verdict(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _verify_context(runs)
    _ledger_lead_fix(runs, "verify-1", "src/components/Header.tsx")
    _per_page_trace(runs, "home", shared_files=["src/components/Header.tsx"])
    _post_fix_trace(runs, "home", epoch=1, verdict="fixed")
    rc = _run(tmp_path)
    assert rc.returncode == 0, rc.stderr


def test_obligation_unmet_when_post_fix_trace_unresolved(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _verify_context(runs)
    _ledger_lead_fix(runs, "verify-1", "src/components/Header.tsx")
    _per_page_trace(runs, "home", shared_files=["src/components/Header.tsx"])
    _post_fix_trace(runs, "home", epoch=1, verdict="unresolved")
    rc = _run(tmp_path)
    assert rc.returncode == 1


def test_ux_journeyer_ui_fix_triggers_obligation(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _verify_context(runs)
    # Per-page trace has reviewed_files containing the .tsx file
    (runs / "agent-traces" / "design-critic-checkout.json").write_text(json.dumps({
        "agent": "design-critic", "page": "checkout",
        "verdict": "pass", "result": "clean",
        "status": "completed",
        "reviewed_files": ["src/app/checkout/page.tsx"],
    }))
    # ux-journeyer modified that page
    (runs / "agent-traces" / "ux-journeyer.json").write_text(json.dumps({
        "agent": "ux-journeyer",
        "verdict": "pass",
        "fixes": [{"file": "src/app/checkout/page.tsx", "symptom": "x", "fix": "y"}],
    }))
    rc = _run(tmp_path)
    assert rc.returncode == 1
    assert "checkout" in rc.stderr


def test_ux_journeyer_obligation_satisfied_by_post_fix_trace(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _verify_context(runs)
    (runs / "agent-traces" / "design-critic-checkout.json").write_text(json.dumps({
        "agent": "design-critic", "page": "checkout",
        "verdict": "pass", "result": "clean",
        "status": "completed",
        "reviewed_files": ["src/app/checkout/page.tsx"],
    }))
    (runs / "agent-traces" / "ux-journeyer.json").write_text(json.dumps({
        "agent": "ux-journeyer",
        "verdict": "pass",
        "fixes": [{"file": "src/app/checkout/page.tsx", "symptom": "x", "fix": "y"}],
    }))
    _post_fix_trace(runs, "checkout", epoch=1, verdict="pass")
    rc = _run(tmp_path)
    assert rc.returncode == 0, rc.stderr


def test_existing_epoch_trace_basename_excluded_from_obligation_pages(tmp_path: Path) -> None:
    """The script considers only base traces (no --epoch suffix) as
    obligation candidates; --epoch traces are the satisfaction signal."""
    runs = _setup_runs(tmp_path)
    _verify_context(runs)
    _ledger_lead_fix(runs, "verify-1", "src/components/Header.tsx")
    # Only an --epoch1 trace exists for `home` — no base trace. The gate
    # should not invent an obligation it cannot prove existed pre-fix.
    _post_fix_trace(runs, "home", epoch=1, verdict="pass")
    rc = _run(tmp_path)
    assert rc.returncode == 0, rc.stderr
