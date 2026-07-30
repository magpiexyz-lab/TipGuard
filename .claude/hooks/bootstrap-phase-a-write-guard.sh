#!/usr/bin/env bash
# bootstrap-phase-a-write-guard.sh — PreToolUse hook for Bash commands.
# EARC slice 3 (closes #1182). Blocks Bash filesystem writes to the four
# Phase A files protected by .claude/skills/bootstrap/gates/write.sh:
#   - src/app/layout.tsx
#   - src/app/not-found.tsx
#   - src/app/error.tsx
#   - src/app/globals.css
#
# Modeled on agent-trace-write-guard.sh — same 4-layer evasion catalogue:
#   (a) chain delimiters (&&, ;, |)
#   (b) fd-redirect normalization (2>&1, >&1, etc.)
#   (c) Python literal open(<phase-a-path>, 'w'|'a')
#   (d) Python variable-indirection (var = "<phase-a>"; open(var, "w"))
#   plus catch-all for sed -i / perl -i / awk redirect / tee-redirect.
#
# The single allowlisted writer is .claude/scripts/write-phase-a-repair.sh,
# which validates external evidence (build-result.json showing the build is
# failing) and stamps a lead-fix trace + attestation. The Phase A skill gate
# (skill convention) ALSO-ALLOWs Edit/Write tool calls when a fresh
# attestation matches.
#
# Mode toggle (matches the proven PR3->PR4 hardening pattern from
# agent-trace-write-gate.sh):
#   BOOTSTRAP_PHASE_A_GUARD_MODE=warn   (telemetry-only override)
#     -> emit stderr + log to hook-friction.jsonl + exit 0
#   BOOTSTRAP_PHASE_A_GUARD_MODE=deny   (default since slice 4b)
#     -> exit 2, deny via deny() (also logs hook-friction)
#
# Slice 4b flip rationale: default flipped from `warn` to `deny` after
# test_phase_a_forgery_surface.py (39 cases) achieved symmetric coverage —
# every known bypass DENIES, every known legitimate command ALLOWS,
# including 12 false-positive guards (git checkout, git status, git diff,
# wc, stat, find, read-only python, echo-with-string-arg, etc.). CI runs
# the full catalogue on every PR, so any new false positive would surface
# immediately. Revert is one line.
#
# Exit codes:
#   0 — allow (or WARN logged when env override is set)
#   2 — deny
set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

MODE="${BOOTSTRAP_PHASE_A_GUARD_MODE:-deny}"

COMMAND=$(read_payload_field "tool_input.command")

# Fast-path: no mention of any Phase A path → allow.
# Cheap raw-string glob — runs BEFORE canonicalization so unrelated commands
# (the common case) skip the python startup entirely. (#1298 r1-c4 perf.)
case "$COMMAND" in
  *src/app/layout.tsx*|*src/app/not-found.tsx*|*src/app/error.tsx*|*src/app/globals.css*) ;;
  *) exit 0 ;;
esac

# Helper: emit a finding. In warn mode, log to hook-friction.jsonl + stderr +
# exit 0. In deny mode, deny() takes care of both logging and exit 2.
emit_finding() {
  local msg="$1"
  if [[ "$MODE" == "deny" ]]; then
    deny "$msg"
  else
    _write_hook_friction "WARN: $msg"
    echo "WARN [bootstrap-phase-a-write-guard] $msg" >&2
    echo "  (mode=warn — soak window in slice 3; flips to deny in slice 4)" >&2
    exit 0
  fi
}

PHASE_A_REGEX='src/app/(layout\.tsx|not-found\.tsx|error\.tsx|globals\.css)'

# ── Pre-canonicalization Python-source checks (RAW $COMMAND) ──
#
# These checks run on RAW $COMMAND BEFORE canonicalization so heredoc-fed
# python attacks (`python3 <<PY ... open('src/app/layout.tsx','w') ... PY`)
# are still caught — canonicalization would strip the body and hide the
# attack surface (#1298 r1-c2).

# Layer (c): Python literal open(<phase-a-path>, 'w'|'a').
# Brace-wrap ${PHASE_A_REGEX} so shellcheck does not misread `[^)]*` as an
# array index expansion (SC1087). Functionally identical for `set -u`.
# coherence-allow: raw-command — heredoc-fed python attack detection (#1298 r1-c2)
if echo "$COMMAND" | grep -qE "open\([^)]*${PHASE_A_REGEX}[^)]*,[[:space:]]*['\"][wa]"; then
  emit_finding "python open-for-write on a Phase A file is blocked — use write-phase-a-repair.sh"
fi

# Layer (d): Python variable-indirection — var = "<phase-a>"; open(var, "w").
# coherence-allow: raw-command — heredoc-fed python attack detection (#1298 r1-c2)
INDIRECT_CHECK=$(echo "$COMMAND" | python3 -c '
import re, sys
cmd = sys.stdin.read()
phase_a = r"src/app/(layout\.tsx|not-found\.tsx|error\.tsx|globals\.css)"
assignments = set()
for m in re.finditer(
    r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*[\x27\x22][^\x27\x22]*" + phase_a + r"[^\x27\x22]*[\x27\x22]",
    cmd,
):
    assignments.add(m.group(1))
for var in assignments:
    pat = r"open\(\s*" + re.escape(var) + r"\s*,[^)]*[\x27\x22][wa][\x27\x22\+b]*"
    if re.search(pat, cmd):
        print("DENY")
        # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
        sys.exit(0)
' 2>/dev/null || true)
if [[ "$INDIRECT_CHECK" == "DENY" ]]; then
  emit_finding "variable-indirection write to a Phase A file detected"
fi

# pathlib.Path("<phase-a>").write_text(...) / .write_bytes(...) — common
# python -c bypass pattern.
# Brace-wrap ${PHASE_A_REGEX} so shellcheck does not misread `[^)]*` as an
# array index expansion (SC1087). Functionally identical for `set -u`.
# coherence-allow: raw-command — heredoc-fed python attack detection (#1298 r1-c2)
if echo "$COMMAND" | grep -qE "Path\([^)]*${PHASE_A_REGEX}[^)]*\)\.write_(text|bytes)"; then
  emit_finding "pathlib.Path.write_text on a Phase A file is blocked"
fi

# Issue #1298: strip heredoc bodies before shell-redirect / allow-list checks
# so heredoc-body data text doesn't trigger the bound regex or falsely match
# a writer-name. Re-test fast-path on canonical: when the Phase A mention
# was ONLY in a heredoc body, exit 0 here.
#
# Resilience: if the canonicalizer fails (python3 missing, script error),
# fall back to RAW $COMMAND. The bound-redirect awk + sed -i checks on
# $NORM / $COMMAND_CANONICAL still fire on real writes — heredoc-body
# false-positive fix is the only thing temporarily lost. Use `if` form for
# bash 3.2 set -e portability.
if CANONICAL_TMP=$(printf '%s' "$COMMAND" | python3 "$(dirname "$0")/../scripts/lib/canonicalize_bash_command.py" 2>/dev/null); then
  COMMAND_CANONICAL="$CANONICAL_TMP"
else
  # coherence-allow: raw-command — fail-soft fallback to RAW $COMMAND when canonicalize unavailable (#1298)
  COMMAND_CANONICAL="$COMMAND"
fi
case "$COMMAND_CANONICAL" in
  *src/app/layout.tsx*|*src/app/not-found.tsx*|*src/app/error.tsx*|*src/app/globals.css*) ;;
  *) exit 0 ;;
esac

# Layer (b): fd-redirect normalization (must run before chain detection).
# Derive from CANONICAL (#1298).
NORM=$(printf '%s' "$COMMAND_CANONICAL" | sed -E 's/[0-9]*>+&[0-9]+//g')

# Allow-list short-circuit. write-phase-a-repair.sh is the canonical writer
# (slice 3). Match leading-anchor pattern for command boundary.
# Use $COMMAND_CANONICAL so heredoc-body prose mentioning the script name
# does not falsely trigger the allow-list (#1298).
ALLOWED_REGEX='(^|[[:space:]]|&&|;|\|)[[:space:]]*bash[[:space:]]+[./]*\.?claude/scripts/write-phase-a-repair\.sh[[:space:]]'
if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_REGEX"; then
  # Defense-in-depth: require --target-file flag (the script's own arg check
  # would catch absence too, but mirroring the agent-trace-write-guard pattern
  # we enforce it at the hook level so the deny path remains reachable for
  # accidentally-malformed invocations).
  if echo "$COMMAND_CANONICAL" | grep -qE 'write-phase-a-repair\.sh[^&|;]*--target-file'; then
    exit 0
  else
    emit_finding "write-phase-a-repair.sh invocation lacks --target-file"
  fi
fi

# Layer (a): chained writes targeting Phase A files. Split on &&/;/|, within
# each segment look for a write operator (>, >>, &>) bound to a Phase A path,
# OR tee/cp/mv targeting Phase A.
if echo "$NORM" | awk -v r="$PHASE_A_REGEX" '
    BEGIN{RS="[&|;]"}
    {
      # Issue #1333: gated path must appear immediately after operator +
      # optional whitespace + optional quote. The prior open exclusion class
      # admitted markdown prose between operator and path as a false-positive.
      if (match($0, "([0-9]*&?>+|[0-9]*>>?)[[:space:]]*[\"'"'"']?"r)) found=1
      else if (match($0, "(^|[[:space:]])(tee|cp|mv|dd)[[:space:]][^|;&]*"r)) found=1
    }
    END{exit !found}'; then
  emit_finding "chained shell write to Phase A file detected — use write-phase-a-repair.sh"
fi

# Catch-all: in-place editors (sed -i, perl -i -pe) and awk redirect chains.
# Use $COMMAND_CANONICAL so heredoc-body text doesn't trigger this check.
if echo "$COMMAND_CANONICAL" | grep -qE "(sed[[:space:]]+(-[a-zA-Z]*)?-i|perl[[:space:]]+(-[a-zA-Z]*)?-i)([^|;&]*)$PHASE_A_REGEX"; then
  emit_finding "in-place editor (sed -i / perl -i) targeting a Phase A file is blocked"
fi

# Final catch-all (mirrors the bound write-operator pattern used in
# agent-trace-write-guard.sh's catch-all). Within each segment, require a
# write operator IMMEDIATELY adjacent to a Phase A target.
if echo "$NORM" | awk -v r="$PHASE_A_REGEX" '
    BEGIN{RS="[&|;]"}
    {
      # Issue #1333: same precision tightening as the earlier check above.
      if (match($0, "([0-9]*&?>+|[0-9]*>>?)[[:space:]]*[\"'"'"']?"r"[^[:space:]\"'"'"']*")) found=1
      else if (match($0, "(^|[[:space:]])(tee|cp|mv|dd)[[:space:]][^|;&]*"r"[^[:space:]\"'"'"']*")) found=1
    }
    END{exit !found}'; then
  emit_finding "Phase A file write must go through write-phase-a-repair.sh; direct shell writes are blocked"
fi

# friction-skip: trivial-fast-path — input absent or non-applicable
exit 0
