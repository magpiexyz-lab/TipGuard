#!/usr/bin/env bash
# test_verify_stage3_demo_mode.sh — integration test for #1042 Session C.
#
# Exercises the state-2a → state-3b pipeline end-to-end against a synthetic
# web-app fixture:
#   1. state-2a writes .runs/design-page-set.json and
#      .runs/page-image-map.json with correct shape + landing classification
#      + dynamic-route URL concretization + image-grep classification.
#   2. write-degraded-trace.py --extra-json produces a trace that
#      validate-recovery.sh accepts (stamps recovery_validated=true).
#   3. merge-design-critic-traces.py preserves self-degraded verdict,
#      sets aggregate provenance=lead-merge + partial=true +
#      contributing_spawn_indexes, and records demo_mode_short_circuit_pages.
#
# Exit 0 on all-pass; exit 1 on any failure.
set -euo pipefail

cd "$(dirname "$0")/../../../.."

TMPDIR=$(mktemp -d)
trap "rm -rf '$TMPDIR'" EXIT

# --- Fixture setup ---
# Copy the repo's .claude/ into the tmp workspace (scripts read it by path).
mkdir -p "$TMPDIR"
cp -R .claude "$TMPDIR/.claude"
mkdir -p "$TMPDIR/src/app/quote/[id]"
mkdir -p "$TMPDIR/src/app/dashboard"
mkdir -p "$TMPDIR/src/app/login"
mkdir -p "$TMPDIR/src/components"
mkdir -p "$TMPDIR/experiment"
mkdir -p "$TMPDIR/.runs/agent-traces"

# Landing page with Image
cat > "$TMPDIR/src/app/page.tsx" <<'EOF'
import Image from "next/image";
export default function() { return <Image src="/hero.webp" alt="" />; }
EOF

# Dashboard imports a shared component that contains an image
cat > "$TMPDIR/src/components/hero.tsx" <<'EOF'
import Image from "next/image";
export function Hero() { return <Image src="/d.webp" alt="" />; }
EOF
cat > "$TMPDIR/src/app/dashboard/page.tsx" <<'EOF'
import { Hero } from "@/components/hero";
export default function() { return <Hero/>; }
EOF

# Dynamic-route page — text only, used for the DEMO_MODE short-circuit path
cat > "$TMPDIR/src/app/quote/[id]/page.tsx" <<'EOF'
export default function() { return <p>Quote detail</p>; }
EOF

# Login — text only
cat > "$TMPDIR/src/app/login/page.tsx" <<'EOF'
export default function() { return <form><input/></form>; }
EOF

# Minimal experiment.yaml
cat > "$TMPDIR/experiment/experiment.yaml" <<'EOF'
name: test-app
type: web-app
golden_path:
  - step: visit
    event: visit_landing
    page: landing
  - step: view-dashboard
    event: view_dash
    page: dashboard
  - step: view-quote
    event: view_quote
    page: quote-detail
stack:
  auth: supabase
EOF

cd "$TMPDIR"

# --- Step 1: Run state-2a's Python helper directly ---
python3 - <<PYEOF
import datetime, json, os, sys
sys.path.insert(0, os.path.join(os.getcwd(), ".claude/scripts"))
import yaml
from lib.derive_pages import (
    derive_landing_for_design_critic,
    derive_page_images,
    derive_page_set_for_design_critic,
)
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
exp = yaml.safe_load(open("experiment/experiment.yaml"))
pages = derive_page_set_for_design_critic(exp, ".")
landing = derive_landing_for_design_critic(".")
image_map = derive_page_images(pages, ".", include_landing=True)
with open(".runs/design-page-set.json", "w") as f:
    json.dump({"generated_at": now, "pages": pages, "landing": landing}, f, indent=2)
with open(".runs/page-image-map.json", "w") as f:
    json.dump(
        {
            "generated_at": now,
            "source_page_set": ".runs/design-page-set.json",
            "pages": image_map,
        },
        f,
        indent=2,
    )
PYEOF

echo "--- design-page-set.json ---"
python3 -c "
import json
d = json.load(open('.runs/design-page-set.json'))
names = [p['name'] for p in d['pages']]
print('pages:', names)
assert 'landing' not in names, 'landing must be excluded from operational list'
# Post-#1144 the dynamic route /quote/[id] is discovered as page name 'quote-id'
quote = next(p for p in d['pages'] if p['name'] == 'quote-id')
assert quote['route_pattern'] == '/quote/[id]', f'bad route_pattern: {quote[\"route_pattern\"]}'
assert '[id]' not in quote['test_url'], f'dynamic segment not concretized: {quote[\"test_url\"]}'
assert quote['dynamic_segments'] == ['id']
print('✓ design-page-set.json shape OK')
# #1143: landing sibling must be present (dict, since this fixture has src/app/page.tsx)
assert 'landing' in d, 'landing field missing in design-page-set.json'
assert isinstance(d['landing'], dict), f'landing must be dict, got {type(d[\"landing\"])}'
assert d['landing']['name'] == 'landing'
assert d['landing']['route_pattern'] == '/'
assert d['landing']['test_url'] == '/'
assert 'src/app/page.tsx' in d['landing']['source_files']
print('✓ landing sibling field present')
"

echo "--- page-image-map.json ---"
python3 -c "
import json
m = json.load(open('.runs/page-image-map.json'))['pages']
assert m['landing']['has_images'] is True and m['landing']['detected_via'] == 'landing-hardcoded'
assert m['dashboard']['has_images'] is True and m['dashboard']['detected_via'] == 'imported-component'
assert m['login']['has_images'] is False
assert m['quote-id']['has_images'] is False
print('✓ page-image-map.json classification OK')
"

# --- Step 2: synthesise a quote-detail self-degraded trace with --extra-json ---
# For isolation, stub resolve_active_identity helpers by forcing env.
export CLAUDE_PROJECT_DIR="$TMPDIR"
# write-degraded-trace.py calls git to resolve spawn_sha; make the tmp dir a git repo
cd "$TMPDIR"
git init -q -b main >/dev/null 2>&1 || git init -q >/dev/null 2>&1
git config user.email "test@test" >/dev/null 2>&1 || true
git config user.name "test" >/dev/null 2>&1 || true
git add -A >/dev/null 2>&1 || true
git commit -m init -q --allow-empty --no-verify >/dev/null 2>&1 || true
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "main")

# Seed .runs/verify-context.json so resolve_active_identity finds a run.
# Branch MUST match the current git branch, timestamp MUST be recent (<48h).
TS=$(python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")
cat > .runs/verify-context.json <<EOF
{
  "skill": "verify",
  "branch": "$CURRENT_BRANCH",
  "timestamp": "$TS",
  "run_id": "integration-test-run",
  "completed_states": [],
  "scope": "full",
  "archetype": "web-app",
  "completed": false,
  "attributed_to": "verify",
  "ancestors": []
}
EOF

# Seed a fake build-result.json so validate-recovery.sh passes its build check
cat > .runs/build-result.json <<'EOF'
{"exit_code": 0, "stderr": "", "stdout": ""}
EOF

# Create lifecycle.json with run_id hook data (not strictly required since
# resolve_active_identity falls back to verify-context.json)

# Invoke write-degraded-trace.py with --extra-json payload
python3 .claude/scripts/write-degraded-trace.py design-critic \
  --reason "demo-mode-fixture-short-circuit" \
  --verdict unresolved \
  --checks-performed "source-review-structural" \
  --trace-filename "design-critic-quote.json" \
  --extra-json '{"review_method":"source-only","review_evidence":{"requested_route":"/quote/00000000-0000-0000-0000-000000000000","final_url":"http://localhost/quote/00000000-0000-0000-0000-000000000000","auth_source":"demo-mode","fallback_reason":"demo-mode-fixture-short-circuit","content_density":null,"final_status":404,"route_pattern":"/quote/[id]"},"page":"quote","source_review_verdict":"pass","source_review_score":9,"image_issues_for_landing":[]}'

echo "--- quote trace ---"
python3 -c "
import json
t = json.load(open('.runs/agent-traces/design-critic-quote.json'))
assert t['provenance'] == 'self-degraded'
assert t['partial'] is True
assert t['verdict'] == 'unresolved'
assert t['degraded_reason'] == 'demo-mode-fixture-short-circuit'
assert t['review_method'] == 'source-only'
assert t['source_review_verdict'] == 'pass'
assert t['image_issues_for_landing'] == []
print('✓ trace shape OK')
"

# --- Step 3: Stage-1c validate-recovery ---
bash .claude/scripts/validate-recovery.sh design-critic-quote
python3 -c "
import json
t = json.load(open('.runs/agent-traces/design-critic-quote.json'))
assert t.get('recovery_validated') is True, f'recovery_validated not stamped: {t}'
print('✓ validate-recovery stamped recovery_validated=true')
"

# --- Step 4: write a landing sibling trace (normal self+pass) ---
python3 - <<'PYEOF'
import json
t = {
    "agent": "design-critic",
    "page": "landing",
    "verdict": "pass",
    "result": "clean",
    "provenance": "self",
    "partial": False,
    "pages_reviewed": 1,
    "min_score": 9,
    "min_score_all": 9,
    "sections_below_8": 0,
    "fixes_applied": 0,
    "unresolved_sections": 0,
    "pre_existing_debt": [],
    "fixes": [],
    "checks_performed": ["layer1_functional", "layer2_taste", "layer3_antipattern"],
    "review_method": "rendered-demo",
    "review_evidence": {
        "requested_route": "/",
        "final_url": "http://localhost/",
        "auth_source": "demo-mode",
        "fallback_reason": None,
        "content_density": 1024,
    },
    "candidates_tried": 3,
    "run_id": "integration-test-run",
}
json.dump(t, open(".runs/agent-traces/design-critic-landing.json", "w"))
PYEOF

# Seed agent-spawn-log.jsonl — hook=skill-agent-gate is REQUIRED; both
# merge-design-critic-traces.py and state-completion-gate.sh filter on it.
cat > .runs/agent-spawn-log.jsonl <<'EOF'
{"agent":"design-critic","run_id":"integration-test-run","spawn_index":0,"hook":"skill-agent-gate"}
{"agent":"design-critic","run_id":"integration-test-run","spawn_index":1,"hook":"skill-agent-gate"}
EOF

# --- Step 5: Run the merge script ---
python3 .claude/scripts/merge-design-critic-traces.py

echo "--- aggregate design-critic.json ---"
python3 -c "
import json
a = json.load(open('.runs/agent-traces/design-critic.json'))
assert a['provenance'] == 'lead-merge', f'bad aggregate provenance: {a[\"provenance\"]}'
assert a['partial'] is True
assert sorted(a['contributing_spawn_indexes']) == [0, 1]
assert a['verdict'] == 'unresolved', f'worst verdict expected unresolved, got {a[\"verdict\"]}'
assert a.get('demo_mode_short_circuit_pages') == ['quote']
assert a['per_page_provenance']['landing'] == 'self'
assert a['per_page_provenance']['quote'] == 'self-degraded'
assert a['per_page_recovery_validated']['quote'] is True
assert a['per_page_source_review_verdict']['quote'] == 'pass'
# Self-heal must NOT have fired for the quote trace (verdict was already unresolved
# AND degraded_reason is the sanctioned carve-out)
assert 'review_method_gate_corrections' not in a or not any(
    c.get('page') == 'quote' for c in a['review_method_gate_corrections']
), f'self-heal should not fire for demo-mode-fixture-short-circuit: {a.get(\"review_method_gate_corrections\")}'
print('✓ aggregate lead-merge contract + demo-mode-short-circuit preservation OK')
"

# --- Step 6: hard-gate evaluation ---
# Simulate verify-report-gate.sh's check_hard_gate_predicates call
TRACE_DIR_ENV="$TMPDIR/.runs/agent-traces" python3 - <<'PYEOF'
import json, os, sys
sys.path.insert(0, ".claude/scripts")
traces_dir = os.environ["TRACE_DIR_ENV"]
# Inline port of aggregate_ok logic (parity with evaluate-hard-gate-predicates.py)
def pass_self_pass_or_fail(t):
    return t.get('verdict') in ('pass', 'fail') and t.get('provenance') == 'self'
def pass_clean(t):
    return (t.get('verdict') == 'pass' and t.get('result') == 'clean'
            and t.get('provenance') == 'self')
def pass_after_fixes(t):
    try: uc = int(t.get('unresolved_critical', 0))
    except: uc = 0
    return (t.get('verdict') == 'pass'
            and t.get('result') in ('fixed', 'partial')
            and t.get('provenance') == 'self' and uc == 0)
def validated_fallback(t):
    return (t.get('provenance') in ('recovery', 'self-degraded')
            and t.get('recovery_validated') is True)
def legacy_pass_no_recovery(t):
    if t.get('provenance') is not None: return False
    return t.get('verdict') == 'pass' and not t.get('recovery')
import glob
agg = json.load(open(os.path.join(traces_dir, "design-critic.json")))
assert agg.get('provenance') == 'lead-merge'
csi = agg.get('contributing_spawn_indexes')
assert isinstance(csi, list) and len(csi) > 0
sibs = [p for p in glob.glob(os.path.join(traces_dir, "design-critic-*.json"))
        if not p.endswith("design-critic.json")]
assert sibs, "no sibling files"
ok = True
for sf in sibs:
    sib = json.load(open(sf))
    if not (pass_clean(sib) or pass_after_fixes(sib) or pass_self_pass_or_fail(sib)
            or validated_fallback(sib) or legacy_pass_no_recovery(sib)):
        ok = False
        print(f"  sibling {os.path.basename(sf)} FAILED predicate check: verdict={sib.get('verdict')} provenance={sib.get('provenance')} recovery_validated={sib.get('recovery_validated')}")
assert ok, "aggregate_ok sibling predicate check FAILED"
print('✓ aggregate_ok predicate passes — no lead override required')
PYEOF

echo ""
echo "======================================"
echo "INTEGRATION TEST PASSED (#1042 Session C)"
echo "======================================"
