# STATE 3: VALIDATE_EXPERIMENT

**PRECONDITIONS:**
- Archetype and stack resolved (STATE 2 POSTCONDITIONS met)
- All stack files and archetype file are in context

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Spec field".
> [spec-field] web-app: `golden_path` | service: `endpoints` | cli: `commands`

- Every one of these fields must be present and non-empty (strings must be non-blank, lists must have at least one item): `name`, `owner`, `type`, `description`, `thesis`, `target_user`, `distribution`, `behaviors`, `stack`, plus fields from the archetype's `required_experiment_fields` (e.g., `golden_path` for web-app, `endpoints` for service)
- If ANY field still contains "TODO" or is missing: stop, list exactly which fields need to be filled in, and do nothing else
- If the archetype requires pages (web-app): verify `golden_path` includes at least one entry with `page: landing`
- If the archetype requires `endpoints` (service): verify `endpoints` is a non-empty list
- If the archetype requires `commands` (cli): verify `commands` is a non-empty list
- Verify `name` is canonical kebab-case (regex `^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$`) by running `python3 .claude/scripts/lib/validate_experiment_yaml.py`. If it exits non-zero, STOP and surface its stderr to the user (it prints a kebab-case suggestion). This script ALSO writes `.runs/bootstrap-validation-trace.json` — the `experiment_valid` flag in the trace is now sourced from this real check, not from agent self-report.
- For each category in the archetype's `excluded_stacks` list: if that category is present in experiment.yaml `stack`, stop and tell the user: "The `<archetype>` archetype excludes `<category>`. Remove `<category>: <value>` from your experiment.yaml `stack` section, or switch to a different archetype."
- For each category in the archetype's `required_stacks` list: verify the category is present in experiment.yaml `stack`. Per-service categories (`framework`, `hosting`, `ui`, `testing`) map to `stack.services[]` keys (`runtime` for framework, others by name). Shared categories (`database`, `auth`, `analytics`, `payment`, `email`) map to `stack.<category>`. If a required category is missing, stop and tell the user: "The `<archetype>` archetype requires `<category>`. Add it to your experiment.yaml `stack` section — shared categories go at the top level (e.g., `database: supabase`), per-service categories go under `stack.services[]` (e.g., `hosting: vercel` under a service entry)."
- Validate stack dependencies per `patterns/stack-dependency-validation.md` — read the Dependency Matrix, Compatibility Constraints, and Error Message Templates sections. Use the canonical error messages from that file for all stop messages. Key checks: payment requires auth+database; email requires auth+database; auth_providers requires auth; playwright incompatible with service/cli.
  - Validate framework-archetype compatibility: web-app requires nextjs; cli requires commander
  - Validate testing-archetype compatibility: if `stack.testing` is `playwright` and the archetype is `service` or `cli`, stop with the canonical error from `stack-dependency-validation.md`: "Playwright requires a browser and is not compatible with the `<archetype>` archetype. Use `testing: vitest` instead."
- Verify `stack.testing` is present. If absent: stop — "Testing framework required. Add `testing: playwright` (web-app) or `testing: vitest` (service/cli) to experiment.yaml `stack` and re-run `/bootstrap`."
- If `stack.auth_providers` is present:
  - Verify it is a non-empty list of strings. If empty: stop — "auth_providers is empty. Either add providers (e.g., `[google, github]`) or remove the field."
  - Warn (don't stop) for unrecognized slugs — Supabase may add new providers.
- If `variants` is present in experiment.yaml and the archetype is NOT `web-app`: stop — "Variants (A/B landing page testing) are only supported for the web-app archetype. Remove the `variants` field from experiment.yaml, or switch to `type: web-app`."
- If `variants` is present in experiment.yaml, validate the variants list:
  - Must be a list with at least 2 entries (testing 1 variant = no variants — tell the user to remove the field)
  - Each variant must have: `slug`, `headline`, `subheadline`, `cta`, `pain_points` (all non-empty)
  - Each `slug` must be lowercase, start with a letter, and use only a-z, 0-9, hyphens
  - Slugs must be unique across all variants
  - No slug may collide with a page name from `golden_path`
  - `pain_points` must have exactly 3 items per variant
  - If any validation fails: stop and list the specific errors

- **Validation trace artifact** (`.runs/bootstrap-validation-trace.json`) — written by `validate_experiment_yaml.py` above. The script always writes the trace (both success and failure paths) so VERIFY can audit a real outcome. Only after that script exits 0 (plus the agent-driven semantic checks above pass) should you proceed.

**POSTCONDITIONS:**
- All required fields present and non-empty <!-- enforced by agent behavior, not VERIFY gate -->
- `name` matches `^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$` (canonical kebab-case) <!-- enforced by validate_experiment_yaml.py + VERIFY regex check -->
- No TODO values remain <!-- enforced by agent behavior, not VERIFY gate -->
- Archetype-specific fields validated <!-- enforced by agent behavior, not VERIFY gate -->
- Stack dependency rules satisfied (payment->auth+db, email->auth+db, playwright->web-app only) <!-- enforced by agent behavior, not VERIFY gate -->
- Quality/testing dependency satisfied if applicable <!-- enforced by agent behavior, not VERIFY gate -->
- Variant structure valid if applicable <!-- enforced by agent behavior, not VERIFY gate -->
- `.runs/bootstrap-validation-trace.json` exists with `experiment_valid` field

**VERIFY:**
```bash
python3 -c "import json,yaml,re; t=json.load(open('.runs/bootstrap-validation-trace.json')); assert t.get('experiment_valid') is True, 'experiment_valid=%s checks_failed=%s' % (t.get('experiment_valid'), t.get('checks_failed')); d=yaml.safe_load(open('experiment/experiment.yaml')); n=d.get('name',''); assert re.match(r'^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$', n), 'experiment.yaml.name must be canonical kebab-case, got %r' % n"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 3
```

**NEXT:** Read [state-3a-bg1-gate.md](state-3a-bg1-gate.md) to continue.
