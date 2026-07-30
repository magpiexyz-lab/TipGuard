# STATE 3: BEHAVIORS

**PRECONDITIONS:**
- Hypotheses generated and approved (STATE 2 POSTCONDITIONS met)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app: behaviors require pages: [...] | service: endpoints: [...] | cli: commands: [...]

## Step 4: Derive Behaviors

Convert each **pending** (experiment-type) hypothesis into testable behaviors using given/when/then format.

For each hypothesis, derive 1-3 behaviors that, if observed, would validate or invalidate it.

### Behavior fields (web-app archetype)
```yaml
- id: b-01                      # Sequential zero-padded: b-01, b-02, ...
  hypothesis_id: h-01           # Which hypothesis this validates
  pages: [landing]              # REQUIRED for web-app + actor:user (default).
                                # Lists every page this behavior interacts with.
                                # gate-keeper BG2 check 3c-1 BLOCKS bootstrap if missing.
                                # See .claude/templates/experiment-yaml.md.
  given: "A visitor lands on the landing page"
  when: "They read the headline and see the CTA"
  then: "They click the CTA button"
  tests:                         # 1-5 verifiable assertions
    - "Landing page renders CTA button"
    - "Clicking CTA navigates to signup"
  level: 1                       # Matches the hypothesis level
```

For service archetype use `endpoints: [...]` instead of `pages:`. For cli use `commands: [...]`. See `.claude/templates/experiment-yaml.md`.

For system or scheduled behaviors, add `actor` and `trigger` (no `pages` needed — system/cron behaviors have no UI surface):
```yaml
- id: b-05
  actor: system                  # system | cron (default: user, omit for user behaviors)
  trigger: "stripe webhook checkout.session.completed"
  hypothesis_id: h-03
  given: "..."
  when: "..."
  then: "..."
  tests:
    - "..."
  level: 3
```

### Rules
- Every pending hypothesis must have at least one behavior
- Behaviors must be observable and measurable (map to analytics events or database state)
- Use concrete user actions, not abstract concepts ("clicks the CTA" not "shows interest")
- Behaviors replace the traditional `features` list — each behavior IS a feature requirement
- Each behavior must have 1-5 `tests` entries — verifiable assertions about the behavior (validator-enforced at `scripts/validate-experiment.py` — search for the `b_tests` length check; matches the inline schema comment in the example block above)
- System/cron behaviors should be derived from monetize or operational hypotheses
- **Web-app + actor:user (default): `pages` field is REQUIRED.** If you cannot infer which page(s) a behavior interacts with, halt and ask the user — do not guess. Behaviors without `pages` cause 404 traps after deploy (#1024).

**POSTCONDITIONS:**
- Each pending hypothesis has at least one behavior
- Each behavior has id, hypothesis_id, given, when, then, tests, level
- For web-app archetype: every behavior with actor `user` (or omitted) has a non-empty `pages` list
- System/cron behaviors have actor and trigger fields
- All behaviors are observable and measurable

**VERIFY:**
```bash
python3 -c "import yaml; d=yaml.safe_load(open('experiment/experiment.yaml')); bs=d.get('behaviors',[]); assert isinstance(bs, list) and len(bs)>0, 'no behaviors'; assert all(b.get('id') and b.get('hypothesis_id') for b in bs), 'behavior missing required fields'; archetype=d.get('type','web-app'); assert archetype != 'web-app' or all((b.get('actor') in ('system','cron')) or (isinstance(b.get('pages'), list) and len(b.get('pages',[]))>0) for b in bs), 'web-app: every actor:user behavior must have non-empty pages list (run `python3 .claude/scripts/validate-behavior-pages.py --all` for detailed diagnostic + migration hint; see .claude/templates/experiment-yaml.md)'" && python3 .claude/scripts/validate-behavior-pages.py --all
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh spec 3
```

**NEXT:** Read [state-4-golden-path.md](state-4-golden-path.md) to continue.
