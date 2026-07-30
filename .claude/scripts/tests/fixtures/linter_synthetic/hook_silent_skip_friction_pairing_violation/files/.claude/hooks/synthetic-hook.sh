#!/usr/bin/env bash
# Synthetic test fixture for hook_silent_skip_friction_pairing rule.
# This hook contains multiple unfrictioned, un-pragma'd `exit 0` forms
# that the rule must flag — covers regex coverage regression test for
# the && / || chain forms (#1349 follow-up: original regex required
# \b before && which fails on `]] && exit 0`).
set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

FILE_PATH=$(read_payload_field "tool_input.file_path")
if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# Form 1: bare `exit 0` with no preceding friction call AND no pragma.
exit 0

# Form 2: `]] && exit 0` (regex regression — must match even when char
# before && is non-word).
[[ -z "$X" ]] && exit 0

# Form 3: `]] || exit 0` (same regex regression).
[[ -z "$X" ]] || exit 0
