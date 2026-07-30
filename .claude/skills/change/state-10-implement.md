# STATE 10: IMPLEMENT

**PRECONDITIONS:**
- Specs updated (STATE 9 POSTCONDITIONS met)
- Checkpoint is `phase2-step6`

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.

Follow archetype behavior check per `patterns/archetype-behavior-check.md`.

#### Feature constraints
Follow the procedure in `.claude/procedures/change-feature.md`.

> **Critical assertions (Feature):**
> - You MUST spawn implementer agents. Do NOT implement tasks directly.
> - Write the failing test (RED) BEFORE writing production code (GREEN).
> - Analytics events MUST be wired before proceeding to Step 7.

#### Upgrade constraints
Follow the procedure in `.claude/procedures/change-upgrade.md`.

> **Critical assertions (Upgrade):**
> - TDD tasks required for credential storage, webhook validation, error handling.
> - You MUST spawn implementer agents. Do NOT implement tasks directly.
> - Preserve the `activate` event name when replacing Fake Door — remove `fake_door: true` only.

#### Fix constraints
Follow the procedure in `.claude/procedures/change-fix.md`.

> **Critical assertions (Fix):**
> - Regression test must FAIL on current code BEFORE writing the fix. Stop and write the test first. Run it — it must fail. Only then implement the fix and verify the test passes.
> - Minimal change only — fix root cause, no refactoring of surrounding code.

#### Polish constraints
- No new features, pages, routes, or libraries
- **Visual capability**: If the change modifies `.tsx` page or component files, load the `frontend-design` skill before implementing. Read `.claude/patterns/design.md` for quality invariants and `src/app/globals.css` for theme tokens. Visual quality is built in during implementation, not fixed after by design-critic.
- Copywriting: follow the copy derivation rules in `.claude/patterns/messaging.md` — headline = outcome for target_user, CTA = action verb + outcome. If the archetype includes a landing page (web-app): landing page must include all content inventory from messaging.md Section B. When experiment.yaml has `variants`, variant messaging fields (`headline`, `subheadline`, `cta`, `pain_points`) override Section A derivation — see messaging.md Section D.
- If the change modifies experiment.yaml `behaviors`, `name`, or `description` AND surface ≠ none: regenerate the surface to reflect the updated content per archetype. (Per `patterns/archetype-behavior-check.md`: web-app=landing page, service=root route or `site/index.html`, cli=`site/index.html`) Re-invoke `frontend-design` for the surface if the visual direction changed. Surface includes layout.tsx `metadata` exports and `public/llms.txt` — regenerate these alongside the landing page using messaging.md Section E derivation rules.
- Visual design: follow `.claude/patterns/design.md` quality invariants. Read existing pages and maintain visual consistency with the established design direction.
- Remove anything that doesn't serve conversion. Keep above-the-fold to: headline, subheadline, CTA.
- Count steps between CTA click and first value moment — remove or defer unnecessary fields
- Every required field: inline validation errors. Every async button: loading state. API errors: user-friendly messages.
- Spacing, hierarchy, and responsive layout must be visually consistent with existing pages
- Preserve all existing analytics events

#### Analytics constraints
- Fix gaps per the audit: add missing tracking calls with all required properties, add missing properties to incomplete calls
- Do NOT change event names — they must match experiment/EVENTS.yaml exactly
- Do NOT remove existing correct analytics calls
- Only add new events the user explicitly approved
- If archetype is `cli`: all `trackServerEvent()` calls must be wrapped in the `isAnalyticsEnabled()` consent guard per the analytics stack file's CLI Opt-In Consent section. CLI telemetry must be opt-in — see CLAUDE.md Rule 2.

#### Test constraints
Follow the procedure in `.claude/procedures/change-test.md`.

> **CHECKPOINT — VERIFICATION GATE**
> Implementation is complete. You MUST now execute Step 7 in full.
> Re-read `.claude/patterns/verify.md` and follow every section applicable to the verification scope from Step 3:
> build loop, scoped parallel review, security fix cycle (if applicable), auto-observe.
> Re-read `.runs/current-plan.md` `## Process Checklist`. Every listed agent MUST be spawned per the scope table. Do NOT skip agents based on which files changed — scope determines spawning.
> **Step 8 is BLOCKED until Step 7 completes.**
> Do NOT commit, push, or open a PR before verification finishes.
>
> **Critical assertions (Verification):**
> - If scope is `full` or `security` — security-defender + security-attacker MUST be spawned.
> - If scope is `full` or `security` — spec-reviewer MUST be spawned.
> - `.runs/verify-report.md` MUST be written before Step 8.

- **Implementer trace audit** (informational — does not block G4):
  ```bash
  python3 -c "
  import json, glob
  traces = glob.glob('.runs/agent-traces/implementer-*.json')
  if not traces:
      print('No implementer traces found')
  else:
      results = {'complete': 0, 'blocked': 0, 'other': 0}
      for f in traces:
          try:
              d = json.load(open(f))
              s = d.get('status', 'other')
              if s == 'complete': results['complete'] += 1
              elif s.startswith('blocked'): results['blocked'] += 1
              else: results['other'] += 1
          except: results['other'] += 1
      merged = sum(1 for f in traces if json.load(open(f)).get('worktree_merged', False))
      print(f'Implementer audit: {results[\"complete\"]} complete, {results[\"blocked\"]} blocked, {merged} merged, {len(traces)} total')
  "
  ```

- **G4 Implementation Gate**: Spawn the `gate-keeper` agent (`subagent_type: gate-keeper`). Pass: "Execute G4 Implementation Gate. Verify: `npm run build` passes. Check git log for worktree merge commits (evidence implementer agents were spawned, not direct implementation). Check no `// TODO: implement` or `throw new Error('not implemented')` markers in new code." If gate-keeper returns BLOCK, fix blocking items before Step 7.

Update checkpoint in `.runs/current-plan.md` frontmatter to `phase2-step7`.

**POSTCONDITIONS:**
- Implementation complete per type-specific constraints
- Implementer trace audit run
- G4 Implementation Gate passed
- Checkpoint updated to `phase2-step7`
- All complete implementer traces have `worktree_merged: true`
- If 2+ implementer traces exist: `.runs/consistency-scan-result.json` exists

**VERIFY:**
```bash
grep -q 'checkpoint: phase2-step7' .runs/current-plan.md && python3 -c "import json,glob,os; ts=glob.glob('.runs/agent-traces/implementer-*.json')+glob.glob('.runs/agent-traces/visual-implementer-*.json'); bad=[t for t in ts if json.load(open(t)).get('status')=='completed' and not json.load(open(t)).get('worktree_merged')]; assert not bad,'Unmerged: '+','.join(bad); assert not(len(ts)>=2 and not os.path.exists('.runs/consistency-scan-result.json')),'2+ implementers but no consistency-scan-result.json'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh change 10
```

**NEXT:** Read [state-11a-verify-prep.md](state-11a-verify-prep.md) to continue.
