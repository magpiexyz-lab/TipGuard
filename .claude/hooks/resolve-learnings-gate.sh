#!/usr/bin/env bash
# resolve-learnings-gate.sh — Claude Code PreToolUse hook for Write/Edit.
# Validates .runs/resolve-learnings.json schema invariants written by
# /resolve STATE 9. Mirrors the shape of patterns-saved-gate.sh but targets
# the new self-learning artifact.
#
# Invariants:
#   learnings         : list
#   target_stacks     : list
#   proposals_filed   : list
#   halt_events       : list
#   pending_proposals : list
#   gh_failed         : bool
#   every entry in learnings has a 12-hex-char composite_identity_hash
#   if gh_failed == true → pending_proposals must be non-empty (no silent drop)

set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

FILE_PATH=$(read_payload_field "tool_input.file_path")

# Only fire when file_path contains "resolve-learnings"
if [[ "$FILE_PATH" != *"resolve-learnings"* ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

extract_write_content

# Skip if content is empty (can't validate)
if [[ -z "$CONTENT" ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

VALIDATION=$(echo "$CONTENT" | python3 -c '
import json, re, sys

content = sys.stdin.read().strip()
errors = []

try:
    d = json.loads(content)
except json.JSONDecodeError:
    print("PARSE_ERROR")
    # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
    sys.exit(0)

def require_list(key):
    v = d.get(key)
    if not isinstance(v, list):
        errors.append("%s must be a list, got %s" % (key, type(v).__name__))
    return v if isinstance(v, list) else []

learnings = require_list("learnings")
require_list("target_stacks")
require_list("proposals_filed")
require_list("halt_events")
pending = require_list("pending_proposals")

gh_failed = d.get("gh_failed")
if not isinstance(gh_failed, bool):
    errors.append("gh_failed must be bool, got %s" % type(gh_failed).__name__)

hash_re = re.compile(r"^[0-9a-f]{12}$")
for i, entry in enumerate(learnings):
    if not isinstance(entry, dict):
        errors.append("learnings[%d] is not an object" % i)
        continue
    h = entry.get("composite_identity_hash")
    if not isinstance(h, str) or not hash_re.match(h):
        errors.append("learnings[%d] composite_identity_hash invalid (%r)" % (i, h))

if gh_failed is True and not pending:
    errors.append("gh_failed=true but pending_proposals is empty (silent drop)")

if errors:
    print("FAIL:" + "; ".join(errors))
else:
    print("OK")
' 2>/dev/null || echo "OK")

handle_validation "$VALIDATION" "Resolve-learnings gate" "Fix invariants before writing resolve-learnings.json."

exit 0
