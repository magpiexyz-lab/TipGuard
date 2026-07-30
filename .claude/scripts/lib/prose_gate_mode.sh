#!/usr/bin/env bash
# prose_gate_mode.sh — bash wrapper for prose_gate_mode.py.
#
# Usage:
#   MODE=$(bash .claude/scripts/lib/prose_gate_mode.sh <gate_id> [<prior_default>])
#
# Returns "warn" or "deny" on stdout. Exits non-zero on configuration error
# (gate not in registry, or binary gate without fail_mode field).
#
# See prose_gate_mode.py module docstring for resolution chain.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 -c "
import sys
sys.path.insert(0, '$HERE')
from prose_gate_mode import resolve, ProseGateError
try:
    gate_id = sys.argv[1]
    prior_default = sys.argv[2] if len(sys.argv) > 2 else 'warn'
    print(resolve(gate_id, prior_default))
except ProseGateError as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
" "$@"
