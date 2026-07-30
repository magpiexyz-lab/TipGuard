# STATE 4: GOLDEN_PATH

**PRECONDITIONS:**
- Behaviors derived (STATE 3 POSTCONDITIONS met)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Spec field".
> [spec-field] web-app: `golden_path` | service: `endpoints` | cli: `commands`
>
> State-specific logic below takes precedence.

Derive golden_path from behaviors. The format depends on the archetype:

**If type is `web-app`:**
```yaml
golden_path:
  - step: "<description>"         # e.g., "Visit landing page"
    event: <project_event>        # Use <object>_<action> naming (e.g., landing_view, page_visit)
    page: <page>
  # Continue through behavior chain to value moment
  - step: "<value-delivering action>"
    event: <core_action_event>    # e.g., invoice_created, repo_scanned
    page: <value page>
target_clicks: <N>
```

**If type is `service`:**
```yaml
endpoints:
  - path: "/<endpoint>"
    method: POST
    description: "<what this endpoint does>"
  # List all API endpoints from behaviors
golden_path:
  - step: "<description>"
    event: <project_event>        # e.g., request_received, data_ingested
    endpoint: "/<endpoint>"
  - step: "<value-delivering action>"
    event: <core_action_event>    # e.g., report_generated, webhook_delivered
    endpoint: "/<value endpoint>"
```

**If type is `cli`:**
```yaml
commands:
  - name: "<command>"
    description: "<what this command does>"
  # List all commands from behaviors
golden_path:
  - step: "<description>"
    event: <project_event>        # e.g., config_initialized, scan_started
    command: "<command>"
  - step: "<value-delivering action>"
    event: <core_action_event>    # e.g., report_exported, migration_completed
    command: "<value command>"
```

- `step:` replaces the old `action:` field
- The canonical page set is computed by `derive_scope_pages()` (see `.claude/templates/experiment-yaml.md` and `.claude/scripts/lib/derive_pages.py`) which unions `golden_path[*].page`, `behaviors[*].pages`, and auth-derived pages. This is what scaffold-pages spawns and what gate-keeper BG2 check 3b/3c enforces. There is no separate top-level `pages:` section.

**POSTCONDITIONS:**
- Golden path derived from behaviors
- Format matches archetype (web-app: pages, service: endpoints, cli: commands)
- Each step has step description, event, and page/endpoint/command

**VERIFY:**
```bash
python3 -c "import yaml; d=yaml.safe_load(open('experiment/experiment.yaml')); gp=d.get('golden_path') or d.get('endpoints') or d.get('commands'); assert isinstance(gp, list) and len(gp)>0, 'no golden_path/endpoints/commands'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh spec 4
```

**NEXT:** Read [state-5-variants.md](state-5-variants.md) to continue.
