# Incident Response

This pattern covers how to respond to production incidents in deployed experiments.

## Severity Classification

| Severity | Definition | Response Time | Examples |
|----------|-----------|---------------|----------|
| **P0** | Service completely down, data loss risk | Immediate | App returns 5xx for all users, database corruption, leaked secrets |
| **P1** | Major feature broken, significant user impact | < 1 hour | Auth flow broken, payment processing failing, main page crashes |
| **P2** | Minor feature broken, workaround exists | < 1 day | Styling broken on one page, non-critical API returning errors, analytics not firing |

## Immediate Response

### 1. Assess Severity

- Check canonical URL: `curl -s <canonical_url>/api/health`
- Check error logs in hosting provider dashboard
- Determine scope: all users vs. subset vs. edge case

### 2. Rollback (P0/P1)

For P0 and P1 incidents, rollback first, investigate later.

Run `/rollback` to revert to the previous deployment. This reverts hosting only — database changes are NOT rolled back.

#### Vercel

- **CLI:** `vercel rollback`
- **Dashboard:** Vercel → Deployments → select previous successful deployment → "..." → "Promote to Production"
- Rollback is instant — no rebuild required

#### Railway

- **Dashboard:** Railway → Deployments → select previous successful deployment → "Redeploy"
- No single CLI command for rollback — use the dashboard

### 3. Database Recovery

Database changes are NOT rolled back by hosting rollback. If the incident involves data:

#### Supabase

- **Point-in-time recovery:** Supabase Dashboard → Database → Backups (7-day retention on Pro plan)
- **Manual fix:** Connect via `psql` and run corrective SQL
- For migration rollback: write a reverse migration via `/change fix`

#### SQLite

- **Volume backup:** Restore from the most recent volume snapshot (provider-specific)
- **Manual fix:** Connect to the running instance and run corrective SQL
- SQLite has no automatic point-in-time recovery — ensure backups are configured

### 4. Secret Rotation

If secrets may have been exposed:

1. Generate new keys/secrets from the provider's dashboard
2. Update environment variables using the hosting stack file's env var method:
   - **Vercel:** `vercel env rm <KEY> production && vercel env add <KEY> production`
   - **Railway:** Railway Dashboard → Variables → update value
3. Redeploy to pick up new env vars
4. Revoke the old keys from the provider's dashboard

## Root Cause Analysis

After the immediate response:

1. **What changed?** Check the most recent PR and deploy. `git log --oneline -5` and review deploy-manifest.json
2. **Why did `/verify` miss it?** Was it a build-time issue, runtime-only issue, or environment-specific?
3. **File a fix:** Run `/change fix <description of root cause>` to prevent recurrence
4. **Template-level root cause?** If the issue stems from a template file (stack file, pattern, skill), follow `.claude/patterns/observe.md` to file a template observation

## Secret Rotation Schedule

Rotate secrets on a regular schedule, not just after incidents:

| Secret Type | Rotation Interval | Method |
|------------|-------------------|--------|
| API keys (analytics, payment, etc.) | 90 days | Regenerate in provider dashboard, update env vars |
| Webhook signing secrets | 90 days | Regenerate in provider dashboard, update env vars |
| Database passwords | 90 days | Reset in database provider dashboard, update env vars |
| OAuth client secrets | 90 days | Regenerate in OAuth provider dashboard, update env vars |

After rotating any secret:
1. Update env vars in hosting provider
2. Redeploy
3. Verify the app still works: `curl -s <canonical_url>/api/health`
