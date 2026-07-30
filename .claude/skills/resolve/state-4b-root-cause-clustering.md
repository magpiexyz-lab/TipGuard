# STATE 4b: ROOT_CAUSE_CLUSTERING

**PRECONDITIONS:**
- Blast radius complete (STATE 4 POSTCONDITIONS met)
- 2+ actionable issues remain

**ACTIONS:**

If only 1 actionable issue remains, write a single-issue clustering artifact and advance:
```bash
PAYLOAD=$(python3 -c "
import json
# Single issue — no clustering possible. Write minimal artifact to satisfy VERIFY.
clusters = {'clusters': [], 'uncorrelated': [<issue_number>]}
print(json.dumps(clusters))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/resolve-clusters.json \
  --payload "$PAYLOAD" \
  --skill resolve
```
Then run STATE TRACKING (advance-state.sh below) and continue to next state.

For 2+ issues, compare divergence points and causal patterns across all actionable issues:

1. Group issues sharing the same root pattern (e.g., 3 issues all
   caused by "missing archetype guard" = 1 cluster)
2. For each cluster of 2+ issues:
   - Designate the highest-severity issue as **primary**
   - Mark others as **correlated**: "shares root cause with #N"
   - Design ONE unified fix in Step 5 (not N separate fixes)
3. Uncorrelated issues get individual fix designs as before

Present in diagnosis report:
```
### Root-Cause Clusters
- Cluster 1 (#A, #B): <shared pattern>. Primary: #A.
- Uncorrelated: #C
```

- **Write clustering artifact** (`.runs/resolve-clusters.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  clusters = {
      'clusters': [
          {'primary_issue': 0, 'related_issues': [], 'root_cause': '<shared root cause>'}
      ],
      'uncorrelated': []
  }
  print(json.dumps(clusters))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/resolve-clusters.json \
    --payload "$PAYLOAD" \
    --skill resolve
  ```

**POSTCONDITIONS:**
- Issues grouped into clusters (or marked uncorrelated)
- Each cluster has a designated primary issue
- `.runs/resolve-clusters.json` exists

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/resolve-clusters.json')); cs=d.get('clusters',[]); assert isinstance(cs, list), 'clusters not a list'; assert isinstance(d.get('uncorrelated'), list), 'uncorrelated not a list'; [c.get('root_cause') or (_ for _ in ()).throw(AssertionError('cluster missing root_cause')) for c in cs]"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh resolve 4b
```

**NEXT:** Read [state-5-fix-design.md](state-5-fix-design.md) to continue.
