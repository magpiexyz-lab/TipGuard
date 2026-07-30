#!/usr/bin/env python3
"""
Recurrence guard for issue #1200 — worktree ownership invariant.

Asserts the canonical worktree-ownership pattern in every command file that
calls EnterWorktree, and that no state file calls EnterWorktree (forbidden
per Rule 13: state files are prose-only — conditional dispatch belongs in
command-file pre/post-loop sections).

Exits non-zero on violation. Intended to run alongside verify-linter.sh from
lifecycle-finalize.sh.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # .claude/scripts/<this> → repo root
COMMANDS = ROOT / ".claude" / "commands"
SKILLS = ROOT / ".claude" / "skills"

errors: list[str] = []


def strip_code_fences(text: str) -> str:
    """Replace fenced-code content with blank lines (preserving line numbers).

    A future skill author cannot evade the parser by putting `EnterWorktree`
    inside a doc-only fenced block; conversely, fenced bash blocks within
    the command file (which DO execute) are detected because their content
    is preserved through the strip — wait, no: this strips ALL fenced content.

    The visibility model: command files use fenced bash blocks for the actual
    EnterWorktree call. The parser must see those. So we keep fenced content
    visible, but we also need to handle the doc-comment case differently.

    Refined approach: do NOT strip fenced content. Instead the parser tolerates
    code-fence presence. The previous worry about doc-only mentions in fences
    is overblown: command files only mention EnterWorktree in their lifecycle
    instructions, and that's exactly where the pattern must be present.
    """
    # No-op: keep all content visible. Code fences are part of the executable
    # instructions in command files.
    return text


def check_command_file(path: Path) -> None:
    raw = path.read_text()
    visible = strip_code_fences(raw)
    if "EnterWorktree" not in visible:
        return  # not a worktree-using command — nothing to assert
    # 1. canonical detection helper called and bound to IN_WORKTREE before first EnterWorktree
    enter_idx = visible.find("EnterWorktree")
    detect_re = re.compile(r"IN_WORKTREE=\$\(bash\s+[^)]*in-worktree\.sh[^)]*\)")
    if not detect_re.search(visible[:enter_idx]):
        errors.append(
            f"{path.relative_to(ROOT)}: missing canonical detection "
            "(expected `IN_WORKTREE=$(bash …/in-worktree.sh)` BEFORE first EnterWorktree)"
        )
    # 2. worktree_owner appears at least twice (one setup, one cleanup)
    if visible.count("worktree_owner") < 2:
        errors.append(
            f"{path.relative_to(ROOT)}: worktree_owner appears {visible.count('worktree_owner')} time(s); "
            "expected ≥2 (one setup, one cleanup)"
        )
    # 3. ExitWorktree gated by OWNER/worktree_owner conditional within ≤4 lines
    lines = visible.splitlines()
    for i, line in enumerate(lines):
        if "ExitWorktree" in line:
            window = "\n".join(lines[max(0, i - 4): i + 1])
            has_conditional = bool(re.search(r"(if\s+.*OWNER|OWNER\s*==|\$OWNER|worktree_owner)", window))
            if not has_conditional:
                errors.append(
                    f"{path.relative_to(ROOT)}:{i + 1}: ExitWorktree not gated by OWNER/worktree_owner conditional within ≤4 lines"
                )


def check_state_file(path: Path) -> None:
    raw = path.read_text()
    for keyword in ("EnterWorktree", "ExitWorktree"):
        if keyword in raw:
            errors.append(
                f"{path.relative_to(ROOT)}: state files MUST NOT call {keyword} "
                "(belongs in command file pre/post-loop per Rule 13)"
            )


def main() -> int:
    for f in sorted(COMMANDS.glob("*.md")):
        check_command_file(f)
    for f in sorted(SKILLS.glob("*/state-*.md")):
        check_state_file(f)
    if errors:
        print("worktree-ownership-pattern violations:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("worktree-ownership-pattern: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
