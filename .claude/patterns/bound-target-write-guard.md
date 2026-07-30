# Bound-Target Write-Guard Pattern

A pattern catalog for **Bash-matcher PreToolUse hooks that protect a path via
shell-redirect detection**. The pattern class is a peer to
`silent-failure-prevention.md`, but addresses a different defect axis:
silent-failure hooks suffer from intent-not-applied; bound-target write-guards
suffer from over-block / false-positive caused by **unbound co-occurrence
regex**.

The canonical fix shape is **bound-target adjacency in the deny predicate**:
the write operator (`>`, `>>`, `&>`, `tee`, `cp`, `mv`, `dd`) must be matched
**immediately adjacent** to the protected path target — not merely co-present
in the same shell segment. Without bound-target adjacency, a command like
`cat <protected> | tee /tmp/elsewhere` (read protected, write elsewhere)
matches both regexes and is wrongly denied.

This file is the canonical convention doc for the
`bash_hook_write_operator_binding` rule (issue #1236) declared in
`.claude/patterns/template-coherence-rules.json` and registered against the
manifest at `.claude/patterns/write-guard-hooks.json`.

## The Anti-Pattern

Three concrete buggy shapes have recurred across 7 historical issues. Each
shape was introduced by a maintainer who reused an earlier hook's structural
shape without internalizing the bound-target invariant.

### Shape A — `grep -qE` with `.*` between operator and path

This is the #1230 / pre-#1185 shape. The `.*` separator allows ANY tokens
between the operator and the protected path, so the regex matches commands
that mention the path in unrelated positions (heredoc bodies, stderr
redirection chains, `cat $path | <something>` reads).

```bash
# BUG: false-positive on `cat agent-spawn-log.jsonl | grep ...`
if echo "$NORM" | grep -qE '(>|>>|&>|tee|cp|mv|dd).*agent-spawn-log\.jsonl'; then
  deny "..."
fi
```

### Shape B — `awk` co-occurrence joined by `&&`

This is the original co-occurrence shape. Two regex literals joined by `&&`
match a single record when both regexes match anywhere in the record — there
is no positional binding between the operator and the path target.

```bash
# BUG: false-positive on `cat agent-traces/foo.json | tee /tmp/copy`
if echo "$NORM" | awk '/agent-traces\// && /(>|>>|tee|cp|mv|dd)/ { print 1; exit }' | grep -q 1; then
  deny "..."
fi
```

### Shape C — bare `match($0, /<op>.*<path>/)` without adjacency

A subtler variant: `match()` takes a single regex pattern, but `.*` between
the operator and the path defeats the bound-target invariant inside the
match. Functionally equivalent to Shape A.

```bash
# BUG: same defect as Shape A, expressed via awk match()
if echo "$NORM" | awk 'match($0, /(>|>>|tee|cp|mv|dd).*agent-traces\//) { print 1 }' | grep -q 1; then
  deny "..."
fi
```

## The Canonical Bound-Target Shape

The post-#1230 `trace-write-guard.sh` is the canonical reference. It uses a
two-pass `sed` normalization to strip read-only fd redirects (`2>/dev/null`,
`2>&1`), then `awk` with `RS="[&|;]"` to split the command into segments and
match the write operator **immediately adjacent** to the protected path
target within a single segment.

```bash
NORM=$(printf '%s' "$COMMAND" \
  | sed -E 's/[0-9]*>+&[0-9]+//g' \
  | sed -E 's/>&[[:space:]]+([^[:space:]]+)/> \1/g')

if printf '%s\n' "$NORM" \
  | awk 'BEGIN { RS="[&|;]" }
         match($0, /([0-9]*&?>+|[0-9]*>>?)[[:space:]]*["'"'"']?[^|;&"'"'"']*agent-spawn-log\.jsonl/) ||
         match($0, /(tee|cp|mv|dd)[[:space:]]+["'"'"']?[^|;&"'"'"']*agent-spawn-log\.jsonl/) { print 1; exit }' \
  | grep -q 1; then
  deny "..."
fi
```

The key invariants:

1. **Pass 1 (sed)**: strip fd-to-fd redirects (`2>&1`, `1>&2`) so they cannot
   match the write-operator regex.
2. **Pass 2 (sed)**: collapse `>& filename` to `> filename` for GNU-bash
   compatibility.
3. **`RS="[&|;]"`**: split on shell segment separators so each `awk` record
   is a single command segment. Adjacent matches in the SAME segment are
   bound; cross-segment matches are not.
4. **`match($0, /<op>[[:space:]]*["']?[^|;&"']*<path>/)`**: explicit adjacency
   — the write operator and the protected-path target must be in the same
   segment with only whitespace, optional quotes, and non-separator chars
   between them.

## Catalogued Issues

Each entry below names the historical defect, its buggy shape (verbatim from
the pre-fix git history where possible), and the fixed shape. The canonical
test fixtures in `.claude/scripts/tests/test_bash_hook_write_operator_binding.py`
must replay each buggy shape and assert the rule flags it.

### #1023 — `agent-trace-write-guard.sh` first instance
- **Symptom:** Bash command writing to `.runs/agent-traces/foo.json` was
  blocked unless it used the canonical `> file` shape; chained reads were
  also denied.
- **Buggy shape:** Shape A (`grep -qE`).
- **Fix:** Migrate to bound `match()` with adjacency.

### #1045 — `agent-trace-write-guard.sh` regression
- **Symptom:** Sibling defect — co-occurrence regex re-introduced when
  adding `cp`/`mv` operators.
- **Buggy shape:** Shape B (awk co-occurrence with `&&`).
- **Fix:** Move `cp`/`mv` into the bound match.

### #1064 — chain-blocked `echo > file` pattern
- **Symptom:** Heredoc bodies containing the protected path triggered
  false-positive deny on commands that wrote elsewhere.
- **Buggy shape:** Shape A in a chained context.
- **Fix:** Strip heredoc bodies before regex match.

### #1123 — co-occurrence false-positives
- **Symptom:** `cat agent-traces/x.json | tee /tmp/copy` denied even though
  the write target was `/tmp/copy`, not the protected path.
- **Buggy shape:** Shape B.
- **Fix:** Bound the write operator to the protected target via positional
  match.

### #1185 — unbounded `.*` redux
- **Symptom:** Same defect as #1123 in a different code path.
- **Buggy shape:** Shape A re-introduced during a refactor.
- **Fix:** Replace with bound `match()` per the canonical shape.

### #1223 — `state-completion-gate.sh` substring grep
- **Symptom:** Different defect class — substring grep over-fired on heredoc
  bodies mentioning `advance-state.sh`.
- **Note:** This is **not** a bound-target write-guard defect. It is a
  separate command-invocation parsing class fixed via heredoc-strip + shlex
  tokenization in `.claude/scripts/lib/check-advance-state-invocation.py`.
  Listed here for traceability — the `bash_hook_write_operator_binding` rule
  does **not** scope-creep to cover this class.

### #1230 — `trace-write-guard.sh` over-block
- **Symptom:** Sibling defect to #1185 in `trace-write-guard.sh`. Pre-fix
  `grep -qE '(>|>>|tee|cp|mv|dd).*agent-spawn-log'` matched legitimate read
  pipelines.
- **Buggy shape:** Shape A.
- **Fix:** Migrate to bound `match()` per the canonical shape (this is the
  pattern shown above as the canonical reference).

## Pattern Maintenance

When adding a new entry to the manifest at
`.claude/patterns/write-guard-hooks.json`:

- Verify the hook source contains the literal `protected_path_regex` string
  (this is the textual proof that a bound `match()` references it).
- Verify every declared `write_operator` appears in the hook source.
- Add a fixture to `test_bash_hook_write_operator_binding.py` lifting the
  pre-fix buggy regex from git history; assert the rule flags it.
- Update the catalogued issues section above with the new defect entry.

When adding a new write-guard hook (sibling to the existing four):

- Add a manifest entry first; the linter rule will then fire on any
  unregistered match in the hook source until the manifest is correct.
- Use the canonical bound-target shape from the canonical reference above.
  Do not invent a new structural shape without first updating this doc and
  the linter rule.

When the linter fires on a legitimate fast-path filter (e.g., a glob-prefix
detection step that uses unbound co-occurrence as a cheap pre-filter before
a downstream bound check), suppress with the pragma:

```bash
# coherence-allow: unbound-fastpath
```

The pragma must appear within ±5 lines of the matched anti-pattern.
Document the legitimate intent in a code comment immediately above the
pragma.

## Canonicalization Requirement (#1298)

**Bound-target adjacency** in the deny predicate is necessary but
insufficient. A second class of false positive exists: heredoc-body data
text in `$COMMAND` matches the bound regex even though the body is
**data**, not shell. Issue #1298 (the 7th sibling-chain instance) showed
that `cat > /tmp/r.txt << EOF\n... write-recovery-trace.sh ...\nEOF`
falsely tripped the allow-list and demanded `--reason`.

The fix: every registered write-guard hook MUST canonicalize `$COMMAND`
via `.claude/scripts/lib/canonicalize_bash_command.py` (which strips
heredoc bodies but preserves the introducer line) **before** any
shell-redirect or allow-list regex match.

### Per-line directive

| Where in the hook | Use which variable |
|---|---|
| Cheap raw-string fast-path glob (first line in the hook body) | RAW `$COMMAND` |
| Pre-canonicalization Python-source checks (`open()`, variable indirection, `Path().write_text`) | RAW `$COMMAND` + `# coherence-allow: raw-command` pragma |
| Re-test fast-path on canonical (after canonicalize) | `$COMMAND_CANONICAL` |
| `NORM` derivation (sed fd-redirect normalization) | `$COMMAND_CANONICAL` |
| Bound-redirect chain-write check (awk) | `$NORM` (CANONICAL-derived) |
| Allow-list regex matches + `--reason` / `--field` token checks | `$COMMAND_CANONICAL` |
| Final catch-all bound-redirect | `$NORM` (CANONICAL-derived) |
| sed -i / perl -i in-place editor check | `$COMMAND_CANONICAL` |

The Python-source checks (`open(...)` literal regex, variable-indirection
helper, `Path().write_text`) **must** stay on RAW `$COMMAND` so heredoc-fed
attacks like `python3 << PY ... open('<protected>','w') ... PY` are still
caught — canonicalization would strip the body and hide the attack
surface. Every such RAW reference must carry the pragma:

```bash
# coherence-allow: raw-command — heredoc-fed python attack detection (#1298 r1-c2)
```

The pragma must appear within ±5 lines of the raw `"$COMMAND"` reference.

### Conservative direction is INTENTIONAL

`strip_heredoc_bodies` over-strips relative to POSIX bash in three ways:

1. Plain `<<DELIM` requires the closing line to be **exactly** the
   delimiter — no leading or trailing whitespace tolerated. POSIX bash
   would NOT close on `   EOF` or `EOF   `; we conservatively over-strip.
2. `<<-DELIM` permits leading **tabs only** (not spaces). POSIX matches.
3. Unterminated heredoc strips to end-of-string. POSIX bash would not
   recover from this either — but we explicitly emit only the introducer
   line + a trailing newline.

Direction matters: **over-strip → over-deny** (false positive, harmless on
retry). **UNDER-STRIP → over-allow** (false negative, security regression).

**Future maintainers: do NOT relax these checks to match POSIX bash
exactly.** A `stripped.strip() == delim` form (which closes on lines
containing only whitespace and the delim) reopens the heredoc-body bypass
class. Any tightening must be accompanied by a security review and a
fixture demonstrating the over-strip behavior is no longer needed.

## Audit list of PreToolUse:Bash hooks

Programmatic enumeration:

```bash
grep -l 'read_payload_field "tool_input.command"' .claude/hooks/*.sh
```

Categorized by canonicalization status:

### In write-guard manifest — covered by this rule (4 hooks)

These are the registered write-guard hooks subject to the
`bash_hook_write_operator_binding` rule's Phase 1+2+3:

- `agent-trace-write-guard.sh` — protects `.runs/agent-traces/*.json`
- `trace-write-guard.sh` — protects `.runs/agent-spawn-log.jsonl`
- `fix-ledger-write-guard.sh` — protects `.runs/fix-ledger.jsonl` and
  `.runs/fix-log.md`
- `bootstrap-phase-a-write-guard.sh` — protects
  `src/app/{layout,not-found,error}.tsx` and `src/app/globals.css`

### Substring-grep hooks with their own canonicalizer (out of scope)

These hooks substring-match `$COMMAND` for invocation detection (not
write-guarding). They use `check-advance-state-invocation.py` which
imports `strip_heredoc_bodies` from `canonicalize_bash_command.py` —
they inherit the loop-restart + POSIX-strictness fixes from #1298
transparently:

- `state-completion-gate.sh`
- `phase-boundary-gate.sh`

The `bash_hook_write_operator_binding` rule does **not** scope-creep to
cover this class — it has its own canonicalizer with its own contract.

### Same-class candidates outside #1298 scope (recommend separate observations)

Round-2 critic of /solve for #1298 confirmed empirically that these three
hooks substring-match `$COMMAND` for command-invocation tokens (commit
create, PR create) and exhibit the same heredoc-body false-positive class:

- `observe-commit-gate.sh` — substring-match commit-create token
- `skill-commit-gate.sh` — substring-match commit-create token
- `verify-pr-gate.sh` — substring-match PR-create token

These are **out of #1298 scope** because the protected operation is
command invocation (not write-guarding) and the false-positive direction
is over-block on legitimate /tmp report writes whose body mentions the
trigger token. They are tracked separately. **Do NOT add them to
`write-guard-hooks.json`** — the manifest is for write-guards only.

### Different surface (not in scope)

- `skill-agent-gate.sh` — PreToolUse:**Agent** matcher (no `$COMMAND`)
- `lib-core.sh` / `lib.sh` / `lib-*.sh` — libraries sourced by hooks, not
  hooks themselves
