# STATE 13: BUILD_VALIDATION

**PRECONDITIONS:**
- Externals done, BG2.5 PASS (STATE 12 POSTCONDITIONS met)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Primary unit".
> [primary-unit] web-app: page (`src/app/<page>/page.tsx`) | service: endpoint (`src/app/api/<ep>/route.ts`) | cli: command (`src/commands/<cmd>.ts`)
>
> State-specific logic below takes precedence.

Run build and artifact-existence verification:

1. **Build**: run `npm run build` -- the project must compile
2. **Page/endpoint/command existence:** Verify each behavior's primary artifact exists per archetype. (Per `patterns/archetype-behavior-check.md`: web-app=`src/app/<page>/page.tsx` + landing, service=handler per framework stack file, cli=`src/commands/<cmd>.ts`)

If any check fails: fix directly (budget: 2 fix attempts). Re-run the build after fixes.
If still failing after 2 attempts: list all remaining errors and their file locations. Ask the user whether to (a) continue and fix later, or (b) stop and investigate now.

Write intermediate artifact:
```bash
PAYLOAD=$(python3 -c "
import json
print(json.dumps({'build_pass': True, 'exit_code': 0, 'artifacts_verified': True}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/bootstrap-build-result.json \
  --payload "$PAYLOAD" \
  --skill bootstrap
```

**POSTCONDITIONS:**
- Build passes (exit code 0)
- All pages/endpoints/commands exist per archetype <!-- enforced by agent behavior, not VERIFY gate -->
- `.runs/bootstrap-build-result.json` written

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/bootstrap-build-result.json')); assert d['exit_code']==0, 'build exit_code=%d' % d['exit_code']"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 13
```

**NEXT:** Read [state-13a-analytics-design-check.md](state-13a-analytics-design-check.md) to continue.
