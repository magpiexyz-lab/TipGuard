# STATE 7b: COMPUTE_QSCORE

**PRECONDITIONS:** STATE 7a complete (`verify-report.md` exists with valid frontmatter).

**ACTIONS:**

8. Extract dimension scores from agent traces (before traces are deleted in the calling skill's cleanup step). These scores feed Q-score computation:

   ```bash
   python3 -c "
   import json, glob, os, datetime

   ctx = json.load(open('.runs/verify-context.json'))
   report = open('.runs/verify-report.md').read()
   lines = report.split('\n')
   fm = {}
   in_fm = False
   for line in lines:
       s = line.strip()
       if s == '---':
           if in_fm: break
           in_fm = True; continue
       if in_fm and ':' in s:
           k, v = s.split(':', 1)
           fm[k.strip()] = v.strip()

   scope = ctx.get('scope', 'full')
   # Q-score attribution: read attributed_to (set by lifecycle-init.sh --embed and
   # by state-0 extra_json) so embedded verify runs (bootstrap-verify, change-verify)
   # record the parent skill in verify-history.jsonl. Falls back to physical skill
   # for legacy contexts pre-#941. Aligns reader with init-context.sh:73 design intent.
   skill = ctx.get('attributed_to') or ctx.get('skill', 'verify')
   dims = {}

   # Q_build (deterministic — from build attempts)
   dims['Q_build'] = round(1 - (int(fm.get('build_attempts', '1')) - 1) / 2, 3)

   # Extract per-agent dimension scores from traces
   for f in glob.glob('.runs/agent-traces/*.json'):
       name = os.path.basename(f).replace('.json', '')
       try:
           d = json.load(open(f))
       except:
           continue

       if name == 'security-fixer' and scope in ('full', 'security'):
           merged = {}
           try: merged = json.load(open('.runs/security-merge.json'))
           except: pass
           findings = merged.get('issues', [])
           if findings:
               weighted = sum(1.0 if i.get('severity','')=='Critical' else 0.5 if i.get('severity','')=='High' else 0.1 for i in findings)
           else:
               weighted = merged.get('merged_issues', 0)
           dims['Q_security'] = round(1 - min(weighted / 5, 1), 3)

       elif name == 'design-critic' and scope in ('full', 'visual'):
           # Coalesce explicit-null min_score to 10 (best-effort no-data;
           # aggregate_ok validates per-sibling). dict.get(k, default) returns
           # None for explicit-null values — would crash int division.
           ms = d.get('min_score')
           dims['Q_design'] = round((10 if ms is None else ms) / 10, 3)

       elif name == 'ux-journeyer' and scope in ('full', 'visual'):
           dims['Q_ux'] = round(1 - min(d.get('unresolved_dead_ends', 0) / 3, 1), 3)

       elif name == 'behavior-verifier' and scope in ('full', 'security'):
           tp = d.get('tests_passed', 0)
           tf = d.get('tests_failed', 0)
           dims['Q_behavior'] = round(tp / max(tp + tf, 1), 3)

       elif name == 'spec-reviewer' and scope in ('full', 'security'):
           dims['Q_spec'] = 1.0 if d.get('verdict', '').upper() == 'PASS' else 0.0

   # Gate: binary — build passes AND no hard gate failure
   gate = 0.0 if fm.get('hard_gate_failure', 'false') == 'true' else 1.0

   # R_system: 1 - mean(dimension scores) — measures auto-remediation
   active_dims = list(dims.values())
   r_system = round(1 - (sum(active_dims) / max(len(active_dims), 1)), 3)

   # R_human: (hard gate failures + exhaustions) / agents_expected — measures user intervention
   exhaustions = 0
   for f in glob.glob('.runs/agent-traces/*.json'):
       try:
           if json.load(open(f)).get('recovery', False): exhaustions += 1
       except: pass
   agents_expected_str = fm.get('agents_expected', '')
   agents_expected = len([a for a in agents_expected_str.split(',') if a.strip()]) if agents_expected_str else 1
   r_human = round((int(fm.get('hard_gate_failure','false')=='true') + exhaustions) / max(agents_expected, 1), 3)

   # R combined: 0.3 * R_system + 0.7 * R_human
   r = round(0.3 * r_system + 0.7 * r_human, 3)

   # Q_skill = Gate * (1 - R)
   q_skill = round(gate * (1 - r), 3)

   entry = {
       'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
       'run_id': ctx.get('run_id', ''),
       'skill': skill,
       'scope': scope,
       'archetype': ctx.get('archetype', ''),
       'build_attempts': int(fm.get('build_attempts', '1')),
       'fix_log_entries': int(fm.get('fix_log_entries', '0')),
       'hard_gate_failure': fm.get('hard_gate_failure', 'false') == 'true',
       'process_violation': fm.get('process_violation', 'false') == 'true',
       'overall_verdict': fm.get('overall_verdict', 'pass').strip(),
       'dimension_scores': dims,
       'gate': gate,
       'r_system': r_system,
       'r_human': r_human,
       'q_skill': q_skill,
   }

   # Write via shared script (see .claude/patterns/q-score.md Write Procedure)
   import subprocess, shlex
   subprocess.run(
       ['python3', '.claude/scripts/write-q-score.py', '--raw', json.dumps(entry)],
       capture_output=False
   )
   "
   ```

9. **Q-score observation trigger** (low-Q auto-observe):

   The `skill` variable above resolves to `attributed_to` first (parent skill for embedded runs) and falls back to physical `skill` for standalone runs. This means:
   - Standalone `/verify`: `skill == "verify"` → trigger does NOT fire (verify itself has no parent to attribute issues to).
   - Embedded `bootstrap-verify` / `change-verify`: `skill == "bootstrap"` / `"change"` (the parent) → trigger CAN fire.

   If `q_skill < 0.5` and `skill != "verify"` (i.e., this is an embedded run with low quality):

   File an observation to the template repo using `.claude/patterns/observe.md` **Path 3** (direct Q-score evaluation):
   - Title: `[observe] Low Q-score: <skill> Q=<q_skill>` (uses attributed parent skill for issue title)
   - Body: parent skill, Q-score breakdown (Gate, R_system, R_human, dimension_scores), timestamp, and the run's physical context (`physical_skill: "verify"`, `attributed_to: "<parent>"`) for cross-reference
   - Follow observe.md's Redaction, Dedup, and Issue Creation procedures (dedup keys on symptom + skill, so attribution-based labeling preserves pattern detection)

   This is a direct evaluation (like Path 2), not a callback to the observation epilogue. Do NOT spawn the observer agent.

**POSTCONDITIONS:**
- `verify-report.md` exists with valid frontmatter
- `verify-history.jsonl` has a new entry appended (via CALL: `.claude/scripts/write-q-score.py`)
- Cross-validation: `verify-history.jsonl` last entry's `dimension_scores` consistent with disk artifacts:
  - If `Q_build > 0` → `.runs/build-result.json` exists and `exit_code == 0`
  - If `Q_security > 0` → `.runs/agent-traces/security-*.json` exists
  - If `Q_design > 0` → `.runs/agent-traces/design-critic.json` exists
- Cross-validation: `hard_gate_failure` consistent with agent verdict traces:
  - If design-critic verdict is `unresolved` or recovery is `true` → `hard_gate_failure` must be `true` **UNLESS** the aggregate is sanctioned (every contributing per-page sibling is `provenance=self` with normal verdict OR `provenance=self-degraded` with `recovery_validated=true` and `degraded_reason ∈ {"demo-mode-fixture-short-circuit", "empty-boundary-fast-path"}`). The sanctioned-aggregate check is performed by `.claude/scripts/check-design-critic-sanctioned.py` (#1042 Sub-branch S1 + #1061 fast-path).
  - If ux-journeyer verdict is `blocked`, unresolved_dead_ends > 0, or recovery is `true` → `hard_gate_failure` must be `true`
  - If security-fixer verdict is `partial` with unresolved_critical > 0, or recovery is `true` → `hard_gate_failure` must be `true`
  - If quality-fixer verdict is `partial` with unresolved_critical > 0, or recovery is `true` → `hard_gate_failure` must be `true`

**VERIFY:**
```bash
head -1 .runs/verify-report.md | grep -q '^---$' && tail -1 .runs/verify-history.jsonl | python3 -c 'import json,sys,os,glob,subprocess; e=json.loads(sys.stdin.read()); ds=e.get("dimension_scores",{}); assert not(ds.get("Q_build",0)>0) or (os.path.exists(".runs/build-result.json") and json.load(open(".runs/build-result.json")).get("exit_code")==0), "Q_build>0 but build failed"; assert not(ds.get("Q_security",0)>0) or glob.glob(".runs/agent-traces/security-*.json"), "Q_security>0 but no security traces"; assert not(ds.get("Q_design",0)>0) or os.path.exists(".runs/agent-traces/design-critic.json"), "Q_design>0 but no design-critic trace"; hgf=e.get("hard_gate_failure",False)
def _dc_sanc(p):
    return p.endswith("design-critic.json") and subprocess.run(["python3",".claude/scripts/check-design-critic-sanctioned.py",p],capture_output=True).returncode==0
for p,vk,vv,ex in [(".runs/agent-traces/design-critic.json","verdict",["unresolved"],None),(".runs/agent-traces/ux-journeyer.json","verdict",["blocked"],[("unresolved_dead_ends",0)]),(".runs/agent-traces/security-fixer.json","verdict",["partial"],[("unresolved_critical",0)]),(".runs/agent-traces/quality-fixer.json","verdict",["partial"],[("unresolved_critical",0)])]:
    if not os.path.exists(p): continue
    t=json.load(open(p))
    n=t.get(vk) in vv or t.get("recovery",False) or any(t.get(ek,0)>ev for ek,ev in (ex or []))
    if not n: continue
    if _dc_sanc(p): continue
    if not hgf: raise AssertionError(p+" requires hard_gate_failure=true")'
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh verify 7b
```

**NEXT:** Read [state-8-save-patterns.md](state-8-save-patterns.md) to continue.
