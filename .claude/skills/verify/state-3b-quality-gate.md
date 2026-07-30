# STATE 3b: QUALITY_GATE

**PRECONDITIONS:** STATE 3a complete (per-page and shared design-critic traces exist, build passes).

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Visual agents".
> [visual-agents] web-app: design-critic, ux-journeyer, consistency-checker | service: skip | cli: skip

#### Stage 0 short-circuit (#1256)

If `.runs/all-pages-fast-path-decision.json` exists, state-3a's Stage 0
already wrote the lead-synthesized `design-critic.json` AND
`design-consistency-checker.json` aggregates. Skip Stages 1c, 2 (Step A
merger), and Step B (consistency-checker spawn) entirely; proceed to the
post-design-critic lint gate and lead-side validation.

> **GRAIM C3 invariant**: Stage 0 fires only when `boundary_kind == diff`
> (gated upstream in state-3a's detector). In `boundary_kind == full-tree`
> mode (no commits exist on the feature branch), Stage 0 is skipped because
> the empty diff is ambiguous, not a "no UI changes" signal — the existing
> per-page lead-supplied fallback boundary path runs instead. This decision
> is made in state-3a; state-3b only reads the resulting decision artifact.

```bash
if [ -f .runs/all-pages-fast-path-decision.json ]; then
  echo "Stage 0 fast-path active — skipping Stage 1c, Step A merger, Step B consistency-checker spawn"
fi
```

The blocks below each gate on file existence directly (`.runs/all-pages-fast-path-decision.json`) — bash variables do NOT persist between separate fenced bash blocks because each fence is its own subprocess.

#### Stage 1c: Pre-merge validate-recovery for self-degraded traces (#1042)

> **Skip when Stage 0 fired.** No per-page self-degraded traces exist in fast-path mode.

For every per-page design-critic trace with `provenance="self-degraded"`
(typically DEMO_MODE fixture short-circuits written via
`write-degraded-trace.py` — see `.claude/agents/design-critic.md` Verdict
gate Sub-branch S1), stamp `recovery_validated=true` BEFORE the Stage-2
merge. Without this stamp, the aggregate trace cannot satisfy the
`aggregate_ok` hard-gate predicate (sibling check requires
`validated_fallback`, which keys on `provenance ∈ {recovery, self-degraded}
AND recovery_validated==true`).

```bash
if [ ! -f .runs/all-pages-fast-path-decision.json ]; then
  for trace in .runs/agent-traces/design-critic-*.json; do
    [[ "$trace" == *"-shared.json" ]] && continue
    [[ "$trace" == *"/design-critic.json" ]] && continue
    prov=$(python3 -c "import json,sys; print(json.load(open('$trace')).get('provenance',''))" 2>/dev/null || echo "")
    if [[ "$prov" == "self-degraded" ]]; then
      base=$(basename "$trace" .json)
      bash .claude/scripts/validate-recovery.sh "$base" || {
        echo "BLOCK: validate-recovery failed for $trace" >&2
        exit 1
      }
    fi
  done
fi
```

Idempotency: `validate-recovery.sh` is re-entrant — when
`recovery_validated` is already `true`, it re-writes the same value with
no side effects beyond a single JSON file touch. Safe to re-run on
retries.

**Prerequisite check:** this block depends on `.runs/build-result.json`
having `exit_code=0` (state-1). If the build failed,
`validate-recovery.sh` returns non-zero and the Stage-1c loop aborts —
which is correct (you cannot clear `aggregate_ok` on a broken build).

#### Stage 2: Consistency check + merge

##### Step A: Lead merges per-page traces

> **Skip when Stage 0 fired.** The lead-synthesized `design-critic.json` aggregate already exists; the merger is not invoked.

Before spawning the consistency checker, the lead merges per-page traces into `design-critic.json`. The merge logic lives in a dedicated script so `agent-trace-write-guard.sh` can authorise exactly this write (issue #1045 — inline `python3 -c` blocks that open `agent-traces/*` for write are blocked by the guard's open-for-write regex):

```bash
if [ ! -f .runs/all-pages-fast-path-decision.json ]; then
  python3 .claude/scripts/merge-design-critic-traces.py
fi
```

Exit codes: `0` merge succeeded, `1` no per-page traces found, `2` per-page trace parse error. Preserves every field the prior inline merge produced (pages_reviewed, min_score, checks_performed, per_page_review_methods, per_page_review_evidence, review_method_gate_corrections, pre_existing_debt, fixes, shared_fixes_applied, run_id, timestamp). The merger also consults `.runs/fix-ledger.jsonl` for lead-applied shared-component fixes (#1274) and emits `lead_fix_corrections[]` audit array; see Stage 1b doc above for the lead-side ledger contract.

After writing the merged trace, validate merge correctness:
```bash
if [ ! -f .runs/all-pages-fast-path-decision.json ]; then
  python3 -c "
import json, glob
merged = json.load(open('.runs/agent-traces/design-critic.json'))
pages = sorted(glob.glob('.runs/agent-traces/design-critic-*.json'))
pages = [p for p in pages if 'shared' not in p and p != '.runs/agent-traces/design-critic.json']
total_checks = sum(len(json.load(open(p)).get('checks_performed', [])) for p in pages)
merged_checks = len(merged.get('checks_performed', []))
if merged_checks != total_checks:
    print(f'WARN: Merge mismatch — per-page total {total_checks}, merged {merged_checks}')
else:
    print(f'Merge validation: PASS ({merged_checks} checks)')
"
fi
```

> **Do NOT delete per-page traces** — the consistency checker needs them for cross-page comparison.

##### Step B: Page-batched consistency check (#1257)

> **STOP HERE when Stage 0 fired (`.runs/all-pages-fast-path-decision.json` exists).** The lead-synthesized `design-consistency-checker.json` aggregate already exists with `verdict=pass, inconsistent_count=0`. Do NOT run the prepass or spawn agents — duplicates would collide with the lead-synthesized trace and waste turns. Skip directly to the post-design-critic lint gate. Concretely:
>
> ```bash
> if [ -f .runs/all-pages-fast-path-decision.json ]; then
>   echo "Stage 0 active — skipping Step B page-batched consistency check"
>   # Jump to the post-design-critic lint gate below; do NOT execute B.1-B.4.
> fi
> ```

The page-batched architecture replaces the prior single-agent loop (PR #1296 soft-exit primitive, superseded by #1257 final). The lead pre-computes deterministic work once; each batch agent only judges severity of pre-detected anomaly candidates. Each batch agent has the full `maxTurns=1000` budget for ≤8 pages — exhaustion class eliminated.

###### B.1: Lead-side prepass

```bash
if [ ! -f .runs/all-pages-fast-path-decision.json ]; then
  python3 .claude/scripts/run-consistency-static-prepass.py \
    --base-url "http://localhost:3000" \
    --batch-size 8
fi
```

Writes `.runs/consistency-check-prepass.json` containing:
- `partition`: list of `{batch_id, pages}` entries (ceil(N/8) batches; `batch_id="single"` when N ≤ 8)
- `global_frequency_maps`: C1-C4 grep frequency maps across all pages
- `dom_features`: C5 structural feature vectors via Playwright (per-page renderer)
- `anomaly_candidates`: pages that deviate from the ≥80% majority on any check
- `c5_method`: `"playwright"` on success or `"static-fallback"` if Playwright was unavailable

###### B.2: Decide single-batch vs multi-batch

Read `prepass.partition`:
- **Single batch** (`batch_id="single"`, N ≤ 8): proceed to B.3a (legacy single-spawn path).
- **Multi-batch** (N > 8): proceed to B.3b (page-batched parallel path).

###### B.3a: Single-batch path

Spawn 1 `design-consistency-checker` agent with the spawn prompt carrying:
- `prepass_artifact`: `.runs/consistency-check-prepass.json`
- `batch_id`: `"single"`
- `assigned_pages`: full page list from `prepass.partition[0].pages`
- `base_url`: `http://localhost:3000`
- `run_id`: from `verify-context.json`

The agent writes `design-consistency-checker.json` directly (no batch suffix) with `provenance=self`.

###### B.3b: Multi-batch path

Spawn K `design-consistency-checker` agents in a **single message batch** (mirrors state-3a Stage 1 pattern — emit K Agent tool calls in one assistant message). Each spawn prompt carries:
- `prepass_artifact`: `.runs/consistency-check-prepass.json`
- `batch_id`: e.g., `"batch1"` (from `prepass.partition[i].batch_id`)
- `assigned_pages`: from `prepass.partition[i].pages`
- `base_url`: `http://localhost:3000`
- `run_id`: from `verify-context.json`

Each batch agent writes `design-consistency-checker-<batch_id>.json` via `write-agent-trace.sh --trace-filename`.

Wait for all batch agents to complete, then run the aggregator:

```bash
python3 .claude/scripts/merge-design-consistency-checker-traces.py
```

The aggregator emits `design-consistency-checker.json` with `provenance="lead-merge"` + `contributing_spawn_indexes` (canonical AOC v1.1 fields). The existing `aggregate_ok` hard-gate predicate (`evaluate-hard-gate-predicates.py:131-174`) accepts it.

###### B.4: Exhaustion handling

If a batch agent exhausts (Tier 2 protocol per `verify.md`), the merger sees a `verdict=incomplete` recovery trace among siblings. The `aggregate_ok` predicate's sibling-validation chain handles this (a recovery trace can satisfy `validated_fallback` if `recovery_validated=true`). No special-case soft-exit logic remains in the procedure.

#### Post-design-critic lint gate

After ALL per-page agents + Stage 1b + Stage 2 (consistency check) complete:

1. Run: `npm run build && npm run lint`
2. If lint errors (not warnings):
   - Fix unused imports (max 2 attempts) — this is the most common issue after multi-agent edits
   - Log each fix via the canonical writer (AOC v1 R2 — do NOT write to `.runs/fix-log.md` directly):
     ```bash
     python3 .claude/scripts/write-fix-ledger.py --lead-fix --skill verify \
       --fix-json '{"file":"<file>","symptom":"lint error after multi-agent edits","fix":"removed unused import"}'
     ```
3. If build errors: fix (max 2 attempts), append to fix-log
4. Re-run `npm run build && npm run lint` to confirm clean.

> **Downstream compatibility**: skill-agent-gate.sh and gate-keeper BG3 check the merged `design-critic.json` — no changes needed. `agents_completed` still lists `"design-critic"` (singular).

#### Lead-side validation (design-critic)

1. Read `.runs/agent-traces/design-critic.json` trace (merged by lead in Step A).
2. Verify `pages_reviewed` >= number of discovered pages (filesystem + golden_path union).
3. If `verdict` == `"unresolved"`, this is a **hard gate failure** — design quality threshold (8/10) was not met after 2 fix attempts. Skip STATEs 4-5 but still write verify-report.md (STATE 7a) and execute STATE 8 (Save Patterns). Report failure to user with the `unresolved_sections` count.
4. If `min_score` < 8 and `verdict` == `"fixed"`, note in verify report that threshold was met after fixes.
5. If `pre_existing_debt` is non-empty, note pre-existing quality debt in verify report (informational, does not block).
6. Extract Fix Summaries from per-page agent return messages. Log each fix via the canonical writer (AOC v1 R2 — do NOT write to `.runs/fix-log.md` directly):
   ```bash
   python3 .claude/scripts/write-fix-ledger.py --lead-fix --skill verify \
     --fix-json '{"file":"<file>","symptom":"<from agent Fix Summary>","fix":"<from agent Fix Summary>"}'
   ```
7. Note `pages` count and `consistency_fixes` count in verify report.

### Lead-applied fixes from Phase 1 findings

After reviewing Phase 1 agent findings (spec-reviewer, accessibility-scanner, behavior-verifier, performance-reporter) and applying any fixes directly (not via a Phase 2 agent), log each fix via the canonical writer (AOC v1 R2 — do NOT write to `.runs/fix-log.md` directly):

```bash
python3 .claude/scripts/write-fix-ledger.py --lead-fix --skill verify \
  --fix-json '{"file":"<file>","symptom":"<what agent found>","fix":"<what you changed>"}'
```

The renderer (`render-fix-log.py`) regenerates `.runs/fix-log.md` from the populated ledger during the skill epilogue, surfacing the fix under a `Fix (lead-<source>)` heading whose source is derived from the calling Phase 1 agent. Sources: `lead-spec-reviewer`, `lead-a11y`, `lead-behavior-verifier`, `lead-perf`.

> **Why:** Phase 1 agents are read-only. When the lead acts on their findings, those fixes must be logged via the canonical ledger or the observation epilogue cannot evaluate them for template-rooted issues. Direct writes to `.runs/fix-log.md` are blocked at runtime by `fix-ledger-write-guard.sh` and are silently overwritten by `render-fix-log.py` (AOC v1 R2).

### Lead-applied SHARED-component fixes (state-3a Stage 1b)

When the lead applies a fix to a shared component during state-3a Stage 1b
(e.g., `src/components/landing-content.tsx` flagged as `unresolved_shared` by a
per-page critic), the fix MUST be logged to BOTH `.runs/fix-log.md` AND
`.runs/fix-ledger.jsonl`:

```bash
python3 .claude/scripts/write-fix-ledger.py --lead-fix \
  --run-id "$RUN_ID" \
  --file "src/components/landing-content.tsx" \
  --symptom "<what the per-page critic flagged>" \
  --fix "<what was changed>"
```

Per-page design-critic traces are immutable post-write — they continue to
record the pre-fix `unresolved_shared` count. The merger
(`merge-design-critic-traces.py`) consults `fix-ledger.jsonl` and credits
lead-applied fixes against the merged aggregate's `unresolved_sections` count.
The audit trail is in `merged["lead_fix_corrections"]`. Without the ledger row,
the merger cannot credit the fix, and the aggregate verdict will keep
`unresolved` even though the underlying issue was fixed (#1274).

**POSTCONDITIONS:**
- Merged `design-critic.json` trace exists in `.runs/agent-traces/`
- `design-consistency-checker.json` trace exists (when scope is `full` or `visual` AND archetype is `web-app`)
- Build and lint pass after all fixes
- Lead-applied fixes from Phase 1 findings logged in `fix-log.md`

**VERIFY:**
```bash
python3 -c "import json,os,glob,sys; ctx=json.load(open('.runs/verify-context.json')); needs_dc=ctx.get('scope') in ('full','visual') and ctx.get('archetype')=='web-app'
if os.path.exists('.runs/all-pages-fast-path-decision.json'):
    assert os.path.exists('.runs/agent-traces/design-critic.json'), 'Stage 0: design-critic.json missing'
    assert os.path.exists('.runs/agent-traces/design-consistency-checker.json'), 'Stage 0: design-consistency-checker.json missing'
    assert json.load(open('.runs/build-result.json'))['exit_code']==0, 'Stage 0: build failed'
    assert os.path.exists('.runs/design-page-set.json'), 'Stage 0: design-page-set.json missing'
    assert os.path.exists('.runs/page-image-map.json'), 'Stage 0: page-image-map.json missing'
    sys.exit(0)
assert not needs_dc or os.path.exists('.runs/agent-traces/design-critic.json'), 'design-critic.json missing (scope=%s, archetype=%s)' % (ctx.get('scope'),ctx.get('archetype')); assert not needs_dc or os.path.exists('.runs/agent-traces/design-consistency-checker.json'), 'design-consistency-checker.json missing'; assert json.load(open('.runs/build-result.json'))['exit_code']==0; assert (not needs_dc) or os.path.exists('.runs/design-page-set.json'), 'design-page-set.json missing (state-2a must run before state-3b)'; assert (not needs_dc) or os.path.exists('.runs/page-image-map.json'), 'page-image-map.json missing (state-2a must run before state-3b)'; ps=json.load(open('.runs/design-page-set.json')) if os.path.exists('.runs/design-page-set.json') else {'pages':[], 'landing': None, 'not_applicable': not needs_dc}; pim=json.load(open('.runs/page-image-map.json')).get('pages',{}) if os.path.exists('.runs/page-image-map.json') else {}; has_candidates=os.path.exists('.runs/image-candidates.json'); landing_trace='.runs/agent-traces/design-critic-landing.json'; landing_d=json.load(open(landing_trace)) if os.path.exists(landing_trace) else None; sc_path='.runs/image-candidates.json'; sidecar={}
if has_candidates:
    try: sidecar=json.load(open(sc_path))
    except (json.JSONDecodeError, OSError): sidecar={}
landing_unused=sum(max(0, len(s.get('candidates',[]))-1) for sn,s in sidecar.get('slots',{}).items() if sn!='empty-state')
landing_sd=(landing_d is not None and landing_d.get('provenance')=='self-degraded' and landing_d.get('recovery_validated') is True)
expects_landing=needs_dc and isinstance(ps.get('landing'), dict)
assert (not expects_landing) or landing_d is not None, 'design-critic-landing.json missing (state-3a must spawn landing critic when design-page-set.json has a landing entry; #1143 defense-in-depth)'
if expects_landing and landing_unused>0 and not landing_sd:
    ct=landing_d.get('candidates_tried', 0); ur=landing_d.get('unresolved_images', []) or []
    assert ct>0 or len(ur)>0, 'design-critic-landing did not run Step 5.5 confirmation pass: sidecar has '+str(landing_unused)+' unused candidates in landing-owned slots, candidates_tried='+str(ct)+', unresolved_images=[]. #1129 (regression of #1076).'
missing_iifl=[]
for p in (ps.get('pages') or []):
    name=p.get('name') if isinstance(p, dict) else None
    if not name: continue
    tp='.runs/agent-traces/design-critic-'+name+'.json'
    if not os.path.exists(tp): continue
    if pim.get(name,{}).get('has_images') and 'image_issues_for_landing' not in json.load(open(tp)):
        missing_iifl.append(name)
assert not missing_iifl, 'image-rendering pages missing image_issues_for_landing field (state-3a prompt + state-2a classifier drift): ' + str(missing_iifl)
unstamped=[t for t in glob.glob('.runs/agent-traces/design-critic-*.json') if json.load(open(t)).get('provenance')=='self-degraded' and not json.load(open(t)).get('recovery_validated')]
assert not unstamped, 'self-degraded design-critic traces missing recovery_validated stamp (Stage-1c validate-recovery skipped?): ' + str(unstamped)
dcc_path='.runs/agent-traces/design-consistency-checker.json'
if needs_dc and os.path.exists(dcc_path) and not os.path.exists('.runs/all-pages-fast-path-decision.json'):
    dcc=json.load(open(dcc_path))
    if dcc.get('provenance')=='lead-merge':
        csi=dcc.get('contributing_spawn_indexes',[])
        assert isinstance(csi,list) and len(csi)>0, 'design-consistency-checker.json provenance=lead-merge but contributing_spawn_indexes empty/missing (#1257)'
        siblings=sorted(glob.glob('.runs/agent-traces/design-consistency-checker-batch*.json'))
        assert len(siblings)>=len(csi), 'expected '+str(len(csi))+' per-batch sibling traces, got '+str(len(siblings))+' (#1257)'
        pp_p='.runs/consistency-check-prepass.json'
        _pp=json.load(open(pp_p)) if os.path.exists(pp_p) else None
        _pt=_pp.get('partition') if _pp else None
        assert (not isinstance(_pt,list)) or len(_pt)<=1 or len(csi)>=len(_pt), 'partition expected '+str(len(_pt))+' batches; csi='+str(len(csi))+' (#1257 partition-cardinality)'" && python3 .claude/scripts/validate-step55-evidence.py
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh verify 3b
```

**NEXT:** Read [state-3c-ux-merge.md](state-3c-ux-merge.md) to continue.
