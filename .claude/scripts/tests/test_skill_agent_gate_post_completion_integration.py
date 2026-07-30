"""test_skill_agent_gate_post_completion_integration.py — end-to-end
integration test of the skill-agent-gate.sh hook's SOURCE_* honoring
path (closes #1275 audit gap, follow-up to PR #1303).

Tests the bash WIRING that test_source_identity_validator_hook.py
cannot cover: env var reading, validator invocation, branch on exit
code, non-degraded entry stamping vs degraded fall-through.

Spawns the actual hook subprocess with a synthesized PreToolUse
payload + controlled env vars and inspects the resulting
agent-spawn-log.jsonl entry.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
from pathlib import Path

import pytest


def _live_timestamp() -> str:
    """Return a UTC timestamp guaranteed to be within the 48h staleness cap
    enforced by `resolve_active_identity` in `.claude/hooks/lib-state.sh`.

    Hardcoded fixture timestamps go stale as the project ages (the test was
    originally green at fixture-write time but starts failing on day 4).
    Using `now()` keeps the fixture live across the project's lifetime.
    """
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / ".claude/hooks/skill-agent-gate.sh"


def _setup_runs(tmp_path: Path) -> Path:
    """Initialize a git repo at tmp_path so the hook's `lib-core.sh`
    `get_project_dir` resolves correctly. Without a git repo,
    resolve_active_identity may fail with exit code 2."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "test@local"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=str(tmp_path), check=True)
    # Empty commit so HEAD exists
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=str(tmp_path), check=True,
    )
    runs = tmp_path / ".runs"
    runs.mkdir()
    return runs


def _completed_context(runs: Path, skill: str, run_id: str) -> None:
    (runs / f"{skill}-context.json").write_text(json.dumps({
        "skill": skill, "run_id": run_id, "completed": True,
        "timestamp": "2026-04-22T13:00:00Z",
    }))


def _spawn_log_lines(runs: Path) -> list[dict]:
    p = runs / "agent-spawn-log.jsonl"
    if not p.is_file():
        return []
    out = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def _invoke_hook(
    tmp_path: Path,
    *,
    subagent_type: str,
    source_run_id: str | None,
    source_skill: str | None,
) -> subprocess.CompletedProcess:
    """Invoke skill-agent-gate.sh with a synthesized PreToolUse payload.

    The hook reads its payload from the CLAUDE_PAYLOAD env var (or
    stdin, depending on harness convention). Looking at
    `.claude/hooks/lib.sh`'s `parse_payload`, it reads from stdin via
    a JSON object with `tool_input.subagent_type`.
    """
    payload = json.dumps({
        "tool_input": {"subagent_type": subagent_type},
        "tool_name": "Agent",
    })
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    if source_run_id is not None:
        env["SOURCE_RUN_ID"] = source_run_id
    else:
        env.pop("SOURCE_RUN_ID", None)
    if source_skill is not None:
        env["SOURCE_SKILL"] = source_skill
    else:
        env.pop("SOURCE_SKILL", None)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=payload,
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )


def test_no_source_env_writes_degraded_entry(tmp_path: Path) -> None:
    """Default behavior (no SOURCE_* env vars) is unchanged: the hook
    writes a degraded spawn-log entry when at least one context file
    exists (bypassing the fast-path) but no active identity resolves.
    Regression test for non-Group-A flows."""
    runs = _setup_runs(tmp_path)
    # Need a completed context so the hook's fast-path (empty CTX_FILES
    # → exit 0 without writing) does NOT trigger; resolve_active_identity
    # returns empty because the only context is completed.
    _completed_context(runs, "bootstrap", "boot-1")
    rc = _invoke_hook(
        tmp_path, subagent_type="design-critic",
        source_run_id=None, source_skill=None,
    )
    # Hook exits 0 (does not block) but writes a degraded entry.
    assert rc.returncode == 0, rc.stderr
    entries = _spawn_log_lines(runs)
    assert len(entries) == 1
    e = entries[0]
    assert e.get("agent") == "design-critic"
    assert e.get("hook") == "skill-agent-gate"
    assert e.get("degraded") is True
    assert e.get("lead_orchestrated") is not True


def test_source_env_with_completed_context_writes_non_degraded(tmp_path: Path) -> None:
    """Happy path — every gate satisfied: completed context exists,
    no active skill, no replay. Hook writes a NON-degraded entry under
    the SOURCE identity."""
    runs = _setup_runs(tmp_path)
    _completed_context(runs, "bootstrap", "boot-1")
    rc = _invoke_hook(
        tmp_path, subagent_type="observer",
        source_run_id="boot-1", source_skill="bootstrap",
    )
    assert rc.returncode == 0, rc.stderr
    entries = _spawn_log_lines(runs)
    assert len(entries) == 1
    e = entries[0]
    assert e.get("agent") == "observer"
    assert e.get("hook") == "skill-agent-gate"
    assert e.get("run_id") == "boot-1"
    assert e.get("skill") == "bootstrap"
    assert e.get("degraded") is not True
    assert e.get("lead_orchestrated") is True
    assert "HONORED" in rc.stderr


def test_source_env_without_completed_context_falls_through(tmp_path: Path) -> None:
    """GATE-I refuses when SOURCE_* names a context that is NOT
    completed:true. To exercise the validator path, we also need
    resolve_active_identity to return empty (so the hook enters the
    degraded branch and consults SOURCE_*). Use a completed context
    for `bootstrap` AND set SOURCE_* to a DIFFERENT skill that has
    no completed context — gate (i) refuses the SOURCE_* identity."""
    runs = _setup_runs(tmp_path)
    # Make active identity empty by having only a completed context.
    _completed_context(runs, "bootstrap", "boot-1")
    rc = _invoke_hook(
        tmp_path, subagent_type="design-critic",
        # SOURCE_* names a NON-EXISTENT skill+run_id pair.
        source_run_id="phantom-1", source_skill="phantom-skill",
    )
    assert rc.returncode == 0, rc.stderr
    entries = _spawn_log_lines(runs)
    lead_entries = [e for e in entries if e.get("lead_orchestrated") is True]
    assert lead_entries == [], f"Should NOT have stamped lead_orchestrated; got {lead_entries}"
    assert "REFUSED" in rc.stderr
    assert "GATE-I" in rc.stderr


def test_source_env_replay_attempt_falls_through(tmp_path: Path) -> None:
    """GATE-III — anti-replay. After a successful first stamping, a
    second invocation with the same SOURCE_RUN_ID for the same agent
    is refused; hook falls through to degraded entry."""
    runs = _setup_runs(tmp_path)
    _completed_context(runs, "bootstrap", "boot-1")
    # First invocation succeeds
    rc1 = _invoke_hook(
        tmp_path, subagent_type="observer",
        source_run_id="boot-1", source_skill="bootstrap",
    )
    assert rc1.returncode == 0
    entries1 = _spawn_log_lines(runs)
    assert len(entries1) == 1
    assert entries1[0].get("lead_orchestrated") is True
    # Second invocation should be refused (anti-replay)
    rc2 = _invoke_hook(
        tmp_path, subagent_type="observer",
        source_run_id="boot-1", source_skill="bootstrap",
    )
    assert rc2.returncode == 0, rc2.stderr
    entries2 = _spawn_log_lines(runs)
    # Exactly ONE lead_orchestrated entry (the first); the second
    # invocation must NOT add a new lead_orchestrated entry (anti-replay).
    lead_entries = [e for e in entries2 if e.get("lead_orchestrated") is True]
    assert len(lead_entries) == 1
    assert "REFUSED" in rc2.stderr
    assert "GATE-III" in rc2.stderr


def test_source_run_id_without_source_skill_falls_through(tmp_path: Path) -> None:
    """R1 (xor): both env vars required. Only one set → hook ignores
    SOURCE_* (does not even invoke validator) and falls through to
    the existing degraded path."""
    runs = _setup_runs(tmp_path)
    _completed_context(runs, "bootstrap", "boot-1")
    rc = _invoke_hook(
        tmp_path, subagent_type="observer",
        source_run_id="boot-1", source_skill=None,
    )
    assert rc.returncode == 0
    entries = _spawn_log_lines(runs)
    assert len(entries) == 1
    e = entries[0]
    assert e.get("lead_orchestrated") is not True
    assert e.get("degraded") is True


def test_active_identity_present_refuses_source_honoring(tmp_path: Path) -> None:
    """When an active skill exists on the branch, the hook never
    enters the degraded path → SOURCE_* env vars are structurally
    bypassed (no chance to honor). GATE-II at the validator layer is
    redundant with this bash-level structure but still serves as
    defense-in-depth if the degraded-detection logic ever changes."""
    runs = _setup_runs(tmp_path)
    # An ACTIVE (not completed) verify context — resolve_active_identity
    # would return ('verify', 'v-1') AND completed:true context for
    # bootstrap is also present. We'd expect the hook's normal
    # non-degraded path to take over because active identity is non-empty.
    (runs / "verify-context.json").write_text(json.dumps({
        "skill": "verify", "run_id": "v-1", "completed": False,
        "timestamp": _live_timestamp(),
        "branch": _current_branch(tmp_path),
    }))
    _completed_context(runs, "bootstrap", "boot-1")
    rc = _invoke_hook(
        tmp_path, subagent_type="design-critic",
        source_run_id="boot-1", source_skill="bootstrap",
    )
    assert rc.returncode == 0, rc.stderr
    entries = _spawn_log_lines(runs)
    # Critical: even though SOURCE_* was supplied, the hook must NOT
    # stamp a lead_orchestrated entry because active identity is set.
    # (The hook may have proceeded down the active-identity path, which
    # in this fixture has no manifest and exits silently — semantic of
    # "did not honor SOURCE_*" still holds.)
    lead_entries = [e for e in entries if e.get("lead_orchestrated") is True]
    assert lead_entries == [], f"Should NOT have stamped lead_orchestrated; got {lead_entries}"


def _current_branch(repo: Path) -> str:
    """Resolve the test process's current branch (the hook checks this
    when filtering contexts via resolve_active_identity)."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(repo) if (repo / ".git").is_dir() else ROOT,
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip() or "main"
    except Exception:
        return "main"
