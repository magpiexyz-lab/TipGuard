#!/usr/bin/env bash
# stop-transient-services.sh — Tear down transient local services started by skills.
#
# Two modes:
#   --for-run <run_id>    Finalize path: stop the stack if the ownership marker's
#                         run_id matches, or if the current run_id appears in
#                         marker.ancestors_run_ids (covers /change->embed /verify).
#   --orphan-cleanup      Init path: (a) GC finalize-completed-*.flag files older
#                         than 7 days, (b) stop any skill-owned marker that has no
#                         matching finalize-completed flag (crash recovery), and
#                         (c) defensive reclaim — if supabase is running but there
#                         is no marker and no recent finalize-completed flag,
#                         assume an orphan (Claude bypassed the wrapper) and stop.
#
# Gates that cause exit 0 without doing anything:
#   - CI=true or GITHUB_ACTIONS=true
#   - experiment.yaml missing, OR stack.database != supabase, OR stack.services has no testing=playwright
#   - Docker daemon down (`docker info` fails)
#   - git-common-dir not resolvable
#
# Locking is via python3 fcntl.flock on <git-common-dir>/supabase.lock (macOS has
# no /usr/bin/flock). The stop command runs with a 60-second background kill
# watchdog so a hung Docker daemon cannot block finalize.
#
# Exit codes: 0 = success or gated-skip, 2 = usage error. All other failures are
# non-fatal (wrapped in `|| true`) so init/finalize are never blocked.

set -euo pipefail

MODE=""
RUN_ID=""
case "${1:-}" in
  --for-run)
    MODE="for-run"
    RUN_ID="${2:-}"
    if [[ -z "$RUN_ID" ]]; then
      echo "usage: $0 --for-run <run_id>" >&2
      exit 2
    fi
    ;;
  --orphan-cleanup)
    MODE="orphan"
    ;;
  *)
    echo "usage: $0 --for-run <run_id> | --orphan-cleanup" >&2
    exit 2
    ;;
esac

# --- Gate 1: CI (CI workflows have their own supabase stop in `if: always()`) ---
if [[ "${CI:-}" == "true" ]] || [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  exit 0
fi

PROJECT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || echo "${CLAUDE_PROJECT_DIR:-.}")"
EXPERIMENT_YAML="$PROJECT_DIR/experiment/experiment.yaml"

# --- Gate 2: stack.database=supabase AND stack.testing=playwright ---
if [[ ! -f "$EXPERIMENT_YAML" ]]; then
  exit 0
fi

STACK_CHECK=$(python3 - "$EXPERIMENT_YAML" << 'PYEOF'
import sys
try:
    import yaml
    d = yaml.safe_load(open(sys.argv[1])) or {}
except Exception:
    print("skip")
    sys.exit(0)
stk = d.get("stack", {}) or {}
svcs = stk.get("services", []) or []
testing_vals = [s.get("testing") for s in svcs if isinstance(s, dict)]
has_pw = "playwright" in testing_vals
if stk.get("database") == "supabase" and has_pw:
    print("go")
else:
    print("skip")
PYEOF
) || STACK_CHECK="skip"

if [[ "$STACK_CHECK" != "go" ]]; then
  exit 0
fi

# --- Gate 3: Docker daemon must be responsive ---
if ! docker info >/dev/null 2>&1; then
  exit 0
fi

# --- Resolve shared paths (worktrees share git-common-dir) ---
COMMON_DIR="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || echo "")"
if [[ -z "$COMMON_DIR" ]] || [[ ! -d "$COMMON_DIR" ]]; then
  exit 0
fi

MARKER="$COMMON_DIR/transient-resources.json"
LOCK="$COMMON_DIR/supabase.lock"

# --- Helper: run a command with an exclusive lock via python3 fcntl.flock ---
with_lock() {
  local cmd_file="$1"
  python3 - "$LOCK" "$cmd_file" << 'PYEOF'
import fcntl, subprocess, sys
lock_path, cmd_path = sys.argv[1], sys.argv[2]
with open(lock_path, "w") as lf:
    try:
        fcntl.flock(lf, fcntl.LOCK_EX)
        rc = subprocess.call(["bash", cmd_path])
        sys.exit(rc)
    finally:
        try:
            fcntl.flock(lf, fcntl.LOCK_UN)
        except Exception:
            pass
PYEOF
}

# --- Helper: build a stop command file (60s background kill watchdog) ---
# macOS lacks timeout(1); use backgrounded kill as portable equivalent.
make_stop_cmd() {
  local repo_root="$1"
  local project_id="$2"
  local cmd_file
  cmd_file="$(mktemp)"
  # All backgrounded commands close stdin/stdout/stderr so the parent process
  # (and any Python subprocess.run capturing pipes) does NOT wait for a 60-second
  # watchdog to exit before returning.
  if [[ -n "$project_id" ]]; then
    cat > "$cmd_file" <<EOF
cd "$repo_root" 2>/dev/null || cd "$PROJECT_DIR"
( npx supabase stop --project-id "$project_id" </dev/null >/dev/null 2>&1 ) &
pid=\$!
( sleep 60 && kill -9 \$pid </dev/null >/dev/null 2>&1 ) </dev/null >/dev/null 2>&1 &
watchdog=\$!
wait \$pid 2>/dev/null || true
kill -9 \$watchdog </dev/null >/dev/null 2>&1 || true
EOF
  else
    cat > "$cmd_file" <<EOF
cd "$repo_root" 2>/dev/null || cd "$PROJECT_DIR"
( npx supabase stop </dev/null >/dev/null 2>&1 ) &
pid=\$!
( sleep 60 && kill -9 \$pid </dev/null >/dev/null 2>&1 ) </dev/null >/dev/null 2>&1 &
watchdog=\$!
wait \$pid 2>/dev/null || true
kill -9 \$watchdog </dev/null >/dev/null 2>&1 || true
EOF
  fi
  echo "$cmd_file"
}

clear_supabase_marker() {
  python3 -c "
import json
try:
    d = json.load(open('$MARKER'))
except Exception:
    d = {}
d.pop('supabase', None)
if d:
    json.dump(d, open('$MARKER', 'w'), indent=2)
else:
    import os
    try: os.remove('$MARKER')
    except Exception: pass
" 2>/dev/null || true
}

# --- 7-day flag GC (orphan mode only) ---
if [[ "$MODE" == "orphan" ]]; then
  find "$COMMON_DIR" -maxdepth 1 -name 'finalize-completed-*.flag' -mtime +7 -delete 2>/dev/null || true
fi

# --- Marker absent ---
if [[ ! -f "$MARKER" ]]; then
  # No marker present → nothing we own is running from our perspective.
  # We deliberately do NOT "defensively reclaim" an unmarked running stack:
  # without a marker we cannot distinguish "user started supabase manually and
  # hasn't invoked the wrapper yet" (must preserve) from "Claude bypassed the
  # wrapper and left a stack running" (a leak). Preserving user state wins —
  # the Claude-bypass leak is documented as the Makefile path's known cost and
  # must be caught by the Makefile-delegates-to-wrapper change or manual cleanup.
  exit 0
fi

# --- Parse marker ---
# Emit a single pipe-delimited line so bash read can split it reliably.
# Fields: owner | run_id | ancestors (joined by \x1f) | project_id | repo_root
SUPA="$(python3 -c "
import json, sys
try:
    d = json.load(open('$MARKER'))
    s = (d.get('supabase') or {})
    if not s:
        print('none'); sys.exit(0)
    anc = '\x1f'.join(s.get('ancestors_run_ids') or [])
    print('%s|%s|%s|%s|%s' % (
        s.get('owner', ''),
        s.get('run_id', ''),
        anc,
        s.get('project_id', ''),
        s.get('repo_root', ''),
    ))
except Exception:
    print('none')
" 2>/dev/null)"

if [[ -z "$SUPA" ]] || [[ "$SUPA" == "none" ]]; then
  exit 0
fi

IFS='|' read -r OWNER M_RUN_ID M_ANCESTORS_JOINED M_PROJECT_ID M_REPO_ROOT <<< "$SUPA"

# --- Only touch skill-owned stacks ---
if [[ "$OWNER" != "skill" ]]; then
  exit 0
fi

# --- Determine whether to stop ---
should_stop="no"
if [[ "$MODE" == "for-run" ]]; then
  if [[ "$M_RUN_ID" == "$RUN_ID" ]]; then
    should_stop="yes"
  else
    # Ancestor match: split on \x1f and look for exact RUN_ID.
    OLD_IFS="$IFS"
    IFS=$'\x1f'
    # shellcheck disable=SC2206
    ANC_ARR=( $M_ANCESTORS_JOINED )
    IFS="$OLD_IFS"
    for a in "${ANC_ARR[@]}"; do
      if [[ "$a" == "$RUN_ID" ]]; then
        should_stop="yes"
        break
      fi
    done
  fi
elif [[ "$MODE" == "orphan" ]]; then
  if [[ -f "$COMMON_DIR/finalize-completed-$M_RUN_ID.flag" ]]; then
    # Already cleaned by a prior finalize — just remove stale marker.
    clear_supabase_marker
    exit 0
  fi
  should_stop="yes"
fi

if [[ "$should_stop" != "yes" ]]; then
  exit 0
fi

# --- Stop under lock ---
stop_cmd="$(make_stop_cmd "$M_REPO_ROOT" "$M_PROJECT_ID")"
# shellcheck disable=SC2064
trap "rm -f '$stop_cmd'" EXIT
if with_lock "$stop_cmd"; then
  clear_supabase_marker
else
  echo "[stop-transient] supabase stop returned non-zero (non-blocking)" >&2
  clear_supabase_marker
fi

exit 0
