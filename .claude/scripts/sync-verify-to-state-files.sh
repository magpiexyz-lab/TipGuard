#!/usr/bin/env bash
# sync-verify-to-state-files.sh — One-directional sync: registry -> state files.
# Reads state-registry.json and overwrites VERIFY code fences in state files.
# Skips VERIFY=true entries (preserves justification comments).
# Usage: bash .claude/scripts/sync-verify-to-state-files.sh [--dry-run]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REGISTRY="$REPO_ROOT/.claude/patterns/state-registry.json"
SKILLS_DIR="$REPO_ROOT/.claude/skills"
PATTERNS_DIR="$REPO_ROOT/.claude/patterns"
DRY_RUN="${1:-}"

if [[ ! -f "$REGISTRY" ]]; then
  echo "ERROR: state-registry.json not found at $REGISTRY" >&2
  exit 1
fi

python3 - "$REGISTRY" "$SKILLS_DIR" "$PATTERNS_DIR" "$DRY_RUN" <<'PYTHON_SCRIPT'
import json, sys, os, glob, re

registry_path = sys.argv[1]
skills_dir = sys.argv[2]
patterns_dir = sys.argv[3]
dry_run = len(sys.argv) > 4 and sys.argv[4] == "--dry-run"

registry = json.load(open(registry_path))
SKIP_KEYS = {"trace_schemas"}
SKILL_DIR_MAP = {
    "iterate-check": "iterate",
    "iterate-cross": "iterate",
    "iterate-cross-phase2": "iterate",
}

updated = 0
skipped_true = 0
skipped_no_fence = 0
already_synced = 0
errors = 0

def extract_verify_cmd(value):
    """Extract the VERIFY command string from a registry entry."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and "verify" in value:
        return value["verify"]
    return None

for skill, states in registry.items():
    if skill in SKIP_KEYS or not isinstance(states, dict):
        continue
    for state_id, value in states.items():
        if state_id.startswith('_'):
            continue

        verify_cmd = extract_verify_cmd(value)
        if verify_cmd is None:
            continue

        # Skip true entries — preserve existing prose + justification
        if verify_cmd.strip() == "true":
            skipped_true += 1
            continue

        # Find state file (skill dir first, then patterns dir for shared terminal
        # states like state-99-epilogue.md)
        directory = SKILL_DIR_MAP.get(skill, skill)
        pattern = os.path.join(skills_dir, directory, f"state-{state_id}-*.md")
        matches = glob.glob(pattern)
        if not matches:
            patterns_pattern = os.path.join(patterns_dir, f"state-{state_id}-*.md")
            matches = glob.glob(patterns_pattern)
        if not matches:
            print(f"WARNING: No state file for [{skill}:{state_id}]", file=sys.stderr)
            errors += 1
            continue
        filepath = matches[0]

        # Read file
        content = open(filepath).read()

        # Find **VERIFY:** header
        verify_header = re.search(r'^\*\*VERIFY:\*\*', content, re.MULTILINE)
        if not verify_header:
            print(f"WARNING: [{skill}:{state_id}] No **VERIFY:** header in {os.path.basename(filepath)}", file=sys.stderr)
            skipped_no_fence += 1
            continue

        # Find code fence after the VERIFY header
        after_header = content[verify_header.end():]
        fence_match = re.search(r'(```bash\s*\n)(.*?)(```)', after_header, re.DOTALL)
        if not fence_match:
            print(f"WARNING: [{skill}:{state_id}] No ```bash fence after **VERIFY:** in {os.path.basename(filepath)}", file=sys.stderr)
            skipped_no_fence += 1
            continue

        # Safety: ensure the fence is before **STATE TRACKING:**
        between = after_header[:fence_match.start()]
        if '**STATE TRACKING:**' in between:
            print(f"WARNING: [{skill}:{state_id}] Code fence appears after STATE TRACKING in {os.path.basename(filepath)}", file=sys.stderr)
            skipped_no_fence += 1
            continue

        # Check if already in sync
        old_content = fence_match.group(2)
        new_fence_content = verify_cmd + "\n"
        if old_content.strip() == verify_cmd.strip():
            already_synced += 1
            continue

        # Compute absolute positions in original content
        abs_start = verify_header.end() + fence_match.start() + len(fence_match.group(1))
        abs_end = abs_start + len(fence_match.group(2))

        new_content = content[:abs_start] + new_fence_content + content[abs_end:]

        if dry_run:
            print(f"WOULD UPDATE: [{skill}:{state_id}] {os.path.basename(filepath)}")
        else:
            with open(filepath, 'w') as f:
                f.write(new_content)
            print(f"UPDATED: [{skill}:{state_id}] {os.path.basename(filepath)}")
        updated += 1

print(f"\nSync complete: {updated} updated, {already_synced} already synced, "
      f"{skipped_true} skipped (true), {skipped_no_fence} skipped (no fence), {errors} errors")
PYTHON_SCRIPT
