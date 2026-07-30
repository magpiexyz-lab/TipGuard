#!/usr/bin/env bash
# validate-recovery.sh — Validate a recovery/self-degraded trace against
# independent evidence (build + e2e + diff-fix correlation).
#
# Used by verify STATE 7a before writing verify-report.md. Stamps
# recovery_validated:true on the trace when all three evidence checks pass.
# This transforms `recovery:true` from an automatic hard-fail into an audit
# marker that verify-report-gate.sh can safely allow under hard_gate_failure:false.
#
# Usage: bash .claude/scripts/validate-recovery.sh <trace-filename-without-ext>
# Example: bash .claude/scripts/validate-recovery.sh design-critic
# Example: bash .claude/scripts/validate-recovery.sh design-critic-landing
#
# Exit codes:
#   0 — all evidence checks passed; recovery_validated stamped true
#   1 — at least one evidence check failed; recovery_validated stays false
#   2 — prerequisite error (trace missing, malformed, etc)
#
# Evidence checks:
#   1. .runs/build-result.json.exit_code == 0
#   2. .runs/e2e-result.json.passed == true (if tests are in scope for archetype)
#   3. Every fixes[].file appears in git diff output. Diff set:
#        - Normal agent: `git diff --name-only <spawn_sha>..HEAD` UNION `git status --porcelain`
#        - lead-merge worktree: merge commit diff (deferred — current impl uses spawn_sha..HEAD)
#      OR no_fixes_claimed:true AND agent ∈ non_fixer_agents AND at least one
#      non-degraded sibling trace exists (findings-only agents).
set -euo pipefail

TRACE_NAME="${1:?Usage: validate-recovery.sh <trace-filename-without-ext>}"

PROJECT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || echo "${CLAUDE_PROJECT_DIR:-.}")"
TRACE_PATH="$PROJECT_DIR/.runs/agent-traces/$TRACE_NAME.json"
BUILD_RESULT="$PROJECT_DIR/.runs/build-result.json"
E2E_RESULT="$PROJECT_DIR/.runs/e2e-result.json"
REGISTRY="$PROJECT_DIR/.claude/patterns/agent-registry.json"

if [[ ! -f "$TRACE_PATH" ]]; then
  echo "ERROR: validate-recovery.sh — trace not found: $TRACE_PATH" >&2
  exit 2
fi

TRACE_PATH_ENV="$TRACE_PATH" BUILD_RESULT_ENV="$BUILD_RESULT" E2E_RESULT_ENV="$E2E_RESULT" \
REGISTRY_ENV="$REGISTRY" PROJECT_DIR_ENV="$PROJECT_DIR" python3 - << 'PYEOF'
import json, os, sys

# Import shared evidence-validation primitives (extracted in EARC slice 0;
# expanded in slice 1 to cover lead-transcribed evidence-anchored recovery).
sys.path.insert(0, os.path.join(os.environ['PROJECT_DIR_ENV'], '.claude', 'scripts'))
from lib.validate_evidence import validate_build_evidence, validate_diff_evidence

trace_path = os.environ['TRACE_PATH_ENV']
build_path = os.environ['BUILD_RESULT_ENV']
e2e_path = os.environ['E2E_RESULT_ENV']
reg_path = os.environ['REGISTRY_ENV']
project = os.environ['PROJECT_DIR_ENV']

try:
    trace = json.load(open(trace_path))
except Exception as exc:
    sys.stderr.write(f'ERROR: cannot parse trace: {exc}\n')
    sys.exit(2)

provenance = trace.get('provenance')
# AOC v1.1: lead-on-behalf goes through validation too. The agent reported
# success but the lead transcribed its output; downstream gates require
# independent evidence (build + e2e + diff-fix correlation) to stamp
# recovery_validated:true. lead-synthesized and lead-fix have their own
# attestation paths (coverage_provider / lead_attestation) and don't go
# through this evidence loop.
if provenance not in ('recovery', 'self-degraded', 'lead-on-behalf'):
    sys.stderr.write(f'SKIP: trace provenance={provenance!r} — only recovery/self-degraded/lead-on-behalf need validation\n')
    sys.exit(0)

errors = []

# Evidence 1: build (delegated to validate_build_evidence — adds freshness +
# commit_sha checks when those fields are recorded; backwards-compatible when
# absent, since this script's existing callers do not yet write them).
ok, build_errors = validate_build_evidence(build_path, project_dir=project)
errors.extend(build_errors)

# Evidence 2: e2e (skip if not applicable — heuristic: file exists means tests in scope)
# Agent-role carve-out: read-only (non-fixer) agents produce analysis, not fixes.
# e2e outcome is not semantically coupled to whether their scan completed correctly,
# so we skip the e2e precondition for any agent listed in agent-registry.json
# non_fixer_agents. This prevents the deadlock where every read-only agent's trace
# gets stuck at recovery_validated:false during bootstrap-verify (issue #1046).
try:
    reg = json.load(open(reg_path))
    non_fixers = set(reg.get('non_fixer_agents', []))
except Exception:
    non_fixers = set()

agent_for_role_check = trace.get('agent', '')
is_non_fixer = agent_for_role_check in non_fixers

if os.path.isfile(e2e_path) and not is_non_fixer:
    try:
        er = json.load(open(e2e_path))
        # Accept either passed:true or skipped:true
        if not (er.get('passed') is True or er.get('skipped') is True):
            errors.append(f'e2e-result.json shows failure (passed={er.get("passed")}, skipped={er.get("skipped")})')
    except Exception as exc:
        errors.append(f'e2e-result.json malformed: {exc}')
# If e2e-result.json is missing OR agent is a non-fixer, don't fail on e2e evidence

# Evidence 3: diff-fix correlation
fixes = trace.get('fixes') or []
agent = trace.get('agent', '')

if fixes:
    # Delegated to validate_diff_evidence (extracted; same diff-set semantics:
    # spawn_sha..HEAD UNION porcelain --untracked-files=all, with HEAD~..HEAD
    # fallback for shallow clones).
    spawn_sha = trace.get('spawn_sha', '')
    ok, diff_errors = validate_diff_evidence(fixes, spawn_sha, project_dir=project)
    errors.extend(diff_errors)
    # EARC slice 1 (closes #1189): when fixes carry lead_transcribed:true,
    # the lead's claim must point to a verifiable evidence_source. Diff
    # correlation above still applies — the lead's claim must be reflected
    # in actual diff. The evidence_source is an ADDITIONAL anchor.
    has_lead_transcribed = any(
        isinstance(f, dict) and f.get('lead_transcribed') is True for f in fixes
    )
    if has_lead_transcribed:
        ev_source = trace.get('lead_evidence_source')
        if not ev_source:
            errors.append(
                'lead_transcribed fixes require lead_evidence_source on trace '
                '(point to .runs/build-result.json or other anchor)'
            )
        else:
            ev_path = ev_source if os.path.isabs(ev_source) else os.path.join(project, ev_source)
            ok2, ev_errors = validate_build_evidence(
                ev_path,
                trace_timestamp=trace.get('timestamp'),
                project_dir=project,
            )
            errors.extend(ev_errors)
elif trace.get('no_fixes_claimed') is True:
    # Findings-only path: agent must be in non_fixer_agents. To confirm scope
    # actually executed, require either (a) a non-degraded sibling trace, OR
    # (b) build-result.json shows success — the latter covers the case where
    # every agent in a session self-degrades (e.g., guard blocks all trace
    # writes, see #1045) and no non-degraded sibling exists. Issue #1046.
    if agent not in non_fixers:
        errors.append(f'no_fixes_claimed:true requires agent in non_fixer_agents (got {agent!r})')
    # Check sibling traces: any trace in agent-traces/ with provenance=self
    traces_dir = os.path.join(project, '.runs', 'agent-traces')
    sibling_ok = False
    if os.path.isdir(traces_dir):
        for fn in os.listdir(traces_dir):
            if not fn.endswith('.json'):
                continue
            if fn == os.path.basename(trace_path):
                continue
            try:
                s = json.load(open(os.path.join(traces_dir, fn)))
            except Exception:
                continue
            if s.get('provenance') == 'self' and s.get('verdict') in ('pass', 'fail'):
                sibling_ok = True
                break
    if not sibling_ok:
        # Fallback: accept when the session's build succeeded
        build_ok = False
        try:
            br = json.load(open(build_path))
            build_ok = br.get('exit_code') == 0
        except Exception:
            pass
        if not build_ok:
            errors.append('no_fixes_claimed:true requires at least one non-degraded sibling trace OR a successful build-result.json')
else:
    # Neither fixes[] nor no_fixes_claimed:true — fixer agents need one or the other
    errors.append('recovery/self-degraded trace must have either fixes[] array or no_fixes_claimed:true')

if errors:
    sys.stderr.write('validate-recovery.sh FAIL:\n')
    for e in errors:
        sys.stderr.write(f'  - {e}\n')
    sys.exit(1)

# All evidence passed — stamp recovery_validated:true
trace['recovery_validated'] = True
json.dump(trace, open(trace_path, 'w'), indent=2)
print(f'validate-recovery.sh PASS: {trace_path} recovery_validated:true stamped')
PYEOF
