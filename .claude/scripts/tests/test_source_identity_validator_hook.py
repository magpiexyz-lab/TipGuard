"""test_source_identity_validator_hook.py — unit tests for
`validate_source_identity_for_hook` (closes #1275 round-2 critic C13).

The hook-side validator runs at PreToolUse Agent spawn time and decides
whether `SOURCE_RUN_ID`/`SOURCE_SKILL` env vars may be honored to stamp
a non-degraded spawn-log entry. Three gates beyond R1+R2:

  (i)   context+completed:true precondition (post-completion only)
  (ii)  active-identity exclusion (no honoring mid-skill)
  (iii) anti-replay (no second non-degraded entry for the same source)

Companion to `test_forgery_surface.py` which exercises the writer-side
`validate_source_identity` (R1-R4).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".claude/scripts/lib/source_identity_validator.py"

_spec = importlib.util.spec_from_file_location("siv", SCRIPT)
siv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(siv)


def _setup_runs(tmp_path: Path) -> Path:
    runs = tmp_path / ".runs"
    runs.mkdir()
    return runs


def _write_context(runs: Path, skill: str, run_id: str, completed: bool) -> None:
    (runs / f"{skill}-context.json").write_text(json.dumps({
        "skill": skill, "run_id": run_id, "completed": completed,
    }))


def _append_spawn_log(runs: Path, entry: dict) -> None:
    log = runs / "agent-spawn-log.jsonl"
    with log.open("a") as f:
        f.write(json.dumps(entry) + "\n")


# ----- R1 (xor) -----

def test_r1_both_required_run_id_only(tmp_path: Path) -> None:
    _setup_runs(tmp_path)
    errors = siv.validate_source_identity_for_hook(
        "run-x", None, agent="design-critic",
        project_dir=str(tmp_path), active_identity=("", ""),
    )
    assert any("R1 (xor)" in e for e in errors)


def test_r1_both_required_skill_only(tmp_path: Path) -> None:
    _setup_runs(tmp_path)
    errors = siv.validate_source_identity_for_hook(
        None, "verify", agent="design-critic",
        project_dir=str(tmp_path), active_identity=("", ""),
    )
    assert any("R1 (xor)" in e for e in errors)


def test_r1_neither_supplied(tmp_path: Path) -> None:
    """Hook MUST require both for honoring; absence is also rejected."""
    errors = siv.validate_source_identity_for_hook(
        None, None, agent="design-critic",
        project_dir=str(tmp_path), active_identity=("", ""),
    )
    assert any("R1 (xor)" in e for e in errors)


# ----- Gate (ii): active-identity exclusion -----

def test_gate_ii_refuses_when_active_identity_nonempty(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _write_context(runs, "verify", "verify-1", completed=False)
    errors = siv.validate_source_identity_for_hook(
        "verify-1", "verify", agent="design-critic",
        project_dir=str(tmp_path),
        active_identity=("verify", "verify-1"),
    )
    assert any("GATE-II" in e for e in errors)


def test_gate_ii_passes_when_active_identity_empty(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _write_context(runs, "bootstrap", "boot-1", completed=True)
    errors = siv.validate_source_identity_for_hook(
        "boot-1", "bootstrap", agent="design-critic",
        project_dir=str(tmp_path),
        active_identity=("", ""),
    )
    assert not any("GATE-II" in e for e in errors)


# ----- Gate (i): context + completed:true -----

def test_gate_i_refuses_when_context_missing(tmp_path: Path) -> None:
    _setup_runs(tmp_path)
    errors = siv.validate_source_identity_for_hook(
        "phantom-1", "ghost", agent="design-critic",
        project_dir=str(tmp_path), active_identity=("", ""),
    )
    assert any("GATE-I" in e for e in errors)


def test_gate_i_refuses_when_context_completed_false(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _write_context(runs, "bootstrap", "boot-1", completed=False)
    errors = siv.validate_source_identity_for_hook(
        "boot-1", "bootstrap", agent="design-critic",
        project_dir=str(tmp_path), active_identity=("", ""),
    )
    assert any("GATE-I" in e for e in errors)


def test_gate_i_passes_when_context_completed_true(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _write_context(runs, "bootstrap", "boot-1", completed=True)
    errors = siv.validate_source_identity_for_hook(
        "boot-1", "bootstrap", agent="design-critic",
        project_dir=str(tmp_path), active_identity=("", ""),
    )
    assert errors == []


# ----- Gate (iii): anti-replay -----

def test_gate_iii_refuses_replay(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _write_context(runs, "bootstrap", "boot-1", completed=True)
    _append_spawn_log(runs, {
        "agent": "design-critic", "run_id": "boot-1",
        "hook": "skill-agent-gate", "degraded": False,
    })
    errors = siv.validate_source_identity_for_hook(
        "boot-1", "bootstrap", agent="design-critic",
        project_dir=str(tmp_path), active_identity=("", ""),
    )
    assert any("GATE-III" in e for e in errors)


def test_gate_iii_allows_replay_after_only_degraded_entries(tmp_path: Path) -> None:
    """A degraded entry from a prior failed honoring attempt must not
    block a fresh non-degraded stamping (the whole point of this fix)."""
    runs = _setup_runs(tmp_path)
    _write_context(runs, "bootstrap", "boot-1", completed=True)
    _append_spawn_log(runs, {
        "agent": "design-critic", "run_id": "boot-1",
        "hook": "skill-agent-gate", "degraded": True,
        "degradation_reason": "active_identity_unresolvable",
    })
    errors = siv.validate_source_identity_for_hook(
        "boot-1", "bootstrap", agent="design-critic",
        project_dir=str(tmp_path), active_identity=("", ""),
    )
    assert errors == []


def test_gate_iii_skipped_when_no_agent(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _write_context(runs, "bootstrap", "boot-1", completed=True)
    errors = siv.validate_source_identity_for_hook(
        "boot-1", "bootstrap", agent=None,
        project_dir=str(tmp_path), active_identity=("", ""),
    )
    assert errors == []


# ----- Composite happy path -----

def test_happy_path_all_gates_pass(tmp_path: Path) -> None:
    runs = _setup_runs(tmp_path)
    _write_context(runs, "bootstrap", "boot-1", completed=True)
    # No prior spawn-log entry → gate iii passes
    errors = siv.validate_source_identity_for_hook(
        "boot-1", "bootstrap", agent="observer",
        project_dir=str(tmp_path), active_identity=("", ""),
    )
    assert errors == []


# ----- Writer-side validator unchanged (regression) -----

def test_writer_validator_completed_false_context_still_accepted(tmp_path: Path) -> None:
    """`validate_source_identity` (writer-side) does NOT require
    completed:true — only the hook does. Regression check."""
    runs = _setup_runs(tmp_path)
    _write_context(runs, "verify", "verify-1", completed=False)
    _append_spawn_log(runs, {
        "agent": "design-critic", "run_id": "verify-1",
        "hook": "skill-agent-gate",
    })
    errors = siv.validate_source_identity(
        "verify-1", "verify", agent="design-critic",
        project_dir=str(tmp_path), active_identity=("", ""),
    )
    # Writer rules R1+R2+R3+R4 all satisfied here.
    assert errors == []


def test_cli_mode_hook(tmp_path: Path) -> None:
    """The CLI shim --mode hook routes to the hook validator."""
    import subprocess
    runs = _setup_runs(tmp_path)
    _write_context(runs, "bootstrap", "boot-1", completed=True)
    rc = subprocess.run(
        [
            "python3", str(SCRIPT),
            "--source-run-id", "boot-1",
            "--source-skill", "bootstrap",
            "--agent", "observer",
            "--project-dir", str(tmp_path),
            "--mode", "hook",
        ],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr


def test_cli_mode_hook_refuses_active_identity(tmp_path: Path) -> None:
    """CLI shim picks up active identity via subprocess; we cover the
    explicit-active-identity path through Python API since the subprocess
    cannot easily inject a fake active identity."""
    runs = _setup_runs(tmp_path)
    _write_context(runs, "bootstrap", "boot-1", completed=True)
    errors = siv.validate_source_identity_for_hook(
        "boot-1", "bootstrap", agent="observer",
        project_dir=str(tmp_path),
        active_identity=("some-active-skill", "active-1"),
    )
    assert any("GATE-II" in e for e in errors)
