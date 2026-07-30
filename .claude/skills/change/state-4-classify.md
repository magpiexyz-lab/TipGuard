# STATE 4: CLASSIFY

**PRECONDITIONS:**
- Solve-reasoning complete (STATE 3 POSTCONDITIONS met)

**ACTIONS:**

Determine the type from `$ARGUMENTS`:

| Type      | Signal                                     |
|-----------|---------------------------------------------|
| Feature   | Adds capability that doesn't exist today    |
| Upgrade   | Replaces Fake Door or stub with real integration |
| Fix       | Repairs broken behavior                     |
| Polish    | Improves UX/copy/visuals of existing stuff  |
| Analytics | Fixes/audits analytics coverage             |
| Test      | Adds or fixes tests                         |

State the classification before proceeding: "I'm treating this as a **[type]** change."

Map the classification to a verification scope for Step 7:

| Type      | Verification Scope |
|-----------|--------------------|
| Feature   | `full`             |
| Upgrade   | `full`             |
| Fix       | `security`         |
| Polish    | `visual`           |
| Analytics | `build`            |
| Test      | `build`            |

State: "Verification scope: **[scope]**"

**POSTCONDITIONS:**
- Classification stated (one of: Feature, Upgrade, Fix, Polish, Analytics, Test)
- Verification scope stated (one of: full, security, visual, build)

**VERIFY:**
```bash
python3 -c "import json; ctx=json.load(open('.runs/change-context.json')); assert ctx.get('classification'), 'classification missing'"
```

**STATE TRACKING:** After postconditions pass, update context and mark this state complete:
```bash
PAYLOAD=$(python3 -c "
import json
ctx = json.load(open('.runs/change-context.json'))
ctx['classification'] = '<stated-classification>'
ctx['verification_scope'] = '<stated-scope>'
print(json.dumps(ctx))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/change-context.json \
  --payload "$PAYLOAD" \
  --skill change
bash .claude/scripts/advance-state.sh change 4
```

**NEXT:** Read [state-5-check-preconditions.md](state-5-check-preconditions.md) to continue.
