# STATE 4

**STATE TRACKING:**
```bash
python3 -c "
import json
ctx = json.load(open('.runs/audit-context.json'))
ctx['classification'] = 'feature'
with open('.runs/audit-context.json', 'w') as f:
    json.dump(ctx, f, indent=2)
"
```
