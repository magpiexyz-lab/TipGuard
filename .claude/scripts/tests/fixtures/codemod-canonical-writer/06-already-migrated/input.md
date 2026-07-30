# STATE 0

**ACTIONS:**
```bash
PAYLOAD=$(python3 -c "
import json
print(json.dumps({'a': 1}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/q-dimensions.json \
  --payload "$PAYLOAD" \
  --skill audit
```
