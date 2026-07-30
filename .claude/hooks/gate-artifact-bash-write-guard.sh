#!/usr/bin/env bash
# gate-artifact-bash-write-guard.sh — Claude Code PreToolUse hook for Bash commands.
# Issue #1299 — sibling to gate-artifact-write-gate.sh (Write/Edit matcher).
#
# The Write/Edit gate cannot see direct-bash writes via shell redirects,
# `tee`, `cat <<EOF > path`, or inline `python3 -c "open(...)"`.
# This Bash-matcher hook closes that bypass: it inspects the outermost
# tool_input.command and, when MODE=deny, blocks chain-bound writes that
# target paths declared in
# .claude/patterns/gate-readable-artifacts-canonical.json.
#
# Class scope (per write-guard-hooks.json convention): Bash-matcher PreToolUse
# hooks only. The Write/Edit-matcher gate-artifact-write-gate.sh is a sibling.
#
# Modeled on .claude/hooks/fix-ledger-write-guard.sh. Conventions:
#   1. Fast-path raw glob (skip python startup when no `.runs/` mention).
#   2. Pre-canonicalization Python source check on RAW $COMMAND for
#      open(...,'w'|'a') heredoc-fed attacks.
#   3. Canonicalize via canonicalize_bash_command.py to strip heredoc bodies.
#   4. Bound chain-write detection: per-segment awk match, runs BEFORE the
#      allow-list short-circuit.
#   5. Allow-list short-circuit for canonical writers.
#   6. Mode handling via dedicated env var (NOT shared with
#      gate-artifact-write-gate.sh — preserves the Write/Edit deny that
#      shipped in PR #1217).
#
# Falsifiable soak (R2-C5): EVERY warn-firing branch calls _write_hook_friction
# before exiting 0. Without this, "zero entries" during soak is unfalsifiable
# (the new code path could be silently dead). The deny() helper from lib.sh
# also calls _write_hook_friction, so deny-mode firings are likewise logged.

set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

COMMAND=$(read_payload_field "tool_input.command")

# Mode handling — dedicated env var so the warn-mode flip in PR-E does not
# accidentally weaken the existing Write/Edit deny in gate-artifact-write-gate.sh.
MODE="${GATE_ARTIFACT_BASH_WRITE_GUARD_MODE:-warn}"

# Fast-path: no mention of .runs/ → allow.
# coherence-allow: raw-command — fast-path raw-glob filter (#1298 r1-c4 perf)
case "$COMMAND" in
  *.runs/*) ;;
  *) exit 0 ;;
esac

# Pre-canonicalization Python-source check (RAW $COMMAND).
# Catches heredoc-fed python attacks (`python3 <<PY ... open('.runs/...','w') ... PY`).
# The protected_path_regex for the bash_hook_write_operator_binding rule
# (must match write-guard-hooks.json byte-for-byte): \.runs\/[^\s"']+\.json
# coherence-allow: raw-command — heredoc-fed python attack detection
if echo "$COMMAND" | grep -qE "open\([^)]*\.runs/[^)]*\.json[^)]*,[[:space:]]*['\"][wa]"; then
  REL_PATH=$(echo "$COMMAND" | grep -oE "\.runs\/[^'\"\)]+\.json" | head -1)
  IS_GATED=$(MANIFEST="$(dirname "$0")/../patterns/gate-readable-artifacts-canonical.json" TARGET="$REL_PATH" python3 -c "
import json, os, sys
try:
    m = json.load(open(os.environ['MANIFEST']))
    declared = {a['path'] for a in m.get('artifacts', [])}
    print('1' if os.environ['TARGET'] in declared else '0')
except Exception:
    print('0')
" 2>/dev/null || echo "0")
  if [ "$IS_GATED" = "1" ]; then
    MSG="Gate-artifact bash write guard: python open-for-write on $REL_PATH is blocked. Use bash .claude/scripts/lib/write-gate-artifact.sh (GRAIM v2 C1)."
    if [ "$MODE" = "deny" ]; then
      deny "$MSG"
    else
      _write_hook_friction "[warn-mode] $MSG" "warn-mode-bypass"
      exit 0
    fi
  fi
fi

# Canonicalize bash command (strip heredoc bodies). Fall back to RAW on failure.
if CANONICAL_TMP=$(printf '%s' "$COMMAND" | python3 "$(dirname "$0")/../scripts/lib/canonicalize_bash_command.py" 2>/dev/null); then
  COMMAND_CANONICAL="$CANONICAL_TMP"
else
  # coherence-allow: raw-command — fail-soft fallback when canonicalize unavailable
  COMMAND_CANONICAL="$COMMAND"
fi
case "$COMMAND_CANONICAL" in
  *.runs/*) ;;
  *) exit 0 ;;
esac

# Normalize fd-to-fd redirects (2>&1, >&1, etc.) so they don't bridge a
# legitimate redirect into a gated-path mention later in the segment.
NORM=$(printf '%s' "$COMMAND_CANONICAL" | sed -E 's/[0-9]*>+&[0-9]+//g')

# ── Bound chain-write check ──
# Per-segment awk match. Splits on &&/;/| and looks for write operator
# (>, >>, &>, tee, cp, mv, dd) bound to a path matching $PROTECTED_PATH_REGEX.
# Then validates that path is in the canonical manifest.
# shellcheck disable=SC2034  # Declarative constant — registered via write-guard-hooks.json (referenced externally, not by this script body).
WRITE_OPERATORS=">|>>|&?>|tee|cp|mv|dd"  # for write-guard-hooks.json registration
GATED_TARGET=$(echo "$NORM" | awk '
    BEGIN{RS="[&|;]"}
    {
      # Bound write operator -> .runs/*.json target.
      # Issue #1333: gated path must appear immediately after operator +
      # optional whitespace + optional quote. The prior open exclusion class
      # admitted markdown prose between operator and path as a false positive
      # when filing observations via gh issue create --body.
      if (match($0, /([0-9]*&?>+|[0-9]*>>?)[[:space:]]*["'\'']?\.runs\/[^|;&"'\''\n]+\.json/)) {
        s = substr($0, RSTART, RLENGTH)
        if (match(s, /\.runs\/[^|;&"'\''\n[:space:]]+\.json/)) {
          print substr(s, RSTART, RLENGTH)
          exit
        }
      }
      # tee / cp / mv / dd with a .runs/*.json target.
      if (match($0, /(^|[[:space:]])(tee|cp|mv|dd)[[:space:]][^|;&\n]*\.runs\/[^|;&"'\''\n]+\.json/)) {
        s = substr($0, RSTART, RLENGTH)
        if (match(s, /\.runs\/[^|;&"'\''\n[:space:]]+\.json/)) {
          print substr(s, RSTART, RLENGTH)
          exit
        }
      }
    }
')

if [ -n "$GATED_TARGET" ]; then
  # Verify the target is actually in the canonical manifest.
  IS_GATED=$(MANIFEST="$(dirname "$0")/../patterns/gate-readable-artifacts-canonical.json" TARGET="$GATED_TARGET" python3 -c "
import json, os
try:
    m = json.load(open(os.environ['MANIFEST']))
    declared = {a['path'] for a in m.get('artifacts', [])}
    print('1' if os.environ['TARGET'] in declared else '0')
except Exception:
    print('0')
" 2>/dev/null || echo "0")
  if [ "$IS_GATED" = "1" ]; then
    # ── Allow-list short-circuit (chain-bound check has already fired
    # for the bound write; if the chain ALSO contains a sanctioned
    # writer, we still report friction for the bound write because the
    # chain-bound check is auth oritative — see fix-ledger-write-guard.sh:103-133
    # rationale).
    ALLOWED_PREFIX_WRITER='(^|[[:space:]]|&&|;|\|)[[:space:]]*bash[[:space:]]+[./]*\.?claude/scripts/lib/write-gate-artifact\.sh'
    ALLOWED_PREFIX_FRICTION='(^|[[:space:]]|&&|;|\|)[[:space:]]*python3?[[:space:]]+[./]*\.?claude/scripts/append-hook-friction\.py'
    ALLOWED_PREFIX_DERIVE='(^|[[:space:]]|&&|;|\|)[[:space:]]*python3?[[:space:]]+[./]*\.?claude/scripts/derive-graim-manifest\.py'
    IS_ALLOWED_CHAIN=0
    if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_PREFIX_WRITER"; then IS_ALLOWED_CHAIN=1; fi
    if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_PREFIX_FRICTION"; then IS_ALLOWED_CHAIN=1; fi
    if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_PREFIX_DERIVE"; then IS_ALLOWED_CHAIN=1; fi

    MSG="Gate-artifact bash write guard: direct write to gate-readable path $GATED_TARGET is blocked. Use bash .claude/scripts/lib/write-gate-artifact.sh (GRAIM v2 C1)."
    if [ "$IS_ALLOWED_CHAIN" = "1" ]; then
      MSG="$MSG [allowed-writer-also-in-chain — review for chain-evasion]"
    fi
    if [ "$MODE" = "deny" ]; then
      deny "$MSG"
    else
      _write_hook_friction "[warn-mode] $MSG" "warn-mode-bypass"
      exit 0
    fi
  fi
fi

# ── Plain allow-list short-circuit (no bound write detected) ──
# A canonical-writer invocation with no other suspect chain content → allow silently.
ALLOWED_REGEX='(^|[[:space:]]|&&|;|\|)[[:space:]]*bash[[:space:]]+[./]*\.?claude/scripts/lib/write-gate-artifact\.sh'
if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_REGEX"; then
  exit 0
fi

# friction-skip: trivial-fast-path — input absent or non-applicable
exit 0
