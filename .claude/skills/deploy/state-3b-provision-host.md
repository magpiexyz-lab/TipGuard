# STATE 3b: PROVISION_HOST

**PRECONDITIONS:**
- STATE 3a POSTCONDITIONS met (database credentials available for env var setting)

**ACTIONS:**

### Step 4: Create hosting project and set env vars

#### 4.1: Project setup

**Update mode:** If `deploy_mode == "update"` and hosting is in `unchanged_services`: skip project setup (project already exists and is linked). Proceed to Step 4.4 (env var sync).

**Initial mode:** Read the hosting stack file's `## Deploy Interface > Project Setup`. Follow the instructions to create/link the project. For the GitHub integration step: connect GitHub for **PR preview deployments only** — then disable production auto-deploy per the hosting stack file's instructions. If the GitHub connection fails, set `git_connect_failed=true` (reported in Step 6 summary) — this is non-blocking since production deploys are manual.

#### 4.2: Domain setup

Read the hosting stack file's `## Deploy Interface > Domain Setup`. Follow the instructions to add a custom domain. The default parent domain is `draftlabs.org`; override with `deploy.domain` in experiment.yaml.
- **On success:** `canonical_url` = the custom domain, `domain_added` = true
- **On failure:** Output a visible warning to the user with the stack file's fallback message:
  > **WARNING: Domain setup failed.** <stack file's fallback message>. The MVP will deploy to the auto-assigned hosting URL. To add the custom domain manually after deploy, see the hosting stack file's `## Deploy Interface > Domain Setup`.

  Set `canonical_url` = null (backfilled by state-3c after deploy with the auto-assigned hosting URL), `domain_added` = false

#### 4.3: Volume setup (if needed)

Read the database stack file's `## Deploy Interface > Hosting Requirements > volume_config`. If `needed: true`:
1. Read the hosting stack file's `## Deploy Interface > Volume Setup`
2. Follow the instructions to create a persistent volume with the specified mount path
3. Set the env vars from `volume_config.env_vars` using the hosting stack file's env var method

If the hosting stack file has no `Volume Setup` section, stop: "Hosting provider <provider> does not support persistent volumes, which are required by <database>."

#### 4.4: Set environment variables

> **Always executed in both initial and update mode.** Env vars are synced using upsert semantics — existing values are overwritten, new values are added. This ensures `.env.example` changes are reflected on the hosting provider.

Read the hosting stack file's `## Deploy Interface > Environment Variables` for the method (API, CLI, auth token location, fallback).

Collect all env vars and set them using the hosting provider's method:

   Variables from database provisioning (Step 3) — the database stack file's Provisioning substep specifies which env vars and their values.

   Additional variables (when `stack.auth: supabase` AND `stack.database` is NOT `supabase`):
   The auth stack needs a Supabase project even without the database stack. Ask the user for their existing Supabase project URL and anon key:
   - `NEXT_PUBLIC_SUPABASE_URL` — from Supabase Dashboard -> Settings -> API -> Project URL
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY` — from Supabase Dashboard -> Settings -> API -> Publishable Key

   Additional variables (when `stack.payment: stripe`):
   - `STRIPE_SECRET_KEY`
   - `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`
   - `STRIPE_WEBHOOK_SECRET` (skip if Stripe CLI is available — set after webhook creation in Step 5)

   Additional variables (when `stack.email` is present):
   - `RESEND_API_KEY` — ask the user (from resend.com -> API Keys)
   - `CRON_SECRET` — generate with `openssl rand -base64 24`
   - `RESEND_FROM` — set to `noreply@<domain>` where `<domain>` is `deploy.domain` from experiment.yaml; fallback to `draftlabs.org`

   Additional variables (external service credentials from bootstrap):
   - Read `.env.example` and collect all env var keys
   - Exclude keys already handled by stack categories above (database, Stripe, email, PostHog)
   - For each remaining key: read the value from `.env.local`. If found, set it on the hosting provider. If `.env.local` is missing or the key is absent, ask the user for the production value.

- **Write intermediate artifact** (`.runs/deploy-provision-3b.json`) via the
  canonical writer so the file carries `{skill, run_id, written_at}` identity
  stamping (GRAIM v2 C1):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  payload = {
      'hosting_created': True,   # or False if skipped for update mode
      'domain_added': True,      # or False if failed
      'canonical_url': '<url or null>',
      'git_connect_failed': False,
      'env_vars_set': True,
      # Secrets collected in Step 4.4 that downstream agents in state-3c need
      # in their shared-context block (Agent A Receives: RESEND_API_KEY,
      # RESEND_FROM, CRON_SECRET when stack.email:resend). Values are the
      # actual secrets just collected from the user — source of truth for
      # the orchestrator between state-3b and state-3c. Omit a key when it
      # was not collected (e.g., stack.email absent). When this state is
      # skipped for surface-only deployment, write collected_secrets = {}.
      'collected_secrets': {
          # 'RESEND_API_KEY': '<value>',  # when stack.email:resend
          # 'RESEND_FROM': '<value>',     # when stack.email is present
          # 'CRON_SECRET': '<value>',     # when stack.email is present
          # Other stack-scoped secrets that state-3c agents Receive: can go
          # here — this artifact is gitignored (.runs/ is in .gitignore).
      }
  }
  print(json.dumps(payload))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/deploy-provision-3b.json \
    --payload "$PAYLOAD" \
    --skill deploy
  ```

  > `.runs/` is gitignored and overwritten per deploy run. `collected_secrets`
  > is in-memory orchestrator state scoped to the current deploy — it is the
  > source of truth for state-3c Step 5b preamble, not `.env.local` (which
  > may not exist on CI / fresh-clone / rotation-only deploys).

**POSTCONDITIONS:**
- Hosting project created/linked
- Domain configured (or fallback recorded)
- All environment variables set on hosting provider
- `collected_secrets` dict written into `.runs/deploy-provision-3b.json`
  (empty when state-3b is skipped for surface-only deployment)
- `.runs/deploy-provision-3b.json` exists

**VERIFY:**
```bash
python3 .claude/scripts/verify-deploy-3b.py  # artifact: .runs/deploy-provision-3b.json
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh deploy 3b
```

**NEXT:** Read [state-3c-deploy-services.md](state-3c-deploy-services.md) to continue.
