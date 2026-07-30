# STATE 12: EXTERNALS_DECISIONS

**PRECONDITIONS:**
- Scaffold done, all subagents returned (STATE 11c POSTCONDITIONS met)
- Externals classification table available from scaffold-externals
- Optional: load Stack Knowledge hints (stable + canonical, non-graduated)
  into memory via `scripts/lib/stack_knowledge_parser.py::parse_stack_knowledge_file`
  across every path returned by `iter_stack_knowledge_files()` (single source of
  truth — currently `.claude/stacks/**/*.md` plus `.claude/scripts/lib/README.md`).
  Absent sections are expected (HC3 —
  never blocking). These hints warn against known-bad env-var guard patterns
  and Fake Door wirings before decisions are made.

**ACTIONS:**

> **BLOCKING by default — present to user.** The purpose is explicit user
> buy-in on external dependencies. NEVER self-decide on a classification
> with `unknown`, conflicting LLM-vs-registry signals, or any non-trivial
> credential question.
>
> **No-stop opt-in (#1450 gap 12):** when the session sets `--no-stop`
> AND every external in the classification table satisfies ALL of:
>   (a) `classification` is `keep` or `stub` (not `unknown`),
>   (b) no conflict between LLM judgment and registry hint,
>   (c) no credential value needs to be collected from the user,
> THEN proceed silently — write the externals-decisions artifact and the
> BG2.5 verdict directly without an interactive prompt. The
> `no_stop_compatible: true` flag on this state's entry in
> `state-registry.json` is the contract that callers (e.g.,
> bootstrap-verify mode) use to know the silent path is sanctioned.
>
> When even one external is ambiguous, the BLOCKING path applies
> regardless of `--no-stop`. The point of the override is to skip
> obvious decisions, not to suppress real choices.

To detect `--no-stop`:
```bash
NO_STOP=$(python3 -c "
import json
try:
    d = json.load(open('.runs/bootstrap-context.json'))
    print('1' if d.get('no_stop') is True else '0')
except Exception:
    print('0')
" 2>/dev/null)
```

Branch:
- If `NO_STOP=1` AND every classification table row is unambiguous (per
  the three conditions above): write artifacts silently and advance.
- Else: continue with the interactive procedure below.

After the externals subagent returns its classification table:

1. **Present classification to user**: show the core/non-core table and
   collect decisions (Fake Door / Skip / Full Integration / Provide now /
   Provision at deploy) for each dependency.
2. **Collect credentials**: for "Provide now" choices, ask the user for
   credential values.
3. **Consult Stack Knowledge hints before deciding**: load
   `.runs/bootstrap-state12-stack-knowledge-hints.json` (may be empty — HC3).
   For each proposed decision, check whether any hint's `composite_identity`
   (particularly `stack_scope` matching the current service and
   `root_cause_class` covering env-var guards or Fake Door wiring) applies.
   When a `canonical` entry applies, treat its `fix_template` as mandatory
   (e.g., a specific env-var guard shape, a specific Fake Door component
   location). When a `stable` entry applies, apply unless there is a concrete
   reason not to; cite the entry's `id` in the externals-decisions artifact.
4. **Execute remaining work** -- explicit externals checklist:

   For each decision where `user_choice` is one of {Provide now, Provision at deploy, Full Integration}:
   - [ ] Check if a pre-built stack file already exists at `.claude/stacks/*/<service-slug>.md`
         (any subdirectory — e.g., `ai/`, `database/`, `payment/`). If found, skip generation
         and use the pre-built file. Only generate `.claude/stacks/external/<service-slug>.md`
         when no pre-built file exists.
   - [ ] Run `python3 .claude/scripts/validate-frontmatter.py` on the resolved stack file path
         (the pre-built file from the glob check above, or the newly generated `external/` file)
         to verify frontmatter is well-formed
   - [ ] Add env var guard: create or update the relevant API route to return 503 with
         `{ error: "<service> not configured" }` when the required env var is missing
   - [ ] Update `.env.example` with the new env var(s) and descriptive comments

   Additional steps by decision type:
   - **Provide now**: write user-provided credential values to `.env.local`
   - **Provision at deploy**: add placeholder values to `.env.example` with
     `# Set during deployment` comment; add to `.env.local` as empty strings
   - **Full Integration**: write credentials to `.env.local`, verify integration
     with a smoke check (e.g., import succeeds, env var is non-empty at runtime)

   After all externals are processed: create Fake Door entries (see below).

If the externals subagent reported "No external dependencies", confirm
to the user and proceed.

### Fake Door Integration

If the externals analysis reported Fake Door features, the bootstrap lead
creates them directly:

For each Fake Door feature, generate a component in the page folder where the
feature would naturally appear (e.g., `src/app/dashboard/sms-fake-door.tsx`):
- Use the canonical Fake Door Component template at `.claude/stacks/ui/<stack.ui>.md` § Fake Door Component (the stack file declared in `experiment.yaml`). Copy the TSX template verbatim into `src/app/<page>/<component>.tsx` (project-owned).
- The template is button-only intent capture: a click fires `track("activate", { fake_door: true, action: actionLabel, service })` per Rule 4 of the Intent Capture Contract (`.claude/procedures/scaffold-externals.md` § Intent Capture Contract). Do NOT collect email or any other PII at the template default — lead-capture features (email + persistence + outreach) go through `/change` as a separately declared Feature.
- Import and render the Fake Door component in the parent page where the feature would naturally live.
- The component should look like a real feature entry point -- not a placeholder or disabled button.

**Fake Door VERIFY**: For each Fake Door component created:
- Confirm the file is in `src/app/<page>/` (NOT in `src/components/`)
- Confirm the parent page imports and renders the component
- If either check fails, move/fix the component immediately

Check off in `.runs/current-plan.md`:
- `- [x] Externals user decisions collected`

Write the externals decisions to disk as a durable artifact:
```bash
cat > externals-decisions.json << 'EXTEOF'
{
  "has_externals": <true|false>,
  "user_confirmed": true,
  "decisions": [<array of {"service","feature","classification","user_choice"}>],
  "fake_doors": [<array of {"feature","service","target_page","component_name","component_export_name","action_label"}>],
  "timestamp": "<ISO 8601>"
}
EXTEOF
```
If no external dependencies: `has_externals` is `false`, arrays are `[]`.

Write Stack Knowledge hints artifact (`.runs/bootstrap-state12-stack-knowledge-hints.json`) — active prevention input consulted during env-var guard + Fake Door wiring decisions:
```bash
PAYLOAD=$(python3 -c "
import json, sys
sys.path.insert(0, 'scripts')
from lib.stack_knowledge_parser import iter_stack_knowledge_files, parse_stack_knowledge_file
ACTIVE = {'stable', 'canonical'}
hints = []
sources = []
for path in iter_stack_knowledge_files():
    entries = parse_stack_knowledge_file(path)
    if not entries:
        continue
    sources.append(path)
    for e in entries:
        if e.get('maturity') in ACTIVE and e.get('graduated_to') is None:
            hints.append({'source': path, 'id': e.get('id'), 'maturity': e.get('maturity'), 'composite_identity': e.get('composite_identity'), 'composite_identity_hash': e.get('composite_identity_hash'), 'fix_template': e.get('fix_template'), 'prevention_mechanism': e.get('prevention_mechanism'), 'occurrence_count': e.get('occurrence_count')})
import sys
print(f'bootstrap state12 stack-knowledge hints: {len(hints)} active entries from {len(sources)} files', file=sys.stderr)
print(json.dumps({'entries': hints, 'source_files': sources, 'count': len(hints)}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/bootstrap-state12-stack-knowledge-hints.json \
  --payload "$PAYLOAD" \
  --skill bootstrap
```
HC3: absent sections = empty hints list. Never blocking. No new VERIFY assertion.

**BG2.5 Externals Gate**: Spawn the `gate-keeper` agent (`subagent_type: gate-keeper`). Pass: "Execute BG2.5 Externals Gate. Verify: (1) externals-decisions.json exists with correct structure (has_externals, user_confirmed, decisions, fake_doors, timestamp); (2) for each decision where user_choice is 'Provide now', 'Provision at deploy', or 'Full Integration': .env.example contains the required env var(s); (3) for each such decision: grep the relevant API route file for a 503 response guard referencing the service's env var — BLOCK if any route is missing the guard; (4) for each such decision: verify a stack file exists at `.claude/stacks/*/<service-slug>.md` (any subdirectory — e.g., `ai/`, `external/`, `database/`) — BLOCK if no stack file found for any such decision."

Check off in `.runs/current-plan.md`: `- [x] BG2.5 Externals Gate passed`

**POSTCONDITIONS:**
- BG2.5 Externals Gate verdict is PASS
- User decisions collected for all external dependencies
- Fake Door components created (if any)
- Env vars written (if any)
- `.runs/bootstrap-state12-stack-knowledge-hints.json` exists (HC3: may contain empty `entries` array)

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/gate-verdicts/bg2.5.json')); assert d.get('verdict')=='PASS', 'BG2.5 verdict is %s' % d.get('verdict'); assert d.get('timestamp','')!='', 'timestamp empty'" && test -f .runs/bootstrap-state12-stack-knowledge-hints.json
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 12
```

**NEXT:** Read [state-13-merged-validation.md](state-13-merged-validation.md) to continue.
