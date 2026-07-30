# STATE 4: CLEANUP

**PRECONDITIONS:**
- Deletion verified (STATE 3 POSTCONDITIONS met)

**ACTIONS:**

### Step 4: Cleanup

1. Delete `.runs/deploy-manifest.json`
2. Remove `.env.local` if it exists (contains deployed credentials that are now invalid).
   Ask user first: "`.env.local` contains credentials for the deleted infrastructure.
   Delete it? (y/n)"
3. Write cleanup manifest:
   ```bash
   PAYLOAD=$(python3 -c "
   import json, datetime
   manifest = {
       'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
       'deploy_manifest_deleted': True,
       'env_local_deleted': '<true-or-false>'
   }
   print(json.dumps(manifest))
   ")
   bash .claude/scripts/lib/write-gate-artifact.sh \
     --path .runs/teardown-cleanup.json \
     --payload "$PAYLOAD" \
     --skill teardown
   ```

### Q-score

Compute teardown quality (see `.claude/patterns/skill-scoring.md`):

```bash
RUN_ID=$(python3 -c "import json; print(json.load(open('.runs/teardown-context.json')).get('run_id', ''))" 2>/dev/null || echo "")
Q_DELETION=$(test ! -f .runs/deploy-manifest.json && echo "1.0" || echo "0.0")
PAYLOAD=$(Q_DELETION_ENV="$Q_DELETION" python3 -c "
import json, os
print(json.dumps({
    'scope': 'teardown',
    'dims': {'deletion': float(os.environ['Q_DELETION_ENV']), 'completion': 1.0}
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/q-dimensions.json \
  --payload "$PAYLOAD" \
  --skill teardown || true
```

### Step 5: Summary

```
## Teardown Complete

**Deleted:**
- [For each successfully deleted resource] <provider> <resource type> <id>
- PostHog dashboard #<id>

**Failed (manual cleanup needed):**
- <resource> — <dashboard URL from stack file's Teardown section>

**External services (manual cleanup):**
- <service> — <dashboard URL>

**Deletion Verification:**
[Include provision scanner output table from STATE 3]

**Local cleanup:**
- .runs/deploy-manifest.json deleted
- [.env.local deleted / .env.local kept]

**What's preserved:**
- All source code on main branch
- experiment.yaml, experiment/EVENTS.yaml (experiment definition)
- Migration files (can re-deploy with /deploy)

**Next steps:**
- To analyze results and decide direction: run `/iterate` (recommended before re-deploying)
- To implement changes based on learnings: run `/change` to modify the experiment
- To re-deploy with updated code: run `/deploy` (creates fresh infrastructure)
- To archive this experiment: `gh release create v1.0 --notes "Experiment <name> concluded"`
```

**POSTCONDITIONS:**
- `.runs/deploy-manifest.json` deleted
- `.env.local` deleted (if user approved) or kept
- Summary printed to user

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/teardown-cleanup.json')); assert d.get('timestamp'), 'timestamp empty'; assert d.get('deploy_manifest_deleted') is not None, 'deploy_manifest_deleted missing'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh teardown 4
```

**NEXT:** Skill states complete.
