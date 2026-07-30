#!/usr/bin/env python3
"""Canonicalize Bash command strings for hook regex matching.

Strips heredoc bodies (preserving the introducer line), so that hook regex
checks operate on shell-executable surface only — not on heredoc-body data
that happens to contain protected substrings.

Closes #1298 (writer-name in heredoc body false-positive). Replaces the
strip_heredoc_bodies that previously lived in check-advance-state-invocation.py
and fixes three pre-existing correctness bugs verified empirically during
the /solve run for #1298:

1. Loop-restart bug — the previous `while True: m = _HEREDOC_START.search(cmd)`
   form re-matched the consumed introducer on the next iteration; when no
   closing delim was found (because the previous iteration removed it), the
   "unterminated" branch wiped everything from body_start to end-of-string.
   This made `cat <<EOF\\nbody\\nEOF\\necho > path` collapse to `cat <<EOF\\n\\n`
   — silently dropping a real trailing write and creating a chained-write
   bypass for write-guard hooks.

2. POSIX strictness bug — `stripped.strip() == delim` closed heredocs on
   `   EOF` and `EOF   `, where POSIX bash for plain `<<DELIM` requires the
   closing line to be exactly the delimiter. Under-strip → over-allow is a
   security regression direction; over-strip → over-deny is acceptable.

3. Same-line multi-heredoc bug — `cat <<E1 <<E2\\nb1\\nE1\\nb2\\nE2` is valid
   bash where bash queues b1 for E1 and b2 for E2. The previous form
   processed only the first introducer per outer-loop iteration; advancing
   the search position past body_start would skip E2 because E2 lives BEFORE
   body_start on the same intro line.

Conservative direction: when ambiguity arises, OVER-STRIP rather than
UNDER-STRIP. Over-strip → over-deny → false positive (harmless on retry).
UNDER-STRIP → over-allow → false negative (security regression).

Usage from a Bash hook (after a cheap fast-path glob):

    COMMAND_CANONICAL=$(printf '%s' "$COMMAND" \\
      | python3 .claude/scripts/lib/canonicalize_bash_command.py)
"""
from __future__ import annotations

import re
import sys

__all__ = ["strip_heredoc_bodies", "canonicalize"]


# Matches `<<DELIM`, `<<-DELIM`, `<<'DELIM'`, `<<"DELIM"`. Delim must start
# with a letter or underscore and be followed by alphanumerics/underscores.
# Pre-existing partial-match behavior on `<<<DELIM` (here-string): the regex
# matches `<<DELIM` starting at offset 1 due to overlapping match. Here-strings
# are rare and the over-strip direction is conservative; not a regression.
_HEREDOC_START = re.compile(
    r"<<(-)?\s*(?P<quote>['\"]?)(?P<delim>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)"
)


def strip_heredoc_bodies(cmd: str) -> str:
    """Remove heredoc bodies. Preserves the heredoc-introducer line.

    Algorithm: scan forward through `cmd`, accumulating output in
    `result_parts`. At each heredoc introducer, find ALL introducers on the
    same intro line (bash queues their bodies in introducer order), then
    consume each queued body in order and resume scanning AFTER the last
    consumed body.
    """
    result_parts: list[str] = []
    pos = 0
    n = len(cmd)
    while pos < n:
        m = _HEREDOC_START.search(cmd, pos)
        if not m:
            result_parts.append(cmd[pos:])
            break

        intro_line_end = cmd.find("\n", m.end())
        if intro_line_end == -1:
            # No newline after the introducer → no body lines exist.
            # Emit the rest of cmd as-is and stop.
            result_parts.append(cmd[pos:])
            break

        # Collect ALL heredoc introducers on this same intro line. Bash
        # queues bodies in introducer order: `cat <<E1 <<E2` → body1 belongs
        # to E1, body2 belongs to E2. (round-2-c2 fix)
        intro_line_start = cmd.rfind("\n", 0, m.start()) + 1
        queue: list[tuple[str, bool]] = []
        for mm in _HEREDOC_START.finditer(cmd, intro_line_start, intro_line_end):
            queue.append((mm.group("delim"), bool(mm.group(1))))

        # Emit everything up to (and including) the intro-line newline.
        result_parts.append(cmd[pos:intro_line_end + 1])
        idx = intro_line_end + 1

        # Consume each queued body in order. POSIX-strict closing-delim match
        # (round-2-c3 fix): plain `<<` requires the closing line to be exactly
        # the delimiter; `<<-` permits leading TABS only (not spaces).
        for delim, strip_indent in queue:
            end_of_close = None
            while idx < n:
                line_end = cmd.find("\n", idx)
                if line_end == -1:
                    line = cmd[idx:]
                    next_idx = n
                else:
                    line = cmd[idx:line_end]
                    next_idx = line_end + 1
                if strip_indent:
                    if line.lstrip("\t") == delim:
                        end_of_close = next_idx
                        break
                else:
                    if line == delim:
                        end_of_close = next_idx
                        break
                idx = next_idx

            if end_of_close is None:
                # Unterminated body — over-strip the rest (conservative).
                return "".join(result_parts) + "\n"
            idx = end_of_close

        pos = idx  # Resume scan AFTER all queued bodies (loop-restart fix).

    return "".join(result_parts)


def canonicalize(cmd: str) -> str:
    """Public entry point — currently equivalent to strip_heredoc_bodies."""
    return strip_heredoc_bodies(cmd)


def main() -> int:
    sys.stdout.write(canonicalize(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
