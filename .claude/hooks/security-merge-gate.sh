#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
parse_payload
exec_merge_gate "merge_gates.security.checks" "security-merge" "Security merge gate"
