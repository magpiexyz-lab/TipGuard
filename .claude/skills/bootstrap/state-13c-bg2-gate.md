# STATE 13c: BG2_GATE

**PRECONDITIONS:**
- Content and SEO checks pass (STATE 13b POSTCONDITIONS met)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, rows "Primary unit", "Favicon + OG image check".
> [primary-unit] web-app: page (`src/app/<page>/page.tsx`) | service: endpoint (`src/app/api/<ep>/route.ts`) | cli: command (`src/commands/<cmd>.ts`)
> [favicon-og] web-app: verify icon.tsx + opengraph-image.tsx | service: skip | cli: skip
>
> State-specific logic below takes precedence.

Follow gate execution procedure per `procedures/gate-execution.md`.

Spawn the `gate-keeper` agent (`subagent_type: gate-keeper`). Pass: "Execute BG2 Orchestration Gate (PRE-WIRE scope). Verify: pre-wire scaffold output. (1) .runs/bootstrap-build-result.json exists and exit_code == 0; (2) scaffold-libs/init/pages/landing output files exist (src/lib/*.ts, .runs/current-visual-brief.md, src/app/icon.tsx and src/app/opengraph-image.tsx (web-app only), src/app/layout.tsx and golden_path pages (web-app only)); (3) landing page exists if surface!=none; (4) checkpoint is phase2-scaffold or later; (5) if stack.analytics present: for each event in experiment/EVENTS.yaml events map (filtered by requires and archetypes for current stack and archetype), grep for the event name in src/ -- BLOCK if any event is missing; (6) if stack.analytics present: run `python3 .claude/scripts/lib/check_project_name.py` -- BLOCK on non-zero exit (catches PROJECT_NAME drift from experiment.yaml.name AND unreplaced 'TODO' in PROJECT_NAME). Additionally grep src/lib/analytics*.ts for PROJECT_OWNER -- BLOCK if 'TODO'. Wire-produced artifacts (nav-bar marker, src/app/api/ routes, post-wire build, full href coverage, wire trace) are deferred to BG2-WIRE Post-Wire Gate at state-14a."

> **Note:** Analytics checks (5) and (6) overlap with STATE 13a step 3. This is intentional
> defense-in-depth — gate-keeper is an independent agent that re-validates from scratch,
> catching regressions introduced by fixes in states 13a-13b.

If gate-keeper returns BLOCK, fix missing outputs before proceeding.

Check off in `.runs/current-plan.md`: `- [x] BG2 Orchestration Gate passed`

**POSTCONDITIONS:**
- BG2 Orchestration Gate verdict is PASS

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/gate-verdicts/bg2.json')); assert d.get('verdict')=='PASS', 'BG2 verdict is %s' % d.get('verdict'); assert d.get('timestamp','')!='', 'timestamp empty'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 13c
```

**NEXT:** Read [state-14-wire-phase.md](state-14-wire-phase.md) to continue.
