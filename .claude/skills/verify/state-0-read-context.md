# STATE 0: READ_CONTEXT

**PRECONDITIONS:** None — this is the entry state.

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app/service/cli: read archetype + scope into context for downstream agent gating

1. **Bootstrap consistency check** (runs in all modes — standalone, bootstrap-verify, change-verify, and any other skill that embeds /verify):
   Assert that the project is bootstrapped AND that `PROJECT_NAME` in `src/lib/analytics.ts` / `analytics-server.ts` (when present) equals `experiment.yaml.name`:
   ```bash
   test -f package.json && test -f experiment/experiment.yaml \
     && python3 .claude/scripts/lib/check_project_name.py
   ```
   If any assertion fails, **STOP** with the underlying error:
   - Missing files → "No bootstrapped app found. Run `/bootstrap` first to scaffold the project from experiment.yaml."
   - PROJECT_NAME drift → quote `check_project_name.py` stderr verbatim (it names every offending file and the expected value). Fix the constant in `src/lib/analytics.ts` (and `analytics-server.ts` if applicable) to match `experiment.yaml.name`. If the rename was intentional and you instead want to update the yaml, note that changing `experiment.yaml.name` after deploys exist will fork PostHog identity — past data won't roll over to the new name.

   This check runs unconditionally to cover **all** entry points: /bootstrap state-13a + state-13c gate-keeper enforce at bootstrap time, but `/change-verify`, `/resolve-verify`, `/review-verify`, and any other skill that embeds /verify do **not** reach state-13a. The check is fast (<100ms) and idempotent — defense-in-depth across the lifecycle. (Bootstrap-verify will run this once at /bootstrap state-13a and again here at /verify state-0; the cost is negligible, the safety is significant — same defense-in-depth pattern as state-13a + state-13c gate-keeper.)

2. Ensure trace directory exists (stale traces cleaned by lifecycle-init.sh):
   ```bash
   mkdir -p .runs/agent-traces
   ```

3. Read context files:
   - Read `experiment/experiment.yaml` — understand pages (via `derive_scope_pages()` canonical SET, sourced from `golden_path` + `behaviors[*].pages` + auth), behaviors, stack
   - Read `experiment/EVENTS.yaml` — understand tracked events
   - Read the archetype file at `.claude/archetypes/<type>.md` (type from experiment.yaml, default `web-app`)
   - If in bootstrap-verify or change-verify mode: read all files listed in current-plan.md `context_files`
   - If `stack.testing` is present in experiment.yaml, read `.claude/stacks/testing/<value>.md`

4. Determine skill name:
   - If `.runs/current-plan.md` exists with a `skill:` field in its frontmatter → use that value (e.g., `"bootstrap"`, `"change"`)
   - Otherwise → use `"verify"` (standalone mode)

5. Read previous verify baseline (if available), filtered by current skill:
   ```bash
   BASELINE_AVAILABLE=false
   if [[ -f .runs/verify-history.jsonl ]]; then
     PREV_RUN=$(python3 -c "
   import json
   skill='<skill from step 4>'
   entries=[json.loads(l) for l in open('.runs/verify-history.jsonl') if l.strip()]
   matching=[e for e in entries if e.get('skill','')==skill]
   print(json.dumps(matching[-1]) if matching else '')
   " 2>/dev/null || echo "")
     if [[ -n "$PREV_RUN" ]]; then
       BASELINE_AVAILABLE=true
     fi
   fi
   ```

6. Merge verify-specific fields into context via shared init script. Extra fields override base: `attributed_to` attributes Q-scores to the calling skill (per #941 design — `skill` is the immutable physical running skill, always `"verify"` here, see `init-context.sh:73`), `scope`/`archetype`/`quality` drive agent gating, `mode` controls PR gate behavior, `baseline_available` enables delta reporting. Base fields (`branch`, `timestamp`, `run_id`, `skill`, `completed_states`) are already set by lifecycle-init.sh and are immutable here:
   ```bash
   bash .claude/scripts/init-context.sh verify "{\"attributed_to\":\"<skill from step 4>\",\"scope\":\"<scope>\",\"archetype\":\"<type>\",\"quality\":\"production\",\"mode\":\"<standalone if skill is verify, otherwise the skill name + -verify e.g. bootstrap-verify, change-verify>\",\"baseline_available\":$BASELINE_AVAILABLE}"
   ```

7. Create `.runs/fix-log.md` on disk:
   ```bash
   echo '# Error Fix Log' > .runs/fix-log.md
   ```

8. Extract context digest (in-memory, passed to agents in STATE 2/3):
   - Pages: canonical SET inventory via `derive_scope_pages()` — run `python3 .claude/scripts/lib/derive_pages.py scope < experiment/experiment.yaml` (unions `golden_path[*].page`, `behaviors[*].pages`, and auth-derived pages). Cross-reference with filesystem scan of `src/app/**/page.tsx` to detect orphans; missing pages from the canonical set indicate a #1024-class scope mismatch to surface in STATE 2/3 agent prompts.
   - Behavior IDs: list all behavior IDs from `behaviors`
   - Event names: list event names from `experiment/EVENTS.yaml`
   - Source file list: `find src/ -type f \( -name '*.ts' -o -name '*.tsx' \) | head -100`
   - PR changed files: `git diff --name-only $(git merge-base HEAD main)...HEAD`
   - Golden path steps: ordered list of funnel steps via `python3 .claude/scripts/lib/derive_pages.py funnel < experiment/experiment.yaml` (used for LIST-semantic consumers like funnel tests and step-by-step assertions).

**POSTCONDITIONS:** All 4 artifacts exist on disk (agent-traces dir, verify-context.json with `attributed_to` field, fix-log.md). Context digest is available in-memory. If `verify-history.jsonl` has a previous entry matching the current skill, baseline data is available for STATE 7 delta reporting.

**VERIFY:**
```bash
test -f .runs/verify-context.json && test -f .runs/fix-log.md && test -d .runs/agent-traces && python3 -c "import json; assert json.load(open('.runs/verify-context.json')).get('attributed_to'), 'attributed_to field empty in verify-context.json'"
```

> **Hook-enforced:** `skill-agent-gate.sh` validates these postconditions before allowing the next state's agents to spawn.

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh verify 0
```

**NEXT:** Read [state-1-build-lint-loop.md](state-1-build-lint-loop.md) to continue.
