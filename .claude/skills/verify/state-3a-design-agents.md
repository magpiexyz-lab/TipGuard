# STATE 3a: DESIGN_AGENTS

**PRECONDITIONS:** All Phase 1 traces exist (hook-enforced by `skill-agent-gate.sh`) AND state-2a artifacts exist when this is a web-app + full/visual scope run (`.runs/design-page-set.json` and `.runs/page-image-map.json`). The Stage-1 spawn list and per-page `has_images` classifications come from those files — Stage-1 does NOT re-scan the filesystem. State-2b drift detection has run (`.runs/drift-report.json` exists with `block_count==0` or `not_applicable=true`); a non-zero block_count would have prevented advancement past state-2b (Issue #1077, PR3).

**ACTIONS:**

Spawn edit-capable agents ONE AT A TIME. Each must complete and pass `npm run build` before the next is spawned. This prevents write conflicts.

> **Trace integrity**: Per-page design-critic agents MUST be spawned via the Agent
> tool. The state-completion-gate cross-references trace files against the spawn
> audit log — traces without matching Agent spawns will be blocked. Do NOT write
> trace files directly. For recovery traces, use `bash .claude/scripts/write-recovery-trace.sh`.

After each edit-capable agent completes, read its completion report and log each fix via the canonical ledger writer (AOC v1 R2 — `.runs/fix-log.md` is derived from `.runs/fix-ledger.jsonl`; do NOT write to fix-log.md directly):

```bash
python3 .claude/scripts/write-fix-ledger.py --lead-fix --skill verify \
  --fix-json '{"file":"<file>","symptom":"<short symptom>","fix":"<short fix description>"}' \
  --severity warn
```

> **Shared algorithms:** Before each edit-capable agent spawn, execute [Atomic Execution Protocol](../verify.md#atomic-execution-protocol) snapshot. After each agent returns, use [Trace State Detection](../verify.md#trace-state-detection) and [Exhaustion Protocol](../verify.md#exhaustion-protocol) to handle the result.

### design-critic (if scope is `full` or `visual`, AND archetype is `web-app`) — PARALLEL PER PAGE

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Visual agents".
>
> [visual-agents] web-app: design-critic, ux-journeyer, consistency-checker | service: skip | cli: skip

#### Stage 0: All-pages fast-path detector (#1256)

If the PR boundary contains zero UI-rendering source files (after excluding
test files, shadcn primitives, and api routes), every per-page design-critic
agent would trivially fast-path via the empty-boundary path. Spawning N
agents to all immediately fast-path burns ~30s of spawn overhead per agent
(~9 min on an 18-page web-app). This Stage 0 detects the condition once
upfront and short-circuits the entire design-quality stage with a single
lead-synthesized aggregate.

**Trigger** (lead-side, no agents):

```bash
# #1381 D3 — Stage 0 must NOT fire during bootstrap-verify. Bootstrap state-16
# spawns implementer agents that commit test files BEFORE /verify runs (state-16
# line 17, 45). This creates BOUNDARY_KIND="diff" with PR_RELEVANT=0 (test
# commits don't touch UI; the 100+ scaffolded UI files are uncommitted in the
# working tree), which would inappropriately fire the all-pages-fast-path and
# zero-design-review the entire bootstrap surface. Skip Stage 0 when the parent
# skill is bootstrap — the working tree IS the surface to review.
MODE=$(python3 -c "
import json
try:
    print(json.load(open('.runs/verify-context.json')).get('mode', ''))
except Exception:
    print('')
" 2>/dev/null)

if [ "$MODE" = "bootstrap-verify" ]; then
  echo "Stage 0 skipped: mode=bootstrap-verify (working tree is the surface; uncommitted scaffolded UI files would not appear in PR diff)"
  ALL_PAGES_FAST_PATH=false
else
  # Compute boundary kind first (matches the existing pre-flight 1a logic).
  if [ "$(git rev-parse HEAD 2>/dev/null)" = "$(git merge-base HEAD main 2>/dev/null)" ]; then
    BOUNDARY_KIND="full-tree"
  else
    BOUNDARY_KIND="diff"
  fi

  ALL_PAGES_FAST_PATH=false
  if [ "$BOUNDARY_KIND" = "diff" ]; then
    PR_RELEVANT=$(git diff --name-only $(git merge-base HEAD main)...HEAD \
      | grep -E '^(src/lib|src/components|src/app)/' \
      | grep -v -E '^src/components/(ui|magicui)/' \
      | grep -v -E '^src/app/api/' \
      | grep -v -E '\.test\.[jt]sx?$' \
      | wc -l | tr -d ' ')
    if [ "$PR_RELEVANT" = "0" ]; then
      ALL_PAGES_FAST_PATH=true
    fi
  fi
fi
```

The detector excludes:
- `*.test.[jt]sx?` — test files (no visual surface)
- `src/components/ui/**` and `src/components/magicui/**` — shadcn primitives (matches the existing thin-wrapper exclusion at the pre-flight step 2's import filter; not in design-review scope)
- `src/app/api/**` — API routes (matches the existing fallback_boundary exclusion in pre-flight step 5a; not visual)

The detector ONLY fires when `BOUNDARY_KIND="diff"` AND `MODE != "bootstrap-verify"`.
- `full-tree` mode (no commits on the feature branch yet): no PR diff to interpret, detector is skipped.
- `bootstrap-verify` mode (#1381 D3): state-16 implementer commits create a non-empty diff that excludes the uncommitted scaffolded UI; detector is skipped so the working tree gets full design review.

**On trigger** (write artifacts, skip pre-flight + Stage 1 + Stage 1b + Stage 1c):

```bash
if [ "$ALL_PAGES_FAST_PATH" = "true" ]; then
  # 1. Decision artifact (consumed by state-completion-gate.sh exemption,
  #    state-3a/3b VERIFY branches, and state-7a verify-report Notes cell).
  PAYLOAD=$(python3 -c "
import json, datetime, subprocess, os
mb = subprocess.check_output(['git','merge-base','HEAD','main']).decode().strip()
pr_files = subprocess.check_output(
    ['git','diff','--name-only', mb + '...HEAD']
).decode().splitlines()
ps = json.load(open('.runs/design-page-set.json'))
print(json.dumps({
    'pr_files': pr_files,
    'boundary_kind': 'diff',
    'page_set': ps.get('pages', []),
    'landing': ps.get('landing'),
    'trigger': 'zero ui-rendering source files in pr boundary after shadcn-primitive, api-route, and test-file exclusion',
    'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
}))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/all-pages-fast-path-decision.json \
    --payload "$PAYLOAD" \
    --skill verify

  # 2. Synthesize design-critic.json aggregate.
  #    Provenance=lead-synthesized + sanctioned coverage_provider clears
  #    state-completion-gate.sh per-trace check (#1256 SANCTIONED_COVERAGE_PROVIDERS
  #    allowlist) and verify-report-gate.sh hard_gate via the
  #    pass_lead_synthesized predicate added to agent-registry.json.
  N_PAGES=$(python3 -c "
import json
ps = json.load(open('.runs/design-page-set.json'))
n = len(ps.get('pages', []))
if isinstance(ps.get('landing'), dict): n += 1
print(n)
")
  bash .claude/scripts/write-agent-trace.sh design-critic \
    --provenance lead-synthesized \
    --coverage-provider .runs/all-pages-fast-path-decision.json \
    --trace-filename design-critic.json \
    --json "{\"verdict\":\"pass\",\"result\":\"clean\",\"pages\":$N_PAGES,\"pages_reviewed\":$N_PAGES,\"min_score\":10,\"min_score_all\":10,\"sections_below_8\":0,\"unresolved_sections\":0,\"unresolved_shared\":0,\"fixes_applied\":0,\"checks_performed\":[],\"image_issues_for_landing\":[],\"weakest_page\":\"\",\"per_page_review_methods\":{},\"per_page_review_evidence\":[],\"per_page_provenance\":{},\"per_page_recovery_validated\":{},\"validated_fallback_pages\":[],\"pre_existing_debt\":[],\"fixes\":[],\"all_validated_fallback\":false,\"shared_fixes_applied\":0,\"review_method\":\"boundary-skip-all-pages\"}"

  # 3. Synthesize design-consistency-checker.json. Same lead-synthesized
  #    provenance + sanctioned coverage_provider clears state-completion-gate.
  #    design-consistency-checker is NOT in agent-registry.json hard_gates,
  #    so no allow_predicates change is needed for this agent.
  bash .claude/scripts/write-agent-trace.sh design-consistency-checker \
    --provenance lead-synthesized \
    --coverage-provider .runs/all-pages-fast-path-decision.json \
    --trace-filename design-consistency-checker.json \
    --json '{"verdict":"pass","result":"count_summary","inconsistent_count":0,"checks_performed":[],"review_method":"boundary-skip-all-pages","inconsistencies":[]}'

  # 4. Empty design-claims.json so state-3a POSTCONDITION ("design-claims.json exists")
  #    is satisfied even though we skipped pre-flight.
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/design-claims.json \
    --payload '{"claims":{},"thin_wrappers":[]}' \
    --skill verify

  # 5. Skip the rest of state-3a (pre-flight + Stage 1 + Stage 1b + Stage 1c).
  #    State-3a VERIFY below branches on the decision artifact and accepts
  #    the synthesized aggregate without per-page traces.
  #    State-3b's Stage 1c validate-recovery loop, Step A merger, and
  #    Stage 2 spawn are similarly skipped via the decision artifact guard.
fi
```

**`review_method="boundary-skip-all-pages"`** is a state-3a-synthetic value, distinct from per-page `boundary-skip` (#1061). It does NOT appear in `render-review-detection.md`'s enum and is not consumed by the merger (the merger is not invoked when Stage 0 fires).

<!-- prose-gate:verify-state-3a-stage0-design-critic -->
> **STOP HERE when Stage 0 fired (`ALL_PAGES_FAST_PATH=true`).** Skip everything between this directive and the **POSTCONDITIONS** block at the end of state-3a — the pre-flight, Stage 1 per-page Agent spawns, Stage 1b shared-fixes, and Stage 1c shared-component agent are ALL bypassed. The lead-synthesized aggregate covers state-3a's outputs; the VERIFY block at the end has its own Stage 0 short-circuit branch. Concretely: when `[ "$ALL_PAGES_FAST_PATH" = "true" ]`, the lead MUST jump directly to `bash .claude/scripts/advance-state.sh verify 3a`.

If `ALL_PAGES_FAST_PATH=false`, proceed to the existing pre-flight + Stage 1 below.

#### Pre-flight: Thin-wrapper detection and claim assignment

> **Skip when Stage 0 fired** (per the STOP-HERE directive above). The Pre-flight + Stage 1 + Stage 1b + Stage 1c blocks below run only when `ALL_PAGES_FAST_PATH != "true"`. A lead reading this section after the STOP-HERE directive has misordered execution.

Before spawning any design-critic agents, detect pages whose visual content
lives entirely in shared components and assign those components as "claims."
This ensures thin-wrapper pages (e.g., landing pages with variants) receive
full visual review instead of fast-pathing with an empty boundary.

1. Compute the PR file boundary: `git diff --name-only $(git merge-base HEAD main)...HEAD`
1a. **Determine boundary_kind** (#1196 — distinguish "PR didn't touch this page" from "no commits exist yet"):
   ```bash
   if [ "$(git rev-parse HEAD 2>/dev/null)" = "$(git merge-base HEAD main 2>/dev/null)" ]; then
     BOUNDARY_KIND="full-tree"
   else
     BOUNDARY_KIND="diff"
   fi
   ```
   - `BOUNDARY_KIND="diff"` → empty FILE_BOUNDARY legitimately means "PR didn't touch this page" → fast-path is correct.
   - `BOUNDARY_KIND="full-tree"` → no commits exist on the feature branch (HEAD == merge-base, typical at /bootstrap pre-commit) → empty FILE_BOUNDARY is **ambiguous**, NOT a signal to skip. The lead supplies a non-empty fallback boundary instead (see step below).

   **Skip this branch** if `design-page-set.json` declares `not_applicable: true` (non-web-app archetype; design-critic does not run anyway per the line-18 archetype gate).
2. For each discovered page file `src/app/<page>/page.tsx`:
   - Compute `PR_file_boundary ∩ src/app/<page>/**`. If non-empty, skip (page has page-local files in PR).
   - Read the page file. Extract all imports from `src/components/` or `src/lib/`
     using regex: `from ['"](@/components/|@/lib/|../components/|../lib/)(.*?)['"]`
   - **Filter out shadcn primitives (#1154):** drop any import path starting with
     `@/components/ui/` or `@/components/magicui/` (matches the eslint config
     `ignores` list). These are auto-generated and not in design-review scope —
     including them inflates `thin_wrappers` and arbitrarily binds shadcn
     primitives to whichever page sorts first alphabetically.
   - Resolve `@/` alias to `src/` to get full paths
   - Intersect imported shared paths with `PR_file_boundary`
   - If intersection is non-empty: this page is a **thin wrapper with claimable dependencies**
2a. **Landing pre-flight (issue #1143):** read `.runs/design-page-set.json["landing"]`.
   If null, skip this sub-step (no landing source on disk — non-web-app, or
   pre-scaffold-pages). Otherwise, treat landing as an additional thin-wrapper
   candidate using the same rules as step 2:
   - For each entry in `landing.source_files` (typically just `src/app/page.tsx`):
     compute `PR_file_boundary ∩ {entry}`. If any landing source file is in PR
     boundary, landing is NOT a thin wrapper for this PR (page-local changes
     present); skip claim assignment for landing and proceed to Stage 1.
   - Otherwise (landing source files all outside PR boundary): read each
     `landing.source_files` file. Extract imports per the same regex/filter
     rules as step 2 (drop shadcn primitives, resolve `@/` alias).
     Intersect imported shared paths with `PR_file_boundary`.
     If intersection is non-empty: landing is a **thin wrapper with claimable
     dependencies** — feed it into step 3 (claim assignment) alongside
     non-landing candidates.
3. **Assign claims (first-claimer-wins):** Sort candidate pages: root `/` (landing) first,
   then alphabetical by route. For each page, for each claimable shared dependency:
   - If not yet claimed by another page → assign to this page
   - If already claimed → skip (first claimer owns it)
4. **Write `.runs/design-claims.json`** before first agent spawn:
   ```json
   {
     "claims": {
       "src/components/landing-content.tsx": "landing"
     },
     "thin_wrappers": ["landing"]
   }
   ```
   If no thin wrappers detected: write with empty `claims` and `thin_wrappers` arrays.
   > **Backward compatible:** All downstream logic (gate validation, Stage 1c exclusion)
   > treats missing or empty `design-claims.json` as "no claims" — current behavior preserved.

5a. **Lead-supplied fallback boundary for full-tree mode OR bootstrap-verify diff mode** (#1196 + #1450 gap 13 — fires when either trigger condition holds):

   **Trigger conditions (either suffices):**
   - `BOUNDARY_KIND == "full-tree"` (no commits on feature branch yet) — the original #1196 case.
   - `BOUNDARY_KIND == "diff" AND MODE == "bootstrap-verify"` (#1450 gap 13) — state-16 implementer commits test files, producing `BOUNDARY_KIND=diff` with non-empty divergence, but test commits don't touch `src/app/<page>/**`, so `PR_file_boundary ∩ src/app/<page>/**` is empty. Per-page agents would fast-path with `verdict=boundary-skip` — exactly the failure mode #1381 D3 was designed to prevent. The lead-supplied `design-page-set.json` boundary is the canonical source of truth in this case.

   For each entry in `.runs/design-page-set.json["pages"]`:
   - Compute `fallback_boundary[page]` = page-local files matched by `src/app/<page>/**` (recursive)
     **MINUS** shadcn primitives (drop any path starting with `src/components/ui/` or `src/components/magicui/` per the same shadcn-primitive filter applied to imports in step 2 above)
     **MINUS** `**/api/**` (API routes are not visual)
   - For landing entry (`design-page-set.json["landing"]`, may be null):
     - If null → skip landing
     - Else use `landing.source_files` (already filtered to non-API page sources by `derive_pages.py:392-421`)
       and apply the same shadcn filter

   When either trigger condition holds, the FILE_BOUNDARY emitted into the agent's spawn prompt (next step) MUST use `fallback_boundary[page]` instead of `PR_file_boundary ∩ src/app/<page>/**`.

   The agent contract is unchanged — design-critic always sees a concrete reviewable boundary. Skill identity stays in the lead.

   **Why this preserves #1381 D3's intent**: D3 was designed to keep test-only commits from masking unreviewed scaffold UI. The fallback fires precisely when test-only commits produce an empty `src/app/<page>/**` intersection — the same condition D3 surfaces — and substitutes the canonical page-set source. The substitution doesn't bypass D3's intent; it implements it.

#### Stage 1: Per-page review (parallel)

**Page set is canonical in `.runs/design-page-set.json`** (produced by
state-2a). Do NOT re-scan the filesystem here; any discrepancy between
state-2a's scan and a re-scan at Stage-1 would silently drift the per-page
VERIFY in state-3b. Read the file and iterate its `pages` array.

```bash
python3 -c "import json; print(json.dumps(json.load(open('.runs/design-page-set.json')).get('pages',[]), indent=2))"
```

Also read `.runs/page-image-map.json` to look up each page's `has_images`
classification (from state-2a's two-layer static classifier) — this flag
must be forwarded into the per-page spawn prompt so agents know whether
`image_issues_for_landing` emission is mandatory (#1042).

**Landing entry (issue #1143):** read `.runs/design-page-set.json["landing"]`.

```bash
python3 -c "import json; ps=json.load(open('.runs/design-page-set.json')); landing=ps.get('landing'); print(json.dumps(landing) if isinstance(landing, dict) else 'NULL')"
```

If non-null, **spawn TWO landing-scope agents in parallel** (#1468 landing-critic split — sections + images on independent maxTurns budgets) in the SAME single-message Agent batch alongside the non-landing per-page agents:

1. `landing-sections-critic` — Layer 1/2/3 section scoring, non-image fixes. Trace filename: `landing-sections-critic.json`.
2. `landing-images-critic` — Step 5.5 image candidate inspection, image-quality anti-patterns, image fixes. Trace filename: `landing-images-critic.json`.

Both agents receive the same landing prompt fields:
- `name: "landing"`, `route_pattern: "/"`, `test_url: "/"`
- `FILE_BOUNDARY` = `landing.source_files ∩ PR_file_boundary` (often empty for
  landing-only-via-shared-component PRs)
- `CLAIMED_SHARED` = files claimed for landing in `.runs/design-claims.json`
  (typically `src/components/landing-content.tsx` when present in PR)
- `has_images: true` (from `page-image-map.json["pages"]["landing"]` —
  always `landing-hardcoded` for landing)

**Sibling coordination:**
- `landing-sections-critic` MUST observe image issues in trace under `image_issues_for_landing` (`[{slot, issue}]`) but MUST NOT touch `.runs/image-candidates.json`.
- `landing-images-critic` owns `candidates_tried`, `new_candidates_generated`, `unresolved_images`, `image_scores`, `image_fixes`. Step 5.5 candidate confirmation is REQUIRED when sidecar exists.
- Both agents share the dev-server URL passed via `base_url`. Do NOT start a second server.

After both landing siblings complete, the lead invokes `python3 .claude/scripts/merge-landing-critic-traces.py` to pre-aggregate the two traces into `design-critic-landing.json`. This pre-merge MUST happen BEFORE the outer `merge-design-critic-traces.py` run so the outer merger sees `design-critic-landing.json` as a normal sibling.

**Non-landing pages** (everything else in `pages[]`) continue to spawn a single `design-critic` per page as below — no split.

Spawn **one design-critic agent per page**, ALL as parallel foreground Agent calls in a **SINGLE message**. Each agent prompt includes:
- Page name and route: "Review SINGLE page: `<page_name>` at route `<route_pattern>` (concrete test URL: `<test_url>`)." Pass BOTH `route_pattern` (literal `/quote/[id]` form) AND `test_url` (concretized with synthetic IDs from state-2a) — the agent forwards both into `render-review-detection.md` so the DEMO_MODE fixture short-circuit branch can fire.
- `base_url`: `http://localhost:3000` (from [Dev Server Preamble](../verify.md#dev-server-preamble-if-archetype-is-web-app))
- `demo_mode`: `"true"` — the preamble runs the dev server under `DEMO_MODE=true` (required by the #1042 DEMO_MODE fixture short-circuit branch in render-review-detection.md).
- `run_id`: from verify-context.json
- Per-page file boundary with structured marker. Compute `PR_file_boundary ∩ src/app/<page>/**` — shared paths (`src/components/**`, `src/lib/**`) are explicitly EXCLUDED from per-page agents. Pass ONLY page-local files. Include in the prompt as a machine-parseable block:
  ```
  FILE_BOUNDARY_START
  src/app/<page>/page.tsx
  src/app/<page>/<page>-content.tsx
  FILE_BOUNDARY_END
  ```
  > **Hook-enforced:** `skill-agent-gate.sh` validates that no shared paths appear between these markers. The hook will BLOCK the agent spawn if shared paths are detected.
- **Claimed shared dependencies** (only for thin-wrapper pages with claims in `design-claims.json`):
  Include a SEPARATE machine-parseable block for claimed shared files. These are placed OUTSIDE
  the `FILE_BOUNDARY` markers:
  ```
  CLAIMED_SHARED_START
  src/components/landing-content.tsx
  CLAIMED_SHARED_END
  ```
  > **Semantics:** The agent MAY read and fix files listed in `CLAIMED_SHARED`. These are shared
  > components that this page visually depends on and that were changed in this PR. The agent
  > should review them in the context of this page's visual design.
  > **Hook-enforced:** `skill-agent-gate.sh` validates claimed paths against `.runs/design-claims.json`.
  > Unclaimed shared paths will BLOCK the agent spawn.
  > Pages without claims in `design-claims.json` do NOT receive this marker block.
- Context digest summary
- Image candidates sidecar path + image-inspection contract (#1042):
  - For the **landing page** critic, include: "Image candidates sidecar:
    `.runs/image-candidates.json` — you have full read-write access for
    candidate evaluation in Step 5.5. Emit `candidates_tried` in your trace."
  - For **non-landing pages** with `page_image_map[<page>].has_images==true`,
    include: "Image candidates sidecar: `.runs/image-candidates.json`
    (READ-ONLY context). This page renders images (`has_images=true` per
    state-2a classifier; evidence: `<detected_via>`). You MUST inspect
    the rendered image(s) in your screenshot and emit
    `image_issues_for_landing` in your trace — a JSON array of
    `{slot, issue}` entries; use `[]` if no issues found. The KEY must
    be present even when the array is empty; its absence will block the
    state-3b VERIFY."
  - For **non-landing pages** with `has_images=false`, include: "Image
    candidates sidecar: `.runs/image-candidates.json` (READ-ONLY context).
    This page does not render images (`has_images=false` per state-2a).
    `image_issues_for_landing` is optional — omit if you observe nothing
    image-related."
- Instruction to write trace as `design-critic-<page_name>.json`
- **Pre-condition for fast-path** (#1196): the empty-boundary fast-path is only valid when `BOUNDARY_KIND == "diff"`. When `BOUNDARY_KIND == "full-tree"` (no commits exist; typical at /bootstrap pre-commit), the lead has already supplied a non-empty fallback boundary in Step 5a above — the FILE_BOUNDARY block in the spawn prompt will not be empty. If you encounter `BOUNDARY_KIND="full-tree"` AND empty FILE_BOUNDARY, this is a contract violation by the lead — emit `degraded_reason="lead-supplied-empty-boundary-in-full-tree-mode"` and verdict=fail; do NOT take fast-path.
- **Empty-boundary fast path** (#1061): If ALL files between `FILE_BOUNDARY_START` and `FILE_BOUNDARY_END`
  are empty (no page-local files in PR) **AND no `CLAIMED_SHARED_START`/`CLAIMED_SHARED_END` block
  is present**, execute a **fast-path review**: check whether any modified library files (`src/lib/**`)
  or shared components (`src/components/**`) from the full PR boundary are imported by this page.
  If no imports found, **SKIP procedures/design-critic.md Step 3.5** (do NOT call
  render-review-detection — there is no render to classify; the agent has no work for this page
  in this PR). Then return the fast-path JSON
  `{"verdict":"pass","fast_path":true,"pages_reviewed":1,"min_score":10,
  "checks_performed":["import-chain-check"],"fixes_applied":0,"sections_below_8":0,
  "unresolved_sections":0}` AND write the trace via the self-degraded helper:
  ```bash
  python3 .claude/scripts/write-degraded-trace.py design-critic \
    --reason "empty-boundary-fast-path" \
    --verdict pass \
    --checks-performed "import-chain-check" \
    --trace-filename design-critic-<page>.json \
    --extra-json '{"review_method":"boundary-skip",
                   "review_evidence":{"requested_route":"<route>","final_url":null,
                                      "auth_source":null,
                                      "fallback_reason":"empty-boundary-fast-path",
                                      "content_density":null},
                   "page":"<page>","fast_path":true,"min_score":10,"min_score_all":10,
                   "pages_reviewed":1,"sections_below_8":0,"fixes_applied":0,
                   "unresolved_sections":0,"image_issues_for_landing":[],
                   "candidates_skipped_evidence":{"reason":"empty-boundary-fast-path"},
                   "boundary_kind":"$BOUNDARY_KIND"}'
  ```
  The helper writes `provenance="self-degraded"`, `partial=true`, `degraded_reason="empty-boundary-fast-path"`,
  and `no_fixes_claimed=true` (since `fixes:[]`). State-3b Stage-1c will run
  `validate-recovery.sh` on this trace to stamp `recovery_validated=true` BEFORE the merge —
  satisfying the `validated_fallback` predicate so `aggregate_ok` accepts this sibling
  without manual lead override.
  > **`review_method="boundary-skip"` semantics:** state-3a-synthetic value, emitted **only**
  > by this fast-path branch. NOT produced by `render-review-detection.md` Section 3
  > (which only outputs `rendered-authed | rendered-demo | source-only | unknown | prereq-unmet`).
  > Distinguishes "no work for this page in PR" from "couldn't render, blind." The merge
  > script's tight gate (`merge-design-critic-traces.py`: search for "boundary-skip" in the source-only/unknown unresolved-forcing branch) excludes `boundary-skip`
  > from the source-only/unknown unresolved-forcing rule. POLICY drift test
  > (`test_review_verdict_gate_policy_drift.py`) is unaffected — `boundary-skip` does NOT
  > appear in `render-review-detection.md`.
  >
  > If imports found, run procedures/design-critic.md Step 3.5 normally and fall back to
  > standard screenshot + 8-criteria review for this page only.
  > **Thin-wrapper override:** If a `CLAIMED_SHARED` block IS present, do NOT fast-path even
  > if FILE_BOUNDARY is empty. The claimed shared files constitute the agent's review and edit
  > scope. Perform full screenshot + 8-criteria review, treating CLAIMED_SHARED files as in-scope
  > for fixes.
- Shared-component reporting instruction:
  > When you find issues in files outside BOTH your `FILE_BOUNDARY` AND your
  > `CLAIMED_SHARED` block (shared components in `src/components/` or `src/lib/`
  > that are NOT listed in either marker), record them in your trace:
  > - `"unresolved_shared": <count>` — number of unresolved issues in unclaimed shared files
  > - `"shared_issues": [{"file": "...", "section": "...", "description": "..."}]`
  > Do NOT attempt to fix these unclaimed files. They will be handled by a separate agent.
  > Files listed in your `CLAIMED_SHARED` block ARE in-scope — fix them directly and
  > count them in `fixes_applied`, not in `unresolved_shared`.

**Wait for all per-page agents to complete.**

After completion: use [Trace State Detection](../verify.md#trace-state-detection) to check **each** `design-critic-<page_name>.json` individually (and `landing-sections-critic.json` + `landing-images-critic.json` for the landing pair). If any agent is State 2 (exhausted), follow [Exhaustion Protocol](../verify.md#exhaustion-protocol) Tier 1 with reduced scope: "Focus on this page only." If State 1 (never started) and agent returned output, write a recovery trace.

**Landing pre-merge (#1468):** If both `landing-sections-critic.json` AND `landing-images-critic.json` exist, run the pre-aggregator BEFORE Stage 1b so the outer Stage-1c flow sees a single `design-critic-landing.json` sibling:

```bash
python3 .claude/scripts/merge-landing-critic-traces.py
```

This writes `.runs/agent-traces/design-critic-landing.json` with `provenance="lead-merge"` and the field ownership table specified in the merger script. If either sub-trace is sparse (init-stub survived), the merger logs a warning and the new GECR rule `sparse-trace-pairing` (`.claude/patterns/gate-evidence-rules.json`) emits a paired-observation candidate via the OARC enumerator path.

#### Stage 1b: Orchestrator shared-component fixes (serial)

After all per-page agents complete AND before Stage 2 (consistency check):

1. Read each per-page trace. If any trace output mentions shared-component issues without fixing them (shared paths were excluded from boundary), the orchestrator applies those fixes serially, one file at a time.
2. Run `npm run build` after shared-component fixes. If build fails, fix (max 2 attempts).
3. Each shared-component fix MUST be logged via the canonical fix-ledger writer in step 4 below — do NOT write to `.runs/fix-log.md` directly (AOC v1 R2: `.runs/fix-log.md` is derived from `.runs/fix-ledger.jsonl` by `render-fix-log.py`; direct writes are silently overwritten and would also be blocked at runtime by `fix-ledger-write-guard.sh`).
4. **Write each fix to the canonical fix-ledger** so the merger's lead-fix crediting (`merge-design-critic-traces.py:284-303`) and the Step 4.7 lifecycle gate have data:
   ```bash
   python3 .claude/scripts/write-fix-ledger.py --lead-fix \
     --skill verify \
     --fix-json '{"file":"<file>","symptom":"<short symptom>","fix":"<short fix description>"}' \
     --severity warn
   ```
5. **Per-page re-evaluation (#1274 — closes Case 1).** After all shared-component fixes
   for this Stage 1b cycle land, re-spawn `design-critic` for every page whose per-page
   trace reported the just-fixed file under `shared_issues[*].file`. Pseudocode:
   ```bash
   python3 -c "
   import json, glob, os, sys
   try:
       fixed = set()
       with open('.runs/fix-ledger.jsonl') as f:
           for line in f:
               try:
                   e = json.loads(line)
               except Exception:
                   continue
               if e.get('provenance') in ('lead', 'lead-on-behalf') and e.get('file'):
                   fixed.add(e['file'])
       affected = set()
       for tf in glob.glob('.runs/agent-traces/design-critic-*.json'):
           bn = os.path.basename(tf)
           if bn in ('design-critic.json', 'design-critic-shared.json'):
               continue
           if '--epoch' in bn:  # already a re-evaluation
               continue
           try:
               d = json.load(open(tf))
           except Exception:
               continue
           page = d.get('page') or d.get('weakest_page') or bn.replace('design-critic-', '').replace('.json', '')
           for si in d.get('shared_issues', []) or []:
               if si.get('file') in fixed:
                   affected.add(page)
                   break
       print(' '.join(sorted(affected)))
   "
   ```
   For each `<page>` returned, spawn `design-critic` via the Agent tool with:
   - `subagent_type: design-critic`
   - File boundary: just the page route (same as the original Stage 1 spawn for that page)
   - Trace name: `design-critic-<page>--epoch<N>.json` (N = highest existing epoch + 1, default 1)
   - The agent invokes `write-agent-trace.sh` with `--provenance self` (verify is still
     the active skill — R4 of `source_identity_validator` forbids `lead-orchestrated`
     mid-skill) AND `--epoch <N>` AND `--trace-filename design-critic-<page>--epoch<N>.json`
   - Task: "This is a post-shared-fix re-evaluation. Re-screenshot and re-score the page
     with the freshly-applied shared-component fix. Confirm `unresolved_sections=0` if
     the fix landed cleanly, or report the remaining issues."

   The merger picks the latest valid trace per page via `select_latest_per_page_traces`,
   so the original `design-critic-<page>.json` stays on disk for HC3 forensic
   provenance but does not feed the aggregate verdict.

6. If no shared-component issues reported: steps 1-5 are no-ops.

#### Stage 1c: Shared-component design-critic agent (serial, conditional)

> **Why Stage 1c does NOT supersede Stage 1b's per-page re-spawn (#1274 round-2 critic
> C6):** Stage 1c reviews the shared component file IN ISOLATION (a synthetic boundary
> containing only the unclaimed shared files). It verifies the FIX works in the
> component's standalone context, but it does NOT re-screenshot the per-page consumers
> of that component — pages may still regress in different theme/layout context. The
> per-page re-spawn from Stage 1b step 5 covers exactly this gap.

**Guard**: scope is `full` or `visual` AND archetype is `web-app` AND any per-page
trace has `unresolved_shared > 0` for **unclaimed** shared components (issues in shared
files that were NOT claimed by any per-page agent via `design-claims.json`). If all
reported shared issues are for claimed components, Stage 1c has no work — skip to Stage 2.

1. Collect reported-but-unfixed shared-component issues from the
   **latest per-page trace** for each page (post-fix epoch traces
   supersede pre-fix originals — closes #1274 follow-up gap):
   ```bash
   python3 -c "
   import sys, json
   sys.path.insert(0, '.claude/scripts/lib')
   from design_critic_trace_selector import select_latest_per_page_traces
   issues = []
   for f in select_latest_per_page_traces('.runs/agent-traces', 'design-critic'):
       d = json.load(open(f))
       for si in d.get('shared_issues', []):
           issues.append(si)
   if issues: print(json.dumps(issues, indent=2))
   else: print('NONE')
   "
   ```
   If `NONE`: this step is a no-op. Skip to Stage 2.

   This consumes the SAME helper as `merge-design-critic-traces.py` and
   `aggregate_ok` so Stage 1c never sees stale shared_issues from a
   pre-fix per-page trace whose page already has a post-fix epoch trace
   showing the issue resolved.
2. Spawn a SINGLE `design-critic` agent (`subagent_type: design-critic`) with:
   - Trace name: `design-critic-shared.json`
   - File boundary: INVERTED — ONLY `src/components/**` and `src/lib/**` files from the PR boundary,
     **MINUS paths claimed in `.runs/design-claims.json`**. Claimed components were already
     reviewed and fixed by their claiming page's agent.
     ```bash
     # Compute Stage 1c boundary (exclude claimed components)
     python3 -c "
     import json
     claims = {}
     try: claims = json.load(open('.runs/design-claims.json')).get('claims', {})
     except: pass
     pr_shared = [f for f in PR_FILES if f.startswith('src/components/') or f.startswith('src/lib/')]
     unclaimed = [f for f in pr_shared if f not in claims]
     for f in unclaimed: print(f)
     "
     ```
     Include only the **unclaimed** files in the FILE_BOUNDARY:
     ```
     FILE_BOUNDARY_START
     <unclaimed src/components/... files>
     <unclaimed src/lib/... files>
     FILE_BOUNDARY_END
     ```
     > **Empty-after-claims guard:** If ALL shared files from the PR are claimed (unclaimed
     > list is empty), Stage 1c has no work to do. Skip to Stage 2.
   - Input: the collected shared-component issues from step 1
   - Task: "Fix ONLY the shared-component visual issues reported by per-page agents. Do NOT perform a full design review — focus on the specific issues listed."
   - Include `run_id`, context digest, and agent-prompt-footer content
3. After completion: use [Trace State Detection](../verify.md#trace-state-detection) on `design-critic-shared.json`. If State 2 (exhausted), follow [Exhaustion Protocol](../verify.md#exhaustion-protocol) Tier 1 with reduced scope: "Fix only the highest-impact shared issue."
4. Run `npm run build`. If build fails, fix (max 2 attempts).
5. Log each fix via the canonical fix-ledger writer (AOC v1 R2 — do NOT write to `.runs/fix-log.md` directly):
   ```bash
   python3 .claude/scripts/write-fix-ledger.py --lead-fix \
     --skill verify \
     --fix-json '{"file":"<file>","symptom":"<short symptom>","fix":"<short fix description>"}' \
     --severity warn
   ```

> **Hook-enforced:** `skill-agent-gate.sh` blocks `design-consistency-checker` spawn if per-page traces report shared-component issues but `design-critic-shared.json` does not exist.

**POSTCONDITIONS:**
- `.runs/design-claims.json` exists (may have empty `claims` if no thin wrappers detected)
- Per-page `design-critic-<page>.json` traces exist for all discovered pages (when scope is `full` or `visual` AND archetype is `web-app`)
- `design-critic-landing.json` trace exists when scope is `full` or `visual` AND archetype is `web-app` AND `.runs/design-page-set.json["landing"]` is a non-null dict (#1143)
- `design-critic-shared.json` exists if any per-page trace reported `unresolved_shared > 0` for unclaimed shared components
- Build passes after all Stage 1/1b/1c fixes

**VERIFY:**
```bash
python3 -c "import json,glob,os,sys; ctx=json.load(open('.runs/verify-context.json')); needs_dc=ctx.get('scope') in ('full','visual') and ctx.get('archetype')=='web-app'
if os.path.exists('.runs/all-pages-fast-path-decision.json'):
    assert os.path.exists('.runs/design-claims.json'), 'Stage 0: design-claims.json missing'
    assert os.path.exists('.runs/agent-traces/design-critic.json'), 'Stage 0: design-critic.json (lead-synthesized aggregate) missing'
    sys.exit(0)
assert not needs_dc or os.path.exists('.runs/design-claims.json'), 'design-claims.json missing (pre-flight must run before agent spawns)'; ps=json.load(open('.runs/design-page-set.json')) if os.path.exists('.runs/design-page-set.json') else {'landing': None, 'not_applicable': True}; expects_landing=needs_dc and isinstance(ps.get('landing'), dict); assert (not expects_landing) or os.path.exists('.runs/agent-traces/design-critic-landing.json'), 'design-critic-landing.json missing — Stage 1 must spawn landing critic when design-page-set.json has a landing entry (#1143)'; fs=sorted(glob.glob('.runs/agent-traces/design-critic-*.json')) if needs_dc else []; per_page=[f for f in fs if os.path.basename(f) not in ('design-critic.json','design-critic-shared.json')]; assert not needs_dc or len(per_page)>=1, 'no per-page design-critic traces (scope=%s, archetype=%s)' % (ctx.get('scope'),ctx.get('archetype')); shallow=[]
for f in per_page:
    d=json.load(open(f))
    if d.get('partial') is True: continue
    if d.get('fast_path') is True: continue
    if d.get('provenance') in ('self-degraded','recovery'): continue
    if d.get('verdict') in ('unresolved','fail'): continue
    if not ('exit_code' in d or 'verdict' in d): shallow.append(f+' (no exit_code/verdict)'); continue
    if not isinstance(d.get('checks_performed'),list) or len(d.get('checks_performed',[]))<3:
        shallow.append(f+' (checks_performed shallow: '+str(len(d.get('checks_performed',[])))+')')
    elif d.get('pages_reviewed',0)<1:
        shallow.append(f+' (pages_reviewed=0)')
assert not shallow, 'non-degraded design-critic traces below depth threshold (issue #1124 over-block fix iterates all): '+str(shallow)"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh verify 3a
```

**NEXT:** Read [state-3b-quality-gate.md](state-3b-quality-gate.md) to continue.
