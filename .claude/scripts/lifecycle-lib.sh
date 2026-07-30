#!/usr/bin/env bash
# lifecycle-lib.sh — Shared functions for lifecycle scripts.
# Facade: sourced by lifecycle-finalize.sh, lifecycle-next.sh, advance-state.sh,
# and state-completion-gate.sh. Provides unified context path, registry key,
# and skill directory resolution with mode awareness.
#
# Requires: caller sets PROJECT_DIR before calling any function.

# --- resolve_context_path <skill> [manifest_path] ---
# Outputs the full context file path to stdout.
# - verify → .runs/verify-context.json
# - manifest with active_mode (non-empty, non-"default") → .runs/{skill}-{mode}-context.json
# - fallback → .runs/{skill}-context.json
resolve_context_path() {
  local skill="$1"
  local manifest="${2:-}"

  if [[ "$skill" == "verify" ]]; then
    echo "$PROJECT_DIR/.runs/verify-context.json"
    return
  fi

  if [[ -n "$manifest" && -f "$manifest" ]]; then
    local ctx_skill
    ctx_skill=$(python3 -c "
import json
m=json.load(open('$manifest'))
am=m.get('active_mode','')
sk='$skill'
print('%s-%s'%(sk,am) if am and am!='default' else sk)
" 2>/dev/null || echo "$skill")
    echo "$PROJECT_DIR/.runs/${ctx_skill}-context.json"
  else
    echo "$PROJECT_DIR/.runs/${skill}-context.json"
  fi
}

# --- resolve_registry_key <skill> [manifest_path] ---
# Outputs the state-registry.json lookup key to stdout.
# - manifest with active_mode (non-empty, non-"default") → {skill}-{mode}
# - fallback → {skill}
resolve_registry_key() {
  local skill="$1"
  local manifest="${2:-}"

  if [[ -n "$manifest" && -f "$manifest" ]]; then
    python3 -c "
import json
m=json.load(open('$manifest'))
am=m.get('active_mode','')
sk='$skill'
print('%s-%s'%(sk,am) if am and am!='default' else sk)
" 2>/dev/null || echo "$skill"
  else
    echo "$skill"
  fi
}

# --- resolve_skill_dir <skill> ---
# Outputs "{directory} {mode}" or just "{directory}" to stdout.
# Maps mode-qualified skill names to their .claude/skills/ directory and mode.
# - iterate-check → iterate check
# - iterate-cross → iterate cross
# - iterate-cross-phase2 → iterate cross-phase2
# The fallback arm derives the split from the filesystem so future modes and
# skills resolve without extending the case list (issue #1990: an unresolved
# mode-qualified key made lifecycle-finalize.sh read the wrong command file and
# manifest, defeating the analysis-only delivery gate):
# - a name whose .claude/skills/<name>/skill.yaml exists is a plain skill
#   (covers legitimately hyphenated skills like ads-ready)
# - otherwise hyphen segments are stripped right-to-left; the first base whose
#   skill.yaml exists wins, with the candidate mode validated against the
#   base's .runs/<base>-lifecycle.json modes when that manifest is readable
#   (mismatch → warn and keep scanning; manifest missing/unreadable → accept,
#   fail-open — this is a resolution aid, not a gate)
# - no match → the name is echoed unchanged (previous behavior)
resolve_skill_dir() {
  local skill="$1"
  case "$skill" in
    iterate-check) echo "iterate check" ;;
    iterate-cross) echo "iterate cross" ;;
    iterate-cross-phase2) echo "iterate cross-phase2" ;;
    *)
      local root="${PROJECT_DIR:-.}"
      if [[ -f "$root/.claude/skills/$skill/skill.yaml" ]]; then
        echo "$skill"
        return
      fi
      local base="$skill" mode=""
      while [[ "$base" == *-* ]]; do
        base="${base%-*}"
        mode="${skill#"$base"-}"
        if [[ -f "$root/.claude/skills/$base/skill.yaml" ]]; then
          local manifest="$root/.runs/${base}-lifecycle.json"
          if [[ -f "$manifest" ]]; then
            local mode_known
            mode_known=$(python3 -c "
import json, sys
try:
    m = json.load(open(sys.argv[1]))
    print('yes' if sys.argv[2] in (m.get('modes') or {}) else 'no')
except Exception:
    print('yes')
" "$manifest" "$mode" 2>/dev/null || echo "yes")
            if [[ "$mode_known" == "no" ]]; then
              echo "WARN: resolve_skill_dir: '$mode' is not a declared mode of '$base' — continuing scan" >&2
              continue
            fi
          fi
          echo "$base $mode"
          return
        fi
      done
      echo "$skill"
      ;;
  esac
}

# --- resolve_default_branch ---
# Outputs the repo's default branch name (stdout). No gh dependency:
# origin/HEAD symbolic ref → origin/main → origin/master → literal "main".
resolve_default_branch() {
  local head_ref
  head_ref=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || true)
  if [[ -n "$head_ref" ]]; then
    echo "${head_ref#origin/}"
    return
  fi
  if git show-ref --verify --quiet refs/remotes/origin/main; then
    echo "main"
    return
  fi
  if git show-ref --verify --quiet refs/remotes/origin/master; then
    echo "master"
    return
  fi
  echo "main"
}

# --- resolve_framework_manifest <skill> ---
# Outputs the framework-owned manifest path (stdout).
# Canonical path: .runs/<skill>-lifecycle.json
#
# The framework manifest (JSON mirror of skill.yaml) and skill domain manifests
# (deploy/iterate/audit outputs) are now on separate paths — framework writes
# -lifecycle.json, domain writes -manifest.json (issue #1006). Callers should
# use this helper instead of hardcoding the path. The previous migration-compat
# fallback (read legacy .runs/<skill>-manifest.json when framework-exclusive
# keys present) was removed per issue #1027 now that the rename release cycle
# has elapsed. Any user who has not re-run any skill since the rename will see
# NO_MANIFEST errors and must delete .runs/ — acceptable because .runs/ is
# git-ignored and skill state is ephemeral.
resolve_framework_manifest() {
  echo "$PROJECT_DIR/.runs/${1}-lifecycle.json"
}
