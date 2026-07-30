# STATE 4b: PROD_VALIDATION

**PRECONDITIONS:**
- STATE 4a POSTCONDITIONS met (health check completed, auto-fix attempted)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.

### 5d.5: Provision scan (independent verification)

Spawn the `provision-scanner` agent (`subagent_type: provision-scanner`).
Pass context:

> Mode: deploy
> Manifest path: .runs/deploy-manifest.json

Wait for the agent to complete. Include the scanner's output table in the Step 6 summary under a **Provision Scan** heading. If any check FAILs, list them as action items — the health check + auto-fix (5c-5d) already attempted remediation, so these are residual issues for the user to address.

### 5d.6: Auto-create Production Test User (conditional)

**Gate:** Skip if `stack.auth` is absent in experiment.yaml OR `stack.database` is not `supabase`.

Create a dedicated test user for production behavior verification. The test user is identifiable by its email pattern and scoped to testing.

1. **Read Supabase credentials** from the hosting provider env vars (set during STATE 3, Step 4.4):
   - Retrieve `NEXT_PUBLIC_SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` using the hosting stack file's `## Deploy Interface > Auto-Fix` verify command (e.g., `vercel env pull` or REST API).
   - These were already set during provisioning — this step reads them back.

2. **Generate credentials:**
   - Email: `mvp-test@<project-slug>.test` where `<project-slug>` is the `name` field from experiment.yaml (lowercased, spaces to hyphens). The `.test` TLD is reserved by RFC 2606.
   - Password: Generate a random 24-character password via `openssl rand -base64 18`

3. **Create or update the test user:**
   ```bash
   node -e "
   const { createClient } = require('@supabase/supabase-js');
   const sb = createClient(process.env.SUPABASE_URL, process.env.SERVICE_ROLE_KEY);
   (async () => {
     const email = process.env.TEST_EMAIL;
     const password = process.env.TEST_PASSWORD;
     // Try to create
     const { data, error } = await sb.auth.admin.createUser({
       email,
       password,
       email_confirm: true,
       user_metadata: { is_test_user: true }
     });
     if (error && error.message?.includes('already been registered')) {
       // User exists — update password
       const { data: list } = await sb.auth.admin.listUsers();
       const existing = list?.users?.find(u => u.email === email);
       if (existing) {
         await sb.auth.admin.updateUserById(existing.id, { password });
         console.log(JSON.stringify({ email, password, userId: existing.id, created: false }));
         return;
       }
     }
     if (error) { console.error(error.message); process.exit(1); }
     console.log(JSON.stringify({ email, password, userId: data.user.id, created: true }));
   })();
   "
   ```
   - `email_confirm: true` bypasses email verification
   - `user_metadata: { is_test_user: true }` marks the user as identifiable test data
   - If the user already exists (re-deploy scenario), update the password instead of failing

4. **Save credentials** to `.runs/prod-test-credentials.json`:
   ```json
   { "email": "mvp-test@slug.test", "password": "<random>", "userId": "<uuid>", "created": true }
   ```

**On failure:** Non-blocking. Record `behavior_verification: { ran: false, reason: "test user creation failed" }`. Report:
> Could not create production test user. Behavior verification skipped.
> To verify manually: ask Claude to run Playwright against the production URL with test credentials.

### 5d.7: Production Smoke Test (conditional)

**Gate:** Skip this step if `playwright.config.ts` does not exist in the project root (testing stack not present).

Run smoke tests and behavior tests against the live production URL:

```bash
npx playwright install chromium --with-deps 2>/dev/null || true
SPEC_FILES="e2e/smoke.spec.ts"
test -f e2e/behaviors.spec.ts && SPEC_FILES="$SPEC_FILES e2e/behaviors.spec.ts"
E2E_BASE_URL=<canonical_url> npx playwright test $SPEC_FILES \
  --project=chromium --global-setup="" --global-teardown=""
```

- `SPEC_FILES` includes `behaviors.spec.ts` only if it exists (existence gate avoids "No tests found" errors for projects without behaviors)
- `E2E_BASE_URL` points Playwright at the live deployment (conditional `webServer` in config skips local dev server)
- `--project=chromium` runs Desktop Chrome only (production smoke prioritizes speed)
- `--global-setup="" --global-teardown=""` disables local Supabase test user lifecycle (same pattern as preview-smoke CI job)

**On success:** Record `smoke_test: { ran: true, passed: true }` for the health artifact.
**On failure:** Record `smoke_test: { ran: true, passed: false, error: "<summary>" }`. Do NOT enter auto-fix loop — smoke failures after a successful health check indicate front-end rendering issues, not infrastructure problems. Report to user:

> Production smoke test failed. The health check passed (APIs work) but page rendering has issues.
> Review the Playwright report at `playwright-report/index.html`.
> Fix the issue, merge to `main`, then re-run `/deploy`. Or run `/rollback` to revert.

Continue to Step 5d.8 regardless of smoke test result (behavior verification may still provide useful signal).

### 5d.8: Production Behavior Verification (conditional)

**Gate:** For web-app: skip if Step 5d.7 (smoke test) was skipped (no `playwright.config.ts`). For service: proceed if `golden_path` or `endpoints` exist in experiment.yaml (behavior-verifier supports service archetype without Playwright). For cli: skip — CLI archetypes do not support production mode (they test the local binary; see behavior-verifier procedure). For all non-skipped archetypes: skip if Step 5d.6 failed AND the app requires auth (auth-gated behaviors need a logged-in user). If no auth stack, behavior verification can still run for anonymous behaviors.

Spawn the `behavior-verifier` agent (`subagent_type: behavior-verifier`) with production mode context:

> Run the behavior-verifier procedure in production mode.
> E2E_BASE_URL=<canonical_url>
> Credentials file: .runs/prod-test-credentials.json (if exists)
>
> Use E2E_BASE_URL as the base URL. If .runs/prod-test-credentials.json exists, use those credentials for login steps. Use captureAnalytics instead of blockAnalytics. Skip behaviors with trigger: stripe webhook.

Wait for the agent to complete (timeout: 5 minutes). Collect results from the agent's trace output (`.runs/agent-traces/behavior-verifier.json`).

**On success (all behaviors pass):** Record in health artifact.
**On partial failure (some behaviors fail):** Record failures in `behavior_verification.failures` array of deploy-health.json. Construct a pre-filled `/change fix` command from the failures and report to user:

> Production behavior verification found issues (N of M behaviors failed):
>
> Failures:
>   [behavior-id]: [failure description from verifier trace]
>   [behavior-id]: [failure description from verifier trace]
>
> Recovery (zero debugging required — root cause already diagnosed):
>   1. Run: /change fix "[behavior-id]: [failure summary], [behavior-id]: [failure summary]"
>   2. Approve the fix plan → wait for verification → merge PR
>   3. Run: /deploy
>
> Or run `/rollback` to revert immediately.

The `/change fix` command string is constructed from the `behavior_verification.failures` array. Each entry includes the behavior ID and a brief root cause description from the verifier agent's findings. This gives `/change` full context to diagnose and fix without requiring the user to investigate.

**On timeout:** Record `behavior_verification: { ran: true, mode: "production", timed_out: true }`. Report:
> Production behavior verification timed out after 5 minutes. This may indicate slow page loads or hanging requests in production. Check application logs.

#### 5d.9a: Auth-provider config health check (conditional)

**Gate:** Only run when ALL of the following are true (otherwise skip silently with log `Skipping 5d.9a — prerequisites not met`):

- `stack.auth_providers` is present in experiment.yaml
- `stack.database: supabase` AND `stack.auth: supabase`
- `.runs/deploy-provision-3b.json` `collected_secrets` contains OAuth credentials for each declared provider (e.g., `GOOGLE_CLIENT_ID` for `google`). If ANY provider lacks credentials in `collected_secrets`, skip — state-3c Agent A never PATCHed the config for that provider, so there is nothing to verify.

**Test:** Read the Supabase access token using the same cascade as state-3c Auth Config step 1 (`~/.supabase/access-token` → macOS Keychain → prompt). On token failure, record `auth_provider_verification: { ran: false, reason: 'access-token unavailable' }` in deploy-health.json and continue — this step is non-blocking.

Query `GET /v1/projects/{ref}/config/auth` and for each provider in `stack.auth_providers` assert:
- `external_<provider>_enabled == true`
- `external_<provider>_client_id` is non-empty

```bash
SUPABASE_TOKEN=<resolved-from-cascade>
PROJECT_REF=<supabase-ref-from-deploy-provision-3a.json>
AUTH_CFG=$(curl -s -H "Authorization: Bearer $SUPABASE_TOKEN" \
  "https://api.supabase.com/v1/projects/$PROJECT_REF/config/auth")
PROVIDERS=$(python3 -c "import yaml,json; s=yaml.safe_load(open('experiment/experiment.yaml')).get('stack',{}).get('auth_providers',[]); print(json.dumps(s))")
FAILURES=()
for provider in $(echo "$PROVIDERS" | python3 -c "import json,sys; print(' '.join(json.load(sys.stdin)))"); do
  enabled=$(echo "$AUTH_CFG" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('external_${provider}_enabled', False))")
  client_id=$(echo "$AUTH_CFG" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('external_${provider}_client_id') or '')")
  [[ "$enabled" == "True" ]] || FAILURES+=("$provider: external_${provider}_enabled is not True (read: $enabled)")
  [[ -n "$client_id" ]] || FAILURES+=("$provider: client_id empty on read-back (PATCH silently dropped)")
done
```

**On success:** Record `auth_provider_verification: { ran: true, passed: true, providers: [<list>] }` in deploy-health.json.

**On failure** (any assertion failed — typically means the state-3c Management API PATCH silently failed or the OAuth credentials were rejected by Supabase): Record `auth_provider_verification: { ran: true, passed: false, failures: [<list>] }`. Report to user:

> **Auth provider configuration incomplete.** The Management API read-back shows some providers are not fully enabled on Supabase. This commonly means: PATCH silently failed, the Google Cloud OAuth client's redirect URI is misconfigured, or the client secret was not accepted.
>
> Failures:
> - [provider]: [reason]
>
> Recovery: re-run `/deploy` (it will re-PATCH the auth config) OR manually configure at Supabase Dashboard → Authentication → Providers.

Continue to 5d.9b regardless — this step does not block other validation. Non-Supabase auth (future auth providers) skips this block via the `stack.auth: supabase` gate.

#### 5d.9b: Synthetic webhook endpoint verification

**Gate:** Only run when webhook endpoints exist. Check: `stack.payment` is present in experiment.yaml, OR `ls src/app/api/webhooks/*/route.ts 2>/dev/null` returns files. Skip with log "No webhook endpoints detected — skipping synthetic webhook test" when neither condition is met.

**Test:** For each webhook route file found, send a POST request with an empty body and no signature headers:
```bash
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST <canonical_url>/api/webhooks/<service>)
```
- Expected: 400 (rejects unsigned request gracefully)
- FAIL if 500 (unhandled error — endpoint crashes on missing signature)
- FAIL if 404 (endpoint not deployed — build may have excluded the route)

Record results in `deploy-health.json` under `webhook_verification: { ran: true, endpoints_tested: N, all_passed: boolean }`.

### 5e: File template observations

If any fix during the deploy flow (Steps 3-5d) required working around a
problem whose root cause is in a template file (stack file, command file,
or pattern file), follow `.claude/patterns/observe.md` to file an
observation issue. This captures deployment-specific template gaps that
verify.md's build loop would not encounter.

Do NOT file observations for environmental issues (missing/mistyped env
vars, temporary network outages, uninitialized CLIs, or authentication
failures) — observe.md's trigger evaluation excludes these.

- **Write health check artifact** (`.runs/deploy-health.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  health = {
      'health_check_passed': True,
      'auto_fix_rounds': 0,
      'provision_scan_completed': True,
      'smoke_test': {
          'ran': True,       # or False if playwright.config.ts absent
          'passed': True     # or False if smoke test failed
      },
      'behavior_verification': {
          'ran': True,        # or False if skipped/failed to start
          'mode': 'production',
          'total': 0,         # from behavior-verifier trace
          'passed': 0,
          'failed': 0,
          'skipped': 0,
          'failures': []      # list of failure strings, e.g. ['b-03: form submit returns 500']
      },
      'observations_filed': 0
  }
  print(json.dumps(health))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/deploy-health.json \
    --payload "$PAYLOAD" \
    --skill deploy
  ```

  Populate `smoke_test` and `behavior_verification` from Steps 5d.6-5d.8 results. If the steps were skipped (no `playwright.config.ts` or no auth stack), set `ran: false` and omit the detail fields. The `behavior_verification.failures` array should contain the behavior IDs and brief descriptions from the verifier agent's trace. For CLI or detached-surface deployments, `provision_scan_completed` reflects all *applicable* checks — some checks (e.g., P2 health endpoint) are skipped with `skip:not-applicable` for static surfaces that have no `/api/health` endpoint.

**POSTCONDITIONS:**
- Health check executed against canonical_url <!-- enforced by agent behavior, not VERIFY gate -->
- Auto-fix attempted if health check failed (max 2 rounds) <!-- enforced by agent behavior, not VERIFY gate -->
- Provision scan completed <!-- enforced by agent behavior, not VERIFY gate -->
- Production smoke test executed (if `playwright.config.ts` exists) <!-- enforced by agent behavior, not VERIFY gate -->
- Production test user created (if auth + supabase stack present) <!-- enforced by agent behavior, not VERIFY gate -->
- Production behavior verification executed (if smoke test ran) <!-- enforced by agent behavior, not VERIFY gate -->
- Template observations filed (if applicable) <!-- enforced by agent behavior, not VERIFY gate -->
- `.runs/deploy-health.json` exists
- `.runs/prod-test-credentials.json` exists (if test user created) <!-- enforced by agent behavior, not VERIFY gate -->

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/deploy-health.json')); assert isinstance(d.get('health_check_passed'), bool), 'health_check_passed not bool'; assert isinstance(d.get('auto_fix_rounds'), int) and d['auto_fix_rounds']>=0, 'auto_fix_rounds invalid'; assert d.get('provision_scan_completed') is not None, 'provision_scan_completed missing'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh deploy 4b
```

**NEXT:** Read [state-5-manifest-write.md](state-5-manifest-write.md) to continue.
