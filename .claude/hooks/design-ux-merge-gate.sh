#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
parse_payload
exec_merge_gate "merge_gates.design_ux.checks" "design-ux-merge" "Design-UX merge gate"
