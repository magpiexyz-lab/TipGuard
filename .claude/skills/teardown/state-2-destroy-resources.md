# STATE 2: DESTROY_RESOURCES

**PRECONDITIONS:**
- User confirmed teardown by typing project name (STATE 1 POSTCONDITIONS met)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "npm cleanup on teardown".
>
> [npm-cleanup] web-app: skip | service: skip | cli: `npm deprecate` reminder

### Step 2: Pre-delete safety check (if database present)

If `database` is in the manifest and the database stack file has a `## Deploy Interface > Teardown` section with a pre-delete safety check:

Follow the stack file's Teardown instructions for the safety check (e.g., query row counts). If any table has rows > 0, warn:

```
Database contains live data:
- <table>: <N> rows
- <table>: <N> rows

Type **delete** to confirm permanent data deletion, or **cancel** to abort.
```

If the user types "cancel", stop.

### Step 2b: npm package cleanup (if archetype is cli)

If archetype is `cli`, check if the experiment was published to npm:
```bash
npm view <name> 2>/dev/null
```
If published, warn: "The npm package `<name>` is still published. After teardown, run `npm deprecate <name>@\"*\" \"Experiment concluded\"` to deprecate it. If published within the last 72 hours, you can also run `npm unpublish <name>` to remove it entirely."

This is a reminder only — npm cleanup is done after infrastructure teardown.

### Step 3: Delete resources (reverse order of /deploy creation)

Delete in reverse order of creation. Each step is independent — continue on failure.

#### 3a: Stripe webhook endpoint (if present in manifest)

If Stripe CLI is available:
```bash
stripe webhook_endpoints list --url <webhook_url>
```
Then delete using the endpoint ID:
```bash
stripe webhook_endpoints delete <endpoint_id>
```
Note: manifest stores the URL, not the endpoint ID. List endpoints to find the ID.

If CLI not available or fails: report "Stripe webhook — delete manually at
https://dashboard.stripe.com/webhooks"

#### 3b: Custom domain (if present in manifest)

Read the hosting stack file's `## Deploy Interface > Teardown`. Execute the remove-domain command with the domain from the manifest.

If fails: report and continue.

#### 3c: Hosting project (if present in manifest)

Read the hosting stack file's `## Deploy Interface > Teardown`. Execute the remove-project command.

If fails: report with the dashboard URL from the stack file's Teardown section for manual fallback.

#### 3c.5: Surface project (if `surface_url` in manifest and no `hosting` in manifest)

This applies to archetypes with detached surfaces (e.g., CLI) where the surface is deployed
independently — no hosting project was created. Read the surface stack file at
`.claude/stacks/surface/detached.md` -> `## Teardown`. Execute the teardown command
(e.g., remove the Vercel project that hosts the surface).

If the surface stack file has no `## Teardown` section, report: "Surface at <surface_url> —
delete manually via the hosting provider's dashboard."

If fails: report with the provider dashboard URL for manual fallback.

#### 3d: Database project (if present in manifest)

Read the database stack file's `## Deploy Interface > Teardown`. Execute the delete command.

If fails: report with the dashboard URL from the stack file's Teardown section for manual fallback.

#### 3e: External services (manual)

For each service in `external_services`:
- Find the service's stack file by searching `.claude/stacks/*/<service-slug>.md` (any category directory) and read it for the dashboard URL
- List the service with its dashboard URL for manual cleanup

**POSTCONDITIONS:**
- All deletable resources have been attempted (stripe, domain, hosting, surface, database)
- External services listed for manual cleanup
- Results (success/failure) recorded for each resource

- **Write result artifact** (`.runs/teardown-result.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  result = {
      'resources_attempted': [],
      'successes': 0,
      'failures': 0
  }
  print(json.dumps(result))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/teardown-result.json \
    --payload "$PAYLOAD" \
    --skill teardown
  ```

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/teardown-result.json')); assert isinstance(d.get('resources_attempted'), list) and len(d['resources_attempted'])>0, 'resources_attempted empty'; assert isinstance(d.get('successes'), int) and d['successes']>=0, 'successes invalid'; assert isinstance(d.get('failures'), int) and d['failures']>=0, 'failures invalid'; assert d['successes']+d['failures']==len(d['resources_attempted']), 'successes+failures != resources count'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh teardown 2
```

**NEXT:** Read [state-3-verify-deletion.md](state-3-verify-deletion.md) to continue.
