# STATE 11a: LIB_SPAWN

**PRECONDITIONS:**
- Core scaffold done (STATE 11 POSTCONDITIONS met)
- Phase A sentinel exists (web-app) or Phase A skipped (service/cli)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.

#### Phase B1 (libs + externals + images)

Spawn scaffold-libs, scaffold-externals, and (conditionally) scaffold-images in parallel. These have no cross-dependency. scaffold-pages and scaffold-landing are NOT spawned yet -- they depend on libs output.

**Libs subagent:**
- subagent_type: scaffold-libs
- prompt: Tell the subagent to:
  1. Read `.claude/procedures/scaffold-libs.md` and execute all steps
  2. Read context files: `experiment/experiment.yaml`, `experiment/EVENTS.yaml`,
     `.runs/current-plan.md`, all stack files
  3. Follow CLAUDE.md Rules 3, 4, 6, 7

**Externals subagent (analysis only):**
- subagent_type: scaffold-externals
- prompt: Tell the subagent to:
  1. Read `.claude/procedures/scaffold-externals.md` and execute the
     analysis steps (evaluate dependencies, classify core/non-core)
  2. Read context files: `experiment/experiment.yaml`, `.runs/current-plan.md`,
     `.claude/stacks/TEMPLATE.md`, existing stack files
  3. Follow CLAUDE.md Rules 3, 4, 6
  4. Return the classification table and Fake Door list -- do NOT collect
     credentials or write env vars (the lead handles those)

**Images subagent (conditional):**
Read `image_gen_status` from `.runs/bootstrap-context.json`.

If `image_gen_status` is `"available"`:
- subagent_type: scaffold-images
- prompt: Tell the subagent to:
  1. Read `.claude/procedures/scaffold-images.md` and execute all steps
  2. Read context files: `experiment/experiment.yaml`,
     `.runs/current-visual-brief.md`, `.runs/current-plan.md`
  3. Follow CLAUDE.md Rules 3, 6
- Expected outputs: `.runs/image-manifest.json` (required), `.runs/image-candidates.json` (bonus — candidate sidecar for design-critic)

If `image_gen_status` is `"skipped"`:
Do NOT spawn the images subagent. Instead, the bootstrap lead generates
SVG placeholders directly:
1. Create `public/images/` directory
2. For each image in the file path contract (see `.claude/stacks/images/fal.md`):
   generate a themed SVG placeholder using the primary color from `globals.css`.
   Save as `.svg` files (e.g., `public/images/hero.svg`, `public/images/feature-1.svg`, etc.)
3. Write `.runs/image-manifest.json`:
   ```json
   {"status": "placeholders", "fallback": true, "images": [
     {"filename": "hero.svg", "publicPath": "/images/hero.svg", "altText": "Hero illustration", "width": 1920, "height": 1080, "fallback": true},
     {"filename": "feature-1.svg", "publicPath": "/images/feature-1.svg", "altText": "Feature illustration", "width": 800, "height": 600, "fallback": true},
     {"filename": "feature-2.svg", "publicPath": "/images/feature-2.svg", "altText": "Feature illustration", "width": 800, "height": 600, "fallback": true},
     {"filename": "feature-3.svg", "publicPath": "/images/feature-3.svg", "altText": "Feature illustration", "width": 800, "height": 600, "fallback": true},
     {"filename": "empty-state.svg", "publicPath": "/images/empty-state.svg", "altText": "Empty state illustration", "width": 400, "height": 400, "fallback": true}
   ]}
   ```

Wait for all B1 subagents to return (libs, externals, and images if spawned). Sanity-check that each agent wrote its trace file:
- `test -f .runs/agent-traces/scaffold-libs.json`
- `test -f .runs/agent-traces/scaffold-externals.json`
- `test -f .runs/agent-traces/scaffold-images.json` (only when `image_gen_status` was `"available"`)

If any expected trace is missing, do NOT advance. Manifest content validation, scaffold-libs retry (1-budget), image SVG fallback, and the `tsc` type-check checkpoint (2-budget) all live in STATE 11b (`state-11b-lib-verify.md`) — keep those out of this state.

**Write spawn-result artifact** (inline, idempotent):

```bash
PAYLOAD=$(python3 -c "
import json, datetime, os
ctx = json.load(open('.runs/bootstrap-context.json'))
image_gen_config = ctx.get('image_gen_status', 'available')
agents = {
    'scaffold-libs':      {'spawned': True, 'spawn_count': 1, 'trace_path': '.runs/agent-traces/scaffold-libs.json'},
    'scaffold-externals': {'spawned': True, 'spawn_count': 1, 'trace_path': '.runs/agent-traces/scaffold-externals.json'},
    'scaffold-images':    {'spawned': image_gen_config == 'available', 'spawn_count': 1, 'image_gen_config': image_gen_config, 'trace_path': '.runs/agent-traces/scaffold-images.json'},
}
result = {
    'schema_version': 1,
    'state': '11a',
    'spawned_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'agents': agents,
}
print(json.dumps(result))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/b1-spawn-result.json \
  --payload "$PAYLOAD" \
  --skill bootstrap
```

**Field semantics:**
- `spawn_count` is the INITIAL spawn count from this state (always 1). It is NEVER updated on retry. Cumulative count after retries lives in `b1-verify-result.json.libs.cumulative_spawn_count` (owned by STATE 11b).
- `agents.scaffold-images.image_gen_config` is the INPUT flag from `bootstrap-context.json.image_gen_status`, NOT the output health. Output health (whether the manifest was actually written, whether SVG fallback was applied, image_count) lives only in `b1-verify-result.json.images`.

**B1 candidate sidecar (non-blocking, informational):**
1. `test -f .runs/image-candidates.json` — check if candidate sidecar exists
2. If present: this is a bonus artifact. Pass it as context to design-critic agents alongside `image-manifest.json`. The design-critic can try pre-generated candidates before regenerating from scratch.
3. If absent: design-critic operates with the current single-image flow (fully backwards compatible). No action needed.

Check off in `.runs/current-plan.md` (the plan template from `state-7-save-plan.md` uses "completed" — keep that wording for compatibility; here it means *agent dispatch completed*, not full validation; full B1 validation is STATE 11b):
- `- [x] scaffold-libs completed`
- `- [x] scaffold-externals completed`
- `- [x] scaffold-images completed` (or mark N/A if `image_gen_status` was `"skipped"`)

**POSTCONDITIONS:**
- `.runs/b1-spawn-result.json` exists with `schema_version=1`, `state="11a"`
- `agents.scaffold-libs.spawned is True`
- All spawned agent trace files exist on disk (presence only — STATE 11b reads `status` and decides retry/fallback/STOP)
- (Manifest content validation, scaffold-libs retry, image SVG fallback, and `tsc` type-check checkpoint are STATE 11b's responsibility — not gated here. This intentional separation lets 11b retry `scaffold-libs` when its trace `status != complete`.)

**VERIFY:**
```bash
test -f .runs/b1-spawn-result.json && python3 -c "import json,os; d=json.load(open('.runs/b1-spawn-result.json')); assert d.get('schema_version')==1 and d.get('state')=='11a'; ag=d.get('agents',{}); assert ag.get('scaffold-libs',{}).get('spawned') is True, 'scaffold-libs not spawned'; missing=[k for k,a in ag.items() if a.get('spawned') and not os.path.exists(a.get('trace_path',''))]; assert not missing, 'agent trace file missing on disk: '+str(missing)"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 11a
```

**NEXT:** Read [state-11b-lib-verify.md](state-11b-lib-verify.md) to continue.
