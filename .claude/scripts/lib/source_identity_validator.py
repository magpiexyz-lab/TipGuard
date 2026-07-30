"""AOC v1.2 source-identity validator.

Validates --source-run-id / --source-skill flags supplied to canonical trace
writers when resolve_active_identity returns empty (post-completion scenario).

Validation rules (R1-R4 per the design):
  R1 (xor): both source flags supplied together (or neither). Exactly one
     supplied is rejected.
  R2 (context-existence): when both supplied, (run_id, skill) must exist in
     some .runs/*-context.json (any state, including completed:true).
  R3 (spawn-log): when both supplied AND an agent name is provided, the
     (agent, run_id) pair must appear in .runs/agent-spawn-log.jsonl with
     hook == 'skill-agent-gate'. Skipped when agent is None (e.g., for
     non-agent-specific writers like lib/write-gate-artifact.sh).
  R4 (HC13 cross-skill forgery gate): when resolve_active_identity returns
     NON-empty, the supplied source_skill MUST differ from the active skill.
     Same-skill source override is forbidden (mirrors write-recovery-trace.sh
     :172-186 cross-skill recovery defense).

Public API:
    validate_source_identity(source_run_id, source_skill, *, agent=None,
                              project_dir=None, active_identity=None)
        -> list[str]   # empty when valid; one ERROR string per failed rule

CLI shim (used by .sh writers):
    python3 .claude/scripts/lib/source_identity_validator.py \
        --source-run-id <ID> --source-skill <NAME> [--agent <name>]
    # exit 0 when valid; non-zero with diagnostics on stderr otherwise.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable


def _resolve_active_identity_default(project_dir: Path) -> tuple[str, str]:
    """Shell out to .claude/hooks/lib.sh::resolve_active_identity.

    Returns (skill, run_id). Both empty strings when no active identity.
    """
    try:
        out = subprocess.check_output(
            ["bash", "-c", "source .claude/hooks/lib.sh && resolve_active_identity"],
            cwd=str(project_dir),
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return ("", "")
    text = out.decode("utf-8", errors="replace").strip()
    if not text:
        return ("", "")
    parts = text.split("\t")
    skill = parts[0] if len(parts) >= 1 else ""
    run_id = parts[1] if len(parts) >= 2 else ""
    return (skill, run_id)


def _context_exists(
    run_id: str,
    skill: str,
    project_dir: Path,
    *,
    require_completed: bool = False,
) -> bool:
    """R2: (run_id, skill) must exist in some .runs/*-context.json.

    When `require_completed=True`, additionally requires the matching
    context's `completed` field to be exactly True (post-completion
    precondition for the hook's lead-orchestrated honoring path).
    """
    runs_dir = project_dir / ".runs"
    if not runs_dir.is_dir():
        return False
    for ctx_path in runs_dir.glob("*-context.json"):
        try:
            data = json.loads(ctx_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("run_id") == run_id and data.get("skill") == skill:
            if require_completed and data.get("completed") is not True:
                continue
            return True
    return False


def _spawn_log_has(
    agent: str,
    run_id: str,
    project_dir: Path,
    *,
    require_non_degraded: bool = False,
) -> bool:
    """R3: (agent, run_id, hook='skill-agent-gate') in agent-spawn-log.jsonl.

    When `require_non_degraded=True`, only returns True when a matching
    entry exists with `degraded` not set to True (used by the hook's
    anti-replay gate to detect a prior non-degraded stamping for the
    same source identity).
    """
    spawn_log = project_dir / ".runs" / "agent-spawn-log.jsonl"
    if not spawn_log.is_file():
        return False
    try:
        with spawn_log.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    entry.get("agent") == agent
                    and entry.get("run_id") == run_id
                    and entry.get("hook") == "skill-agent-gate"
                ):
                    if require_non_degraded and entry.get("degraded") is True:
                        continue
                    return True
    except OSError:
        return False
    return False


def validate_source_identity(
    source_run_id: str | None,
    source_skill: str | None,
    *,
    agent: str | None = None,
    project_dir: str | os.PathLike | None = None,
    active_identity: tuple[str, str] | None = None,
) -> list[str]:
    """Apply R1-R4 to the supplied source flags.

    Returns a list of ERROR strings (empty when valid). Caller is responsible
    for either propagating these to stderr/exit-code or merging into a larger
    validation report.

    `active_identity` may be passed by callers that already resolved it (avoids
    double subprocess call). When None, the validator shells out itself.
    """
    project_dir = Path(project_dir or os.getcwd()).resolve()
    errors: list[str] = []

    # R1 (xor): both supplied together, or neither.
    has_run_id = bool(source_run_id)
    has_skill = bool(source_skill)
    if has_run_id != has_skill:
        which_present = "--source-run-id" if has_run_id else "--source-skill"
        which_missing = "--source-skill" if has_run_id else "--source-run-id"
        errors.append(
            f"R1 (xor): {which_present} supplied without {which_missing} — both source flags "
            f"must be supplied together or neither."
        )
        return errors  # subsequent rules require both flags present

    # When neither is supplied, no validation needed (writer falls back to
    # resolve_active_identity per its existing path).
    if not has_run_id:
        return errors

    # R2 (context-existence): (run_id, skill) must exist in .runs/*-context.json.
    if not _context_exists(source_run_id, source_skill, project_dir):
        errors.append(
            f"R2 (context-existence): no .runs/*-context.json has run_id={source_run_id!r} "
            f"AND skill={source_skill!r}. Cannot attribute trace to a non-existent context."
        )

    # R3 (spawn-log): only when agent is provided.
    if agent is not None:
        if not _spawn_log_has(agent, source_run_id, project_dir):
            errors.append(
                f"R3 (spawn-log): no skill-agent-gate spawn-log entry for "
                f"(agent={agent!r}, run_id={source_run_id!r}). Agent must have been "
                f"spawned via the Agent tool in that run before its trace can be "
                f"lead-orchestrated."
            )

    # R4 (HC13 cross-skill forgery gate): when active identity is non-empty,
    # source_skill MUST differ from active skill.
    if active_identity is None:
        active_skill, _active_run_id = _resolve_active_identity_default(project_dir)
    else:
        active_skill, _active_run_id = active_identity
    if active_skill and source_skill == active_skill:
        errors.append(
            f"R4 (HC13 cross-skill forgery gate): source_skill={source_skill!r} "
            f"equals the currently-active skill. Same-skill identity override "
            f"is forbidden — use the no-override path instead (writer's normal "
            f"resolve_active_identity flow)."
        )

    return errors


def validate_source_identity_for_hook(
    source_run_id: str | None,
    source_skill: str | None,
    *,
    agent: str | None = None,
    project_dir: str | os.PathLike | None = None,
    active_identity: tuple[str, str] | None = None,
) -> list[str]:
    """Hook-side counterpart of `validate_source_identity` (closes #1275 C13).

    Called from `.claude/hooks/skill-agent-gate.sh` BEFORE the hook stamps
    a non-degraded spawn-log entry from `SOURCE_RUN_ID` / `SOURCE_SKILL`
    env vars. The writer's `validate_source_identity` runs at WRITE time
    and trusts the spawn-log; this function runs at SPAWN time and
    independently verifies the post-completion precondition before any
    spawn-log entry is written.

    Three gates beyond R1+R2:
      (i) Context existence + completed:true — the supplied identity must
          name a real prior skill that finished (post-completion only).
      (ii) Active-identity exclusion — if any skill is currently active,
          the normal writer path applies; honoring SOURCE_* mid-skill is
          the forgery vector.
      (iii) Anti-replay — refuse if a non-degraded spawn-log entry
          already exists for the same (agent, source_run_id). Each
          post-completion re-spawn must produce exactly one fresh entry.

    R3 is intentionally inverted here vs. the writer: the writer asserts
    the entry exists; the hook asserts the non-degraded entry does NOT
    yet exist (so this hook invocation is the entry's first writer).
    """
    project_dir = Path(project_dir or os.getcwd()).resolve()
    errors: list[str] = []

    # R1 (xor) — both required for hook honoring.
    has_run_id = bool(source_run_id)
    has_skill = bool(source_skill)
    if not (has_run_id and has_skill):
        errors.append(
            "R1 (xor): SOURCE_RUN_ID and SOURCE_SKILL must both be set "
            "to invoke the lead-orchestrated honoring path at the hook."
        )
        return errors

    # Gate (ii): active-identity exclusion. The hook only honors SOURCE_*
    # when no active skill exists on the branch. If active_identity is
    # populated, the normal spawn-log path applies; SOURCE_* should be
    # ignored to prevent mid-skill forgery (sharpened R4).
    if active_identity is None:
        active_skill, _active_run_id = _resolve_active_identity_default(project_dir)
    else:
        active_skill, _active_run_id = active_identity
    if active_skill:
        errors.append(
            f"GATE-II (active-identity exclusion): active skill={active_skill!r} "
            f"is non-empty. SOURCE_RUN_ID/SOURCE_SKILL honoring is reserved for "
            f"true post-completion conditions. Use the normal spawn-log path."
        )
        # Subsequent gates would still apply; return early to mirror
        # write-recovery-trace.sh's fail-closed posture.
        return errors

    # Gate (i): context existence + completed:true.
    if not _context_exists(
        source_run_id, source_skill, project_dir, require_completed=True
    ):
        errors.append(
            f"GATE-I (context+completed): no .runs/*-context.json has "
            f"run_id={source_run_id!r} AND skill={source_skill!r} AND "
            f"completed:true. Hook honoring requires a real prior skill that "
            f"finished (post-completion precondition)."
        )

    # Gate (iii): anti-replay. Only meaningful when an agent is supplied
    # (the hook always knows the agent name from the tool payload).
    if agent is not None:
        if _spawn_log_has(
            agent, source_run_id, project_dir, require_non_degraded=True
        ):
            errors.append(
                f"GATE-III (anti-replay): a non-degraded spawn-log entry "
                f"already exists for (agent={agent!r}, run_id={source_run_id!r}). "
                f"Each post-completion re-spawn must produce exactly one "
                f"fresh entry; replay attempts are refused."
            )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate AOC v1.2 source-identity overrides (R1-R4 / hook gates).",
    )
    parser.add_argument("--source-run-id", default="")
    parser.add_argument("--source-skill", default="")
    parser.add_argument("--agent", default=None)
    parser.add_argument(
        "--project-dir",
        default=os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()),
    )
    parser.add_argument(
        "--mode",
        choices=("writer", "hook"),
        default="writer",
        help="writer: R1-R4 (default; called from canonical writers). "
             "hook: R1+gates I/II/III (called from skill-agent-gate.sh).",
    )
    args = parser.parse_args(argv)

    if args.mode == "hook":
        errors = validate_source_identity_for_hook(
            args.source_run_id or None,
            args.source_skill or None,
            agent=args.agent,
            project_dir=args.project_dir,
        )
    else:
        errors = validate_source_identity(
            args.source_run_id or None,
            args.source_skill or None,
            agent=args.agent,
            project_dir=args.project_dir,
        )
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
