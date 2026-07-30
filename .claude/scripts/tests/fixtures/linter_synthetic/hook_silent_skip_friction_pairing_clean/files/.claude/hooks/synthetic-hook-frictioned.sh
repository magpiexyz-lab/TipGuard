#!/usr/bin/env bash
# Synthetic clean fixture: friction-call within lookback window pairs the exit.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
parse_payload
_write_hook_friction "synthetic-hook: trace logged for retrospective audit"
exit 0
