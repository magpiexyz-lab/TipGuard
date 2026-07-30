# Plan Validation Procedure

> Called by change.md Phase 1 after drafting the plan, BEFORE presenting to the user.
> Runs automatically — no user interaction required.
> For /bootstrap: skip this procedure (no existing codebase to validate against).

## Purpose

Catch conflicts between the proposed plan and the existing codebase. Auto-adjust the plan when possible, or flag issues in the Questions section for the user to resolve.

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
>
> State-specific logic below takes precedence.

## Validation Checks

Run all applicable checks based on the archetype and stack. If a check finds a conflict, either auto-adjust the plan or add a flagged item to the plan's Questions section.

### Check 1: Route/Endpoint/Command Conflict

For each proposed NEW route/endpoint/command in the plan:

- **web-app**: Check if `src/app/<route>/page.tsx` already exists
- **service**: Check if `src/app/api/<route>/route.ts` already exists
- **cli**: Check if `src/commands/<name>.ts` already exists

**If conflict found**: Add to Questions: "Route `/[route]` already exists. Should I extend the existing page, create a sub-route, or replace it?"

### Check 2: Schema Conflict (if stack.database present)

For each proposed new table or column in the plan:

- Read existing migration files to find current table definitions
- Check if a table with the proposed name already exists
- Check if proposed columns on existing tables already exist

**If table exists**: Auto-adjust the plan's Data Model section to use ALTER TABLE instead of CREATE TABLE, and note: "Table `[name]` already exists — plan adjusted to add columns rather than create a new table."

**If column exists**: Add to Questions: "Column `[name]` already exists on table `[table]`. Should I rename the new column or modify the existing one?"

### Check 3: Import Availability

For each file the plan proposes to import from:

- Verify the source file exists
- If the plan references a specific named export: grep for that export in the source file

**If file missing**: Auto-adjust — note in the plan that the file needs to be created as part of this change.

**If export missing**: Add to Questions: "Plan references `[exportName]` from `[file]` but that export doesn't exist. I'll create it as part of this change."

### Check 4: Component Reuse (web-app only)

For each proposed new component:

- Search `src/components/` for existing components with similar names or overlapping purposes (based on exploration results from plan-exploration.md Step 4)

**If match found**: Add to Questions: "Existing `<[ComponentName]>` in `[path]` may serve a similar purpose. Should I reuse it, extend it, or create a new component?"

This check is **advisory only** — it flags opportunities, never auto-replaces.

### Check 5: Analytics Event Naming

For each proposed new event:

- Check the experiment/EVENTS.yaml `events` map for conflicts with existing event names
- Verify the proposed name follows the `<object>_<action>` snake_case convention

**If name conflict**: Auto-adjust — append a differentiating suffix and note: "Event `[name]` already exists in experiment/EVENTS.yaml. Renamed to `[new_name]`."

**If naming convention violation**: Auto-adjust to match `<object>_<action>` format.

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app: routes + components | service: API routes only | cli: command modules only

| Check | web-app | service | cli |
|-------|---------|---------|-----|
| 1. Route conflict | `src/app/<route>/page.tsx` | `src/app/api/<route>/route.ts` | `src/commands/<name>.ts` |
| 2. Schema conflict | Yes (if stack.database) | Yes (if stack.database) | Yes (if stack.database) |
| 3. Import availability | Yes | Yes | Yes |
| 4. Component reuse | `src/components/` | Skip | Skip |
| 5. Analytics naming | Yes (if stack.analytics) | Yes (if stack.analytics) | Yes (if stack.analytics) |

## Output

- If all checks pass: proceed to present the plan with no additional annotations
- If checks found issues: the plan is adjusted in-place before presentation. Flagged items appear in the plan's **Questions** section prefixed with "[Validation]"
- **Never block** on validation — if a check cannot complete (file unreadable, timeout), skip it silently and proceed
