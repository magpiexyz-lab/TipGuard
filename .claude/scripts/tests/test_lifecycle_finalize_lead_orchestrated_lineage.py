"""test_lifecycle_finalize_lead_orchestrated_lineage.py — Step 4.8 gate
(closes #1275 — actual recurrence guard for lead-orchestrated trace
lineage to spawn-log).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
GATE = ROOT / ".claude/scripts/verify-lead-orchestrated-spawn-log-lineage.py"


def _setup_runs(tmp_path: Path) -> Path:
    runs = tmp_path / ".runs"
    (runs / "agent-traces").mkdir(parents=True)
    return runs


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(GATE), "--project-dir", str(tmp_path)],
        capture_output=True, text=True,
    )


def _lead_orchestrated_trace(runs: Path, agent: str, source_run_id: str) -> Path:
    p = runs / "agent-traces" / f"{agent}.json"
    p.write_text(json.dumps({
        "agent": agent,
        "provenance": "lead-orchestrated",
        "lead_attestation": True,
        "source_run_id": source_run_id,
        "source_skill": "bootstrap",
        "verdict": "pass",
        "status": "completed",
    }))
    return p


def _spawn_log_entry(runs: Path, entry: dict) -> None:
    with (runs / "agent-spawn-log.jsonl").open("a") as f:
        f.write(json.dumps(entry) + "\n")


def test_no_lead_orchestrated_traces_passes(tmp_path: Path) -> None:
    _setup_runs(tmp_path)
    rc = _run(tmp_path)
    assert rc.returncode == 0, rc.stderr


def test_lead_orchestrated_with_matching_non_degraded_entry_passes(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _lead_orchestrated_trace(runs, "observer", "boot-1")
    _spawn_log_entry(runs, {
        "agent": "observer", "run_id": "boot-1",
        "hook": "skill-agent-gate",
    })
    rc = _run(tmp_path)
    assert rc.returncode == 0, rc.stderr


def test_lead_orchestrated_with_only_degraded_entry_blocks(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _lead_orchestrated_trace(runs, "observer", "boot-1")
    _spawn_log_entry(runs, {
        "agent": "observer", "run_id": "boot-1",
        "hook": "skill-agent-gate", "degraded": True,
    })
    rc = _run(tmp_path)
    assert rc.returncode == 1
    assert "no non-degraded spawn-log entry" in rc.stderr


def test_lead_orchestrated_with_no_spawn_log_blocks(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _lead_orchestrated_trace(runs, "observer", "boot-1")
    rc = _run(tmp_path)
    assert rc.returncode == 1


def test_lead_orchestrated_missing_source_run_id_blocks(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    p = runs / "agent-traces" / "observer.json"
    p.write_text(json.dumps({
        "agent": "observer",
        "provenance": "lead-orchestrated",
        "lead_attestation": True,
        # No source_run_id
        "source_skill": "bootstrap",
        "verdict": "pass",
        "status": "completed",
    }))
    rc = _run(tmp_path)
    assert rc.returncode == 1
    assert "source_run_id missing" in rc.stderr


def test_self_provenance_traces_ignored(tmp_path: Path) -> None:
    """The gate only fires on lead-orchestrated traces; --provenance self
    traces are unaffected."""
    runs = _setup_runs(tmp_path)
    p = runs / "agent-traces" / "design-critic.json"
    p.write_text(json.dumps({
        "agent": "design-critic", "provenance": "self",
        "verdict": "pass", "status": "completed",
    }))
    rc = _run(tmp_path)
    assert rc.returncode == 0, rc.stderr


def test_multi_lead_orchestrated_traces_partial_lineage_blocks(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _lead_orchestrated_trace(runs, "observer", "boot-1")
    _lead_orchestrated_trace(runs, "pattern-classifier", "boot-1")
    # Only observer's entry is in spawn-log
    _spawn_log_entry(runs, {
        "agent": "observer", "run_id": "boot-1",
        "hook": "skill-agent-gate",
    })
    rc = _run(tmp_path)
    assert rc.returncode == 1
    assert "pattern-classifier" in rc.stderr
