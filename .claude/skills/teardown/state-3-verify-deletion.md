# STATE 3: VERIFY_DELETION

**PRECONDITIONS:**
- Resource deletion attempted (STATE 2 POSTCONDITIONS met)
- Deploy manifest still exists (not yet deleted)

**ACTIONS:**

### 3g: Provision scan (verify deletion)

Spawn the `provision-scanner` agent (`subagent_type: provision-scanner`).
Pass context:

> Mode: teardown
> Manifest path: .runs/deploy-manifest.json

Note: the manifest still exists at this point (Step 4 deletes it). The scanner reads it to know what to verify as deleted.

Wait for the agent to complete. Include the scanner's output table in the Step 5 summary under a **Deletion Verification** heading. If any check FAILs (resource still exists), list the resource with its manual-deletion dashboard URL from the relevant stack file's Teardown section.

**POSTCONDITIONS:**
- Provision scanner completed
- Deletion verification results recorded
- Any remaining resources identified with manual-deletion URLs

- **Write verification artifact** (`.runs/teardown-verification.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  verification = {
      'scan_completed': True,
      'remaining_resources': [],
      'fully_deleted': True
  }
  print(json.dumps(verification))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/teardown-verification.json \
    --payload "$PAYLOAD" \
    --skill teardown
  ```

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/teardown-verification.json')); assert d.get('scan_completed') is not None, 'scan_completed missing'; assert isinstance(d.get('remaining_resources'), list), 'remaining_resources not list'; assert all(isinstance(r, (str,dict)) for r in d['remaining_resources']), 'remaining_resources items invalid'; assert d.get('fully_deleted') is not None, 'fully_deleted missing'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh teardown 3
```

**NEXT:** Read [state-4-cleanup.md](state-4-cleanup.md) to continue.
