#!/usr/bin/env bash
# fix-ledger-write-guard.sh — Claude Code PreToolUse hook for Bash commands.
# Blocks arbitrary Bash writes to .runs/fix-ledger.jsonl and .runs/fix-log.md.
#
# AOC v1 FLS v1 runtime guard. Complements the static R2 coherence rule
# (aoc-fix-ledger-ownership in template-coherence-rules.json) by blocking
# runtime writes the static check cannot see (e.g., ad-hoc shell commands
# issued by the agent during execution).
#
# Only these scripts are allowed to write the gated paths:
#   - .claude/scripts/write-fix-ledger.py  (ledger consolidator + AOC v1.1 --lead-fix)
#   - .claude/scripts/render-fix-log.py    (fix-log renderer)
#
# Benign known-residual (after AOC v1.1 PR5):
#   - echo '# Error Fix Log' > .runs/fix-log.md  (verify STATE 0 init).
#     render-fix-log.py overwrites the file on every state advance, so the
#     transient header line never causes drift. This is the ONLY echo>fix-log
#     pattern retained.
#
# Removed by AOC v1.1 PR5 (migrated to write-fix-ledger.py --lead-fix):
#   - echo 'WARN (e2e-config)...' >> .runs/fix-log.md  (now: --lead-fix --severity warn)
#   - echo 'Fix (e2e)...' >> .runs/fix-log.md           (now: --lead-fix)
#   - echo 'Fix (e2e-config)...' >> .runs/fix-log.md   (now: --lead-fix)
#   - echo 'Fix (spec)...' >> .runs/fix-log.md          (now: --lead-fix)
#
# ORDERING (issue #1156): the chain-write detector uses a BOUND regex
# (operator → gated path) modeled after agent-trace-write-guard.sh. The bound
# check MUST run BEFORE the allow-list short-circuit — otherwise a chain like
# `python3 write-fix-ledger.py && echo forge > .runs/fix-log.md` fires the
# allow-list on segment 1 and exits 0 before segment 2 is inspected. The
# original co-occurrence check ran pre-allow specifically to catch this. The
# bound form is per-segment; pre-allow ordering preserves chain-evasion
# rejection while still allowing legitimate reads of the gated paths to fall
# through to `exit 0` (the bound regex requires a `>` operator that is
# absent from pure-read commands).

set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

COMMAND=$(read_payload_field "tool_input.command")

# Fast-path: no mention of the gated paths → allow.
# Cheap raw-string glob — runs BEFORE canonicalization so unrelated commands
# (the common case) skip the python startup entirely. (#1298 r1-c4 perf.)
case "$COMMAND" in
  *fix-ledger.jsonl*|*fix-log.md*) ;;
  *) exit 0 ;;
esac

# ── Pre-canonicalization Python-source checks (RAW $COMMAND) ──
#
# Block Python open(...) for write/append on the gated paths (independent of
# the bound chain check below — open(..., 'w') has no shell-redirect to bind).
# These run on RAW $COMMAND so heredoc-fed python attacks
# (`python3 <<PY ... open('.runs/fix-ledger.jsonl','w') ... PY`) are still
# caught — canonicalization would strip the body and hide the attack
# surface (#1298 r1-c2).
# coherence-allow: raw-command — heredoc-fed python attack detection (#1298 r1-c2)
if echo "$COMMAND" | grep -qE "open\([^)]*\.runs/fix-ledger\.jsonl[^)]*,[[:space:]]*['\"][wa]"; then
  deny "Fix-ledger write guard: python open-for-write on .runs/fix-ledger.jsonl is blocked. Use write-fix-ledger.py (AOC v1 FLS v1)."
fi
# coherence-allow: raw-command — heredoc-fed python attack detection (#1298 r1-c2)
if echo "$COMMAND" | grep -qE "open\([^)]*\.runs/fix-log\.md[^)]*,[[:space:]]*['\"][wa]"; then
  deny "Fix-ledger write guard: python open-for-write on .runs/fix-log.md is blocked. Use render-fix-log.py (AOC v1 FLS v1)."
fi

# Issue #1298: strip heredoc bodies before shell-redirect / allow-list checks
# so heredoc-body data text doesn't trigger the bound regex or falsely match
# a writer-name. Re-test fast-path on canonical: when the gated-path mention
# was ONLY in a heredoc body, exit 0 here.
#
# Resilience: if the canonicalizer fails (python3 missing, script error),
# fall back to RAW $COMMAND. The bound-redirect awk on $NORM still fires on
# real shell writes. Use `if` form for bash 3.2 set -e portability.
if CANONICAL_TMP=$(printf '%s' "$COMMAND" | python3 "$(dirname "$0")/../scripts/lib/canonicalize_bash_command.py" 2>/dev/null); then
  COMMAND_CANONICAL="$CANONICAL_TMP"
else
  # coherence-allow: raw-command — fail-soft fallback to RAW $COMMAND when canonicalize unavailable (#1298)
  COMMAND_CANONICAL="$COMMAND"
fi
case "$COMMAND_CANONICAL" in
  *fix-ledger.jsonl*|*fix-log.md*) ;;
  *) exit 0 ;;
esac

# Normalize fd-to-fd redirects (2>&1, >&1, etc.) — same rationale as
# agent-trace-write-guard.sh. Derive from CANONICAL (#1298).
NORM=$(printf '%s' "$COMMAND_CANONICAL" | sed -E 's/[0-9]*>+&[0-9]+//g')

# Benign known-residual: allow STATE 0 header init
# (matches `echo '# Error Fix Log' > .runs/fix-log.md`).
# render-fix-log.py overwrites the file on every state advance, so the
# transient header line never causes drift. This is the only echo>fix-log.md
# pattern retained after AOC v1.1 PR5 migrated STATE 5 inline writes to the
# --lead-fix path. Allowed BEFORE the bound check because the bound regex
# would otherwise deny it (the `>` IS bound to the gated path here).
if echo "$NORM" | grep -qE "echo[[:space:]]+['\"]?# Error Fix Log['\"]?[[:space:]]*>[[:space:]]*\.runs/fix-log\.md"; then
  exit 0
fi

# ── Bound chain-write check (#1156) — runs BEFORE allow-list ──
# Reject chained writes whose redirect target is a gated path. Split on &&/;/|
# and deny only when a write operator is BOUND to the gated path (operator
# followed, after optional whitespace/quote, by a non-delimiter token containing
# the gated path). The exclusion class includes a literal newline so heredoc
# bodies cannot bridge a `>` redirecting to /tmp into a `.runs/fix-log.md`
# inside the heredoc body.
#
# Issue #1156: the previous co-occurrence regex
# (`/(fix-log\.md|fix-ledger\.jsonl)/ && /(>|>>|tee|cp|mv)/`) false-positived on
# heredocs that wrote to OTHER paths but mentioned the gated path inside their
# body. The bound regex matches the actual write target, not co-occurrence.
#
# Order rationale: the bound check runs BEFORE the allow-list so a sanctioned
# writer chained with a forge (`write-fix-ledger.py && echo forge > .runs/fix-log.md`)
# is caught — the allow-list would otherwise short-circuit on segment 1 and
# exit before segment 2 is inspected.
if echo "$NORM" | awk '
    BEGIN{RS="[&|;]"}
    {
      # Bound write operator -> gated path target (>file, >>file, &>file).
      # Issue #1333: the gated path MUST appear immediately after the
      # operator + optional whitespace + optional quote. The previous open
      # exclusion class between operator and path admitted markdown
      # blockquote shapes (prose between > and the gated path) as false
      # positives during gh issue create --body. The narrow form below
      # rejects prose-between cases while still matching real shell
      # redirects (with or without space, with or without quote).
      if (match($0, /([0-9]*&?>+|[0-9]*>>?)[[:space:]]*["'\'']?\.runs\/(fix-ledger\.jsonl|fix-log\.md)/)) found=1
      # tee / cp / mv / dd with a gated path target later on the same segment
      else if (match($0, /(^|[[:space:]])(tee|cp|mv|dd)[[:space:]][^|;&\n]*\.runs\/(fix-ledger\.jsonl|fix-log\.md)/)) found=1
    }
    END{exit !found}'; then
  deny "Fix-ledger write guard: writes to .runs/fix-ledger.jsonl / .runs/fix-log.md must go through write-fix-ledger.py / render-fix-log.py (AOC v1 FLS v1). Direct shell writes are blocked."
fi

# ── Allow-list short-circuit ──

# Allow-list regex matches use $COMMAND_CANONICAL (heredoc bodies stripped) so
# narrative prose mentioning these script names does not falsely allow. (#1298)
ALLOWED_REGEX_WRITER='(^|[[:space:]]|&&|;|\|)[[:space:]]*python3?[[:space:]]+[./]*\.?claude/scripts/write-fix-ledger\.py'
if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_REGEX_WRITER"; then
  exit 0
fi

ALLOWED_REGEX_RENDERER='(^|[[:space:]]|&&|;|\|)[[:space:]]*python3?[[:space:]]+[./]*\.?claude/scripts/render-fix-log\.py'
if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_REGEX_RENDERER"; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# AOC v1.1 PR5: STATE 5 inline writes (Fix(e2e), Fix(e2e-config), Fix(spec),
# WARN(e2e-config)) are NO LONGER allowlisted. They migrated to
# write-fix-ledger.py --lead-fix [--severity warn]. If you see this hook
# blocking a STATE 5 echo, update the state file to use the lead-fix path
# (state-5-e2e-tests.md was migrated in PR5).

# friction-skip: trivial-fast-path — input absent or non-applicable
exit 0
