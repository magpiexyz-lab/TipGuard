# STATE 9: UPDATE_SPECS

**PRECONDITIONS:**
- Phase 2 pre-flight complete (STATE 8 POSTCONDITIONS met)
- `## Process Checklist` exists in `.runs/current-plan.md`
- Checkpoint is `phase2-step5`

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Spec field".
> [spec-field] web-app: `golden_path` | service: `endpoints` | cli: `commands`
>
> State-specific logic below takes precedence.

> **Gate check:** Read `.runs/current-plan.md` and look for `## Process Checklist`.
> If missing, STOP — execute the Phase 2 Pre-flight above first.

- **Feature**: add the new behavior to experiment.yaml `behaviors` list. If the new behavior changes the user journey, update the archetype-specific journey field per the archetype routing in `.claude/patterns/archetype-behavior-check.md`. Do NOT remove or modify existing behaviors.
- **Upgrade**: do NOT modify experiment.yaml `behaviors` (the behavior already exists — it was listed when the Fake Door was created). Add new env vars to `.env.example`.
- **Analytics**: if the user approved new events, add them to the `events` map in experiment/EVENTS.yaml with appropriate `funnel_stage`, following the `<object>_<action>` naming convention with all properties.
- **Fix / Polish**: do NOT modify experiment.yaml or experiment/EVENTS.yaml.
- **Test**: do NOT modify experiment/EVENTS.yaml. If adding tests for the first time (no `stack.testing` in experiment.yaml and no `playwright.config.ts` on disk), add `testing: <value>` to experiment.yaml `stack` section. Do not modify other parts of experiment.yaml.

Update checkpoint in `.runs/current-plan.md` frontmatter to `phase2-step6`.

> **Checkpoint update:** Edit only the `checkpoint:` line in the frontmatter — single-line edit, not a full file rewrite.

**POSTCONDITIONS:**
- Specs updated per type-specific rules
- Checkpoint updated to `phase2-step6`
- If type is Feature: behavior IDs exist in `experiment/experiment.yaml`

**VERIFY:**
```bash
grep -q 'checkpoint: phase2-step6' .runs/current-plan.md && python3 -c "import json; pt=json.load(open('.runs/change-context.json')).get('preliminary_type',''); assert pt!='Feature' or '  - id:' in open('experiment/experiment.yaml').read(), 'Feature requires behaviors'" && python3 .claude/scripts/validate-behavior-pages.py --diff-vs-main
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh change 9
```

**NEXT:** Read [state-10-implement.md](state-10-implement.md) to continue.
