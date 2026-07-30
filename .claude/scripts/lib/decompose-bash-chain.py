#!/usr/bin/env python3
"""Decompose a Bash command into chained command segments.

Used by .claude/hooks/state-completion-gate.sh (issue #1339) and
.claude/hooks/branch-checkout-propagation-gate.sh (issue #1328) to inspect
sibling commands within a single Bash invocation.

Behavior contract
-----------------
* `decompose(cmd: str) -> list[tuple[str, list[str]]]` returns one
  (head_token, args_tokens) pair per chain segment. Segments are split by
  the standard shell separators: && || ; | & ( ).
* Heredoc bodies are stripped via `canonicalize_bash_command.strip_heredoc_bodies`
  before tokenization, so heredoc content cannot be mis-attributed to a
  segment.
* `__main__` reads the full command from stdin and emits one TSV row per
  segment: `<head>\t<json-encoded args list>`. Exit 0 on success.
* On parse error (unbalanced quotes, etc.) the helper FAILS CLOSED — exit 1
  with a stderr diagnostic. Callers that want fail-open semantics check
  the exit code and fall through to their default path.

Design contrast with check-advance-state-invocation.py: the older helper
fails OPEN on parse error to preserve the legacy grep behavior (and avoid
silent over-blocking of the LLM). This helper is invoked by hooks that
need to make a SAFE decision about deferring or pairing commands; "I
cannot tell what's in this chain" must surface as a deny rather than a
silent skip. See issue #1339 round-2 critic concern 10.
"""
from __future__ import annotations

import json
import os
import shlex
import sys

# Reuse the canonical heredoc stripper.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from canonicalize_bash_command import strip_heredoc_bodies  # noqa: E402


_SEGMENT_SEPARATORS = {"&&", "||", ";", "|", "&", "(", ")"}


def decompose(cmd: str) -> list[tuple[str, list[str]]]:
    """Split a Bash command into (head, args) per chain segment.

    Raises ValueError on tokenization failure (callers must catch + deny).
    """
    cleaned = strip_heredoc_bodies(cmd)
    try:
        # punctuation_chars=True tokenizes shell control chars (; | & < >) as
        # standalone tokens. Without it, `a.sh; b.sh` parses as `["a.sh;",
        # "b.sh"]` and the semicolon is glued to the head — see Python docs.
        # Default punctuation set is "();<>|&". `&&` / `||` are also returned
        # as single tokens.
        lexer = shlex.shlex(cleaned, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError as e:
        raise ValueError(f"shlex tokenization failed: {e}") from e

    segments: list[tuple[str, list[str]]] = []
    current: list[str] = []
    for tok in tokens:
        if tok in _SEGMENT_SEPARATORS:
            if current:
                segments.append((current[0], current[1:]))
                current = []
            continue
        current.append(tok)
    if current:
        segments.append((current[0], current[1:]))
    return segments


def main() -> int:
    cmd = sys.stdin.read()
    try:
        segments = decompose(cmd)
    except ValueError as e:
        sys.stderr.write(f"decompose-bash-chain: {e}\n")
        return 1
    for head, args in segments:
        sys.stdout.write(head + "\t" + json.dumps(args) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
