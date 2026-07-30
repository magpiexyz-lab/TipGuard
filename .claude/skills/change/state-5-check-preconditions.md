# STATE 5: CHECK_PRECONDITIONS

**PRECONDITIONS:**
- Classification determined (STATE 4 POSTCONDITIONS met)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.

> **Precondition types:** This step contains two kinds of checks: (1) *condition-specific* checks that trigger based on what the change involves (e.g., adding payment, setting production mode), applying to all change types when the condition is met; and (2) *type-specific* checks that apply only to certain classifications (e.g., Test, Upgrade). Both must be evaluated.

> **Branch cleanup on failure:** Any "stop" in this step leaves you on a feature branch (created in Step 1). Append cleanup boilerplate per `.claude/patterns/branch-cleanup-error-template.md` to every stop message — Variant A when a recovery action is given inline, Variant B when only an abort path applies. **Important:** the typical recovery for `/change` precondition stops is to switch to main (`git checkout main`), edit experiment.yaml as the stop message specifies, then re-run `/change` — do NOT edit experiment.yaml on the feature branch, as `/change` reads it during state 2 on the base branch.

- Follow checkpoint resumption protocol per `patterns/checkpoint-resumption.md`. (Key: read frontmatter, validate archetype match, restore context, jump to target state)
- If `.runs/current-plan.md` exists and the current branch starts with `change/`:
  1. Read frontmatter. If parsing fails: stop — "Plan file has corrupted frontmatter. Delete `.runs/current-plan.md` and re-run `/change` to start fresh."
  2. Compare frontmatter `archetype` to current experiment.yaml `type`. If they differ: stop — "Saved plan was for archetype `<saved>`, but experiment.yaml now specifies `<current>`. Delete `.runs/current-plan.md` and re-run `/change` for a new plan."
  3. Use frontmatter values directly — do NOT re-classify or re-resolve stack. Read context_files to restore context.
  4. Resume per /change checkpoint mapping:

     | Checkpoint | Resumes at |
     |-----------|------------|
     | `phase2-gate` | STATE 8 (Phase 2 Pre-flight) |
     | `phase2-step5` | STATE 9 (update specs) |
     | `phase2-step6` | STATE 10 (implement) |
     | `phase2-step7` | STATE 11a (verify prep) |
     | `phase2-step8` | STATE 12 (commit/PR) |

     If `checkpoint` is present but does not match any row above: stop — "Saved plan has unrecognized checkpoint `<value>`. Delete `.runs/current-plan.md` and re-run `/change` for a fresh start. (Append Variant B.)"

  5. If no frontmatter (old format): warn user, read experiment.yaml type, skip Phase 1, jump to Step 5.
- Else if `.runs/current-plan.md` exists but NOT on a `change/` branch: offer resume or fresh start, then stop.
> **If resuming from a failed /change:** see `.claude/patterns/recovery.md`. The plan persists across sessions.
- If the change will add any new category to experiment.yaml `stack`: read the archetype file's `excluded_stacks` list. If the new category appears in `excluded_stacks`, stop: "The `<archetype>` archetype excludes the `<category>` stack. You cannot add `<category>: <value>` to this project. (Append Variant B.)"
- For analytics changes: verify the analytics library file exists (see analytics stack file for expected path). If it doesn't, stop and tell the user: "Analytics library not found. Run `/bootstrap` first. (Append Variant B.)"
- Validate stack dependencies per `patterns/stack-dependency-validation.md` — read the Dependency Matrix, Compatibility Constraints, Error Message Templates, and Assumes-List Validation sections. Use the canonical error messages from that file (appending branch cleanup instructions for `/change` context). Key checks: payment requires auth+database; email requires auth+database; auth_providers requires auth; playwright incompatible with service/cli.
- If `$ARGUMENTS` mentions payment or the change will add `payment` to the stack: verify auth and database are present per the Dependency Matrix, then read the payment stack file's `assumes` list and verify each `category/value` pair against experiment.yaml `stack` per the Assumes-List Validation section. If any assumption is unmet, stop with the unmet dependencies and branch cleanup instructions.
- If `$ARGUMENTS` mentions email or the change will add `email` to the stack: verify auth and database are present per the Dependency Matrix, then read the email stack file's `assumes` list and verify per the Assumes-List Validation section. If any assumption is unmet, stop with the unmet dependencies and branch cleanup instructions.
- If `testing` is present in experiment.yaml `stack` and the classified type is NOT Test: read the testing stack file's `assumes` list and verify each `category/value` pair against experiment.yaml `stack` (the value must match exactly, not just the category — e.g., `database/supabase` requires `stack.database: supabase`, not just any database provider). If any assumption is unmet, stop: "Your testing setup assumes [unmet dependencies]. Tests will break. Run '/change fix test configuration' first, or remove 'testing' from experiment.yaml 'stack'. (Append Variant A, recovery: 'address the missing dependencies, then re-run `/change`'.)" Then check archetype compatibility: if archetype is `service` or `cli` and `stack.testing` is `playwright`, stop: "Playwright requires a browser and is not compatible with the `<archetype>` archetype. Use `testing: vitest` instead. (Append Variant A, recovery: 'change `stack.testing` to `vitest`, then re-run `/change`'.)"
- Validate framework-archetype compatibility: if archetype is `web-app` and framework is not `nextjs`, stop — "The `web-app` archetype requires `nextjs` as the framework. Change `stack.services[].runtime` to `nextjs`. (Append Variant B.)" If archetype is `cli` and framework is not `commander`, stop — "The `cli` archetype requires `commander` as the framework. Change `stack.services[].runtime` to `commander`. (Append Variant B.)"
- If classified as Test type AND `stack.testing` is absent: this is valid — the Test type change will add testing to experiment.yaml. Skip the testing-presence check below and proceed to the Test type handler. Check archetype compatibility: if archetype is `service` or `cli` and the planned testing value is `playwright`, stop: "Playwright requires a browser and is not compatible with the `<archetype>` archetype. Use `testing: vitest` instead. (Append Variant A, recovery: 'change `stack.testing` to `vitest`, then re-run `/change`'.)" Record that testing will be added during this change — the plan must include adding `testing` to experiment.yaml `stack` and creating test infrastructure.
- If classified as NOT Test type: verify `stack.testing` is present in experiment.yaml. If absent: stop — "Testing framework required. Add `testing: playwright` (web-app) or `testing: vitest` (service/cli) to experiment.yaml `stack`. (Append Variant A, recovery: 'switch to main (`git checkout main`), add testing to experiment.yaml stack, then re-run `/change`'.)"
- If classified as Test type AND `stack.testing` is present: check archetype compatibility first — if archetype is `service` or `cli` and `stack.testing` is `playwright`, stop: "Playwright requires a browser and is not compatible with the `<archetype>` archetype. Use `testing: vitest` instead. (Append Variant A, recovery: 'change `stack.testing` to `vitest`, then re-run `/change`'.)" Then read the testing stack file's `assumes` list and check each `category/value` against experiment.yaml `stack` (per bootstrap's validation approach: the value must match, not just the category). Record the result — this determines the template path reported in the plan.
- If classified as Upgrade: scan for a Fake Door or stub related to the feature described in `$ARGUMENTS`. Where to scan depends on the archetype: web-app → scan `src/app/` for a Fake Door component (`fake_door: true` in a `track()` call) or a stub route (501/503); service → scan route handlers (path per framework stack file) for a stub route (501/503 with `"Service not configured"`); cli → scan `src/commands/` for a stub command (prints "Coming soon" or exits with error). If neither a Fake Door nor a stub is found, reclassify as Feature and tell the user: "No Fake Door or stub found for this feature — treating as a new Feature instead."

**POSTCONDITIONS:**
- All precondition checks passed (or resuming from checkpoint)
- No blocking conditions remain
- If resuming: checkpoint target state identified

**VERIFY:**
```bash
python3 -c "import json; ctx=json.load(open('.runs/change-context.json')); assert isinstance(ctx.get('preconditions_checked'), list) and len(ctx['preconditions_checked'])>0, 'preconditions_checked missing or empty'"
```

**STATE TRACKING:** After postconditions pass, update context and mark this state complete:
```bash
PAYLOAD=$(python3 -c "
import json
ctx = json.load(open('.runs/change-context.json'))
ctx['preconditions_checked'] = ['<list>', '<of>', '<checks>', '<that>', '<passed>']
print(json.dumps(ctx))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/change-context.json \
  --payload "$PAYLOAD" \
  --skill change
bash .claude/scripts/advance-state.sh change 5
```

**NEXT:** If resuming from a checkpoint, follow the checkpoint target (see resume logic above). Otherwise, read [state-6-present-plan.md](state-6-present-plan.md) to continue.
