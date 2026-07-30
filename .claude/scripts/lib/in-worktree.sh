#!/usr/bin/env bash
# in-worktree.sh — Canonical detection of "am I inside a non-primary git worktree?"
#
# Returns "true" on stdout if cwd is inside a non-primary git worktree, "false" otherwise.
# Uses the canonical comparison documented in .claude/patterns/branch.md (--git-common-dir
# vs --git-dir): they are equal in the primary worktree and differ inside any linked worktree.
#
# Single source of truth for skill lifecycle decisions. Replaces the empirically-unreliable
# CLAUDE_WORKTREE env var (which is NOT auto-set when a session starts inside a pre-existing
# worktree — verified during issue #1200 investigation).
#
# Usage:
#   IN_WORKTREE=$(bash .claude/scripts/lib/in-worktree.sh)
#   if [ "$IN_WORKTREE" = "true" ]; then ...; fi
if [ "$(git rev-parse --git-common-dir 2>/dev/null)" != "$(git rev-parse --git-dir 2>/dev/null)" ]; then
  echo "true"
else
  echo "false"
fi
