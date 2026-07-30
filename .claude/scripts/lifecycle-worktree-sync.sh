#!/usr/bin/env bash
# lifecycle-worktree-sync.sh — Sync .runs/ artifacts from worktree to main repo.
# Usage: bash .claude/scripts/lifecycle-worktree-sync.sh
# Must be called BEFORE ExitWorktree while still in the worktree.
#
# Rules:
#   .json  → overwrite (point-in-time snapshot, latest run replaces stale)
#   .jsonl → append    (cumulative log, worktree doesn't inherit main's history)
set -euo pipefail

MAIN_DIR=$(git worktree list | head -1 | awk '{print $1}')
mkdir -p "$MAIN_DIR/.runs/agent-traces" "$MAIN_DIR/.runs/gate-verdicts"

# All files except .jsonl: overwrite (covers .json, .md, .txt, etc.)
for f in .runs/*; do
  [ -f "$f" ] && [[ "$f" != *.jsonl ]] && cp "$f" "$MAIN_DIR/$f"
done
for f in .runs/agent-traces/*.json; do
  [ -f "$f" ] && cp "$f" "$MAIN_DIR/$f"
done
for f in .runs/gate-verdicts/*.json; do
  [ -f "$f" ] && cp "$f" "$MAIN_DIR/$f"
done

# .jsonl: append
for f in .runs/*.jsonl; do
  [ -f "$f" ] && cat "$f" >> "$MAIN_DIR/$f"
done
