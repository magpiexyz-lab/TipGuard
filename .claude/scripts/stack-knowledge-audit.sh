#!/usr/bin/env bash
# Stack Knowledge nightly audit — shell driver.
#
# Files GitHub issues for knowledge-base hygiene: dedup reconciliation,
# pattern family candidates, archive candidates, and maturity promotions.
# Implementation lives in .claude/scripts/lib/stack_knowledge_audit.py.
#
# Usage:
#   bash .claude/scripts/stack-knowledge-audit.sh             # live run
#   bash .claude/scripts/stack-knowledge-audit.sh --dry-run   # print planned actions
#   bash .claude/scripts/stack-knowledge-audit.sh --no-gh     # offline mode (no gh calls)
#
# Guard: refuses to run if there are uncommitted changes under
# .claude/stacks/ — an in-progress edit could poison the audit's view of
# "live knowledge" and lead to spurious issue filings.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
AUDIT_PY="$SCRIPT_DIR/lib/stack_knowledge_audit.py"

cd "$REPO_ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found" >&2
  exit 1
fi

if [[ ! -f "$AUDIT_PY" ]]; then
  echo "ERROR: $AUDIT_PY not found" >&2
  exit 1
fi

# Guard 1: refuse to run against uncommitted stack changes.
if [[ -d .git ]] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  dirty="$(git status --porcelain -- .claude/stacks/ 2>/dev/null || true)"
  if [[ -n "$dirty" ]]; then
    echo "ERROR: uncommitted changes under .claude/stacks/ — commit or stash before running audit" >&2
    echo "$dirty" >&2
    exit 1
  fi
fi

exec python3 "$AUDIT_PY" "$@"
