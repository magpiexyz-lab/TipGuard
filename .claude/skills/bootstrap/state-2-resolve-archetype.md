# STATE 2: RESOLVE_ARCHETYPE_STACK

**PRECONDITIONS:**
- Context files read (STATE 1 POSTCONDITIONS met)
- `experiment/experiment.yaml` content is in context

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app: full app shell + pages + API + tests | service: skip Steps 3-4 (no app shell, no pages) | cli: skip Steps 3-5 (no app shell, no pages, no API)

- Validate the archetype type: read `type` from experiment.yaml (default `web-app`). If the archetype file `.claude/archetypes/<type>.md` does not exist, stop and tell the user: "Unrecognized archetype: `<type>`. Valid archetypes are the `.md` files in `.claude/archetypes/` (currently: web-app, service, cli). Check experiment.yaml `type` field or create a new archetype file at `.claude/archetypes/<type>.md` using web-app.md as a template."
- Read the archetype file at `.claude/archetypes/<type>.md`. The archetype defines required experiment.yaml fields, file structure, and funnel template. **If the archetype is `service`:** Steps 3-4 (app shell + pages) do not apply — skip them. Step 5 (API routes) becomes the primary implementation step. Step 7b uses the testing stack file's test runner (not necessarily Playwright). See the archetype file for full guidance. **If the archetype is `cli`:** Steps 3 (app shell/root layout), 4 (pages), and 5 (API routes) do not apply — skip them. The primary implementation is `src/index.ts` (CLI entry point with bin config) and `src/commands/` (one module per experiment.yaml command). There is no HTTP server, no landing page, no UI components. Analytics uses `trackServerEvent()` from the server analytics library. Step 7b uses the testing stack file's test runner (not Playwright — no browser). See the archetype file for full guidance.
- Read experiment.yaml `stack`. Skip structural keys (`services`, `auth_providers`) and configuration keys (`surface`) during category validation — these are not stack file categories. For each remaining category present in experiment.yaml `stack`, verify it appears in the archetype's `required_stacks`, `optional_stacks`, or known shared categories (`database`, `auth`, `analytics`, `payment`, `email`, `ai`, `telephony`, `voice`, `notifications`, `project-management`). If a category is in the archetype's `excluded_stacks`, stop and tell the user: "Stack category `<category>` is excluded by the `<archetype>` archetype. Remove it from experiment.yaml `stack` or choose a different archetype." If a category is not in any of these lists, stop and tell the user: "Unrecognized stack category: `<category>`. The `<archetype>` archetype allows: [list required + optional + shared]. Check experiment.yaml or the archetype file for valid categories." Then, for each valid category, read `.claude/stacks/<category>/<value>.md`.
- If a stack file doesn't exist for a given value:
  1. Read `.claude/stacks/TEMPLATE.md` for the required frontmatter schema.
  2. Read existing stack files in the same category (`.claude/stacks/<category>/*.md`) as reference for conventions and structure. If no files exist in that category, read a well-populated stack file from another category (e.g., `database/supabase.md` or `analytics/posthog.md`) as a structural reference.
  3. Generate `.claude/stacks/<category>/<value>.md` with:
     - Complete frontmatter (assumes, packages, files, env, ci_placeholders, clean, gitignore) — populate each field based on knowledge of the technology. Use empty lists/dicts for fields that genuinely don't apply.
     - Code templates for library files and route handlers using `### \`path\`` heading format.
     - Environment Variables, Packages, and Patterns sections following the TEMPLATE.md structure.
  4. Run `python3 scripts/validate-frontmatter.py` to verify the generated file passes structural checks. If it fails, fix the frontmatter and re-run (max 2 attempts). If still failing, stop and tell the user: "Could not generate a valid stack file for `<category>/<value>`. Create `.claude/stacks/<category>/<value>.md` manually using TEMPLATE.md as a guide, then re-run `/bootstrap`."
  5. Tell the user: "Generated `.claude/stacks/<category>/<value>.md` — this is auto-generated from Claude's knowledge and has not been team-reviewed. Review it after bootstrap completes."
  6. File an observation per `.claude/patterns/observe.md` noting the missing stack file, so the template repo can add a reviewed version.
  7. Continue bootstrap using the generated stack file.
- These files define packages, library files, env vars, and patterns for each technology.
- For each stack file read, validate its `assumes` entries: every `category/value` in the file's `assumes` list must match a `category: value` pair in experiment.yaml `stack`. If any assumption is unmet:
  - **If the stack file contains a fallback section** (a heading matching `## *Fallback`, e.g., `## No-Auth Fallback`): log which assumes are unmet and continue — the fallback templates will be used in place of the full templates. Include the unmet assumes list in this state's output so STATE 5 can display the fallback path (e.g., "Testing stack: using No-Auth Fallback — assumes unmet: [auth/supabase, database/supabase]").
  - **If no fallback section exists**: stop and list the incompatibilities (e.g., "analytics/posthog assumes framework/nextjs, but your stack has framework: remix"). The user must either change the mismatched stack value or create a compatible stack file.

- **Write archetype trace artifact** (`.runs/bootstrap-archetype-trace.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  trace = {
      'archetype': '<type field value>',
      'archetype_file': '.claude/archetypes/<type>.md',
      'stacks_resolved': {'framework': '<value>', 'ui': '<value>'},  # map of category->value
      'stack_files_read': ['.claude/stacks/framework/<value>.md']  # list of files actually read
  }
  print(json.dumps(trace))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/bootstrap-archetype-trace.json \
    --payload "$PAYLOAD" \
    --skill bootstrap
  ```

**POSTCONDITIONS:**
- Archetype file read and type recorded
- All stack files for categories in experiment.yaml `stack` exist and have been read
- All `assumes` entries validated — either all met, or unmet with a fallback section logged
- `.runs/bootstrap-archetype-trace.json` exists with `archetype` field non-empty

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/bootstrap-archetype-trace.json')); assert d.get('archetype'), 'archetype field empty'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 2
```

**NEXT:** Read [state-3-validate-experiment.md](state-3-validate-experiment.md) to continue.
