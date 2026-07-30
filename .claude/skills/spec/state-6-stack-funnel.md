# STATE 6: STACK_FUNNEL

**PRECONDITIONS:**
- Variants approved (STATE 5 POSTCONDITIONS met)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
>
> State-specific logic below takes precedence.

## Step 6: Assemble experiment.yaml

Build the complete experiment.yaml with these 7 sections:

### Section 1 — Identity
```yaml
name: <slugified-name>
owner: <team-or-user-slug>       # Derive from `gh repo view --json owner --jq '.owner.login'`, or ask user
type: web-app                    # web-app | service | cli
level: <selected level>
status: draft
quality: production              # Always active. TDD and spec-reviewer enabled.
```

### Section 2 — Intent
```yaml
description: |
  <2-3 sentences, refined from idea + research>

thesis: "<If [action], then [outcome], as measured by [metric]>"
target_user: "<Specific ICP>"

distribution: |
  <Channels from reach hypotheses>

hypotheses:
  <all from Step 3>
```
- `description` merges problem + solution into one field
- `thesis` is required
- `hypotheses` are inline under Intent

### Section 3 — Behaviors
```yaml
behaviors:
  <all from Step 4, with tests[] and optional actor/trigger>
```

### Section 4 — Journey
The golden_path and endpoints/commands from Step 4 (state-4-golden-path).

### Section 5 — Variants

**If type is `web-app`:**
```yaml
variants:
  <all from Step 5>
```

**If type is `service` or `cli`:** Omit the `variants` section entirely — variants (A/B landing page testing) are only supported for the web-app archetype.

### Section 6 — Funnel
Dimension thresholds are derived from the highest-priority hypothesis in each category (no per-dimension metric/threshold fields in the funnel itself).
```yaml
funnel:
  available_from:
    reach: L1
    demand: L1
    activate: L2
    monetize: L2
    retain: L3
  decision_framework:
    scale: "All tested dimensions >= 1.0"
    kill: "Any top-funnel (REACH or DEMAND) < 0.5"
    pivot: "2+ dimensions < 0.8"
    refine: "1+ dimensions < 1.0 but fewer than 2 below 0.8"
```

### Section 7 — Stack + Deploy
Stack is deterministic from level and archetype:

**If type is `web-app`:**

Level 1:
```yaml
stack:
  services:
    - name: app
      runtime: nextjs
      hosting: vercel
      ui: shadcn
      testing: playwright
  analytics: posthog
deploy:
  url: null
  repo: null
```

Level 2: Level 1 + `database: supabase`

Level 3: Level 2 + `auth: supabase` (and `payment: stripe` if monetize hypotheses exist)

**If type is `service`:**

Level 1:
```yaml
stack:
  services:
    - name: app
      runtime: hono
      hosting: railway
      testing: vitest
  analytics: posthog
deploy:
  url: null
  repo: null
```

Level 2: Level 1 + `database: supabase`

Level 3: Level 2 + `auth: supabase` (and `payment: stripe` if monetize hypotheses exist)

**If type is `cli`:**

Level 1:
```yaml
stack:
  services:
    - name: app
      runtime: commander
      testing: vitest
  analytics: posthog
deploy:
  url: null
  repo: null
```

Level 2: Level 1 + `database: sqlite`

Level 3: Level 2 (cli excludes auth and payment per archetype definition)

### Section 8 — Events (EVENTS.yaml)

Derive project-specific analytics events from golden_path, behaviors, and hypothesis formulas. There are NO standard/template events — every project defines its own events. `funnel_stage` is the only cross-MVP standardization layer.

**Derivation algorithm:**

1. **From golden_path**: each step's `event:` field → one event entry
2. **From hypothesis formulas**: extract all event names referenced in `metric.formula` fields (e.g., `user_signup / landing_view` → `user_signup`, `landing_view`). Ensure each appears in the event set.
3. **From behaviors**: scan `then` clauses for additional observable actions not yet covered. Derive event names using `<object>_<action>` snake_case convention.
4. **Assign funnel_stage**: derive from the hypothesis category that references each event (reach → reach, demand → demand, etc.). If an event is referenced by multiple hypotheses, use the earlier funnel stage.
5. **Assign trigger**: derive from the behavior's `then` clause or golden_path step description.
6. **Variant property**: if the experiment has `variants` and the first golden_path event is a landing page event, add a `variant` property (type: string, required: false) to that event.
7. **Payment events**: if `stack.payment` is present, derive payment-related events from monetize hypotheses and behaviors. Add `requires: [payment]` to those events.
8. **Archetype-specific events**: if type is `service`, add `archetypes: [service]` to API-specific events. If `cli`, add `archetypes: [cli]` to command-specific events.
9. **Stack-emitted events** (#1447): iterate every active stack file and read its frontmatter `emits_events:` list (a new optional list field — absent or empty means the stack fires no analytics events from its own template code). Active stacks come from:
   - Shared categories: `stack.{database,auth,analytics,payment,email,ai,notifications,telephony,voice,project-management}` → `.claude/stacks/<category>/<value>.md`
   - Per-service: for each `stack.services[]`, the keys `runtime`, `hosting`, `ui`, `testing` resolve to stack files under `.claude/stacks/<category>/<value>.md` using the canonical category mapping per CLAUDE.md Rule 3 (`runtime`→`framework/`, `hosting`→`hosting/`, `ui`→`ui/`, `testing`→`testing/`).

   For each event name in any active stack's `emits_events:`, ensure an entry exists in the EVENTS.yaml `events:` map. If the entry is already present from steps 1-3 (experiment-derived), do NOT overwrite — experiment-defined trigger and properties win. If absent, synthesize a minimal entry:
   - `funnel_stage`: derive from the analytics stack file's event-to-stage mapping (e.g., posthog.md maps `retain_return → retain`, `signup_start → activate`, `signup_complete → activate`). If the analytics stack does not list the event, infer from name conventions (`*_start`/`*_complete` → `activate`; `retain_*`/`return_*` → `retain`; `view_*`/`landing_*` → `reach`).
   - `trigger`: derive from the source stack file's template-fire context (e.g., `retain_return` fires from RetainTracker.tsx on return after 24h; `signup_start` fires on signup-page mount; `signup_complete` fires after successful auth). Read the source stack's relevant section for the precise phrasing.
   - `archetypes`: copy from the stack frontmatter annotation if declared (e.g., `# archetypes: [web-app]`). Default `[web-app]` if absent and the stack is web-app-only.

   This handles framework-emitted events (events the framework or auth template fires automatically) that no experiment golden_path / behavior / hypothesis would reference. Without this, `nextjs.md`'s hardcoded `import { trackRetainReturn }` (RetainTracker) and `auth/supabase.md`'s `import { trackSignupStart, trackSignupComplete }` produce typed-wrapper drift on every analytics-enabled bootstrap (spec-reviewer S3b flags).

**Generate EVENTS.yaml structure:**
```yaml
global_properties:
  project_name:
    description: From experiment.yaml `name` field. Identifies which experiment this data belongs to.
    type: string
    required: true
  project_owner:
    description: From experiment.yaml `owner` field. Identifies who owns this experiment.
    type: string
    required: true

events:
  <derived events in funnel_stage order: reach → demand → activate → monetize → retain>
```

Present the derived EVENTS.yaml alongside experiment.yaml for review.

### CHECKPOINT

Present the assembled experiment.yaml and EVENTS.yaml in full. Then say:
> **Review the assembled experiment specification above.**
>
> `experiment/experiment.yaml` has been progressively written during STATES 2–6
> — each state's VERIFY gate requires its fields to be on disk. `experiment/EVENTS.yaml`
> is assembled in-memory here and written alongside the other delivery artifacts
> (`.runs/spec-manifest.json`, Q-score) in STATE 7.
>
> - Check that hypotheses match your intuition
> - Check that behaviors cover what you want to test
> - Check that variants feel genuinely different
> - Check that the stack matches your needs
> - Check that analytics events cover the key actions you want to measure
>
> Reply **approve** to advance to STATE 7 (finalize delivery — writes EVENTS.yaml,
> spec-manifest.json, and the Q-score), or tell me what to change and I will revise
> both files in place.

**STOP.** Wait for explicit `approve`. The spec is not delivered until STATE 7 completes — this approval gates delivery-artifact writes, not the progressive spec writes (which are already on disk to satisfy the STATE 2–5 VERIFY gates).

If the user requests changes, revise `experiment/experiment.yaml` on disk (and the in-memory EVENTS.yaml) and present again. Repeat until approved.

**POSTCONDITIONS:**
- Complete experiment.yaml assembled with all 7 sections
- Complete EVENTS.yaml derived from golden_path, behaviors, and hypotheses
- User approved the specification and events <!-- enforced by agent behavior, not VERIFY gate -->

**VERIFY:**
```bash
python3 -c "import yaml; d=yaml.safe_load(open('experiment/experiment.yaml')); assert d.get('name'), 'name missing'; assert d.get('type'), 'type missing'; assert d.get('thesis'), 'thesis missing'; assert d.get('behaviors'), 'behaviors missing'; gp=d.get('golden_path') or d.get('endpoints') or d.get('commands'); assert gp, 'no golden_path/endpoints/commands'; assert d.get('stack'), 'stack missing'; assert d.get('funnel'), 'funnel missing'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh spec 6
```

**NEXT:** Read [state-7-output.md](state-7-output.md) to continue.
