#!/usr/bin/env bash
# commit.sh — Convention gate for /change commit checks.
# Extracted from change-commit-gate.sh (change-specific logic only).
# Called by: skill-commit-gate.sh (PR 5) after framework checks pass.
# NOT called yet — created in PR 4b, enabled in PR 5.
set -euo pipefail

source "$(dirname "$0")/../../../hooks/lib.sh"

# Accept env vars (convention gate protocol) or derive from payload/defaults
if [[ -z "${PAYLOAD:-}" ]]; then parse_payload; fi
SKILL="${SKILL:-change}"
PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"
BRANCH="${BRANCH:-$(get_branch)}"
COMMAND="${COMMAND:-$(read_payload_field "tool_input.command")}"

# --- Bypass 1: Worktree merge commits pass unconditionally ---
if [[ "$COMMAND" == *"Merge implementer"* ]]; then
  exit 0
fi

# --- Bypass 2: Recover commits allowed when plan exists ---
if [[ "$COMMAND" == *"recover:"* ]]; then
  if [[ ! -f "$PROJECT_DIR/.runs/current-plan.md" ]]; then
    deny "recover: commit blocked — no current-plan.md found. Cannot recover without an existing plan."
  fi
  exit 0
fi

# --- Bypass 3: Checkpoint timing — only enforce at phase2-step8+ ---
PLAN="$PROJECT_DIR/.runs/current-plan.md"
if [[ -f "$PLAN" ]]; then
  CHECKPOINT=$(python3 -c "
import re
with open('$PLAN') as f:
    content = f.read()
m = re.search(r'checkpoint:\s*(\S+)', content)
print(m.group(1) if m else '')
" 2>/dev/null || echo "")
  if [[ -n "$CHECKPOINT" && "$CHECKPOINT" != "phase2-step8" ]]; then
    exit 0
  fi
fi

# --- Final commit gate checks ---
ERRORS=()

# Check 1: G4 verdict file exists with PASS
VERDICTS_DIR="$PROJECT_DIR/.runs/gate-verdicts"
check_verdict_gates "g4" "$VERDICTS_DIR" "$BRANCH"

# Check 2: verify-report.md exists with passing build
REPORT="$PROJECT_DIR/.runs/verify-report.md"
if [[ ! -f "$REPORT" ]]; then
  ERRORS+=("verify-report.md missing — run /verify before committing")
else
  BUILD_RESULT=$(python3 -c "
import re
with open('$REPORT') as f:
    content = f.read()
if 'Result: pass' in content or 'result: pass' in content:
    print('pass')
else:
    print('unknown')
" 2>/dev/null || echo "unknown")
  if [[ "$BUILD_RESULT" != "pass" ]]; then
    ERRORS+=("verify-report.md does not show build pass")
  fi
fi

# If any check failed, deny the commit
if [[ ${#ERRORS[@]} -gt 0 ]]; then
  deny_errors "Change commit blocked: " "Complete G4 gate and verification before final commit."
fi

# All checks passed — allow
exit 0
