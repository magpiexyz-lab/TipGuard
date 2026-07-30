# STATE 2b: SLOT_INTENT_DRIFT_DETECTION

**PRECONDITIONS:** STATE 2a complete. `.runs/page-image-map.json` and
`.runs/design-page-set.json` exist (state-2a postconditions). Optional:
`.runs/slot-intent.json` (written by scaffold-init in PR1b). When the
slot-intent file is absent OR `design_slots_enabled == false`, this state
short-circuits with `not_applicable=true` (legacy projects pre-PR1b or
soft-launch projects with the flag off).

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Visual agents".
> [visual-agents] web-app: design-critic, ux-journeyer, consistency-checker | service: skip | cli: skip

Run the slot-intent drift detector to compare declared `intended_render`
(from `.runs/slot-intent.json`) against observed JSX in `src/` (Issue
#1077, PR3). Asymmetric severity table:

  - `slot_role=focal × observed_weight < 0.5` → **BLOCK** (catches the
    4 named cases in #1077)
  - `slot_role=texture × observed_weight > 0.5` → **WARN** (preserves
    design iteration ergonomics)
  - `slot_role=watermark × outside [0.3, 0.9]` → **WARN**
  - `slot_role=conditional × any` → **INFO** (runtime-gated)
  - `slot_role=none × image present in JSX` → **BLOCK**
  - `production_method=dynamic_runtime × image present in JSX` → **BLOCK**
  - any × `effective_weight=null` (clsx/cva unresolvable) → **INFO**

Boundary-skip handling: when state-2a wrote `not_applicable=true` (non
web-app archetype OR scope mismatch), state-2b short-circuits with the
same `not_applicable=true` semantics — drift detection cannot run when
no image pipeline runs (closes Round 2 critic Concern 4).

```bash
python3 .claude/scripts/check-slot-intent-drift.py \
  --slot-intent .runs/slot-intent.json \
  --src-root src \
  --output .runs/drift-report.json \
  --page-image-map .runs/page-image-map.json
```

**POSTCONDITIONS:**

- `.runs/drift-report.json` exists with valid schema:
  `{_schema_version, _kind: "slot-intent-drift-report", generated_at,
  block_count, warn_count, info_count, pass_count, findings: [...]}`
  OR `{not_applicable: true, skip_reason}`.
- `block_count == 0` (or `not_applicable=true`).

**VERIFY:**
```bash
python3 -c "import json,os; d=json.load(open('.runs/drift-report.json')); assert d.get('not_applicable') or d.get('block_count',0)==0, 'drift detected: %s' % [f for f in d.get('findings',[]) if f.get('severity')=='BLOCK']"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh verify 2b
```

**NEXT:** Read [state-3a-design-agents.md](state-3a-design-agents.md) to continue.
