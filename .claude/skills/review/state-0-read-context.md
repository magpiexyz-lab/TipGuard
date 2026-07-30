# STATE 0: READ_CONTEXT

**PRECONDITIONS:**
- Git repository exists in working directory
- Current branch is `main` (or resuming on existing `chore/review-fixes*` branch)

**ACTIONS:**

- Read `CLAUDE.md`
- Read `experiment/EVENTS.yaml`
- Read `scripts/check-inventory.md`
- Read `experiment/experiment.example.yaml` (for understanding template structure)
- **Check open observation issues** (use current repo via `gh`):
  ```bash
  gh issue list --label observation --state open --limit 10 --json number,title,body
  ```
  If any open issues exist, save them as `observation_backlog`. These will be
  used as additional input in Step 2a below. If none exist or the command fails,
  set `observation_backlog` to empty and continue.
- **Read prior review precision** (use current repo via `gh`):
  ```bash
  gh pr list --state merged --search "Automated review-fix" --limit 1 --json number,body
  ```
  If found, extract the Precision Summary. Store as `prior_precision`.
  Use prior precision to coach each dimension's agent in Step 2a:
  - If `disputed_rate` > 30%: add to prompt: "Prior review had high dispute rate — only report findings where the contradiction cannot be resolved by reading surrounding context."
  - If `skipped_rate` > 20%: add to prompt: "Prior review had many unfixable findings — focus on findings directly fixable in a single PR."
  - If `reverted_rate` > 20%: add to prompt: "Prior review had fixes that caused regressions — be conservative with fixes that touch cross-file invariants."
  - **Per-dimension budget allocation** (from `prior_precision`):
    Extract per-dimension precision from the Precision Summary (A, B, C rates).
    Set `max_findings` per dimension:
    - precision >= 60%: `max_findings_per_dimension` (full budget)
    - precision 30-59%: `ceil(max_findings_per_dimension * 0.6)` (reduced)
    - precision < 30%: 2 (minimum floor)
    - If no per-dimension data available: use uniform `max_findings_per_dimension`
    The total findings budget shifts toward dimensions that produce real fixes.
  If not found or command fails, set `prior_precision` to empty and continue.
- **Compute observation hot spots** (from `observation_backlog`):
  Count observations per template file path. Files with 3+ open observations
  are "hot spots." Pass to each dimension agent in Step 2a:
  > These template files have 3+ open observations — scan them with extra
  > scrutiny: [list of hot spot file paths]
  If no hot spots, skip this instruction.

**POSTCONDITIONS:**
- `CLAUDE.md`, `experiment/EVENTS.yaml`, `scripts/check-inventory.md`, `experiment/experiment.example.yaml` have been read <!-- enforced by agent behavior, not VERIFY gate -->
- `observation_backlog` is set (possibly empty) <!-- enforced by agent behavior, not VERIFY gate -->
- `prior_precision` is set (possibly empty) <!-- enforced by agent behavior, not VERIFY gate -->
- Observation hot spots computed (possibly none) <!-- enforced by agent behavior, not VERIFY gate -->
- `.runs/review-context.json` exists with state tracking initialized

**VERIFY:**
```bash
test -f .runs/review-context.json && python3 -c "import json,glob; d=json.load(open('.runs/review-context.json')); ctx=None
for f in glob.glob('.runs/*-context.json'):
    if 'epilogue' in f: continue
    try: c=json.load(open(f))
    except: continue
    if c.get('completed') is True: continue
    if ctx is None or (c.get('timestamp','') > (ctx.get('timestamp','') or '')): ctx=c
active_skill=ctx.get('skill','') if ctx else ''
active_run_id=ctx.get('run_id','') if ctx else ''
assert d.get('skill') == active_skill, 'review-context.json skill=%r does not match active_skill=%r (stale prior-skill artifact)' % (d.get('skill'), active_skill)
assert d.get('run_id') == active_run_id, 'review-context.json run_id=%r does not match active_run_id=%r (stale artifact)' % (d.get('run_id'), active_run_id)"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh review 0
```

**NEXT:** Read [state-1-baseline-validators.md](state-1-baseline-validators.md) to continue.
