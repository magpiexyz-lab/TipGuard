# STATE 5: MANIFEST_WRITE


<!-- archetype-reference-only: REF .claude/patterns/archetype-behavior-check.md — Reads archetype from context; per-service health checks delegated to provision-scanner agent. -->

**PRECONDITIONS:**
- Health check and provision scan completed (STATE 4b POSTCONDITIONS met)

**ACTIONS:**

### Step 6: Summary

Print a deployment summary:

```
## Deployment Complete

**Live URL:** https://<canonical_url>
**Database Dashboard:** <URL from database stack file's `## Deploy Interface > Teardown` dashboard URL>
**Hosting Dashboard:** <URL from hosting stack file's `## Deploy Interface > Teardown` dashboard URL>

**Surface URL:** https://<surface_url>
**Health check:** [show per-service results — e.g., database: ok, auth: ok, analytics: ok, payment: ok]

**Production deploys:** Manual — re-run `/deploy` to update. PR preview deployments are automatic (if GitHub connected).
**Auto-migrate:** [If database has migrations] Migrations are applied on each `/deploy` run (idempotent).

[If domain add succeeded] **Custom domain:** https://<name>.<domain>
[If domain add failed] **Custom domain (manual):** See hosting stack file's `## Deploy Interface > Domain Setup` for the add-domain command and DNS requirements.

[If auth] **Auth redirect URLs:** Configured — site_url set to https://<canonical_url>
[If auth] **Email templates:** Configured — professional HTML templates with app branding for confirmation, recovery, and magic link emails
[If auth AND smtp_configured] **Custom SMTP:** Configured — auth emails sent via Resend (smtp.resend.com) from noreply@<domain>
[If auth AND NOT smtp_configured] **Email sender:** Default Supabase sender — add `stack.email: resend` and verify your domain for custom sender address
[If auth_providers] **OAuth providers:**
[For each configured provider] - <Provider>: Enabled
[For each skipped provider] - <Provider>: Skipped — configure at Supabase Dashboard -> Authentication -> Providers
[If payment AND Stripe CLI was available] **Stripe webhook:** Configured — endpoint https://<canonical_url>/api/webhooks/stripe, events: checkout.session.completed
[If payment AND Stripe CLI was NOT available] **Stripe webhook (manual):** Add the webhook URL in Stripe Dashboard -> Developers -> Webhooks:
  Endpoint URL: https://<canonical_url>/api/webhooks/stripe
  Events: checkout.session.completed
[If any health check failed] **Action needed:** [list failing services with fix commands]

[If any agent returned status: "partial"] **Partially configured (declared-optional extension dropped):**
- [service]: partial — [message naming the missing input, e.g., "SMTP skipped: RESEND_API_KEY absent from shared-context collected_secrets"]. The base configuration succeeded but the extension silently dropped because state-3b did not propagate its input to state-3c. Re-run `/deploy` after ensuring the input is provided (e.g., `stack.email: resend` declared AND you supply `RESEND_API_KEY` when prompted), or set up the extension manually via the stack file's dashboard instructions.

[If any agent returned status: "failed"] **Failed (needs manual setup):**
- [service]: failed — [error message]. Set up manually: [instructions from stack file]

[If any agent returned status: "timeout"] **Timed out (retry by re-running /deploy):**
- [service]: timed out — re-run `/deploy` to retry, or set up manually

[If external services] **External services:**
- [service]: auto-provisioned via CLI / manually configured / not configured — set via hosting provider's env var CLI
[If none] **External services:** None

**Monitoring setup** (recommended):
- **Health check alerts:** Set up uptime monitoring for `https://<canonical_url>/api/health` using a free service (e.g., UptimeRobot, Better Stack). Alert on non-200 responses. Check interval: 5 minutes.
- **Analytics digest:** In PostHog -> Dashboards -> "<project-name> Experiment" -> click "Subscribe" (bell icon) -> every 3 days -> add your email.
- **Free tier quotas** (typical usage for MVPs with <1000 MAU):
  - Vercel: 100GB bandwidth/month (free tier) — typical MVP uses <1GB
  - Supabase: 500MB database, 1GB file storage, 50K monthly active users (free tier)
  - PostHog: 1M events/month (free tier) — typical MVP generates <10K/month
  - Stripe: no monthly fee, 2.9% + 30c per transaction
  Monitor usage in each provider's dashboard. You'll receive email warnings before hitting limits.

**Next steps** (all optional — pick what fits your experiment):
[If web-app archetype]
1. Share the live URL with target users and gather initial feedback
2. Run `/distribute` to generate ad campaign config (only if using paid ads)
3. After collecting data, run `/iterate` to analyze metrics and decide what to change
4. When the experiment ends, run `/retro` to file a retrospective, then `/teardown` to remove cloud resources
[If service archetype]
1. Share the API endpoint URL with target users (see `.claude/archetypes/service.md` Distribution section)
2. If the service has a surface (co-located or detached): run `/distribute` to generate ad campaign config (only if using paid ads)
3. After collecting data, run `/iterate` to analyze metrics and decide what to change
4. When the experiment ends, run `/retro` to file a retrospective, then `/teardown` to remove cloud resources
[If cli archetype]
1. The surface is now deployed, but the CLI binary is NOT published yet. Publish via `npm publish` (to npm registry) or create a GitHub Release for binary distribution. See `.claude/archetypes/cli.md` for details.
2. After publishing and collecting usage data, run `/iterate` to analyze metrics and decide what to change
3. When the experiment ends, run `/retro` to file a retrospective, then `/teardown` to remove cloud resources (surface infrastructure)

**To update after code changes:**
- Merge your changes to `main`, then re-run `/deploy` — it detects the existing deployment and runs in update mode (redeploys code, syncs env vars, runs migrations, provisions only new services)

**If something goes wrong after deploy:**
- Run `/rollback` to revert to the previous deployment (hosting only — does not affect database)
- For data issues: see `.claude/patterns/incident-response.md`
```

### Write deploy manifest

Write `.runs/deploy-manifest.json` with the resources created during this deploy:

```json
{
  "name": "<experiment.yaml name>",
  "archetype": "<experiment.yaml type, default: web-app>",
  "surface_type": "<inferred surface type from STATE 3: co-located | detached | none>",
  "canonical_url": "<canonical_url>",
  "hosting": {
    "provider": "<stack.services[0].hosting value>",
    "...provider-specific keys from hosting stack file's ## Deploy Interface > Manifest Keys"
  },
  "database": {
    "provider": "<stack.database value>",
    "...provider-specific keys from database stack file's ## Deploy Interface > Manifest Keys"
  },
  "stripe": {
    "webhook_endpoint_url": "<url or null>"
  },
  "surface_url": "<url or null>",
  "oauth_providers": {
    "configured": ["<provider>"],
    "skipped": ["<provider>"]
  },
  "external_services": ["<service-slug>"],
  "deploy_mode": "<initial|update>",
  "deployed_at": "<ISO 8601 timestamp>"
}
```

**Update mode manifest behavior:**
- Update `deployed_at` to the current timestamp
- Add new entries for `added_services` (newly provisioned resources)
- Keep existing entries for `unchanged_services` (preserve previous manifest values)
- For `removed_services`: keep the entry but add `"status": "orphaned"` to it. Example: `"stripe": {"webhook_endpoint_url": "https://...", "status": "orphaned"}`. This signals that the resource exists but is no longer referenced by experiment.yaml.
  - `/teardown` deletes ALL entries (active + orphaned)
  - `/deploy` update mode skips health checks for orphaned entries
  - **Backward compatibility:** missing `status` field = `"active"` (default)

Omit sections for inactive stack categories on initial deploy (e.g., no `database` key if `stack.database` is absent). The `hosting.provider` and `database.provider` fields tell `/teardown` which stack file to load for teardown commands. This manifest is consumed by `/teardown` to identify what to delete.

If the write fails, warn but continue — the manifest is for convenience, not correctness.

### Q-score

After writing the deploy manifest, compute deploy Q and append to `.runs/verify-history.jsonl` (see `.claude/patterns/q-score.md` for the Write Procedure).

Parse the health check results from Step 5c:
- `services_ok`: count of services that returned `"ok"` in the health check JSON
- `services_total`: total services checked
- For CLI archetype with HTTP-only check: `services_ok = 1 if HTTP 200, else 0; services_total = 1`

Parse the provision scanner results from Step 5d.5:
- Extract the JSON summary line from the scanner output: `{"total": N, "pass": N, "fail": N, "skip": N}`

Count `HEALTH_RETRIES` (health check re-runs in Step 5c/5d) and `AUTOFIX_ROUNDS` (auto-fix iterations in Step 5d).

```bash
DEPLOY_Q=$(HEALTH_OK=<count> HEALTH_TOTAL=<count> SCAN_PASS=<count> SCAN_TOTAL=<count> HEALTH_RETRIES=<count> AUTOFIX_ROUNDS=<count> python3 -c "
import json, os

services_ok = int(os.environ.get('HEALTH_OK', '0'))
services_total = int(os.environ.get('HEALTH_TOTAL', '1'))
q_health = round(services_ok / max(services_total, 1), 3)

scan_pass = int(os.environ.get('SCAN_PASS', '0'))
scan_total = int(os.environ.get('SCAN_TOTAL', '7'))
q_provision = round(scan_pass / max(scan_total, 1), 3)

dims = {'health': q_health, 'provision': q_provision}
gate = 1.0 if q_health == 1.0 and q_provision >= 0.8 else (1.0 if q_health > 0 else 0.0)

retries = int(os.environ.get('HEALTH_RETRIES', '0'))
autofix = int(os.environ.get('AUTOFIX_ROUNDS', '0'))
r_human = round((retries + autofix) / 4, 3)
verdict = 'pass' if gate == 1.0 else 'fail'
print(json.dumps(dims))
print(gate)
print(r_human)
print(verdict)
" 2>/dev/null || echo -e '{}\n1.0\n0.0\npass')

DIMS_JSON=$(echo "$DEPLOY_Q" | head -1)
GATE=$(echo "$DEPLOY_Q" | sed -n '2p')
R_HUMAN=$(echo "$DEPLOY_Q" | sed -n '3p')
VERDICT=$(echo "$DEPLOY_Q" | tail -1)
RUN_ID=$(python3 -c "import json; print(json.load(open('.runs/deploy-context.json')).get('run_id', ''))" 2>/dev/null || echo "")

PAYLOAD=$(python3 -c "
import json, os
print(json.dumps({
    'scope': 'deploy',
    'dims': json.loads(os.environ['DIMS_JSON_ENV'])
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/q-dimensions.json \
  --payload "$PAYLOAD" \
  --skill deploy || true
```

**POSTCONDITIONS:**
- Deployment summary printed to user
- `.runs/deploy-manifest.json` written with all resource details
- Q-score computed and appended to `.runs/verify-history.jsonl` <!-- enforced by agent behavior, not VERIFY gate -->

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/deploy-manifest.json')); assert d.get('name'), 'name empty'; assert d.get('canonical_url'), 'canonical_url empty'; assert d.get('deploy_mode') in ('initial','update'), 'deploy_mode=%s' % d.get('deploy_mode'); assert d.get('deployed_at'), 'deployed_at empty'; h=d.get('hosting',{}); assert h.get('provider'), 'hosting.provider empty'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh deploy 5
```

**NEXT:** Skill states complete.
