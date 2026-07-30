# STATE 9a: GRADUATE_EXTERNAL_STACK


<!-- archetype-reference-only: REF .claude/patterns/archetype-behavior-check.md — Mentions 'external services' generically; no archetype-conditional logic. -->

**PRECONDITIONS:**
- Patterns saved (STATE 9 POSTCONDITIONS met)

**ACTIONS:**

Evaluate whether any resolved issue targets an external service that qualifies
for graduation to a permanent template-level stack file. Multiple services
may be identified — evaluate each independently.

### 1. Identify external services

Check resolved issue titles/bodies for references to `external/<service>.md`
or `[pattern] external/<service-slug>`. Extract all unique `<service-slug>` values.

If no external service is referenced in any resolved issue:
→ Write graduation-result.json with `services: []`,
  `skipped_reason: "no external service in resolved issues"` → skip to NEXT.

### For each identified service, run steps 2-6:

### 2. Check if permanent file already exists

Search `.claude/stacks/*/<service-slug>.md` (any category directory). If a stack
file already exists for this service in any category (e.g., `ai/anthropic.md`,
`telephony/twilio.md`, or `external/xero.md`):
→ Record `{ "service": "<slug>", "graduated": false, "skipped_reason": "permanent stack file already exists" }` → continue to next service.

### 3. Count observations (dual search)

```bash
TEMPLATE_REPO="magpiexyz-lab/mvp-template"

# Search 1: pattern-classifier issues
gh issue list --repo $TEMPLATE_REPO --label observation \
  --search "[pattern] external/<service-slug>" --state all --limit 50 \
  --json number,title

# Search 2: observer issues (keyword)
gh issue list --repo $TEMPLATE_REPO --label observation \
  --search "<service-name>" --state all --limit 50 \
  --json number,title
```

Deduplicate by issue number. Post-filter: only count issues whose title or
body references the service name or `external/<service-slug>.md`.

### 4. Apply threshold

- **≥2 total observations** → graduate.
- **≥1 observation with HIGH security severity** → graduate immediately.
  Security keywords in title: "signature", "SSRF", "injection", "XSS",
  "HMAC", "validation bypass", "PII", "authentication bypass".

If threshold not met:
→ Record `{ "service": "<slug>", "graduated": false, "skipped_reason": "threshold not met (<count>/<threshold>)" }` → continue to next service.

### 5. Determine category and synthesize permanent stack file

**5a. Determine category** — Propose a category directory name based on the
service's domain. Use short, descriptive names following the existing convention
(e.g., `telephony` for SMS/voice, `voice` for AI voice agents, `notifications`
for webhook notifications, `project-management` for issue tracking). Present the
proposed category to the user for confirmation. Create `.claude/stacks/<category>/`
if the directory does not exist.

**5b. Create the stack file** at `.claude/stacks/<category>/<service-slug>.md` using:

**Content sources:**
- Resolved observations' "Suggested template change" sections
- `scaffold-externals.md` Known Service Quirks entries for this service
- Existing permanent files in other categories as structural reference
- Claude's knowledge of the service API

**Required sections:**
- YAML frontmatter (per `.claude/stacks/TEMPLATE.md` schema)
- `## Packages` — npm install commands
- `## Files to Create` — client library + webhook route handler code templates
- `## Environment Variables` — documented secrets
- `## Patterns` — security/architectural best practices
- `## Security` — threat vectors and mitigations
- `## CLI Provisioning` — CLI availability or "No CLI available..."
- `## PR Instructions` — manual provisioning steps

**Constraints:**
- `ci_placeholders`: set placeholder values for each env var in `env.server` and
  `env.client` (e.g., `TWILIO_ACCOUNT_SID: placeholder-twilio-sid`). Empty `{}`
  is only acceptable when the service has zero env vars.
- Server vars in `env.server`, client vars in `env.client`
- Next.js client vars must use `NEXT_PUBLIC_` prefix

**5c. Auto-register the new category** — Update ALL of the following registration
points to include the new `<category>`:

| File | Field to update |
|------|-----------------|
| `.claude/archetypes/web-app.md` | `optional_stacks` |
| `.claude/archetypes/service.md` | `optional_stacks` |
| `.claude/archetypes/cli.md` | `optional_stacks` |
| `.claude/skills/bootstrap/state-2-resolve-archetype.md` | known shared categories list |
| `.claude/procedures/scaffold-externals.md` | exclusion list (search for "shared categories" — top of file) |
| `scripts/validate-experiment.py` | `SHARED_STACK_KEYS` |
| `scripts/validators/_utils.py` | `OPTIONAL_CATEGORIES` |
| `scripts/validators/_stack_deps.py` | `SHARED_STACK_CATEGORIES` |
| `.claude/commands/bootstrap.md` | `stack_categories` |
| `.claude/commands/change.md` | `stack_categories` |
| `.claude/commands/deploy.md` | `stack_categories` |

If the category already exists in a registration point (from a prior graduation),
skip that point.

### 6. Validate frontmatter

```bash
python3 scripts/validate-frontmatter.py .claude/stacks/<category>/<service-slug>.md
```

Max 2 retries on failure. Record graduated service result.

### 7. Write graduation artifact

After evaluating all services, write the combined result:

- **Write graduation-result artifact** (`.runs/graduation-result.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  result = {
      'evaluated': True,
      'services': [
          # one entry per identified service:
          {
              'service': '<service-slug>',
              'category': '<category>',
              'observation_count': N,
              'threshold': 2,
              'graduated': True,  # or False
              'file_path': '.claude/stacks/<category>/<service-slug>.md',
              'frontmatter_valid': True,
              'skipped_reason': None  # or reason string
          }
      ],
      'skipped_reason': None  # set only when no external services found
  }
  print(json.dumps(result))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/graduation-result.json \
    --payload "$PAYLOAD" \
    --skill resolve
  ```

### Q-score

Write dimension data for lifecycle-finalize:

```bash
RUN_ID=$(python3 -c "import json; print(json.load(open('.runs/resolve-context.json')).get('run_id', ''))" 2>/dev/null || echo "")
PAYLOAD=$(python3 -c "
import json, os
print(json.dumps({
    'scope': 'resolve',
    'dims': {'completion': 1.0}
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/q-dimensions.json \
  --payload "$PAYLOAD" \
  --skill resolve || true
```

**POSTCONDITIONS:**
- `.runs/graduation-result.json` exists with required fields
- For each service with `graduated: true`: permanent stack file exists and frontmatter is valid

<!-- VERIFY=registry: graduation-result.json artifact validation -->
**VERIFY:**
```bash
python3 -c "import json,os; d=json.load(open('.runs/graduation-result.json')); assert d.get('evaluated')==True, 'not evaluated'; svcs=d.get('services',[]); assert isinstance(svcs, list), 'services not a list'; [None for s in svcs if s.get('graduated') and not (s.get('file_path') and os.path.exists(s['file_path']) and s.get('frontmatter_valid')==True and not s['file_path'].startswith('.claude/stacks/external/')) and (_ for _ in ()).throw(AssertionError('graduated %s but file missing, invalid, or in external/' % s.get('service')))]"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh resolve 9a
```

**NEXT:** Read [state-10-post-fix-review.md](state-10-post-fix-review.md) to continue.
