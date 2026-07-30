# STATE 2: USER_APPROVAL

**PRECONDITIONS:**
- Configuration gathered (STATE 1 POSTCONDITIONS met)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app + service hosting: full deploy plan | cli detached / web-app detached: surface-only deploy plan

Present a summary based on `deploy_mode`:

### Initial mode plan

```
## Deployment Plan

**Hosting (<provider>):** <name> (<team/account info from Config Gathering>)
**Database (<provider>):** <name> (<org/account info from Config Gathering>)
**Environment variables:** <list of env vars to be set>
**Migrations:** <N migration files will be applied>

**External service credentials (post-deploy):**
- [service] — auto via CLI (`<cli>` installed + authed)
- [service] — manual setup — CLI `<cli>` available but not installed (`<install-cmd>`)
- [service] — manual setup (no CLI)
- (Or: "None")

Reply **approve** to proceed, or tell me what to change.
```

### Update mode plan

```
## Update Deploy Plan

**Code redeploy:** YES — `<deploy command from hosting stack file>`
**DB migrations:** YES — idempotent (already-applied migrations are no-ops)
**Environment variables:** upsert sync from .env.example

**Added services** (full provisioning):
- [service] — <config gathered>
- (Or: "None — no new stack entries since last deploy")

**Removed services** (marked orphaned in manifest):
- [service] — will not be torn down; run `/teardown` to clean up
- (Or: "None")

**Unchanged services** (health check only):
- [service] — skip provisioning, verify health
- (Or: "None")

Reply **approve** to proceed, or tell me what to change.
```

### Surface-only mode plan

If the deployment is surface-only (archetype's `excluded_stacks` includes `hosting` and surface is `detached`):

```
## Surface-Only Deployment Plan

**Surface deployment:** Vercel (or configured surface hosting provider)
**No hosting/database infrastructure:** This archetype uses `surface: detached` — only the marketing surface will be deployed.

Reply **approve** to proceed, or tell me what to change.
```

**STOP.** Do not proceed until the user approves.

If the user requests changes, revise the plan and present it again. Repeat until approved.

- **Record approval** in `deploy-context.json`:
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  ctx = json.load(open('.runs/deploy-context.json'))
  ctx['approved'] = True
  print(json.dumps(ctx))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/deploy-context.json \
    --payload "$PAYLOAD" \
    --skill deploy
  ```

**POSTCONDITIONS:**
- User has explicitly approved the deployment plan
- `approved` field set to `true` in `deploy-context.json`

**VERIFY:**
```bash
python3 -c "import json; assert json.load(open('.runs/deploy-context.json')).get('approved') == True, 'approved not set'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh deploy 2
```

**NEXT:** Read [state-3a-provision-db.md](state-3a-provision-db.md) to continue.
