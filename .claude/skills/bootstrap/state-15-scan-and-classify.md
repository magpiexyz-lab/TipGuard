# STATE 15: SCAN_AND_CLASSIFY

**PRECONDITIONS:**
- STATE 14 POSTCONDITIONS met (wire phase complete, build passes)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Primary unit".
> [primary-unit] web-app: page (`src/app/<page>/page.tsx`) | service: endpoint (`src/app/api/<ep>/route.ts`) | cli: command (`src/commands/<cmd>.ts`)

Scan the bootstrapped codebase to classify modules for unit test generation.

- Read `experiment/experiment.yaml` (behaviors, golden_path, stack, type)
- Read the archetype file at `.claude/archetypes/<type>.md`
- Read the framework stack file at `.claude/stacks/framework/<runtime>.md` for file structure conventions
- Scan for modules based on archetype:
  - **web-app**: page and API route directories (e.g., `src/app/` for Next.js), `src/components/`, `src/lib/`
  - **service**: route handler directory (e.g., `src/app/api/` for Next.js, `src/routes/` for Hono), `src/lib/`
  - **cli**: `src/commands/`, `src/lib/`
- Glob for existing tests (`**/*.test.*`, `**/*.spec.*`, `e2e/**`)
- Classify each module into 4 categories:

  **CRITICAL** (generate unit tests now): Auth/session logic, payment/billing, data mutations (POST/PUT/DELETE API routes with DB writes), golden_path activation steps, behaviors with `actor: system/cron`, non-trivial business logic

  **ON-TOUCH** (defer to /change): Read-only API routes (GET), form validation, data fetching/transformation, golden_path non-value-moment steps

  **SKIP** (no unit tests needed): Page/view components (rendering + layout only), UI components, static content, configuration

  **ALREADY COVERED**: Modules with existing test files

- **Write scan artifact** (`.runs/bootstrap-scan.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  scan = {
      'critical': [],      # list of {module, files, reason}
      'on_touch': [],      # list of {module, reason}
      'skip': [],          # list of {module, reason}
      'already_covered': []  # list of {module, test_file}
  }
  print(json.dumps(scan))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/bootstrap-scan.json \
    --payload "$PAYLOAD" \
    --skill bootstrap
  ```

Check off in `.runs/current-plan.md`: `- [x] Scan & classify (state 15)` (#1118)

**POSTCONDITIONS:**
- All modules scanned and classified
- `.runs/bootstrap-scan.json` exists

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/bootstrap-scan.json')); assert isinstance(d.get('critical'), list), 'critical not a list'; assert isinstance(d.get('on_touch'), list), 'on_touch not a list'; assert isinstance(d.get('skip'), list), 'skip not a list'; assert isinstance(d.get('already_covered'), list), 'already_covered not a list'; assert len(d['critical'])+len(d['on_touch'])+len(d['skip'])+len(d['already_covered'])>0, 'scan classified nothing'; assert all(isinstance(m,dict) and m.get('module') for m in d['critical']), 'critical items missing module field'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 15
```

**NEXT:** Read [state-16-unit-test-generation.md](state-16-unit-test-generation.md) to continue.
