# STATE 2

**ACTIONS:**

```bash
python3 -c "
import json
json.dump({'a': 1, 'b': 2}, open('.runs/q-dimensions.json', 'w'), indent=2)
"
```

**VERIFY:**
```bash
test -f .runs/q-dimensions.json
```

**STATE TRACKING:** Done.
