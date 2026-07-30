# STATE 2a

**ACTIONS:**
```bash
python3 -c "
import json
data1 = {'a': 1}
data2 = {'b': 2}
json.dump(data1, open('.runs/q-dimensions.json', 'w'))
json.dump(data2, open('.runs/change-context.json', 'w'))
"
```
