#!/usr/bin/env bash
# clean-stale-worktrees.sh — Remove >24h stale skill worktrees.
#
# Lifts the inline pattern previously in .claude/commands/change.md (24h-age cleanup)
# into a shared helper so /resolve, /solve, /change all benefit. Guards against
# removing in-use work: self-excludes the worktree it runs inside, skips any
# worktree whose .runs/<prefix>-context.json has completed:false, and skips any
# stale worktree with uncommitted changes.
#
# Uses `git worktree list --porcelain` (registered worktrees only) instead of a
# filesystem glob to avoid removing user-created directories that happen to live
# under .claude/worktrees/.
#
# Argument: prefix (e.g., "solve", "resolve", "change"). Required.
# Behavior: silent on no-op; warnings on stderr.
set -euo pipefail
PREFIX="${1:-}"
[ -z "$PREFIX" ] && exit 0

NOW=$(date +%s)

# Resolve the worktree this script is running inside. Self-exclusion (below) is the
# decisive guard against deleting the active session's own worktree — it does not
# depend on the .runs/<prefix>-context.json marker, which does not exist yet when
# commands invoke cleanup at Step 0 (before init-context.sh writes it).
SELF=$(git rev-parse --show-toplevel 2>/dev/null || true)

for wt in $(git worktree list --porcelain 2>/dev/null | awk '/^worktree / {print $2}' | grep "/.claude/worktrees/${PREFIX}-" || true); do
  # Self-exclusion: never remove the worktree we are running inside, whatever its
  # marker or mtime says.
  if [ -n "$SELF" ] && [ -e "$wt" ] && [ "$wt" -ef "$SELF" ]; then
    continue
  fi
  CTX="${wt}/.runs/${PREFIX}-context.json"
  # Active-session guard: skip if context exists and is in-flight (completed:false).
  if [ -f "$CTX" ] && python3 -c "import json,sys; sys.exit(0 if json.load(open('$CTX')).get('completed') is False else 1)" 2>/dev/null; then
    continue
  fi
  # Portable mtime (epoch). GNU `stat -c %Y` first, BSD `stat -f %m` second: BSD-first
  # silently corrupts the value on Linux, where `-f` means --file-system and dumps a
  # filesystem block into the capture (mirrors .claude/skills/bootstrap/gates/write.sh).
  MTIME=$(stat -c %Y "$wt" 2>/dev/null || stat -f %m "$wt" 2>/dev/null || echo 0)
  if [ "$MTIME" -gt 0 ] && [ $((NOW - MTIME)) -gt 86400 ]; then
    # Dirty-worktree safety: never force-remove a stale worktree that still has
    # uncommitted changes — it may hold unsaved work.
    if [ -n "$(git -C "$wt" status --porcelain 2>/dev/null || true)" ]; then
      echo "clean-stale-worktrees: skipping stale $wt (uncommitted changes present)" >&2
      continue
    fi
    git worktree remove --force "$wt" 2>/dev/null || true
  fi
done
