#!/usr/bin/env python3
"""Detect whether a Bash command actually invokes advance-state.sh.

Used by .claude/hooks/state-completion-gate.sh and
.claude/hooks/phase-boundary-gate.sh to filter out false-positive matches
where the literal text "advance-state.sh" appears inside heredoc bodies,
single/double-quoted strings, --body / --body-file argument values, or
comments — without actually being the head of a Bash command.

Closes #1223. Wired in by both hooks via:

    if ! printf '%s' "$COMMAND" | python3 .../check-advance-state-invocation.py; then
      exit 0   # not an actual invocation
    fi
    SKILL=$(printf '%s' "$COMMAND" | python3 .../check-advance-state-invocation.py --print-skill)
    STATE_ID=$(printf '%s' "$COMMAND" | python3 .../check-advance-state-invocation.py --print-state-id)

Behavior contract
-----------------
* `__main__` reads the full command from stdin.
* Default mode (no flag): exit 0 when the command DOES invoke
  advance-state.sh at a command-head position, exit 1 otherwise. This
  matches the existing `grep -qE` semantics (exit 0 means "fire").
* `--print-skill` / `--print-state-id`: print the parsed skill / state_id
  argument to stdout (empty if not detectable). Exit 0 always.
* On parse exceptions (malformed shlex, etc.) the helper FAILS OPEN —
  returns the same status as "not an invocation" — so callers do NOT
  silently change a previously-allowing path into a blocking one.

Heredoc handling
----------------
Heredoc bodies are scanned line-by-line and stripped before tokenization,
so `gh issue create --body "$(cat <<EOF ... advance-state.sh ... EOF)"`
no longer matches. The scan supports:
  * `<<DELIM` and `<<-DELIM` (tab-strip variant)
  * Quoted delimiters (`<<'EOF'`, `<<"EOF"`)
  * Custom delimiter names (`PYEOF`, `SCRIPTEND`, etc.)
  * Multiple heredocs in a single command (loop until stable)

Quoted-string handling
----------------------
After heredoc stripping, shlex.split (POSIX mode) is used to tokenize.
shlex correctly preserves single/double-quoted regions as a single token,
so `--body "...advance-state.sh..."` becomes one token whose VALUE contains
the script name but whose token POSITION is not a command head — the
walker below skips it.

Command-head detection
----------------------
A token is at command-head position if it is at index 0 OR the previous
token is one of the segment separators: && || ; | & ( ).
"""
from __future__ import annotations

import os
import shlex
import sys

# Re-export from the canonicalizer module. Closes #1298 — the previous inline
# implementation had three pre-existing correctness bugs (loop-restart wipes
# trailing real writes; POSIX-strictness over-permissive; same-line multi-
# heredoc skipped). The shared module fixes all three; existing #1223 callers
# (state-completion-gate.sh, phase-boundary-gate.sh) inherit the fix
# transparently through this import.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from canonicalize_bash_command import strip_heredoc_bodies  # noqa: E402


_SEGMENT_SEPARATORS = {"&&", "||", ";", "|", "&", "(", ")"}


def parse_invocation(cmd: str) -> tuple[bool, str, str]:
    """Return (is_invocation, skill, state_id).

    Fails open on malformed input — returns (False, "", "").
    """
    try:
        cleaned = strip_heredoc_bodies(cmd)
    except Exception:
        return False, "", ""

    try:
        tokens = shlex.split(cleaned, posix=True, comments=False)
    except ValueError:
        # Unbalanced quotes — fail open.
        return False, "", ""

    n = len(tokens)
    for i, tok in enumerate(tokens):
        is_head = (i == 0) or (i > 0 and tokens[i - 1] in _SEGMENT_SEPARATORS)
        if not is_head:
            continue

        # Direct invocation: <path>/advance-state.sh <skill> <state_id>
        if tok.endswith("advance-state.sh") and tok != "advance-state.sh" or (
            tok == "advance-state.sh" and (i == 0 or tokens[i - 1] in _SEGMENT_SEPARATORS)
        ) or (
            "/" in tok and os.path.basename(tok) == "advance-state.sh"
        ):
            skill = tokens[i + 1] if i + 1 < n else ""
            state_id = tokens[i + 2] if i + 2 < n else ""
            return True, skill, state_id

        # Indirect invocation: bash <path>/advance-state.sh <skill> <state_id>
        if tok == "bash" and i + 1 < n:
            next_tok = tokens[i + 1]
            if next_tok.endswith("advance-state.sh"):
                skill = tokens[i + 2] if i + 2 < n else ""
                state_id = tokens[i + 3] if i + 3 < n else ""
                return True, skill, state_id

    return False, "", ""


def main() -> int:
    args = sys.argv[1:]
    cmd = sys.stdin.read()
    is_invocation, skill, state_id = parse_invocation(cmd)

    if not args:
        # Default mode: exit 0 when the command IS an invocation, else 1.
        return 0 if is_invocation else 1

    if "--print-skill" in args:
        sys.stdout.write(skill or "")
        return 0
    if "--print-state-id" in args:
        sys.stdout.write(state_id or "")
        return 0

    # Unknown flag — fail open.
    return 1


if __name__ == "__main__":
    sys.exit(main())
