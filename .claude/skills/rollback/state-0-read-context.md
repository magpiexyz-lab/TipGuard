# STATE 0: READ_CONTEXT


<!-- archetype-reference-only: REF .claude/patterns/archetype-behavior-check.md — Reads archetype into context for state-3-execute branching. -->

**PRECONDITIONS:**
- Git repository exists in working directory

**ACTIONS:**

Read these context files:
- Read `.runs/deploy-manifest.json` and extract:
  - `hosting.provider` -- the hosting provider
  - `canonical_url` -- the production URL
- If the file is missing or `hosting` is absent, STOP: "No deploy manifest found. Has this project been deployed with `/deploy`?"

Read the hosting stack file at `.claude/stacks/hosting/<provider>.md`, specifically the `### Rollback` subsection under `## Deploy Interface`.

If no `### Rollback` subsection exists, STOP: "Rollback procedure not documented for this hosting provider. See `.claude/patterns/incident-response.md` for manual recovery steps."

Read `experiment/experiment.yaml` to determine the archetype (`type` field, default: `web-app`).

**POSTCONDITIONS:**
- `.runs/deploy-manifest.json` has been read and `hosting.provider` and `canonical_url` extracted
- Hosting stack file has been read and rollback procedure identified
- `experiment/experiment.yaml` has been read for archetype
- `.runs/rollback-context.json` exists

**VERIFY:**
```bash
test -f .runs/rollback-context.json
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh rollback 0
```

**NEXT:** Read [state-1-plan.md](state-1-plan.md) to continue.
