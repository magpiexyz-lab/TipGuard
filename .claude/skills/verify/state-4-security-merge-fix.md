# STATE 4: SECURITY_MERGE_FIX

**PRECONDITIONS:** STATE 3d complete.

**Always write** `.runs/security-merge.json` — this is a metadata artifact, not an operational step:

- If security agents ran: merge Defender FAILs + Attacker findings (see below)
- If security agents did NOT run (scope `visual` or `build`): write `{"findings":[],"source":"no-security-agents","run_id":"<run_id>"}`
- If hard gate fired in STATE 3: write full merge + `"fixer_skipped":true,"reason":"hard_gate_failure"`

The decision of whether to spawn the security-fixer (or skip it via one of two skip paths) is made in **Step 0** of ACTIONS below — not in this preamble.

**ACTIONS:**

### Step 0: Check skip paths (AOC v1.2)

Read `.runs/security-merge.json` (write it first if it doesn't yet exist — see preamble). Three paths:

**(a) Scope-based skip** — security agents were not spawned this run. Detected by `source == "no-security-agents"`. Proceed to STATE 5 immediately. NO `lead-skipped` trace is written (no fixer was supposed to run for this scope; absent trace is correct and exempted by `state-completion-gate.sh` F4 check).

**(b) Hard-gate-failure skip** — security agents ran but the upstream gate fired. Detected by `"fixer_skipped": true`. Write the audit-only trace and proceed:

```bash
SKIP_BRANCH=$(python3 -c "
import json, os
if not os.path.isfile('.runs/security-merge.json'):
    print('normal')
else:
    d = json.load(open('.runs/security-merge.json'))
    if d.get('source') == 'no-security-agents':
        print('scope-skip')
    elif d.get('fixer_skipped') is True:
        print('audit-skip')
    else:
        print('normal')
")

if [ "$SKIP_BRANCH" = "audit-skip" ]; then
    REASON=$(python3 -c "import json; print(json.load(open('.runs/security-merge.json')).get('reason',''))")
    bash .claude/scripts/write-skipped-fixer-trace.sh security-fixer \
        --reason "$REASON" \
        --upstream-merge-path .runs/security-merge.json
fi

if [ "$SKIP_BRANCH" != "normal" ]; then
    # Skip Step 1 (merge) and Step 2 (spawn) below; proceed directly to STATE 5.
    # State-completion-gate F4 will validate either the scope-skip exemption
    # (source == no-security-agents) or the audit-skip exemption (lead-skipped
    # trace exists with upstream_evidence_path).
    :  # Caller proceeds to STATE 5 after this Step 0 block exits non-error
fi
```

**(c) Normal path** — neither scope-skip nor fixer-skip flag set. Continue with Step 1 (merge) and Step 2 (security-fixer spawn) below.

### Step 1: Merge Security Results (if scope is `full` or `security`)

Run the automated security merge script:

```bash
PAYLOAD=$(python3 -c "
import json, os
traces = '.runs/agent-traces'
ctx = json.load(open('.runs/verify-context.json'))
run_id = ctx.get('run_id', '')

defender = json.load(open(os.path.join(traces, 'security-defender.json')))
attacker = json.load(open(os.path.join(traces, 'security-attacker.json')))

d_fails = defender.get('fails', [])
a_findings = attacker.get('findings', [])

# Backward compat: block if structured arrays missing but counts > 0
if not d_fails and defender.get('fails_count', 0) > 0:
    raise ValueError('security-defender trace missing fails array — update agent definition')
if not a_findings and attacker.get('findings_count', 0) > 0:
    raise ValueError('security-attacker trace missing findings array — update agent definition')

# Deduplicate: same file + same desc -> keep attacker finding
# Skip findings with empty file AND empty desc to avoid false collisions
seen = set()
merged = []
for f in a_findings:
    file_val, desc_val = f.get('file',''), f.get('desc','')
    if file_val or desc_val:
        key = (file_val, desc_val)
        seen.add(key)
    merged.append({**f, 'source': 'attacker'})
for f in d_fails:
    file_val, desc_val = f.get('file',''), f.get('desc','')
    if not file_val and not desc_val:
        merged.append({**f, 'source': 'defender'})
    else:
        key = (file_val, desc_val)
        if key not in seen:
            merged.append({**f, 'source': 'defender'})

import sys
result = {
    'timestamp': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    'defender_fails': defender.get('fails_count', 0),
    'attacker_findings': attacker.get('findings_count', 0),
    'merged_issues': len(merged),
    'issues': merged,
}
print(f'Security merge: {result[\"defender_fails\"]} defender FAILs + {result[\"attacker_findings\"]} attacker findings -> {result[\"merged_issues\"]} merged issues', file=sys.stderr)
print(json.dumps(result))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/security-merge.json \
  --payload "$PAYLOAD" \
  --skill verify
```

### Step 2: security-fixer (if merged security has issues)

Before spawning, execute the [Atomic Execution Protocol](../verify.md#atomic-execution-protocol) snapshot:

```bash
git diff --name-only > /tmp/pre-agent-snapshot.txt
```

Spawn the `security-fixer` agent (`subagent_type: security-fixer`).
Pass: merged Defender table + Attacker findings.

**Wait for the fixer to complete before continuing.**

If agent returns with Trace State 2 (exhausted), execute the [Atomic Execution Protocol](../verify.md#atomic-execution-protocol) revert before retrying (see [Exhaustion Protocol](../verify.md#exhaustion-protocol) Tier 1).

After security-fixer completes: verify `.runs/agent-traces/security-fixer.json` exists; if agent returned output but trace is missing, write a recovery trace with `"recovery":true`.

After each fix, log via the canonical writer (AOC v1 R2 — do NOT write to `.runs/fix-log.md` directly):

```bash
python3 .claude/scripts/write-fix-ledger.py --lead-fix --skill verify \
  --fix-json '{"file":"<file>","symptom":"<short symptom>","fix":"<short fix description>"}'
```

#### Step 2a: Lead-side validation (security-fixer)

1. Read `.runs/agent-traces/security-fixer.json` trace.
2. If `verdict` == `"partial"` AND `unresolved_critical` > 0, this is a **hard gate failure** — Critical/High security issues or Defender FAILs remain unfixed after 2 fix cycles. Skip STATE 5 but still write verify-report.md (STATE 7a) and execute STATE 8 (Save Patterns). Report failure to user with the unresolved items.
3. If trace has `"recovery": true` AND `verdict` == `"partial"`, treat as hard gate failure (recovery traces cannot confirm fixes succeeded).
4. Extract Fix Summaries from the agent's return message. Log each fix via the canonical writer (AOC v1 R2 — do NOT write to `.runs/fix-log.md` directly):
   ```bash
   python3 .claude/scripts/write-fix-ledger.py --lead-fix --skill verify \
     --fix-json '{"file":"<file>","symptom":"<from agent Fix Summary>","fix":"<from agent Fix Summary>"}'
   ```
5. If the lead directly applies additional security fixes beyond what security-fixer handled (e.g., defender findings the fixer did not address), log via the canonical writer:
   ```bash
   python3 .claude/scripts/write-fix-ledger.py --lead-fix --skill verify \
     --fix-json '{"file":"<file>","symptom":"<finding>","fix":"<what changed>"}'
   ```

**POSTCONDITIONS:** `security-merge.json` exists. Security-fixer trace exists (if spawned). If security-fixer verdict is `"partial"` with `unresolved_critical` > 0, pipeline is halted.

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/security-merge.json')); assert 'run_id' in d, 'run_id missing'; has_source=d.get('source')=='no-security-agents'; assert has_source or (isinstance(d.get('issues'), list) and isinstance(d.get('merged_issues'), int)), 'full-scope merge missing issues or merged_issues'"
```

> **Hook-enforced:** `skill-agent-gate.sh` validates STATE 4 postconditions before allowing observer to spawn.

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh verify 4
```

**NEXT:** Read [state-5-e2e-tests.md](state-5-e2e-tests.md) to continue.
