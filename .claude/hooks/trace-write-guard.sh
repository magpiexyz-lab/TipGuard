#!/usr/bin/env bash
# trace-write-guard.sh — Claude Code PreToolUse hook for Bash commands.
# Blocks Bash commands that write to agent-spawn-log.jsonl.
#
# The spawn-log is hook-managed: only skill-agent-gate.sh (a PreToolUse:Agent
# hook) may write to it. Hook execution does not trigger PreToolUse hooks,
# so the gate's own writes pass through while LLM-initiated Bash writes are
# caught here.
#
# Issue #963 fix: this hook no longer whitelists write-recovery-trace.sh
# (that script no longer mutates the spawn-log; it relies on the existing
# skill-agent-gate entry).
#
# Issue #1230 fix: replace unbound co-occurrence regex with bound-target
# awk (mirror agent-trace-write-guard.sh's #1185 design). The previous
# `(>|>>|tee|cp|mv|dd).*agent-spawn-log` regex and
# `/agent-spawn-log/ && /(>|>>|tee|cp|mv|dd)/` awk co-occurrence over-blocked
# any segment that mentioned the path AND any `>`/`>>`/`tee`/`cp`/`mv`/`dd`
# token, including pure reads with `2>/dev/null`, gh chains with `2>&1`,
# and python source mentioning the path inside string literals or grep/rg
# arguments. The bound-target match() requires the write operator to be
# IMMEDIATELY adjacent (modulo whitespace/quotes) to a spawn-log target
# path with the canonical `.jsonl` extension.

set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

COMMAND=$(read_payload_field "tool_input.command")

# Fast-path: no mention of spawn-log → allow.
# Cheap raw-string glob — runs BEFORE canonicalization so unrelated commands
# (the common case) skip the python startup entirely. (#1298 r1-c4 perf.)
case "$COMMAND" in
  *agent-spawn-log*) ;;
  *) exit 0 ;;
esac

# ── Pre-canonicalization Python-source checks (RAW $COMMAND) ──
#
# These checks run on RAW $COMMAND BEFORE canonicalization so heredoc-fed
# python attacks (`python3 <<PY ... open('...spawn-log.jsonl','w') ... PY`)
# are still caught — canonicalization would strip the body and hide the
# attack surface (#1298 r1-c2).

# Block Python open(...) for write/append on the canonical spawn-log file.
# The literal-path form: `open(".runs/agent-spawn-log.jsonl", "w")`.
# coherence-allow: raw-command — heredoc-fed python attack detection (#1298 r1-c2)
if echo "$COMMAND" | grep -qE "open\([^)]*agent-spawn-log\.jsonl[^)]*,[[:space:]]*['\"][wa]"; then
  deny "Trace write guard: agent-spawn-log.jsonl is hook-managed (Python open-for-write detected)."
fi

# Block Python variable-indirection writes to the spawn-log.
#
# Pattern: `f="...agent-spawn-log.jsonl..."; ... open(f, "w")` — the literal
# path is bound to a variable, and the open() call uses the variable rather
# than the literal. The literal-path regex above only catches direct
# open(<literal>) forms, so this Python helper closes the indirection gap
# (mirrors agent-trace-write-guard.sh:114-133).
#
# Implementation: scan the COMMAND string as a single unit (NOT split on `;` —
# the chain-record awk's RS="[&|;]" would tear Python `import json; ...`
# source across awk records, breaking variable correlation).
# coherence-allow: raw-command — heredoc-fed python attack detection (#1298 r1-c2)
INDIRECT_CHECK=$(echo "$COMMAND" | python3 -c '
import re, sys
cmd = sys.stdin.read()
# Capture all <var> = "...agent-spawn-log.jsonl..." assignments.
assignments = set()
for m in re.finditer(
    r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*[\x27\x22][^\x27\x22]*agent-spawn-log\.jsonl[^\x27\x22]*[\x27\x22]",
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
  deny "Trace write guard: agent-spawn-log.jsonl variable-indirection write blocked (variable bound to spawn-log path is later passed to open() with write mode)."
fi

# Issue #1298: strip heredoc bodies before shell-redirect bound-target check
# so heredoc-body data text doesn't trigger the bound regex. Re-test fast-path
# on canonical: when the `agent-spawn-log` mention was ONLY in a heredoc body,
# exit 0 here.
#
# Resilience: if the canonicalizer fails (python3 missing, script error),
# fall back to RAW $COMMAND. The bound-redirect awk on $NORM still fires on
# real shell writes — heredoc-body false-positive fix is the only thing
# temporarily lost. Use `if` form for bash 3.2 set -e portability.
if CANONICAL_TMP=$(printf '%s' "$COMMAND" | python3 "$(dirname "$0")/../scripts/lib/canonicalize_bash_command.py" 2>/dev/null); then
  COMMAND_CANONICAL="$CANONICAL_TMP"
else
  # coherence-allow: raw-command — fail-soft fallback to RAW $COMMAND when canonicalize unavailable (#1298)
  COMMAND_CANONICAL="$COMMAND"
fi
case "$COMMAND_CANONICAL" in
  *agent-spawn-log*) ;;
  *) exit 0 ;;
esac

# Two-pass NORM (mirrors agent-trace-write-guard.sh):
#
# Pass 1 — strip fd-to-fd redirects (2>&1, >&1, 3>&2, 2>>&1). These are
# stderr/fd redirection tokens, not file writes — but their bare `>`
# character falsely matches the write-operator regex below, and their
# embedded `&` falsely splits the awk chain-record (RS="[&|;]"). Strip
# `[0-9]*>+&[0-9]+` so both checks see the command without fd tokens.
# File writes (>file, >>file, &>file, >&file GNU extension, tee, cp, mv, dd)
# do NOT match this pattern and are preserved intact.
#
# Pass 2 — collapse the GNU `>& filename` form (cmd >& filename ≡
# cmd > filename 2>&1, a real file write) to plain `> filename`. Without
# this, the literal `&` between `>` and the filename is consumed as the
# awk chain-record separator (RS="[&|;]"), splitting the write operator
# from its target into two adjacent records and silently allowing the
# write. Order matters: pass 1 strips digit-after-& first, pass 2 reshapes
# the file form (non-digit-after-&) second.
#
# Derive from CANONICAL so heredoc-body text doesn't pollute the bound-
# redirect check on $NORM (#1298).
NORM=$(printf '%s' "$COMMAND_CANONICAL" \
  | sed -E 's/[0-9]*>+&[0-9]+//g' \
  | sed -E 's/>&([[:space:]]*)([^&|;[:space:]])/> \1\2/g')

# Bound-target write check on chain segments.
#
# Split on &|;|, then within each segment require a write operator IMMEDIATELY
# adjacent (modulo whitespace/quotes) to the canonical spawn-log target
# (agent-spawn-log\.jsonl). The `.jsonl` extension is required — paths like
# /tmp/agent-spawn-log-debug or agent-spawn-log.bak are intentionally NOT
# matched (the fast-path glob lets them past, but the bound-target check
# only trips on the canonical hook-managed file).
#
# Also matches tee/cp/mv/dd as command words followed (later in the same
# segment) by a spawn-log target. `dd` is preserved from the pre-#1230
# write-marker set even though the sibling agent-trace-write-guard.sh lacks
# it (sibling parity gap tracked in #1236).
if echo "$NORM" | awk '
    BEGIN{RS="[&|;]"}
    {
      # Bound write operator -> spawn-log target (>file, >>file, &>file).
      # Issue #1333 + post-fix: between operator and the gated basename allow
      # only path-like chars (no whitespace, no quote) so legitimate writes
      # like > .runs/agent-spawn-log.jsonl match while markdown-blockquote
      # prose > 1b. some text agent-spawn-log.jsonl does not. Pre-#1333 the
      # exclusion class was non-chain-delim chars, which still admitted prose;
      # #1333 removed it entirely which broke real .runs/-prefixed writes.
      if (match($0, /([0-9]*&?>+|[0-9]*>>?)[[:space:]]*["'\'']?[^[:space:]"'\'']*agent-spawn-log\.jsonl/)) found=1
      # tee / cp / mv / dd as words with a spawn-log target on the same segment
      else if (match($0, /(^|[[:space:]])(tee|cp|mv|dd)[[:space:]][^|;&]*agent-spawn-log\.jsonl/)) found=1
    }
    END{exit !found}'; then
  deny "Trace write guard: agent-spawn-log.jsonl is hook-managed. Only skill-agent-gate.sh may write to it."
fi

exit 0
