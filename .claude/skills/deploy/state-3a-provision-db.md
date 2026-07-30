# STATE 3a: PROVISION_DB

**PRECONDITIONS:**
- User approved deployment plan (STATE 2 POSTCONDITIONS met)

**ACTIONS:**

> **Update mode behavior:** When `deploy_mode == "update"` (from deploy-context.json), provisioning is diff-based. The following steps are modified:
> - **Always execute** (both modes): Step 5a (code deploy), Step 4.4 (env var sync with upsert), and DB migrations (idempotent)
> - **Added services only**: Full provisioning (Steps 3, 3.5, 4.1–4.3 as applicable for new services)
> - **Unchanged services**: Skip provisioning entirely — health check in STATE 4 verifies they still work
> - **Removed services**: Skip entirely — marked orphaned in STATE 5 manifest
> - **Post-deploy agents (5b)**: Only spawn for added services
>
> For the steps below, "skip for update mode (unchanged)" means: skip this step if `deploy_mode == "update"` AND the relevant stack category is in `unchanged_services`.

### Step 3: Provision database

Skip this step if `stack.database` is absent or if the database stack file's `## Deploy Interface > Provisioning` says "none" (e.g., SQLite — auto-created on startup).

**Update mode:** If `deploy_mode == "update"` and database is in `unchanged_services`: skip provisioning but **always run migrations** — read the database stack file's migration command and execute it. Migrations are idempotent (already-applied migrations are no-ops). If database is in `added_services`: run full provisioning below.

**Initial mode / added service:** Read the database stack file's `## Deploy Interface > Provisioning` and follow each substep in order. The stack file specifies the exact CLI commands, polling logic, key extraction, and migration commands for the configured database provider.

### Step 3.5: Collect OAuth credentials (first deploy only)

Skip if `stack.auth_providers` is absent OR credentials already collected in Step 1.

Now that the Supabase ref is known from Step 3, for each provider in `auth_providers`:
show the callback URL (`https://<ref>.supabase.co/auth/v1/callback`), ask for Client ID
and Secret (or **skip**). Store as `oauth_credentials: { provider: { client_id, secret } }`.

- **Write intermediate artifact** (`.runs/deploy-provision-3a.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  artifact = {
      'database_provisioned': True,   # or False if skipped
      'supabase_ref': '<ref or null>',
      'oauth_credentials_collected': True  # or False if skipped
  }
  print(json.dumps(artifact))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/deploy-provision-3a.json \
    --payload "$PAYLOAD" \
    --skill deploy
  ```

**POSTCONDITIONS:**
- Database provisioned (if applicable) with migrations applied
- OAuth credentials collected (if applicable)
- `.runs/deploy-provision-3a.json` exists

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/deploy-provision-3a.json')); assert isinstance(d.get('database_provisioned'), bool), 'database_provisioned not bool'; assert 'supabase_ref' in d, 'supabase_ref missing'; assert isinstance(d.get('oauth_credentials_collected'), bool), 'oauth_credentials_collected not bool'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh deploy 3a
```

**NEXT:** Read [state-3b-provision-host.md](state-3b-provision-host.md) to continue.
