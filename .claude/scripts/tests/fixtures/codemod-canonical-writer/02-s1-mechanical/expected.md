# STATE 4

**STATE TRACKING:**
```bash
PAYLOAD=$(python3 -c "
import json
ctx = json.load(open('.runs/audit-context.json'))
ctx['classification'] = 'feature'
print(json.dumps(ctx))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/audit-context.json \
  --payload "$PAYLOAD" \
  --skill audit
```
