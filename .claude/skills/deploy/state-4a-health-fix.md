# STATE 4a: HEALTH_FIX

**PRECONDITIONS:**
- Infrastructure provisioned and deployed (STATE 3c POSTCONDITIONS met)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
>
> State-specific logic below takes precedence.

### 5c: Health check

If archetype is `cli` (surface-only deployment): skip the `/api/health` check — CLI surfaces are static HTML pages with no API routes. Instead, verify the surface loads:
```bash
curl -s -o /dev/null -w "%{http_code}" <canonical_url>
```
If HTTP 200 -> proceed to Step 5e. If not -> report to the user:

> Surface returned HTTP <code>. Recovery options:
> 1. **Wait and retry** — DNS propagation can take 1-5 minutes after first deploy. Re-run the curl command above.
> 2. **Check hosting dashboard** — see the hosting stack file's `## Deploy Interface > Teardown` for the dashboard URL. Verify the deployment succeeded and the domain is configured.
> 3. **Redeploy** — re-run `/deploy` (it is idempotent — safe to repeat).
> 4. **Teardown and restart** — run `/teardown` to remove partial infrastructure, then retry `/deploy`.

Skip Step 5d (no services to auto-fix for static surfaces).

For all other archetypes:

The default health endpoint is `/api/health` (created by bootstrap for web-app and service archetypes). If the deployed app uses a non-standard health endpoint, read the framework stack file for the actual route convention.

```bash
curl -s <canonical_url>/api/health
```
Parse the JSON response. Each service returns `"ok"` or an error message.

If all checks pass -> proceed to Step 5d.5.

### 5d: Auto-fix (max 2 rounds)

If any health check fails, diagnose and attempt to fix:

| Check | Diagnosis | Auto-fix |
|-------|-----------|----------|
| `database` | Re-extract keys using database stack file's Provisioning steps. Compare with hosting stack file's `## Deploy Interface > Auto-Fix` verify command. | If mismatch: re-set env vars using hosting stack file's env var method, then redeploy |
| `auth` | Re-check auth config via database stack file's `## Deploy Interface > Auth Config` | Re-run the auth config step |
| `analytics` | Code integration issue — cannot fix via CLI | Report: "Analytics health check failed. This is a code issue — the analytics library is not initializing correctly in production. Recovery: 1. Run `/rollback` to revert to the last working deployment. 2. Run `/change fix analytics integration` to diagnose and fix the issue locally. 3. After the fix PR is merged to `main`, re-run `/deploy`." |
| `payment` | Verify webhook: `stripe webhook_endpoints list`. Check env var using hosting stack file's Auto-Fix verify command. | Re-set env vars if missing/wrong, redeploy |

After all fixable issues are addressed:
- If any env vars were changed -> batch into a single redeploy using the hosting stack file's `## Deploy Interface > Deploy` command
- Re-run health check: `curl -s <canonical_url>/api/health`

If still failing after 2 fix rounds -> report precise per-service diagnosis with actionable next steps.

- **Write intermediate artifact** (`.runs/deploy-health-4a.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  artifact = {
      'health_check_passed': True,  # or False
      'auto_fix_rounds': 0,         # 0, 1, or 2
      'per_service_results': {}     # service -> ok/error
  }
  print(json.dumps(artifact))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/deploy-health-4a.json \
    --payload "$PAYLOAD" \
    --skill deploy
  ```

**POSTCONDITIONS:**
- Health check executed against canonical_url
- Auto-fix attempted if health check failed (max 2 rounds)
- `.runs/deploy-health-4a.json` exists

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/deploy-health-4a.json')); assert isinstance(d.get('health_check_passed'), bool), 'health_check_passed not bool'; assert isinstance(d.get('auto_fix_rounds'), int) and d['auto_fix_rounds']>=0, 'auto_fix_rounds invalid'; assert isinstance(d.get('per_service_results'), dict) and len(d['per_service_results'])>0, 'per_service_results empty'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh deploy 4a
```

**NEXT:** Read [state-4b-production-validation.md](state-4b-production-validation.md) to continue.
