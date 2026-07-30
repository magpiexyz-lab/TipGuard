# STATE 11b: LIB_VERIFY

**PRECONDITIONS:**
- STATE 11a POSTCONDITIONS met (`.runs/b1-spawn-result.json` exists, all spawned agent traces present)
- May execute multiple times if STATE 11b STOPped on a previous attempt — supports resume contract

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
>
> All archetypes run this state — lib verification + type-check are universal. The libs scaffolded in STATE 11a need validation regardless of whether the project goes on to scaffold pages (web-app) or skip B2 (service/cli).

#### Phase B1 verification (libs + externals + images)

This state owns all *content* validation of B1 outputs. STATE 11a only spawns and confirms the agents returned; this state inspects what they wrote.

**(1) Resume detection:**

Read `.runs/b1-verify-result.json` if it exists from a prior STOP attempt. Extract `libs.cumulative_spawn_count` (default 1) and `type_check.fix_attempts` (default 0).

- Remaining libs retry budget = `2 - cumulative_spawn_count` (refuse retry once `cumulative_spawn_count >= 2`)
- Remaining type-check fix budget = `2 - fix_attempts` (refuse fix once `fix_attempts >= 2`)

If the file does not exist: initial values are `cumulative_spawn_count=1`, `fix_attempts=0`.

**(2) Libs manifest verification + 1-budget retry:**

1. `test -f .runs/agent-traces/scaffold-libs.json`
2. Read manifest, check `"status": "completed"`; `ls src/lib/*.ts` returns ≥ 1 file.
3. If manifest is missing or `status != "completed"`:
   - If remaining libs retry budget == 0 → write `b1-verify-result.json` (see (6) below) with `libs.manifest_status='incomplete'` and `type_check.passed=false`. **STOP.**
   - Else → re-spawn `scaffold-libs` ONCE with the same prompt as STATE 11a (`subagent_type: scaffold-libs`, same context files). Increment `cumulative_spawn_count`. After return, re-check the manifest.
   - If retry also fails → write `b1-verify-result.json` with the failure fields. **STOP.**

**(3) Image manifest + SVG fallback (non-blocking):**

1. `test -f .runs/image-manifest.json`
2. Read `b1-spawn-result.json.agents.scaffold-images.image_gen_config`.
3. If manifest is missing AND `image_gen_config == "available"`:
   - Bootstrap lead generates SVG placeholders directly (logic identical to STATE 11a's `"skipped"` path; see `.claude/stacks/images/fal.md` for filename contract).
   - Write `.runs/image-manifest.json` with `"status": "placeholders", "fallback": true`.
   - Set `images.fallback_applied=true` in the verify-result.
4. If the manifest exists with `"status": "complete"` but `len(images) < 7`: log a warning. This is informational only and never blocks.
5. **Image generation failure NEVER blocks the pipeline.**

**(4) Externals manifest verification:**

1. `test -f .runs/agent-traces/scaffold-externals.json`
2. Read `"status": "completed"`.
3. If manifest is missing or incomplete → write `b1-verify-result.json` with `externals.manifest_status='incomplete'` and `type_check.passed=false`. **STOP.**

**(5) Type-check checkpoint with 2-budget fix loop:**

1. Run `npx tsc --noEmit --project tsconfig.json`.
2. While there are errors AND remaining fix budget > 0:
   - Bootstrap lead fixes types directly (do not delegate to a subagent).
   - Increment `fix_attempts`.
   - Re-run `npx tsc --noEmit`.
3. If `tsc` still fails after the budget is exhausted → write `b1-verify-result.json` with `type_check.passed=false`, `fix_attempts=2`, `errors=[<list>]`. **STOP.** Do not advance to 11c. Report errors to the user: "Type errors in scaffold-libs output. Cannot proceed to page scaffold — page agents would inherit broken types. Errors: [list errors]"

**(6) Write verify-result UNCONDITIONALLY (R2-C4, R2-C5):**

Write `.runs/b1-verify-result.json` per the schema below. **Even on STOP** the file MUST be written so retry counts and fix attempts persist across resume cycles. Set the `passed` and `manifest_status` fields to reflect the actual outcome.

```json
{
  "schema_version": 1,
  "run_id": "<bootstrap-context.run_id>",
  "state": "11b",
  "verified_at": "<ISO8601>",
  "libs": {
    "manifest_path": ".runs/agent-traces/scaffold-libs.json",
    "manifest_present": true,
    "manifest_status": "complete",
    "retry_count": 0,
    "cumulative_spawn_count": 1,
    "ts_files_count": 5
  },
  "externals": {
    "manifest_path": ".runs/agent-traces/scaffold-externals.json",
    "manifest_present": true,
    "manifest_status": "complete"
  },
  "images": {
    "manifest_path": ".runs/image-manifest.json",
    "manifest_present": true,
    "manifest_status": "complete",
    "fallback_applied": false,
    "image_count": 7
  },
  "type_check": {
    "passed": true,
    "fix_attempts": 0,
    "errors": []
  }
}
```

**Field semantics:**
- `libs.retry_count`: re-spawns of `scaffold-libs` performed in *this* 11b instance.
- `libs.cumulative_spawn_count`: `1` (initial 11a spawn) + `retry_count`. Authoritative for cross-resume retry budget.
- `images.fallback_applied`: `true` when bootstrap lead generated SVG placeholders.
- `type_check.fix_attempts`: 0..2. `2` means budget exhausted; in that case `passed` MUST be `true` or this state STOPs without advancing.

Check off in `.runs/current-plan.md`:
- `- [x] B1 manifests verified`
- `- [x] type-check passes`

**POSTCONDITIONS:**
- `.runs/b1-verify-result.json` exists with `schema_version=1`, `state="11b"`
- `libs.manifest_status='complete'` AND `type_check.passed is True`
- `src/lib/` contains ≥ 1 `.ts` file
- Type-check passes (`npx tsc --noEmit` exit 0)

**VERIFY:**
```bash
test -f .runs/b1-verify-result.json && python3 -c "import json,glob; assert len(glob.glob('src/lib/*.ts'))>=1, 'no .ts in src/lib/'; d=json.load(open('.runs/b1-verify-result.json')); assert d.get('schema_version')==1 and d.get('state')=='11b'; assert d.get('libs',{}).get('manifest_status')=='complete', 'libs manifest not complete'; assert d.get('type_check',{}).get('passed') is True, 'type-check not passed'" && (test ! -f .runs/image-manifest.json || python3 .claude/scripts/verify-state-11a-image-count.py) && python3 .claude/scripts/validate-image-spec-compliance.py && python3 .claude/scripts/validate-scaffold-recommendations-schema.py
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 11b
```

**NEXT:** Read [state-11c-page-scaffold.md](state-11c-page-scaffold.md) to continue.
