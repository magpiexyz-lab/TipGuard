# STATE 3d: QUALITY_FIX

**PRECONDITIONS:** STATE 3c complete.

**Always write** `.runs/quality-merge.json` — this is a metadata artifact, not an operational step:

- If quality agents ran: merge A11y violations + Consistency inconsistencies (see below)
- If quality agents did NOT run (scope `security` or `build`): write `{"findings":[],"source":"no-quality-agents","run_id":"<run_id>"}`
- If hard gate fired in STATE 3: write full merge + `"fixer_skipped":true,"reason":"hard_gate_failure"`

The decision of whether to spawn the quality-fixer (or skip it via one of two skip paths) is made in **Step 0** of ACTIONS below — not in this preamble.

**ACTIONS:**

### Step 0: Check skip paths (AOC v1.2)

Read `.runs/quality-merge.json` (write it first if it doesn't yet exist — see preamble). Three paths:

**(a) Scope-based skip** — quality agents were not spawned this run. Detected by `source == "no-quality-agents"`. Proceed to STATE 4 immediately. NO `lead-skipped` trace is written (no fixer was supposed to run for this scope; absent trace is correct and exempted by `state-completion-gate.sh` F4 check).

**(b) Hard-gate-failure skip** — quality agents ran but the upstream gate fired. Detected by `"fixer_skipped": true`. Write the audit-only trace and proceed:

```bash
SKIP_BRANCH=$(python3 -c "
import json, os
if not os.path.isfile('.runs/quality-merge.json'):
    print('normal')
else:
    d = json.load(open('.runs/quality-merge.json'))
    if d.get('source') == 'no-quality-agents':
        print('scope-skip')
    elif d.get('fixer_skipped') is True:
        print('audit-skip')
    else:
        print('normal')
")

if [ "$SKIP_BRANCH" = "audit-skip" ]; then
    REASON=$(python3 -c "import json; print(json.load(open('.runs/quality-merge.json')).get('reason',''))")
    bash .claude/scripts/write-skipped-fixer-trace.sh quality-fixer \
        --reason "$REASON" \
        --upstream-merge-path .runs/quality-merge.json
fi

if [ "$SKIP_BRANCH" != "normal" ]; then
    # Skip Archetype Gate, Step 1 (merge), Step 2 (spawn) below; proceed
    # directly to STATE 4. State-completion-gate F4 will validate either the
    # scope-skip exemption (source == no-quality-agents) or the audit-skip
    # exemption (lead-skipped trace exists with upstream_evidence_path).
    :
fi
```

**(c) Normal path** — neither scope-skip nor fixer-skip flag set. Continue with the Archetype Gate and Step 1/Step 2 below.

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, rows "Visual agents", "Performance + a11y agents".
> [visual-agents] web-app: design-critic, ux-journeyer, consistency-checker | service: skip | cli: skip
> [perf-a11y] web-app: performance-reporter, accessibility-scanner | service: skip | cli: skip

### Step 1: Merge Quality Results (if scope is `full` or `visual`, AND archetype is `web-app`)

Run the automated quality merge script:

```bash
PAYLOAD=$(python3 -c "
import json, os
traces = '.runs/agent-traces'
ctx = json.load(open('.runs/verify-context.json'))
run_id = ctx.get('run_id', '')

a11y = json.load(open(os.path.join(traces, 'accessibility-scanner.json')))
consistency = json.load(open(os.path.join(traces, 'design-consistency-checker.json')))

a11y_violations = a11y.get('violations', [])
c_inconsistencies = consistency.get('inconsistencies', [])

# Text-fallback parser (fix #1075): when the degraded-trace path dropped the
# structured inconsistencies[] field but the agent reported verdict='fail',
# parse its text report for the canonical findings table. Defense-in-depth —
# the primary path via write-degraded-trace.py --extra-json keeps this
# unused on well-formed runs, but stops silent-drops when the canonical
# field is empty. Permissive header regex accepts 'Pages' or 'Pages Affected'
# to tolerate column-header drift.
if not c_inconsistencies and consistency.get('verdict') == 'fail':
    import re
    text = consistency.get('text_report', '') or consistency.get('report', '')
    header_re = re.compile(r'\|\s*Check\s*\|\s*Status\s*\|\s*Severity\s*\|\s*Pages[^|]*\|\s*Detail\s*\|', re.IGNORECASE)
    row_re = re.compile(r'^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|', re.MULTILINE)
    if header_re.search(text):
        for m in row_re.finditer(text):
            check, status, severity, pages, detail = [x.strip() for x in m.groups()]
            if check.lower() == 'check' or set(check) == {'-'}:
                continue  # skip header and separator rows
            if status.lower() not in ('fail', 'warn'):
                continue
            c_inconsistencies.append({
                'check': check,
                'severity': severity.lower(),
                'pages': [p.strip() for p in pages.split(',') if p.strip()],
                'detail': detail,
                'source': 'text-fallback',
            })

# Normalize into unified findings array
merged = []
for v in a11y_violations:
    merged.append({
        'source': 'a11y',
        'impact': v.get('impact', 'moderate'),
        'rule': v.get('rule', ''),
        'page': v.get('page', ''),
        'element': v.get('element', ''),
        'detail': v.get('detail', ''),
        'wcag': v.get('wcag', '')
    })
for c in c_inconsistencies:
    merged.append({
        'source': 'consistency',
        'impact': c.get('severity', 'minor'),
        'check': c.get('check', ''),
        'pages': c.get('pages', []),
        'detail': c.get('detail', '')
    })

import sys
result = {
    'timestamp': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    'a11y_violations': a11y.get('violations_count', len(a11y_violations)),
    'consistency_issues': consistency.get('inconsistent_count', consistency.get('inconsistencies_found', len(c_inconsistencies))),
    'merged_issues': len(merged),
    'issues': merged,
}
print(f'Quality merge: {result[\"a11y_violations\"]} a11y violations + {result[\"consistency_issues\"]} consistency issues to {result[\"merged_issues\"]} merged issues', file=sys.stderr)
print(json.dumps(result))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/quality-merge.json \
  --payload "$PAYLOAD" \
  --skill verify
```

### Step 2: quality-fixer (if merged quality has issues AND at least one critical/serious a11y violation or major consistency issue)

Before spawning, execute the [Atomic Execution Protocol](../verify.md#atomic-execution-protocol) snapshot:

```bash
git diff --name-only > /tmp/pre-agent-snapshot.txt
```

Spawn the `quality-fixer` agent (`subagent_type: quality-fixer`).
Pass: merged A11y violations + Consistency inconsistencies.

**Wait for the fixer to complete before continuing.**

If agent returns with Trace State 2 (exhausted), execute the [Atomic Execution Protocol](../verify.md#atomic-execution-protocol) revert before retrying (see [Exhaustion Protocol](../verify.md#exhaustion-protocol) Tier 1).

After quality-fixer completes: verify `.runs/agent-traces/quality-fixer.json` exists; if agent returned output but trace is missing, write a recovery trace with `"recovery":true`.

After each fix, log via the canonical writer (AOC v1 R2 — do NOT write to `.runs/fix-log.md` directly):

```bash
python3 .claude/scripts/write-fix-ledger.py --lead-fix --skill verify \
  --fix-json '{"file":"<file>","symptom":"<short symptom>","fix":"<short fix description>"}'
```

#### Step 2a: Lead-side validation (quality-fixer)

1. Read `.runs/agent-traces/quality-fixer.json` trace.
2. If `verdict` == `"partial"` AND `unresolved_critical` > 0, this is a **hard gate failure** — Critical/Serious a11y violations or Major consistency issues remain unfixed after 2 fix cycles. Skip STATE 5 but still write verify-report.md (STATE 7a) and execute STATE 8 (Save Patterns). Report failure to user with the unresolved items.
3. If trace has `"recovery": true` AND `verdict` == `"partial"`, treat as hard gate failure (recovery traces cannot confirm fixes succeeded).
4. Extract Fix Summaries from the agent's return message. Log each fix via the canonical writer (AOC v1 R2 — do NOT write to `.runs/fix-log.md` directly):
   ```bash
   python3 .claude/scripts/write-fix-ledger.py --lead-fix --skill verify \
     --fix-json '{"file":"<file>","symptom":"<from agent Fix Summary>","fix":"<from agent Fix Summary>"}'
   ```
5. If the lead directly applies additional quality fixes beyond what quality-fixer handled, log via the canonical writer:
   ```bash
   python3 .claude/scripts/write-fix-ledger.py --lead-fix --skill verify \
     --fix-json '{"file":"<file>","symptom":"<finding>","fix":"<what changed>"}'
   ```

**POSTCONDITIONS:** `quality-merge.json` exists. Quality-fixer trace exists (if spawned). If quality-fixer verdict is `"partial"` with `unresolved_critical` > 0, pipeline is halted.

**VERIFY:**
```bash
python3 -c "import json,os; ctx=json.load(open('.runs/verify-context.json')); run_id=ctx.get('run_id',''); d=json.load(open('.runs/quality-merge.json')); assert 'run_id' in d, 'run_id missing'; has_source=d.get('source')=='no-quality-agents'; assert has_source or (isinstance(d.get('issues'), list) and isinstance(d.get('merged_issues'), int)), 'full-scope merge missing issues or merged_issues'; ledger=[json.loads(l) for l in open('.runs/fix-ledger.jsonl') if l.strip()] if os.path.exists('.runs/fix-ledger.jsonl') else None; by_agent={}; [by_agent.update({r.get('agent'): by_agent.get(r.get('agent'),0)+1}) for r in (ledger or []) if r.get('run_id')==run_id]; fl=open('.runs/fix-log.md').read() if os.path.exists('.runs/fix-log.md') else ''; checks=[('quality-fixer','.runs/agent-traces/quality-fixer.json')]; errs=[]
for n,p in checks:
    if not os.path.exists(p): continue
    tf=len(json.load(open(p)).get('fixes',[]))
    if tf==0: continue
    if ledger is not None:
        lf=by_agent.get(n,0)
        if lf!=tf: errs.append(n+': trace='+str(tf)+' ledger='+str(lf))
    else:
        if 'Fix ('+n not in fl: errs.append(n+': trace has fixes but fix-log missing Fix ('+n+')')
assert not errs, '; '.join(errs)"
```

> **Hook-enforced:** `skill-agent-gate.sh` validates STATE 3d postconditions before allowing security-fixer to spawn.

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh verify 3d
```

**NEXT:** Read [state-4-security-merge-fix.md](state-4-security-merge-fix.md) to continue.
