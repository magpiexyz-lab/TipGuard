#!/usr/bin/env bash
# agent-trace-write-guard.sh — Claude Code PreToolUse hook for Bash commands.
# Blocks arbitrary Bash writes to .runs/agent-traces/*.json.
#
# Only these scripts are allowed to write agent traces:
#   - scripts/init-trace.py          (start-of-run stub)
#   - .claude/scripts/write-recovery-trace.sh  (orchestrator recovery path)
#   - .claude/scripts/write-degraded-trace.py  (agent self-degradation path)
#   - .claude/scripts/validate-recovery.sh     (stamps recovery_validated only)
#   - .claude/scripts/migrate-legacy-traces.py (one-shot legacy migration)
#   - .claude/scripts/merge-design-critic-traces.py   (verify state-3b lead-merge)
#   - .claude/scripts/merge-design-consistency-checker-traces.py  (verify state-3b
#                                                                  page-batched lead-merge, #1257)
#   - .claude/scripts/merge-scaffold-pages-traces.py  (bootstrap state-11c lead-merge,
#                                                     extracted from inline json.dump in PR2b)
#   - .claude/scripts/write-agent-trace.sh   (AOC v1.1 centralized writer for
#                                             self / self-degraded / lead-on-behalf /
#                                             lead-synthesized; replaces the
#                                             chain-blocked echo>file pattern
#                                             from #1064 D1)
#   - .claude/scripts/augment-trace.py       (AOC v1.1 narrow descriptive-field
#                                             augmenter; whitelisted fields only,
#                                             requires spawn-log match)
#
# This is the runtime half of the R2 C7 fix (static test_forgery_surface.py
# handles CI). Together they ensure no new script silently becomes an
# unauthorized writer of agent traces.
#
# Write tool (Write/Edit) writes to agent-traces are handled separately by
# artifact-integrity-gate.sh (schema validation).
#
# ORDER matters: the chain-delimiter / raw-write checks run BEFORE the
# allowed-writer short-circuit, so a sanctioned script invocation chained
# with a forged raw write (`bash write-recovery-trace.sh --reason x ; echo > .runs/agent-traces/forged`)
# cannot bypass detection.

set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

COMMAND=$(read_payload_field "tool_input.command")

# Fast-path: no mention of agent-traces → allow.
# Cheap raw-string glob — runs BEFORE canonicalization so unrelated commands
# (the common case) skip the python startup entirely. (#1298 r1-c4 perf.)
case "$COMMAND" in
  *agent-traces*) ;;
  *) exit 0 ;;
esac

# ── Pre-canonicalization Python-source checks (RAW $COMMAND) ──
#
# These checks run on RAW $COMMAND BEFORE canonicalization so heredoc-fed
# python attacks (`python3 <<PY ... open('agent-traces/x','w') ... PY`) are
# still caught — canonicalization would strip the body and hide the attack
# surface (#1298 r1-c2).

# Block Python open(...) for write/append on agent-traces.
# coherence-allow: raw-command — heredoc-fed python attack detection (#1298 r1-c2)
if echo "$COMMAND" | grep -qE "open\([^)]*agent-traces/[^)]*,[[:space:]]*['\"][wa]"; then
  deny "Agent trace write guard: python open-for-write on agent-traces/ is blocked. Use write-recovery-trace.sh or write-degraded-trace.py."
fi

# Block Python variable-indirection writes to agent-traces.
#
# Pattern: `f="...agent-traces/..."; ... open(f, "w")` — the literal path is
# bound to a variable, and the open() call uses the variable rather than the
# literal. The regex above only catches literal `open(...agent-traces/...)`,
# so this Python helper closes the gap.
#
# Implementation: scan the COMMAND string as a single unit (NOT split on `;` —
# the existing chain-record awk uses `RS="[&|;]"` which would tear Python
# `import json; ...` source across awk records, breaking variable correlation
# by construction). The helper:
#   1. Find every `<varname> = "..agent-traces/..."` (or `'..agent-traces/..'`)
#      assignment in the command string.
#   2. For each such variable, check if `open(<varname>, ...)` appears later
#      with mode 'w' or 'a'.
#   3. If any pair matches, print DENY.
# coherence-allow: raw-command — heredoc-fed python attack detection (#1298 r1-c2)
INDIRECT_CHECK=$(echo "$COMMAND" | python3 -c '
import re, sys
cmd = sys.stdin.read()
# Capture all <var> = "...agent-traces/..." assignments.
assignments = set()
for m in re.finditer(
    r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*[\x27\x22][^\x27\x22]*agent-traces/[^\x27\x22]*[\x27\x22]",
    cmd,
):
    assignments.add(m.group(1))
for var in assignments:
    # open(<var>, ..., "w") or "a" or with positional mode arg
    pat = r"open\(\s*" + re.escape(var) + r"\s*,[^)]*[\x27\x22][wa][\x27\x22\+b]*"
    if re.search(pat, cmd):
        print("DENY")
        # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
        sys.exit(0)
' 2>/dev/null || true)
if [[ "$INDIRECT_CHECK" == "DENY" ]]; then
  deny "Agent trace write guard: variable-indirection write to agent-traces/ blocked (variable bound to agent-traces path is later passed to open() with write mode). Use write-agent-trace.sh / write-recovery-trace.sh / write-degraded-trace.py."
fi

# Issue #1298: strip heredoc bodies before shell-redirect / allow-list checks
# so heredoc-body data text doesn't trigger the bound-redirect catch-all or
# falsely match a writer-name. Re-test fast-path on canonical: when the
# `agent-traces` mention was ONLY in a heredoc body, exit 0 here.
#
# Resilience: if the canonicalizer fails for any reason (python3 missing,
# script error, malformed input), fall back to RAW $COMMAND. Direct shell
# writes are still caught by the bound-redirect catch-all on $NORM. The
# heredoc-body false-positive fix is temporarily lost — acceptable trade
# vs the harder failure mode of denying every Bash command. Use the `if`
# form (not `var=$(...) || var=...`) for bash 3.2 set -e portability.
if CANONICAL_TMP=$(printf '%s' "$COMMAND" | python3 "$(dirname "$0")/../scripts/lib/canonicalize_bash_command.py" 2>/dev/null); then
  COMMAND_CANONICAL="$CANONICAL_TMP"
else
  # coherence-allow: raw-command — fail-soft fallback to RAW $COMMAND when canonicalize unavailable (#1298)
  COMMAND_CANONICAL="$COMMAND"
fi
case "$COMMAND_CANONICAL" in
  *agent-traces*) ;;
  *) exit 0 ;;
esac

# Normalize fd-to-fd redirects (2>&1, >&1, 3>&2, 2>>&1, etc.) before write-op
# detection. These are stderr/fd redirection tokens, not file writes — but
# their bare `>` character falsely matches the write-operator regex below,
# and their embedded `&` falsely splits the awk chain-record (RS="[&|;]").
# Strip them at the source so both checks see the command without fd tokens.
# File writes (>file, >>file, &>file, >&file GNU extension, tee, cp, mv) do
# NOT match the `>+&[digit]` pattern and are preserved intact.
#
# Second pass collapses the GNU `>& filename` form (cmd >& filename ≡
# cmd > filename 2>&1 — a real file write) to plain `> filename`. Without
# this, the literal `&` between `>` and the filename is consumed as the
# awk chain-record separator (RS="[&|;]"), splitting the write operator
# from its target into two adjacent records and silently allowing the
# write. Order matters: the first sed strips fd-to-fd forms (digit-after-&)
# so this second pass only reshapes the file form (non-digit-after-&).
#
# Derive from CANONICAL so heredoc-body text doesn't pollute the bound-
# redirect catch-all on $NORM (#1298).
NORM=$(printf '%s' "$COMMAND_CANONICAL" \
  | sed -E 's/[0-9]*>+&[0-9]+//g' \
  | sed -E 's/>&([[:space:]]*)([^&|;[:space:]])/> \1\2/g')

# ── Pre-allow shell-redirect chain check (MUST run before allow-list) ──

# Reject chained writes whose redirect target is an agent-traces path.
# Split on &&/;/| and deny only when a write operator is BOUND to an
# agent-traces target (operator followed by a token containing agent-traces/).
# Issue #1123: the previous co-occurrence regex (`/agent-traces\// && /(>|>>|tee|cp|mv)/`)
# false-positived on chained commands that READ from agent-traces and WROTE to
# unrelated paths (e.g., `python -c '...read agent-traces...' > /tmp/foo` or
# `ls .runs/agent-traces && bash advance-state.sh`).
# The bound regex matches: optional file descriptor, redirect operator, optional
# whitespace/quote, anything-but-chain-delimiters, then `agent-traces/`. Or:
# tee/cp/mv as words followed (eventually on the same segment) by an
# agent-traces target. The Python open-for-write regex above handles the
# scripted write path separately.
if echo "$NORM" | awk '
    BEGIN{RS="[&|;]"}
    {
      # Bound write operator -> agent-traces target (>file, >>file, &>file).
      # Issue #1333 + post-fix: between the operator and the gated basename
      # allow only path-like chars (no whitespace, no quote) so legitimate
      # write paths like > .runs/agent-traces/<NAME>.json match while
      # markdown-blockquote prose > 1b. After each fix in agent-traces/...
      # does NOT — the space after 1b. breaks the path-token capture.
      # Pre-#1333 the exclusion class was non-chain-delim chars, which still
      # admitted prose; #1333 removed it entirely which broke real
      # .runs/-prefixed writes.
      if (match($0, /([0-9]*&?>+|[0-9]*>>?)[[:space:]]*["'\'']?[^[:space:]"'\'']*agent-traces\//)) found=1
      # tee / cp / mv / dd with an agent-traces target later on the same segment
      else if (match($0, /(^|[[:space:]])(tee|cp|mv|dd)[[:space:]][^|;&]*agent-traces\//)) found=1
    }
    END{exit !found}'; then
  deny "Agent trace write guard: agent-traces/*.json write target detected on a chained command segment (write operator bound to agent-traces path)."
fi

# ── Allow-list short-circuit ──

# Leading-anchor regex: each sanctioned writer must appear at a command
# boundary (start, whitespace, or chain delimiter). Optional `bash ` /
# `python3 ` wrapper permitted.

# Helper (#1249): check that --reason token appears AFTER a script-name token
# within the same shell segment (chain-delimiter bound). Combines segment
# binding (preserves the original regex's positional semantics — a stray
# --reason in an unrelated chained command does not satisfy the check) with
# shlex tokenization (handles single/double-quoted reason values containing
# newlines, line-continuations, and chain-delimiter characters inside quotes).
# The prior regex `[^&|;]*--reason` was unbound across newlines AND failed to
# distinguish quoted vs literal chain delimiters.
# Args: $1 = script_name; $2 = command string (canonical form per #1298)
_check_reason_token() {
  local script_name="$1"
  local cmd_str="$2"
  printf '%s' "$cmd_str" | python3 -c "
import re, shlex, sys
cmd = sys.stdin.read()
script = '$script_name'
try:
    tokens = shlex.split(cmd, comments=False, posix=True)
except ValueError:
    sys.exit(1)
segments, current = [], []
for t in tokens:
    if t in ('&&', '||', ';', '&', '|'):
        if current:
            segments.append(current)
            current = []
    else:
        current.append(t)
if current:
    segments.append(current)
script_re = re.compile(r'(^|/)' + re.escape(script) + r'\$')
for seg in segments:
    script_idx = next((i for i, t in enumerate(seg) if script_re.search(t)), -1)
    if script_idx == -1:
        continue
    if '--reason' in seg[script_idx + 1:]:
        # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
        sys.exit(0)
sys.exit(1)
" 2>/dev/null
}

# Allow-list regex matches use $COMMAND_CANONICAL (heredoc bodies stripped) so
# narrative prose mentioning a sanctioned writer-name does not trigger the
# allow-list and then a false `--reason` deny. (#1298)
ALLOWED_REGEX='(^|[[:space:]]|&&|;|\|)[[:space:]]*(bash[[:space:]]+|python3?[[:space:]]+)?[./]*\.?claude/scripts/write-recovery-trace\.sh[[:space:]]'
if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_REGEX"; then
  # write-recovery-trace.sh must include --reason (defense-in-depth with the
  # script's own argument check). #1249: shlex-tokenizing helper handles
  # multi-line / quoted reason values that the prior bash regex could not.
  if _check_reason_token "write-recovery-trace.sh" "$COMMAND_CANONICAL"; then
    # friction-skip: trivial-fast-path — input absent or non-applicable
    exit 0
  else
    deny "Agent trace write guard: write-recovery-trace.sh invocation lacks --reason (required by issue #963 contract)."
  fi
fi

ALLOWED_REGEX_DEGRADED='(^|[[:space:]]|&&|;|\|)[[:space:]]*(bash[[:space:]]+|python3?[[:space:]]+)?[./]*\.?claude/scripts/write-degraded-trace\.py[[:space:]]'
if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_REGEX_DEGRADED"; then
  if _check_reason_token "write-degraded-trace.py" "$COMMAND_CANONICAL"; then
    exit 0
  else
    deny "Agent trace write guard: write-degraded-trace.py invocation lacks --reason (required by trace schema)."
  fi
fi

ALLOWED_REGEX_INIT='(^|[[:space:]]|&&|;|\|)[[:space:]]*python3?[[:space:]]+[./]*scripts/init-trace\.py[[:space:]]'
if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_REGEX_INIT"; then
  exit 0
fi

# Allow the recovery-validator (read-modify-write on recovery traces only —
# it only stamps recovery_validated:true on existing traces).
ALLOWED_REGEX_VALIDATE='(^|[[:space:]]|&&|;|\|)[[:space:]]*bash[[:space:]]+[./]*\.?claude/scripts/validate-recovery\.sh[[:space:]]'
if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_REGEX_VALIDATE"; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# Allow the legacy-trace migrator (read-modify-write, no new traces created)
ALLOWED_REGEX_MIGRATE='(^|[[:space:]]|&&|;|\|)[[:space:]]*python3?[[:space:]]+[./]*\.?claude/scripts/migrate-legacy-traces\.py'
if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_REGEX_MIGRATE"; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# Allow the official design-critic merge script (lead-merge aggregation at
# verify state-3b — issue #1045 extracted this from an inline python3 -c
# block that tripped the open-for-write regex below).
ALLOWED_REGEX_MERGE_DESIGN_CRITIC='(^|[[:space:]]|&&|;|\|)[[:space:]]*python3?[[:space:]]+[./]*\.?claude/scripts/merge-design-critic-traces\.py'
if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_REGEX_MERGE_DESIGN_CRITIC"; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# Allow the official scaffold-pages merge script (lead-merge aggregation at
# bootstrap state-11c — PR2b extracted this from an inline python3 -c block
# that wrote .runs/agent-traces/scaffold-pages.json directly, mirroring the
# #1045 resolution for design-critic).
ALLOWED_REGEX_MERGE_SCAFFOLD_PAGES='(^|[[:space:]]|&&|;|\|)[[:space:]]*python3?[[:space:]]+[./]*\.?claude/scripts/merge-scaffold-pages-traces\.py'
if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_REGEX_MERGE_SCAFFOLD_PAGES"; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# Allow the official design-consistency-checker merge script (lead-merge
# aggregation at verify state-3b page-batched path — issue #1257 mirrors
# the #1045 resolution for design-critic).
ALLOWED_REGEX_MERGE_DESIGN_CONSISTENCY_CHECKER='(^|[[:space:]]|&&|;|\|)[[:space:]]*python3?[[:space:]]+[./]*\.?claude/scripts/merge-design-consistency-checker-traces\.py'
if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_REGEX_MERGE_DESIGN_CONSISTENCY_CHECKER"; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# Allow the official landing-critic pre-merge script (lead-merge pre-aggregation
# for #1468 landing-critic split — landing-sections-critic.json + landing-images-critic.json
# → design-critic-landing.json BEFORE merge-design-critic-traces.py runs). Mirrors
# the #1257 convention.
ALLOWED_REGEX_MERGE_LANDING_CRITIC='(^|[[:space:]]|&&|;|\|)[[:space:]]*python3?[[:space:]]+[./]*\.?claude/scripts/merge-landing-critic-traces\.py'
if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_REGEX_MERGE_LANDING_CRITIC"; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# AOC v1.1: centralized agent-trace writer. Required to include --json
# (the trace payload). Provenance, source, coverage_provider preconditions
# are enforced inside the script.
ALLOWED_REGEX_WRITE_AGENT_TRACE='(^|[[:space:]]|&&|;|\|)[[:space:]]*bash[[:space:]]+[./]*\.?claude/scripts/write-agent-trace\.sh[[:space:]]'
if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_REGEX_WRITE_AGENT_TRACE"; then
  if echo "$COMMAND_CANONICAL" | grep -qE 'write-agent-trace\.sh[^&|;]*--json'; then
    # friction-skip: trivial-fast-path — input absent or non-applicable
    exit 0
  else
    deny "Agent trace write guard: write-agent-trace.sh invocation lacks --json '<...>' (required AOC v1.1)."
  fi
fi

# AOC v1.1: descriptive-field augmenter. Must include --field (defends against
# accidental no-op invocations). The script itself enforces field allowlist
# and spawn-log validation. --augment-spawn-index is optional from PR2b
# onward — when omitted, the script accepts ANY spawn-log entry matching
# agent + run_id, which is required for per-page parallel spawns where the
# agent does not know its specific spawn_index.
ALLOWED_REGEX_AUGMENT_TRACE='(^|[[:space:]]|&&|;|\|)[[:space:]]*python3?[[:space:]]+[./]*\.?claude/scripts/augment-trace\.py'
if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_REGEX_AUGMENT_TRACE"; then
  if echo "$COMMAND_CANONICAL" | grep -qE 'augment-trace\.py[^&|;]*--field'; then
    # friction-skip: trivial-fast-path — input absent or non-applicable
    exit 0
  else
    deny "Agent trace write guard: augment-trace.py invocation lacks --field <key>=<value> (required: at least one whitelisted descriptive field to augment)."
  fi
fi

# AOC v1.2 (PR3): audit-only sanctioned-skip writer for fixer agents that
# were blocked from spawning by an upstream hard gate. Required to include
# both --reason (the canonical hard_gate_failure enum) and
# --upstream-merge-path (the proof artifact). The writer itself enforces
# fixer-only restriction, upstream validation, and unresolved_critical
# computation. Without this allow-rule, the writer would be caught by the
# final catch-all below and every #1250 fixer-skip would be denied.
ALLOWED_REGEX_SKIPPED_FIXER='(^|[[:space:]]|&&|;|\|)[[:space:]]*bash[[:space:]]+[./]*\.?claude/scripts/write-skipped-fixer-trace\.sh[[:space:]]'
if echo "$COMMAND_CANONICAL" | grep -qE "$ALLOWED_REGEX_SKIPPED_FIXER"; then
  if echo "$COMMAND_CANONICAL" | grep -qE 'write-skipped-fixer-trace\.sh[^&|;]*--reason' \
     && echo "$COMMAND_CANONICAL" | grep -qE 'write-skipped-fixer-trace\.sh[^&|;]*--upstream-merge-path'; then
    # friction-skip: trivial-fast-path — input absent or non-applicable
    exit 0
  else
    deny "Agent trace write guard: write-skipped-fixer-trace.sh invocation lacks --reason and/or --upstream-merge-path (both required AOC v1.2; closes #1250)."
  fi
fi

# ── Final catch-all: any direct write operator targeting agent-traces ──
# Use the fd-redirect-stripped NORM so `cmd 2>&1 > agent-traces/<NAME>.json` still
# denies correctly (on the real `>` that writes the file) but
# `ls agent-traces/ 2>&1` is not falsely flagged.
#
# #1185 fix: the previous regex `(>|>>|tee|cp|mv).*agent-traces/...json` used
# unbounded `.*` and over-blocked any python -c whose source contains a
# comparison `len(x) > 0` AND mentions an agent-traces glob — VERIFY blocks
# in state files were forced to externalize to disk just to evade this regex.
# The replacement below uses the same shell-segment-bound check as the
# chained-redirect awk on line 71: split on &|;|, then within each segment
# require a write operator IMMEDIATELY adjacent (modulo whitespace/quotes)
# to an agent-traces/...json target. Read-only python -c expressions over
# agent-traces no longer match because `>` from a python comparison is
# separated from `agent-traces/` by other tokens (or by a `;` that triggers
# segment split inside `python -c "import x,y,z; ..."`).

if echo "$NORM" | awk '
    BEGIN{RS="[&|;]"}
    {
      # Bound write operator -> agent-traces target (>file, >>file, &>file)
      # within the same un-split shell segment.
      # Issue #1333 + post-fix: between operator and the gated basename allow
      # only path-like chars (no whitespace, no quote) so legitimate writes
      # like > .runs/agent-traces/<NAME>.json match while markdown-blockquote
      # prose > 1b. After each fix in agent-traces/<NAME>.json does not.
      # Pre-#1333 the exclusion class was non-chain-delim chars, which still
      # admitted prose; #1333 removed it entirely which broke real
      # .runs/-prefixed writes.
      if (match($0, /([0-9]*&?>+|[0-9]*>>?)[[:space:]]*["'\'']?[^[:space:]"'\'']*agent-traces\/[^[:space:]"'\'']*\.json/)) found=1
      # tee / cp / mv / dd with an agent-traces target later on the same segment
      else if (match($0, /(^|[[:space:]])(tee|cp|mv|dd)[[:space:]][^|;&]*agent-traces\/[^[:space:]"'\'']*\.json/)) found=1
    }
    END{exit !found}'; then
  deny "Agent trace write guard: .runs/agent-traces/*.json writes must go through init-trace.py / write-recovery-trace.sh / write-degraded-trace.py / write-agent-trace.sh / augment-trace.py. Direct shell writes are blocked."
fi

exit 0
