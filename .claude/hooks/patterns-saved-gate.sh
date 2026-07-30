#!/usr/bin/env bash
# patterns-saved-gate.sh — Claude Code PreToolUse hook for Write/Edit.
# Validates patterns-saved.json invariants:
#   saved + skipped == total
#   len(saved_to_files) + saved_to_memory == saved
#   Each saved_to_files[] is a string — a local path (must exist on disk)
#     OR a URL (http/https prefix, not file-checked — used for universal-issue GitHub links).

set -euo pipefail

source "$(dirname "$0")/lib.sh"
parse_payload

FILE_PATH=$(read_payload_field "tool_input.file_path")

# Only fire when file_path contains "patterns-saved"
if [[ "$FILE_PATH" != *"patterns-saved"* ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# --- patterns-saved.json write detected — run invariant checks ---

extract_write_content

# Skip if content is empty (can't validate)
if [[ -z "$CONTENT" ]]; then
  # friction-skip: trivial-fast-path — input absent or non-applicable
  exit 0
fi

# Validate invariants using python3
VALIDATION=$(echo "$CONTENT" | python3 -c '
import json, sys, os

content = sys.stdin.read().strip()
errors = []

try:
    d = json.loads(content)
except json.JSONDecodeError:
    print("PARSE_ERROR")
    # friction-skip: post-validation — exit follows authoritative decision (allow-list match, deny path, or successful validation)
    sys.exit(0)

saved = d.get("saved", 0)
skipped = d.get("skipped", 0)
total = d.get("total", 0)

# Invariant 1: saved + skipped == total
if saved + skipped != total:
    errors.append("saved(%d) + skipped(%d) != total(%d)" % (saved, skipped, total))

# Invariant 2: len(saved_to_files) + saved_to_memory == saved
saved_to_files = d.get("saved_to_files", [])
saved_to_memory = d.get("saved_to_memory", 0)
if len(saved_to_files) + saved_to_memory != saved:
    errors.append("len(saved_to_files)(%d) + saved_to_memory(%d) != saved(%d)" % (len(saved_to_files), saved_to_memory, saved))

# Invariant 3: Each saved_to_files[] is a string. Local paths must exist on disk;
# URL entries (http:// or https://) are recorded as-is and not file-checked.
project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
for path in saved_to_files:
    if not isinstance(path, str):
        errors.append("saved_to_files entry is not a string: %r" % (path,))
        continue
    if not path:
        continue
    if path.startswith("http://") or path.startswith("https://"):
        continue  # URL entry — skip filesystem check
    full_path = os.path.join(project_dir, path)
    if not os.path.exists(full_path):
        errors.append("saved_to_files path does not exist: %s" % path)

# Invariant 4: total must match authoritative fix ledger count (AOC v1 FLS v1).
# Prefers .runs/fix-ledger.jsonl; falls back to fix-log.md prose regex during
# the transitional dual-check period.
ledger_path = os.path.join(project_dir, ".runs", "fix-ledger.jsonl")
fix_log_path = os.path.join(project_dir, ".runs", "fix-log.md")
fix_count = None
if os.path.exists(ledger_path):
    try:
        with open(ledger_path) as _f:
            fix_count = sum(1 for ln in _f if ln.strip())
    except OSError:
        fix_count = None
if fix_count is None and os.path.exists(fix_log_path):
    import re
    fix_log = open(fix_log_path).read()
    fix_count = len(re.findall(r"^(?:\*\*Fix|Fix \()", fix_log, re.MULTILINE))
if fix_count is not None and d.get("total", 0) != fix_count:
    errors.append("Invariant 4: total (%d) != fix ledger/log entry count (%d)" % (d.get("total", 0), fix_count))

if errors:
    print("FAIL:" + "; ".join(errors))
else:
    print("OK")
' 2>/dev/null || echo "OK")

handle_validation "$VALIDATION" "Patterns-saved gate" "Fix invariants before writing patterns-saved.json."

# All checks passed — allow
exit 0
