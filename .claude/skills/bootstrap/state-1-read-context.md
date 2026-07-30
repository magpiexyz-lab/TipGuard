# STATE 1: READ_CONTEXT

**PRECONDITIONS:**
- On `feat/bootstrap*` branch (STATE 0 POSTCONDITIONS met)

**ACTIONS:**

DO NOT write any code, create any files, or run any install commands during States 1-7.

Read these two context files:
- Read `experiment/experiment.yaml` — this is the single source of truth
- Read `experiment/EVENTS.yaml` — these are the canonical analytics events to wire up

**POSTCONDITIONS:**
- Both files have been read: `experiment/experiment.yaml`, `experiment/EVENTS.yaml`
- Their contents are in context for subsequent states

**VERIFY:**
```bash
test -f experiment/experiment.yaml && grep -q 'name:' experiment/experiment.yaml && test -f experiment/EVENTS.yaml && grep -q 'events:' experiment/EVENTS.yaml
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 1
```

**NEXT:** Read [state-2-resolve-archetype.md](state-2-resolve-archetype.md) to continue.
