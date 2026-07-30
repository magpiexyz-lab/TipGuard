#!/usr/bin/env bash
# branch-checkout-propagation-gate.sh — PreToolUse hook on Bash.
# Issue #1328: deny any Bash chain containing `git checkout -b` that does
# NOT have a sibling `update-context-branch.sh` invocation in the same
# chain. Without same-turn propagation, .runs/*-context.json's `branch`
# field stays stale relative to `git branch --show-current`, and
# resolve_active_identity (lib-state.sh) filters out the active context.
# Agent spawns in the gap stamp `degradation_reason: active_identity_unresolvable`.
#
# Escape hatch: BRANCH_CHECKOUT_PROPAGATION_GATE_SKIP=1 (for tests / ad-hoc
# checkouts that intentionally skip propagation). Always-enforce default —
# silent-bypass risk exceeds false-positive risk for legitimate manual
# checkouts.
set -euo pipefail

# Honor escape hatch — read from the hook payload's tool_input.command's
# enclosing environment is not directly available; instead callers prefix
# the env var on the Bash invocation itself, so the env var is visible to
# the hook process. Tests can also set it before invoking the hook.
if [[ "${BRANCH_CHECKOUT_PROPAGATION_GATE_SKIP:-0}" == "1" ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

source "$(dirname "$0")/lib.sh"
parse_payload

COMMAND=$(read_payload_field "tool_input.command")
# friction-skip: trivial-fast-path — empty Bash COMMAND has no chain to analyze.
[[ -z "$COMMAND" ]] && exit 0

# Quick filter — no `git checkout -b` literal anywhere → not our concern.
# Match: `git checkout -b <name>` (with arbitrary whitespace).
if ! printf '%s' "$COMMAND" | grep -qE 'git[[:space:]]+checkout[[:space:]]+-b[[:space:]]'; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || echo .)}"
DECOMPOSER="$PROJECT_DIR/.claude/scripts/lib/decompose-bash-chain.py"

# If decomposer missing, fail OPEN — avoid blocking unrelated work.
# (Decomposer was added by PR #1339; if for some reason it's not present
# in this checkout, the gate cannot reliably analyze the chain.)
# #1349 follow-up: friction-log so missing-decomposer is observable in
# retrospectives (was a silent fail-open until regex fix in fix/1349-1350-followup).
if [[ ! -f "$DECOMPOSER" ]]; then
  _write_hook_friction "branch-checkout-propagation-gate: decomposer $DECOMPOSER absent — failing open. Gate cannot analyze the chain."
  exit 0
fi

# Decompose chain — fail-CLOSED on parse error (mirror state-completion-gate).
DECOMP_OUT=$(printf '%s' "$COMMAND" | python3 "$DECOMPOSER" 2>&1)
DECOMP_EXIT=$?
if [[ $DECOMP_EXIT -ne 0 ]]; then
  deny "branch-checkout-propagation-gate: chain decomposition failed (parse uncertain). If this checkout is intentional and ad-hoc, set BRANCH_CHECKOUT_PROPAGATION_GATE_SKIP=1 to bypass."
fi

# Walk segments — must have BOTH `git checkout -b` AND `update-context-branch.sh`.
HAS_CHECKOUT=0
HAS_PROPAGATE=0
while IFS=$'\t' read -r HEAD ARGS_JSON; do
  [[ -z "$HEAD" ]] && continue
  # `git checkout -b ...` segment
  if [[ "$HEAD" == "git" ]]; then
    if printf '%s' "$ARGS_JSON" | python3 -c "
import sys, json
try:
    a = json.loads(sys.stdin.read() or '[]')
except Exception:
    sys.exit(1)
sys.exit(0 if (len(a) >= 2 and a[0] == 'checkout' and a[1] == '-b') else 1)
" 2>/dev/null; then
      HAS_CHECKOUT=1
    fi
  fi
  # `bash .../update-context-branch.sh ...` segment
  if [[ "$HEAD" == "bash" ]]; then
    if printf '%s' "$ARGS_JSON" | python3 -c "
import sys, json
try:
    a = json.loads(sys.stdin.read() or '[]')
except Exception:
    sys.exit(1)
for tok in a:
    if 'update-context-branch.sh' in tok:
        # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
        sys.exit(0)
sys.exit(1)
" 2>/dev/null; then
      HAS_PROPAGATE=1
    fi
  fi
  # Direct invocation: `update-context-branch.sh ...` (no leading `bash`)
  if [[ "$HEAD" == *"update-context-branch.sh" ]]; then
    HAS_PROPAGATE=1
  fi
done <<< "$DECOMP_OUT"

if [[ "$HAS_CHECKOUT" == "1" && "$HAS_PROPAGATE" != "1" ]]; then
  deny "branch-checkout-propagation-gate: \`git checkout -b\` must be paired with \`bash .claude/scripts/update-context-branch.sh\` in the same Bash chain. Use the bundled pattern from .claude/patterns/branch.md, or set BRANCH_CHECKOUT_PROPAGATION_GATE_SKIP=1 to bypass for ad-hoc checkouts."
fi

exit 0
