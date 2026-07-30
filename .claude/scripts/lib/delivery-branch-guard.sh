#!/usr/bin/env bash
# delivery-branch-guard.sh <skill> [default-branch]
#
# Ensures lifecycle-finalize.sh's delivery step never commits on the default
# branch (issue #1990: an analysis-mode skill with no init-created branch had
# its run record committed and pushed directly to main). Invoked (not sourced)
# so pytest can drive it against a throwaway repo; no gh dependency.
#
# Stdout contract (single line, consumed by the caller):
#   GUARD=noop                 already on a non-default branch — safe to commit
#   GUARD=skip-no-changes      on default branch, clean tree, HEAD == origin —
#                              nothing to deliver, do not create an empty branch
#   GUARD=branched:<name>      chore branch created and checked out
# Exit 1 means safety could not be guaranteed — the caller MUST NOT commit.
set -euo pipefail

SKILL="${1:?usage: delivery-branch-guard.sh <skill> [default-branch]}"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"

DEFAULT_BRANCH="${2:-}"
if [[ -z "$DEFAULT_BRANCH" ]]; then
  # shellcheck source=/dev/null
  source "$PROJECT_DIR/.claude/scripts/lifecycle-lib.sh"
  DEFAULT_BRANCH=$(resolve_default_branch)
fi

CURRENT=$(git branch --show-current)

# Detached HEAD cannot be proven safe — fall through to branch creation.
if [[ -n "$CURRENT" && "$CURRENT" != "$DEFAULT_BRANCH" ]]; then
  echo "GUARD=noop"
  exit 0
fi

if [[ "$CURRENT" == "$DEFAULT_BRANCH" ]]; then
  if [[ -z "$(git status --porcelain -uno)" ]]; then
    if git show-ref --verify --quiet "refs/remotes/origin/$DEFAULT_BRANCH"; then
      if [[ "$(git rev-parse HEAD)" == "$(git rev-parse "origin/$DEFAULT_BRANCH")" ]]; then
        echo "GUARD=skip-no-changes"
        exit 0
      fi
    else
      echo "GUARD=skip-no-changes"
      exit 0
    fi
  fi
  if git show-ref --verify --quiet "refs/remotes/origin/$DEFAULT_BRANCH" \
    && [[ -n "$(git rev-list "origin/$DEFAULT_BRANCH..HEAD" 2>/dev/null)" ]]; then
    echo "WARN: local $DEFAULT_BRANCH is ahead of origin/$DEFAULT_BRANCH — those commits will ride into the delivery PR; realign $DEFAULT_BRANCH manually after merge" >&2
  fi
fi

TS="${DELIVERY_GUARD_TS:-$(date -u +%Y%m%d-%H%M%SZ)}"
BASE_NAME="chore/${SKILL}-delivery-${TS}"
NEW_BRANCH="$BASE_NAME"
suffix=2
while git show-ref --verify --quiet "refs/heads/$NEW_BRANCH"; do
  if (( suffix > 5 )); then
    echo "ERROR: delivery-branch-guard: branch names $BASE_NAME(-2..-5) all exist — refusing to guess further" >&2
    exit 1
  fi
  NEW_BRANCH="${BASE_NAME}-${suffix}"
  suffix=$((suffix + 1))
done

# Bundled checkout chain (branch-checkout-propagation-pairing rule): the
# sentinel + update-context-branch.sh call must share the chain with
# `git checkout -b` so context.branch propagation can never be skipped.
echo "$(date +%s)" > "$PROJECT_DIR/.runs/last-branch-checkout.tsv" && \
  OLD_BRANCH="$(git branch --show-current)" && \
  git checkout -b "$NEW_BRANCH" && \
  bash "$PROJECT_DIR/.claude/scripts/update-context-branch.sh" "$OLD_BRANCH" || {
    echo "ERROR: delivery-branch-guard: failed to create/propagate $NEW_BRANCH" >&2
    exit 1
  }

echo "GUARD=branched:$NEW_BRANCH"
