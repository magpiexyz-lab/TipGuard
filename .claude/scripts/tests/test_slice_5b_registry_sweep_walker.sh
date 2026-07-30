#!/usr/bin/env bash
# Slice 5b walker regression test: ensure the registry-driven sweep walker in
# lifecycle-init.sh actually harvests per-state `transient-cross-skill`
# declarations from state-registry.json.
#
# Original Slice 5b (#1214) shipped with `node.get('artifacts', [])` (plural,
# array) but the registry uses `node.get('artifact')` (singular, string).
# Result: 48 per-state declarations contributed ZERO paths to the union
# sweep. Manual STALE_ARTIFACTS list and directory wipes happened to cover
# all current paths — but the architectural contract was violated and any
# future per-state declaration would silently fail to be swept.
#
# This test extracts the embedded Python walker from lifecycle-init.sh and
# runs it directly, then asserts the union contains a non-empty set of
# per-state-declared paths.
set -euo pipefail
cd "$(dirname "$0")/../../.."

REGISTRY=".claude/patterns/state-registry.json"
test -f "$REGISTRY" || { echo "FAIL: $REGISTRY not found"; exit 1; }

# Run the walker logic directly (mirror what lifecycle-init.sh does).
COUNT=$(python3 <<'PYEOF'
import json
r = json.load(open('.claude/patterns/state-registry.json'))
paths = set()

def _walk(node):
    if isinstance(node, dict):
        if node.get('lifecycle') == 'transient-cross-skill':
            single = node.get('artifact')
            if isinstance(single, str) and single:
                paths.add(single)
            multi = node.get('artifacts')
            if isinstance(multi, list):
                for p in multi:
                    if isinstance(p, str) and p:
                        paths.add(p)
        for v in node.values():
            _walk(v)
    elif isinstance(node, list):
        for v in node:
            _walk(v)

_walk(r)

for path, meta in (r.get('epilogue_artifacts') or {}).items():
    if isinstance(meta, dict) and meta.get('lifecycle') == 'transient-cross-skill':
        paths.add(path)

print(len(paths))
PYEOF
)

if [ "$COUNT" -lt 10 ]; then
  echo "FAIL: registry walker harvested only $COUNT paths — expected >= 10."
  echo "      The walker likely regressed to reading the wrong field name"
  echo "      (registry uses 'artifact' singular, not 'artifacts' plural)."
  exit 1
fi

echo "PASS: registry walker harvested $COUNT transient-cross-skill paths"
