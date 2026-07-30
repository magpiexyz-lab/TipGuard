# STATE 11a: VERIFY_PREP

**PRECONDITIONS:**
- Implementation complete (STATE 10 POSTCONDITIONS met)
- Checkpoint is `phase2-step7`

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Primary unit".
> [primary-unit] web-app: page (`src/app/<page>/page.tsx`) | service: endpoint (`src/app/api/<ep>/route.ts`) | cli: command (`src/commands/<cmd>.ts`)
>
> State-specific logic below takes precedence.

- Re-read `.runs/current-plan.md` to verify implementation matches the approved plan. Check that every item in the plan has been addressed.
- Type-specific checks:
  - **Feature**: trace the user flow — can a user discover, use, and complete the feature? Verify all new analytics events fire.
  - **Fix**: trace the bug report's user flow through code to confirm it's fixed.
  - **Polish**: open each changed file and confirm analytics imports and event calls are intact.
  - **Analytics**: re-trace each funnel event through the code to confirm it now fires correctly.
  - **Production quality**: verify.md spawns spec-reviewer in addition to scope-determined agents. Pass experiment.yaml + `.runs/current-plan.md` to spec-reviewer.
  - **Test**: verify test discovery works by running the testing stack file's test command in dry-run/list mode (e.g., `npx playwright test --list` for Playwright, `npx vitest run --reporter=verbose` for Vitest). If test discovery fails, treat it as a build error — fix the test files and re-run. If still failing after the verify.md retry budget, report to the user with the error output.
  - **Feature (spec compliance)**: Re-read `.runs/current-plan.md` and `experiment/experiment.yaml`. Verify implementation matches the archetype's primary units:
    - If archetype requires pages: enumerate via `python3 .claude/scripts/lib/derive_pages.py scope < experiment/experiment.yaml` and confirm `src/app/<page-name>/page.tsx` exists for each returned page. The canonical set includes `behaviors[*].pages` — #1024 scope fix.
    - If archetype requires `endpoints`: confirm API route exists for each endpoint in experiment.yaml `endpoints` (path depends on framework stack file)
    - If archetype requires `commands` (cli): confirm `src/commands/<command-name>.ts` exists for each entry in the experiment.yaml command list
    - For each behavior in `behaviors`, confirm the implementation addresses it. For each event in `experiment/EVENTS.yaml`, confirm tracking calls are intact. If anything is missing, fix it before proceeding.
  - **Fix (skill deficiency attribution)**: After confirming the fix works (above), analyze which upstream skill should have prevented this bug:
    1. Read `.claude/patterns/skill-coverage-map.md`
    2. Classify the defect from the actual fix diff (`git diff --name-only $(git merge-base HEAD main)...HEAD`) and `.runs/fix-log.md` (if exists). Use verifier taxonomy codes (B1-B6, D1-D6, A1-A5, S1-S8). Priority: D/A > B > S. If ambiguous, use "unclassified"
    3. Look up the coverage map: which skill(s) + state(s) should prevent this defect category
    4. Check `.runs/verify-history.jsonl` for execution history — only attribute to skills that actually ran. If file doesn't exist, note "execution history unavailable"
    5. Write optional fields to `.runs/change-context.json`:
       - `defect_category`: string (e.g. "D3") or "unclassified"
       - `skill_deficiency`: array of `{"skill": "<name>", "state": "<N>", "reason": "<why>"}` or null if unclassified
       - `attribution_confidence`: "high" (category clear + skill ran), "medium" (category clear + no history), "low" (unclassified)
    Conservative attribution: only attribute to skills whose coverage map entry explicitly includes the defect category. When uncertain, set `skill_deficiency` to null.

Update checkpoint in `.runs/current-plan.md` frontmatter to `phase2-step8`.

**POSTCONDITIONS:**
- Type-specific checks passed
- Implementation matches approved plan
- If type is Fix: `defect_category` field present in change-context.json (may be "unclassified")
- Checkpoint updated to `phase2-step8`

**VERIFY:**
```bash
grep -q 'checkpoint: phase2-step8' .runs/current-plan.md
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh change 11a
```

**NEXT:** Read [state-11b-verify-embed.md](state-11b-verify-embed.md) to continue.
