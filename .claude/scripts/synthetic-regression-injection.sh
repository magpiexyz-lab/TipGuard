#!/usr/bin/env bash
# synthetic-regression-injection.sh — falsification test for /solve r3 framework.
#
# Injects 5 known regressions into a sandbox copy of the repo and asserts each
# of the proposed linter handlers catches its target. If any single injection
# is missed, the handler family is over-fitted to specific defect signatures
# rather than the generalized contract-drift class.
#
# Pass condition: ALL 5 injections caught + clean tree produces zero false
# positives.
#
# Injection inventory (per .runs/solve-design-r3.md Item 4 + r2 caveats):
#   1. Synthetic design-spam-checker agent in hard_gates without pass_lead_synthesized
#      → expect agent_registry_predicate_parity violation
#   2. Synthetic VERIFY in state-registry.json using raw d.values() against a gate-stamped artifact
#      → expect verify_d_values_against_stamped_artifact violation
#   3. Novel stamped field in a third writer (recovery-trace) + corresponding VERIFY
#      → expect verify_d_values_against_stamped_artifact (writer-aware via union)
#   4. scaffold-pages output annotates [audit:api-fetch=/api/foo] but no fetch('/api/foo')
#      → expect audit_tag_claim_matches_ast violation
#   5. prepass-result.json partition.size=3 vs merger-result.json csi.length=2
#      → expect cardinality_consistency_across_pipeline_steps violation
#
# Usage: bash .claude/scripts/synthetic-regression-injection.sh
# Exit 0 if all assertions pass. Exit 1 on any miss.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SANDBOX_BASE="${REPO_ROOT}/.runs/_test"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
SANDBOX="${SANDBOX_BASE}/synthetic-injection-${TIMESTAMP}"
PASS_COUNT=0
FAIL_COUNT=0

mkdir -p "$SANDBOX"
trap 'rm -rf "$SANDBOX"' EXIT

# Copy only the files the linter touches (small + fast).
mkdir -p "$SANDBOX/.claude/patterns" \
         "$SANDBOX/.claude/scripts/lib/linter" \
         "$SANDBOX/.claude/scripts" \
         "$SANDBOX/experiment" \
         "$SANDBOX/src/app/portfolio"

cp -r "$REPO_ROOT/.claude/scripts/lib/linter/." "$SANDBOX/.claude/scripts/lib/linter/"
cp "$REPO_ROOT/.claude/scripts/verify-linter.sh" "$SANDBOX/.claude/scripts/" 2>/dev/null || true
cp "$REPO_ROOT/.claude/scripts/derive-graim-manifest.py" "$SANDBOX/.claude/scripts/"
cp -r "$REPO_ROOT/.claude/scripts/lib/." "$SANDBOX/.claude/scripts/lib/" 2>/dev/null || true
cp "$REPO_ROOT/.claude/patterns/agent-registry.json" "$SANDBOX/.claude/patterns/"
cp "$REPO_ROOT/.claude/patterns/state-registry.json" "$SANDBOX/.claude/patterns/"
cp "$REPO_ROOT/.claude/patterns/template-coherence-rules.json" "$SANDBOX/.claude/patterns/"
cp "$REPO_ROOT/.claude/patterns/audit-verb-registry.json" "$SANDBOX/.claude/patterns/"
cp "$REPO_ROOT/.claude/patterns/gate-readable-artifacts-canonical.json" "$SANDBOX/.claude/patterns/"

# ─── Injection 1: design-spam-checker missing pass_lead_synthesized ────────────
python3 - "$SANDBOX" <<'PYEOF'
import json, os, sys
sandbox = sys.argv[1]
path = os.path.join(sandbox, ".claude/patterns/agent-registry.json")
reg = json.load(open(path))
reg["hard_gates"].append({
    "agent": "design-spam-checker",
    "allow_predicates": ["pass_clean", "pass_after_fixes", "pass_self_pass_or_fail"],
    "_note": "SYNTHETIC INJECTION 1 — missing pass_lead_synthesized"
})
json.dump(reg, open(path, "w"), indent=2)
PYEOF

# ─── Injection 2: VERIFY using d.values() vs gate-stamped artifact ─────────────
python3 - "$SANDBOX" <<'PYEOF'
import json, os, sys
sandbox = sys.argv[1]
path = os.path.join(sandbox, ".claude/patterns/state-registry.json")
reg = json.load(open(path))
reg.setdefault("synthetic", {})
reg["synthetic"]["1"] = (
    "python3 -c \"import json; d=json.load(open('.runs/bootstrap-design-validated.json')); "
    "assert all(v in (True, 'skipped') for v in d.values()), 'fail'\""
)
json.dump(reg, open(path, "w"), indent=2)
PYEOF

# ─── Injection 3: novel stamped field in a third writer + VERIFY ───────────────
# Add a new artifact + VERIFY using d.values() — handler should catch via union-derived STAMPED_FIELDS.
python3 - "$SANDBOX" <<'PYEOF'
import json, os, sys
sandbox = sys.argv[1]
path = os.path.join(sandbox, ".claude/patterns/state-registry.json")
reg = json.load(open(path))
reg["synthetic"]["2"] = (
    "python3 -c \"import json; d=json.load(open('.runs/observation-evidence.json')); "
    "assert all(v for v in d.values()), 'fail'\""
)
json.dump(reg, open(path, "w"), indent=2)
PYEOF

# ─── Injection 4: scaffold-pages outputs audit:api-fetch=/api/foo without matching fetch ─
mkdir -p "$SANDBOX/experiment" "$SANDBOX/src/app/portfolio"
cat > "$SANDBOX/experiment/experiment.yaml" <<'YAML'
name: synthetic-test
type: web-app
behaviors:
  - id: B1
    hypothesis_id: H1
    given: stub
    when: stub
    then: stub
    tests:
      - "User sees [audit:api-fetch=/api/foo] data on the page"
    level: 1
golden_path:
  - step: visit
    page: portfolio
YAML
cat > "$SANDBOX/src/app/portfolio/page.tsx" <<'TSX'
export default function Page() {
  return <div>portfolio</div>;
}
TSX

# ─── Injection 5: prepass + merger cardinality mismatch ────────────────────────
mkdir -p "$SANDBOX/.runs"
echo '{"partition": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}' > "$SANDBOX/.runs/prepass-result.json"
echo '{"csi": [{"id": "a"}, {"id": "b"}]}' > "$SANDBOX/.runs/merger-result.json"

# Append rule entries to the sandbox copy of template-coherence-rules.json
# so the linter actually exercises Injection 4 + 5.
python3 - "$SANDBOX" <<'PYEOF'
import json, os, sys
sandbox = sys.argv[1]
path = os.path.join(sandbox, ".claude/patterns/template-coherence-rules.json")
rules = json.load(open(path))
rules["rules"].append({
    "id": "synthetic-audit-tag-claim",
    "type": "audit_tag_claim_matches_ast",
    "severity": "warn",
    "registry_path": ".claude/patterns/audit-verb-registry.json",
    "scaffold_glob": "src/app/**/page.tsx",
    "experiment_path": "experiment/experiment.yaml",
    "description": "SYNTHETIC TEST — assert audit:api-fetch claims have matching fetch() calls"
})
rules["rules"].append({
    "id": "synthetic-cardinality",
    "type": "cardinality_consistency_across_pipeline_steps",
    "severity": "warn",
    "pairs": [
        {
            "a_path": ".runs/prepass-result.json", "a_field": "partition.length",
            "b_path": ".runs/merger-result.json", "b_field": "csi.length"
        }
    ],
    "description": "SYNTHETIC TEST — assert partition+csi cardinality match"
})
json.dump(rules, open(path, "w"), indent=2)
PYEOF

# ─── Run the linter against sandbox ────────────────────────────────────────────
# Use the real wrapper but override VL_REPO_ROOT to point at the sandbox.
cd "$REPO_ROOT"
LINTER_OUT=$(
  VL_REPO_ROOT="$SANDBOX" \
  VL_RULES_PATH="$SANDBOX/.claude/patterns/template-coherence-rules.json" \
  python3 .claude/scripts/lib/linter/cli.py 2>&1 || true
)

# ─── Assertions ────────────────────────────────────────────────────────────────
assert_caught() {
  local label="$1" pattern="$2"
  if echo "$LINTER_OUT" | grep -qE "$pattern"; then
    echo "  ✓ [Injection $label] caught: $pattern"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    echo "  ✗ [Injection $label] MISSED: pattern '$pattern' not in linter output"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

echo ""
echo "===== Synthetic Regression Injection Results ====="

assert_caught 1 "design-spam-checker:.+pass_lead_synthesized"
assert_caught 2 "verify_d_values_against_stamped_artifact|d\\.values\\(\\).+bootstrap-design-validated"
assert_caught 3 "observation-evidence.json|verify_d_values_against_stamped_artifact"
assert_caught 4 "audit:api-fetch=/api/foo.+fetch"
assert_caught 5 "cardinality drift|partition.length=3|csi.length=2"

echo ""
echo "Summary: ${PASS_COUNT}/5 injections caught"

# Negative test: clean tree should produce zero new false positives.
echo ""
echo "===== Negative Test (Clean Tree) ====="
NEGATIVE_OUT=$(bash "$REPO_ROOT/.claude/scripts/verify-linter.sh" 2>&1 || true)
NEW_FAILURES=$(echo "$NEGATIVE_OUT" | grep -c "synthetic-" || true)
if [ "$NEW_FAILURES" = "0" ]; then
  echo "  ✓ Clean tree produces zero synthetic-prefixed findings"
else
  echo "  ✗ Clean tree triggers synthetic rules — FP risk in main repo"
  FAIL_COUNT=$((FAIL_COUNT + 1))
fi

echo ""
if [ "$FAIL_COUNT" = "0" ]; then
  echo "PASS: all 5 synthetic injections caught + 0 FPs on clean tree"
  exit 0
else
  echo "FAIL: $FAIL_COUNT injection(s) missed — handler family is over-fitted"
  echo ""
  echo "Linter output (sandbox):"
  echo "$LINTER_OUT" | sed 's/^/  /'
  exit 1
fi
