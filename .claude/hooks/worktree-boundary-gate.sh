#!/usr/bin/env bash
# worktree-boundary-gate.sh — PreToolUse guard for Write/Edit/MultiEdit/NotebookEdit.
#
# Closes issue #1225: when a skill (e.g. /solve, /resolve, /change) enters an
# isolated worktree via EnterWorktree, the harness tools accept any absolute
# file_path. If the lead Claude misremembers the worktree prefix (long context,
# scrolled-away EnterWorktree event), an Edit/Write call with a main-repo path
# succeeds silently against the main repo while `git status` from the worktree
# shows clean. Recovery requires manual `git diff > /tmp/patch; git checkout
# --; git apply /tmp/patch` and is invisible until cross-checked.
#
# This hook validates `tool_input.file_path` (or `tool_input.notebook_path`
# for NotebookEdit) against the active worktree root. Out-of-bounds writes are
# blocked with a corrective-suggestion error.
#
# Defect class: silent-failure (siblings #1170, #1222, #1224). Distinct from
# #1200 (worktree LIFECYCLE entry/exit/ownership); this fix covers worktree
# BOUNDARY (path validation during active state).
#
# Coverage:
#   - Write: tool_input.file_path
#   - Edit: tool_input.file_path
#   - MultiEdit: tool_input.file_path (defensive — see plan first-principles #9)
#   - NotebookEdit: tool_input.notebook_path
#
# Allowlist (writes safe regardless of worktree state):
#   - /tmp/* and /private/tmp/* (macOS symlink), /var/tmp/* and /private/var/tmp/*
#   - $HOME/.claude/projects/*/memory/* (auto-memory, harness-managed)
#
# Out of scope (documented in silent-failure-prevention.md):
#   - Bash-redirect writes (cat >, tee, cp, mv) — different tool surface.
#   - Parent-cwd-writes-to-stale-worktree — different defect class.

set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

# 1. Read path. Write/Edit/MultiEdit use file_path; NotebookEdit uses notebook_path.
FILE_PATH=$(read_payload_field "tool_input.file_path")
if [[ -z "$FILE_PATH" ]]; then
  FILE_PATH=$(read_payload_field "tool_input.notebook_path")
fi

# Defensive: if neither field is present, the hook has nothing to validate.
# friction-skip: trivial-fast-path — neither file_path nor notebook_path provided.
[[ -z "$FILE_PATH" ]] && exit 0

# 2. Lexical allowlist fast-path. Zero git invocation for the common case.
case "$FILE_PATH" in
  /tmp/*|/private/tmp/*|/var/tmp/*|/private/var/tmp/*) exit 0 ;;
  "$HOME"/.claude/projects/*/memory/*) exit 0 ;;
esac

# 3. Inline worktree detection (avoids spawning in-worktree.sh subshell).
# Mirrors .claude/scripts/lib/in-worktree.sh logic.
GIT_DIR=$(git rev-parse --git-dir 2>/dev/null || true)
GIT_COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null || true)

# Not in a git repo → NO-OP.
# friction-skip: trivial-fast-path — outside any git repo, hook does not apply.
[[ -z "$GIT_DIR" || -z "$GIT_COMMON_DIR" ]] && exit 0

# Primary worktree (or non-worktree) → NO-OP. The hook only enforces in
# non-primary worktrees, where the boundary defect originates.
# friction-skip: post-validation — primary worktree authoritatively determined; boundary check does not apply.
[[ "$GIT_DIR" == "$GIT_COMMON_DIR" ]] && exit 0

# 4. In a non-primary worktree. Validate FILE_PATH against worktree root.
# Resolve symlinks on both sides — workstations sometimes have a symlinked
# workspace root (/Users/me/proj → /Volumes/data/proj). Comparing realpath
# on both sides eliminates the false-positive class.
ABS_PATH=$(python3 -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$FILE_PATH")
ABS_REAL=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$ABS_PATH")
WT_REAL=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$CLAUDE_PROJECT_DIR")

# Allow if either lexical or realpath form is inside the worktree root.
if [[ "$ABS_PATH" == "$CLAUDE_PROJECT_DIR"/* || "$ABS_REAL" == "$WT_REAL"/* ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# 5. Out-of-bounds. Compute MAIN_REPO_ROOT for the categorized denial message.
# Use `dirname --` (NOT `xargs dirname`) to handle paths with spaces.
MAIN_ROOT=$(dirname -- "$GIT_COMMON_DIR")
MAIN_REAL=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$MAIN_ROOT")

# Cross-worktree write: another worktree's path.
if [[ "$ABS_REAL" == "$MAIN_REAL"/.claude/worktrees/* ]]; then
  deny "worktree-boundary-gate (issue #1225): target is in a different worktree, not the active one.
Active worktree: $CLAUDE_PROJECT_DIR
Target:          $FILE_PATH
Cross-worktree writes are never legitimate. Use the active worktree path."
fi

# Main-repo write: emit a corrective-suggestion line.
if [[ "$ABS_REAL" == "$MAIN_REAL"/* ]]; then
  # Build suggestion on realpath form so prefix substitution survives the
  # /tmp ↔ /private/tmp and /var ↔ /private/var symlink dances on macOS,
  # where `git rev-parse --git-common-dir` returns canonical paths but
  # FILE_PATH may use the non-canonical form.
  SUGGESTED="${ABS_REAL/#$MAIN_REAL/$WT_REAL}"
  deny "worktree-boundary-gate (issue #1225): target is outside the active worktree (in main repo).
Active worktree: $CLAUDE_PROJECT_DIR
Target:          $FILE_PATH
Did you mean:    $SUGGESTED ?
Allowed exceptions: /tmp/*, /var/tmp/*, ~/.claude/projects/*/memory/*"
fi

# Other out-of-bounds: not in main repo, not in any worktree, not in allowlist.
deny "worktree-boundary-gate (issue #1225): target is outside the active worktree and not in the allowlist.
Active worktree: $CLAUDE_PROJECT_DIR
Target:          $FILE_PATH
Allowed exceptions: /tmp/*, /var/tmp/*, ~/.claude/projects/*/memory/*"
