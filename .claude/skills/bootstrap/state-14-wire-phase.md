# STATE 14: WIRE_PHASE

**PRECONDITIONS:**
- BG2 PASS, build passes (STATE 13c POSTCONDITIONS met)
- Optional: load Stack Knowledge hints (stable + canonical, non-graduated)
  into memory via `scripts/lib/stack_knowledge_parser.py::parse_stack_knowledge_file`
  across every path returned by `iter_stack_knowledge_files()` (single source of
  truth — currently `.claude/stacks/**/*.md` plus `.claude/scripts/lib/README.md`).
  Absent sections are expected (HC3 —
  never blocking). Wire decisions consult these hints to avoid known-bad
  layout / provider-wiring patterns.

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, rows "Trace field", "Spec field", "Primary unit".
>
> [trace-field] web-app: `pages_wired` + `api_routes_wired` | service: `api_routes_wired` | cli: `commands_wired`
> [spec-field] web-app: `golden_path` | service: `endpoints` | cli: `commands`
> [primary-unit] web-app: page (`src/app/<page>/page.tsx`) | service: endpoint (`src/app/api/<ep>/route.ts`) | cli: command (`src/commands/<cmd>.ts`)
>
> State-specific logic below takes precedence.

Spawn a subagent via Agent with:
- subagent_type: scaffold-wire
- prompt: Tell the subagent to:
  1. Read `.claude/procedures/wire.md` and execute Steps 5 through 8b ONLY.
     Do NOT run Step 8 (verify.md) or Step 9 (PR).
  2. Read context files before starting: `experiment/experiment.yaml`, `experiment/EVENTS.yaml`,
     `.runs/current-plan.md`, `.claude/archetypes/<type>.md`,
     all `.claude/stacks/<category>/<value>.md` for categories in experiment.yaml `stack`,
     `.claude/patterns/visual-review.md`,
     `.claude/patterns/security-review.md`,
     `.github/PULL_REQUEST_TEMPLATE.md`
  3. Include the completion reports from init, libs, pages, landing, and
     externals subagents (external dep decisions, generated files, env vars)
     in the prompt so the wire subagent has context
  4. **Read `.runs/bootstrap-state14-stack-knowledge-hints.json`** (may be
     empty — HC3). Every entry in `entries[]` is a pattern that has already
     been observed and sedimented. Treat `maturity: canonical` entries as
     HARD CONSTRAINTS — the wire implementation MUST avoid the
     `divergence_pattern` they describe. Treat `maturity: stable` entries as
     strong guidance. For each matching entry, apply the `fix_template`
     preemptively; cite the entry's `id` in the wire trace when you do.
  5. Follow CLAUDE.md Rules 1, 4, 5, 6, 7, 8, 10, 12

Update checkpoint in `.runs/current-plan.md` frontmatter to `awaiting-verify`.

Check off in `.runs/current-plan.md`: `- [x] scaffold-wire completed`

Verify scaffold-wire trace: `test -f .runs/agent-traces/scaffold-wire.json && python3 -c "import json;d=json.load(open('.runs/agent-traces/scaffold-wire.json'));assert d.get('status')=='completed';print('scaffold-wire trace: OK')"`. If trace missing: log "WARN: scaffold-wire did not write trace -- continuing with file-based verification".

- **Write Stack Knowledge hints artifact** (`.runs/bootstrap-state14-stack-knowledge-hints.json`) — active prevention consulted during wire decisions:
  ```bash
  python3 -c "
  import json, os, sys
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
  os.makedirs('.runs', exist_ok=True)
  json.dump({'entries': hints, 'source_files': sources, 'count': len(hints)}, open('.runs/bootstrap-state14-stack-knowledge-hints.json', 'w'), indent=2)
  print(f'bootstrap state14 stack-knowledge hints: {len(hints)} active entries from {len(sources)} files')
  "
  ```
  HC3: absent sections = empty hints list. Never blocking. No new VERIFY assertion. Pass this artifact's entries into the `scaffold-wire` agent prompt so wiring decisions avoid known-bad patterns.

- **Write wire trace artifact** (`.runs/bootstrap-wire-trace.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json, glob, os, yaml
  ey = yaml.safe_load(open('experiment/experiment.yaml'))
  arch = ey.get('type', 'web-app')
  stack = ey.get('stack', {})
  trace = {'checkpoint': 'awaiting-verify'}
  if arch == 'web-app':
      trace['pages_wired'] = [os.path.relpath(os.path.dirname(f), 'src/app') for f in glob.glob('src/app/**/page.tsx', recursive=True) if '/api/' not in f]
      trace['api_routes_wired'] = [os.path.relpath(os.path.dirname(f), 'src/app/api') for f in glob.glob('src/app/api/**/route.ts', recursive=True)]
      layout_components = []
      if stack.get('auth') and os.path.isfile('src/components/nav-bar.tsx'): layout_components.append('NavBar')
      if stack.get('analytics') and os.path.isfile('src/components/RetainTracker.tsx'): layout_components.append('RetainTracker')
      trace['layout_components_wired'] = layout_components
  elif arch == 'service':
      trace['pages_wired'] = []
      trace['api_routes_wired'] = [os.path.relpath(os.path.dirname(f), 'src/app/api') for f in glob.glob('src/app/api/**/route.ts', recursive=True)]
  elif arch == 'cli':
      trace['pages_wired'] = []
      trace['api_routes_wired'] = []
      trace['commands_wired'] = [os.path.splitext(os.path.basename(f))[0] for f in glob.glob('src/commands/*.ts')]
  print(json.dumps(trace))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/bootstrap-wire-trace.json \
    --payload "$PAYLOAD" \
    --skill bootstrap
  ```

**POSTCONDITIONS:**
- API routes created (if mutation behaviors exist) <!-- enforced by agent behavior, not VERIFY gate -->
- Wire integration complete <!-- enforced by agent behavior, not VERIFY gate -->
- Checkpoint updated to `awaiting-verify`
- `.runs/bootstrap-wire-trace.json` exists with wiring details
- `.runs/bootstrap-state14-stack-knowledge-hints.json` exists (HC3: may contain empty `entries` array)

**VERIFY:**
```bash
python3 -c "import json,os,re; d=json.load(open('.runs/bootstrap-wire-trace.json')); assert 'checkpoint' in d, 'checkpoint missing'; a=json.load(open('.runs/bootstrap-context.json')).get('archetype','web-app'); assert a!='web-app' or (isinstance(d.get('pages_wired'),list) and len(d['pages_wired'])>0), 'web-app: pages_wired empty or missing'; assert a!='service' or (isinstance(d.get('api_routes_wired'),list) and len(d['api_routes_wired'])>0), 'service: api_routes_wired empty or missing'; assert a!='cli' or (isinstance(d.get('commands_wired'),list) and len(d['commands_wired'])>0), 'cli: commands_wired empty or missing'; ey=open('experiment/experiment.yaml').read() if a=='web-app' else ''; has_auth=bool(re.search(r'^\s+auth:\s+\S',ey,re.MULTILINE)); has_analytics=bool(re.search(r'^\s+analytics:\s+\S',ey,re.MULTILINE)); layout=open('src/app/layout.tsx').read() if a=='web-app' and os.path.isfile('src/app/layout.tsx') else ''; assert not (a=='web-app' and has_auth) or 'nav-bar' in layout, 'layout.tsx missing NavBar import (stack.auth present)'; assert not (a=='web-app' and has_analytics) or 'RetainTracker' in layout, 'layout.tsx missing RetainTracker import (stack.analytics present)'" && python3 .claude/scripts/validate-scaffold-recommendations-schema.py
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 14
```

**NEXT:** Read [state-14a-bg2-wire-gate.md](state-14a-bg2-wire-gate.md) to continue.
