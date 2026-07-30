# STATE 9: SETUP_PHASE

**PRECONDITIONS:**
- Preflight done (STATE 8 POSTCONDITIONS met)
- `tsp_status` and quality flag available for subagent prompts

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
>
> State-specific logic below takes precedence.

Spawn a subagent via Agent with:
- subagent_type: scaffold-setup
- prompt: Tell the subagent to:
  1. Read `.claude/procedures/scaffold-setup.md` and execute all steps
  2. Read context files: `experiment/experiment.yaml`, all `.claude/stacks/<category>/<value>.md`
     for categories in experiment.yaml `stack`, `.claude/archetypes/<type>.md`
  3. TSP-LSP status: `<tsp_status from preamble>`
  4. Follow CLAUDE.md Rules 3, 4, 6, 7, 9

Wait for setup to complete before proceeding.

Run `npm audit --audit-level=critical`. If critical vulnerabilities are found, warn:
> "Critical npm vulnerabilities detected. Run `npm audit fix` after bootstrap completes."
Continue regardless — this is non-blocking during bootstrap.

Update checkpoint in `.runs/current-plan.md` frontmatter to `phase2-design`.

**Resolve surface type** (used by Design Phase and Landing subagent). Evaluate in order — first match wins:
1. If `stack.surface` is set in experiment.yaml, use it.
2. If the archetype is `service` and `stack.surface` is not set and the experiment defines no `golden_path` and no `endpoints` that serve HTML (pure API with no user-facing surface): `none`. Log to user: "Surface resolved to `none` — `/deploy` will not auto-deploy this service. Deploy your API manually, then create `.runs/deploy-manifest.json` with all service keys matching your stack (see `/deploy` STATE 0 and STATE 5 for the schema) to enable `/distribute` and `/teardown`."
3. If the archetype's `excluded_stacks` includes `hosting` and `stack.surface` is not set: `detached`.
4. Otherwise infer from hosting: `stack.services[0].hosting` present -> `co-located`; absent -> `detached`.

Check off in `.runs/current-plan.md`: `- [x] scaffold-setup completed`

Verify scaffold-setup trace: `test -f .runs/agent-traces/scaffold-setup.json && python3 -c "import json;d=json.load(open('.runs/agent-traces/scaffold-setup.json'));assert d.get('status')=='completed',f'unexpected status: {d.get(\"status\")}';print('scaffold-setup trace: OK')"`. If trace missing: log "WARN: scaffold-setup did not write trace -- continuing with file-based verification".

**POSTCONDITIONS:**
- `package.json` exists with `dependencies`
- `node_modules/` exists and is non-empty
- Surface type resolved
- Checkpoint updated to `phase2-design`

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('package.json')); assert 'dependencies' in d, 'dependencies missing'" && test -d node_modules && test -n "$(ls -A node_modules)"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 9
```

**NEXT:** Read [state-10-design-phase.md](state-10-design-phase.md) to continue.
