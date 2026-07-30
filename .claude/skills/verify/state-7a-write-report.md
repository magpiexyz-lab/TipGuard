# STATE 7a: WRITE_REPORT

**PRECONDITIONS:** STATE 5 complete. All agents finished. All traces written.

> **This state is gated by `verify-report-gate.sh`.** The hook checks that
> verify-context.json, fix-log.md, and agent traces exist before allowing
> the write. If the hook denies the write, go back and complete the missing steps.

**ACTIONS:**

### Evidence validation for recovery / self-degraded traces

Before extracting verdicts, stamp `recovery_validated` on every trace whose
`provenance ∈ {recovery, self-degraded}` — the hard-gate predicate rules in
`agent-registry.json` require this for the report to pass
`verify-report-gate.sh` with `hard_gate_failure: false`. The validator
cross-checks `build-result.json`, `e2e-result.json`, and `git diff` /
`git status --porcelain` against the trace's `fixes[]` (or `no_fixes_claimed`
path for findings-only agents).

```bash
for tf in .runs/agent-traces/*.json; do
  [ -f "$tf" ] || continue
  prov=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('provenance',''))" "$tf" 2>/dev/null || echo "")
  case "$prov" in
    recovery|self-degraded)
      name=$(basename "$tf" .json)
      bash .claude/scripts/validate-recovery.sh "$name" || \
        echo "WARN: validate-recovery $name FAILED — trace keeps recovery_validated:false (hard gate will require hard_gate_failure:true)"
      ;;
  esac
done
```

Before writing the report, extract BOTH raw (pre-fix) and after-fix agent verdicts.

The `agent_verdicts_after_fixes` derivation is the #1151 fix. After Phase-2 fixers run,
Phase-1 agents are NOT re-spawned; instead, post-fix verdicts are derived from the FIXER
traces' `unresolved_critical` (security/quality) or the agent's own `unresolved_dead_ends`
(ux-journeyer). Recovery-stamped traces are gated on AOC v1.1 hard_gate predicates via
the `is_trace_valid_pass` helper (mirrors `agent-registry.json:202-213`).

```bash
AGENT_VERDICTS_FULL=$(python3 -c "
import json, glob, os

FIXER_MAP = {
    'security-defender': 'security-fixer',
    'security-attacker': 'security-fixer',
    'accessibility-scanner': 'quality-fixer',
    'design-consistency-checker': 'quality-fixer',
}

def is_trace_valid_pass(trace):
    # Mirror AOC v1.1 hard_gate predicates from agent-registry.json:202-213.
    # A trace's 'pass' value is only safe to propagate when the trace itself
    # is structurally valid per its provenance class.
    prov = trace.get('provenance', 'self')
    if prov == 'self':
        return True
    if prov in ('recovery', 'self-degraded', 'lead-on-behalf'):
        return trace.get('recovery_validated') is True
    if prov == 'lead-fix':
        return trace.get('lead_attestation') is True
    if prov == 'lead-synthesized':
        return trace.get('coverage_provider') is not None
    return False  # unknown provenance — conservative

verdicts = {}
after = {}
source = {}
for f in glob.glob('.runs/agent-traces/*.json'):
    name = os.path.basename(f).replace('.json', '')
    d = json.load(open(f))
    verdicts[name] = d.get('verdict', 'missing')

    if name in FIXER_MAP:
        # Post-fix verdict comes from the fixer's trace (not the Phase-1 trace)
        fixer = FIXER_MAP[name]
        fpath = '.runs/agent-traces/' + fixer + '.json'
        if os.path.isfile(fpath):
            ftrace = json.load(open(fpath))
            unresolved = ftrace.get('unresolved_critical', -1)
            valid = is_trace_valid_pass(ftrace)
            after[name] = 'pass' if (unresolved == 0 and valid) else 'fail'
            source[name] = fixer + '.json'
        else:
            # Fixer didn't run — verdict is unchanged from raw
            after[name] = verdicts[name]
            source[name] = 'self (fixer absent)'
    elif name == 'ux-journeyer':
        # ux-journeyer is its own source — check its OWN provenance + dead-ends
        unresolved = d.get('unresolved_dead_ends', -1)
        valid = is_trace_valid_pass(d)
        after[name] = 'pass' if (unresolved == 0 and valid) else 'fail'
        source[name] = 'self'
    else:
        # design-critic (own fixer), behavior-verifier, performance-reporter,
        # spec-reviewer, build-info-collector, security-fixer itself,
        # quality-fixer itself, observer, solve-critic, resolve-challenger, etc.
        after[name] = verdicts[name]
        source[name] = 'self'

print(json.dumps({
    'agent_verdicts': verdicts,
    'agent_verdicts_after_fixes': after,
    'agent_verdicts_after_fixes_source': source,
}))
" 2>/dev/null || echo '{}')

# Pull each map for the report template
AGENT_VERDICTS=$(echo "$AGENT_VERDICTS_FULL" | python3 -c "import json,sys; print(json.dumps(json.loads(sys.stdin.read() or '{}').get('agent_verdicts', {})))")
AGENT_VERDICTS_AFTER_FIXES=$(echo "$AGENT_VERDICTS_FULL" | python3 -c "import json,sys; print(json.dumps(json.loads(sys.stdin.read() or '{}').get('agent_verdicts_after_fixes', {})))")
AGENT_VERDICTS_AFTER_FIXES_SOURCE=$(echo "$AGENT_VERDICTS_FULL" | python3 -c "import json,sys; print(json.dumps(json.loads(sys.stdin.read() or '{}').get('agent_verdicts_after_fixes_source', {})))")
```

Write `.runs/verify-report.md`:

```markdown
---
timestamp: [ISO 8601]
scope: [full|security|visual|build]
build_attempts: [1-3]
fix_log_entries: [N]
agents_expected: [list from scope table]
agents_completed: [list as they finish]
consistency_scan: pass | skipped | N/A
auto_observe: evaluated-in-epilogue
lead_retrospective: evaluated-in-epilogue
agent_verdicts: <AGENT_VERDICTS JSON>
agent_verdicts_after_fixes: <AGENT_VERDICTS_AFTER_FIXES JSON>
agent_verdicts_after_fixes_source: <AGENT_VERDICTS_AFTER_FIXES_SOURCE JSON>
hard_gate_failure: false
process_violation: false
overall_verdict: pass | fail
---

## Build
- Attempts: [N]/3
- Result: pass
- Last output: [last 3-5 lines of build output]

## Quality Delta
> Populated when `.runs/verify-history.jsonl` has a previous entry **matching the current skill**. Otherwise emit a note: "Quality Delta: no prior baseline for this skill. This run establishes baseline; subsequent runs will show delta."
>
> Read `.runs/verify-history.jsonl` and find the last entry where `skill` matches the current skill (from verify-context.json). If no matching entry exists, emit the note above.

| Metric | Previous | Current | Delta |
|--------|----------|---------|-------|
| Build attempts | [prev] | [curr] | [+/-N or —] |
| Fix log entries | [prev] | [curr] | [+/-N or —] |
| Overall verdict | [prev] | [curr] | [improved/regressed/—] |
| Q-score | [prev] | [curr] | [+/-N or —] |

## Review Agents
| Agent | Verdict | Notes |
|-------|---------|-------|
| design-critic | [pass/fixed/skipped] | [1-line summary; if `review_method == "boundary-skip-all-pages"` (#1256 Stage 0): "all-pages-fast-path-shortcut — N pages, zero UI source files in PR boundary"] |
| design-critic-shared | [fixed/skipped/N/A] | [shared component fixes, or "no shared issues"] |
| design-consistency-checker | [pass/fail/partial] | [if `provenance: "lead-merge"` (#1257 page-batching): format as `"<K> batches × <pages_reviewed> pages reviewed (page-batched, #1257)"` where `K = len(trace.contributing_spawn_indexes)` and `pages_reviewed = trace.pages_reviewed`; if `partial: true` (a batch hit Tier 2 fallback): also append `"; remaining: " + ", ".join(trace.pages_remaining)`; if `review_method: "boundary-skip-all-pages"` (#1256 Stage 0): "all pages fast-path; cross-page consistency unchanged"; else: "1-line summary"] |
| ux-journeyer | [pass/fixed/skipped] | [1-line summary] |
| security-defender | [pass/N issues] | [1-line summary] |
| security-attacker | [pass/N findings] | [1-line summary] |
| security-fixer | [fixed N/skipped] | [1-line summary] |
| quality-fixer | [fixed N/skipped] | [1-line summary] |
| behavior-verifier | [pass/N issues] | [1-line summary] |
| performance-reporter | [summary/skipped] | [1-line summary] |
| accessibility-scanner | [pass/N issues/skipped] | [1-line summary] |
| spec-reviewer | [pass/N gaps/skipped] | [1-line summary] |

## Observations Filed
Evaluated in post-finalize epilogue via observation-phase.md.
- Pending epilogue completion

## Process Compliance
> Always populated.

- Process Checklist in current-plan.md: [present | missing]
- TDD order: [pass | WARN — N violations | N/A]
- Source: spec-reviewer S8
```

Only include agents that were spawned (per scope). Mark others as "skipped — out of scope".

> **Default fields:** The `hard_gate_failure: false` and `process_violation: false` fields are always present in the template. Set them to `true` when the relevant conditions are triggered (see below). The verify-report-gate hook validates their presence unconditionally.

> **Completion audit.** Before writing verify-report.md, compare
> `agents_expected` (from scope table) against `agents_completed`.
> If any expected agent was not spawned:
> - List it as `"SKIPPED — PROCESS VIOLATION"` (not `"skipped — out of scope"`)
> - Set `process_violation: true` in verify-report.md frontmatter
> - BG3 gate will BLOCK on process violations
>

> **This file is a hard gate.** The commit/PR step in the calling skill
> reads this file and includes its contents in the PR body. If the file
> does not exist, the PR step must run verify.md first.

6. **Config-error gate:** Before computing the verdict, check if E2E tests were skipped due to config errors:

   ```bash
   if test -f .runs/e2e-result.json && python3 -c "import json; exit(0 if json.load(open('.runs/e2e-result.json')).get('config_error') else 1)" 2>/dev/null; then
     python3 -c "
   import re
   with open('.runs/verify-report.md', 'r') as f:
       content = f.read()
   content = re.sub(r'^hard_gate_failure: false$', 'hard_gate_failure: true', content, flags=re.MULTILINE)
   with open('.runs/verify-report.md', 'w') as f:
       f.write(content)
   "
     echo "Config-error gate: set hard_gate_failure=true (tests never executed)"
   fi
   ```

7. Compute `overall_verdict`: if `hard_gate_failure` is `true` OR `process_violation` is `true` → `fail`, otherwise → `pass`. Write this into the frontmatter.

**POSTCONDITIONS:**
- `verify-report.md` exists with valid frontmatter (starts with `---`)
- `overall_verdict` field is present in frontmatter
- `agents_expected` and `agents_completed` fields are present
- `hard_gate_failure` and `process_violation` fields are present

**VERIFY:**
```bash
head -1 .runs/verify-report.md | grep -q '^---$' && python3 -c "c=open('.runs/verify-report.md').read(); fm=c.split('---')[1] if c.count('---')>=2 else ''; missing=[f for f in ['overall_verdict:','hard_gate_failure:','process_violation:','agents_expected:','agents_completed:'] if f not in fm]; assert not missing, 'verify-report frontmatter missing: %s' % missing"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh verify 7a
```

**NEXT:** Read [state-7b-compute-qscore.md](state-7b-compute-qscore.md) to continue.
