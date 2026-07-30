# STATE 1: CONFIG_GATHER

**PRECONDITIONS:**
- Pre-flight checks passed (STATE 0 POSTCONDITIONS met)
- experiment.yaml read and parsed
- Archetype and surface type resolved

**ACTIONS:**

> **Update mode shortcut:** If `deploy_mode == "update"` (from deploy-context.json), config gathering is streamlined. Only **added services** (from the diff in STATE 0) need full config collection. Unchanged services already have their config on the hosting provider. See the update mode branch below.

### Initial mode (full config gathering)

1. **Hosting config** (skip for surface-only deployments)**:** Read the hosting stack file's `## Deploy Interface > Config Gathering`. Follow the instructions to discover the team/org/account (e.g., run the CLI command listed there). Check the experiment.yaml field listed in the stack file — if set, skip the prompt.
2. **Database config** (if `stack.database` is present): Read the database stack file's `## Deploy Interface > Config Gathering`. Follow the instructions to discover the org/region/account. Check the experiment.yaml fields listed — if set, skip the prompts.
3. **DB password** (if applicable): Generate with `openssl rand -base64 24`.
5. **Stripe keys** (if `stack.payment` is present): Ask the user for `STRIPE_SECRET_KEY` and `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`. If Stripe CLI is available, the webhook secret will be auto-generated in Step 5. If not, also ask for `STRIPE_WEBHOOK_SECRET`.
7. **OAuth provider credentials** (if `stack.auth_providers` present):
   - If `deploy-manifest.json` exists (re-run): Supabase ref is known -> collect credentials now
   - If first deploy: note that OAuth needs setup after Step 3 creates the Supabase project
   - For each provider, tell the user:
     > Create an OAuth app at [provider console URL].
     > Set redirect URI to: `https://<ref>.supabase.co/auth/v1/callback`
     > Paste Client ID and Secret here, or type **skip** to configure later.
   - Provider console URLs: google -> console.cloud.google.com/apis/credentials,
     github -> github.com/organizations/<org>/settings/applications (org) or github.com/settings/developers (personal),
     facebook -> developers.facebook.com/apps,
     apple -> developer.apple.com/account/resources/authkeys,
     discord -> discord.com/developers/applications, gitlab -> gitlab.com/-/user_settings/applications
   - Provider-specific notes (include in the prompt for the relevant provider):
     - **Google (Workspace):** Set the OAuth consent screen to **External** user type. In development mode (up to 100 test users), no Google verification is needed — sufficient for MVP validation.
     - **Facebook:** Development mode (up to 25 test users) does not require Meta app review — sufficient for MVP validation. Add the **Facebook Login** product to your app.
     - **GitHub:** Create the OAuth App under your Organization (not personal account) for centralized management. Any Org member can create OAuth Apps unless the Org has restricted this.
   - Store credentials in memory (never in files — secrets go to Management API only)
6. **External service credentials**: Read `.env.example`, collect env vars not handled by stack categories. For each external service, use CLI status from Step 0.10:
   - **Auto via CLI** — installed + authenticated -> will auto-provision in Step 5b
   - **Manual (CLI available)** — CLI exists but not installed/authed -> user can install to enable auto
   - **Manual (no CLI)** — no CLI for this service -> web dashboard
   - Note: Fake Door features have no env vars and no API routes — UI-only. Skip them.

### Update mode (diff-based config gathering)

When `deploy_mode == "update"`:

1. **Unchanged services** — skip config gathering entirely. Their credentials are already set on the hosting provider from the previous deploy.
   - Prompt the user: "Existing service credentials are already configured on the hosting provider. Type **resync** to re-gather all credentials (e.g., after key rotation), or press Enter to skip."
   - If user types `resync`: fall back to **initial mode** gathering above for all services.
2. **Added services** — gather full config using the same steps as initial mode, but only for the newly added stack categories. For example, if `stack.payment: stripe` was added since last deploy, collect Stripe keys.
3. **Removed services** — skip entirely. These will be marked as `"orphaned"` in the manifest (STATE 5).

- **Write config artifact** (`.runs/deploy-config.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  config = {
      'hosting_gathered': True,
      'database_gathered': True,  # or False if skipped
      'stripe_gathered': False,   # True if stack.payment present
      'oauth_gathered': False,    # True if auth_providers present
      'external_services': []     # list of {name, method: auto|manual}
  }
  print(json.dumps(config))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/deploy-config.json \
    --payload "$PAYLOAD" \
    --skill deploy
  ```

**POSTCONDITIONS:**
- Hosting config gathered (team/org/account) or skipped for surface-only
- Database config gathered (org/region) or skipped
- DB password generated (if applicable)
- Stripe keys collected (if applicable)
- OAuth credentials collected or deferred to Step 3.5
- External service credentials categorized (auto/manual)
- `.runs/deploy-config.json` exists

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/deploy-config.json')); assert isinstance(d.get('hosting_gathered'), bool), 'hosting_gathered not bool'; assert isinstance(d.get('database_gathered'), bool), 'database_gathered not bool'; assert isinstance(d.get('external_services'), list), 'external_services not a list'; assert all(isinstance(s, (str,dict)) for s in d['external_services']), 'external_services items invalid'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh deploy 1
```

**NEXT:** Read [state-2-user-approval.md](state-2-user-approval.md) to continue.
