# STATE 13a: ANALYTICS_DESIGN_CHECK

**PRECONDITIONS:**
- Build passes, artifacts verified (STATE 13 POSTCONDITIONS met)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, rows "Design tokens check", "Favicon + OG image check".
>
> [design-tokens] web-app: verify `--primary` in globals.css | service: skip | cli: skip
> [favicon-og] web-app: verify icon.tsx + opengraph-image.tsx | service: skip | cli: skip
>
> State-specific logic below takes precedence.

Run analytics and design verification checks:

3. **Analytics wiring** (if `stack.analytics` is present) -- systematic batch verification:
   - (a) Read `experiment/EVENTS.yaml` `events` map. Filter entries by `requires` (match
     current stack keys) and `archetypes` (match current archetype). This produces the
     canonical set of events that MUST be wired.
   - (b) Batch-grep all filtered event names in `src/` in a single pass:
     `grep -rn "event_name_1\|event_name_2\|..." src/` -- collect which events have
     tracking calls and which are missing.
   - (c) Group missing events by their target page (the page where the event should fire
     based on golden_path context). This groups fixes for efficient per-page editing.
   - (d) Fix missing events per-page. Budget: 2 fix attempts per page, max 5 pages.
     If a page exceeds 2 attempts, log the remaining missing events and move on.
   - (e) Verify `PROJECT_NAME` equals `experiment.yaml.name`:
     `python3 .claude/scripts/lib/check_project_name.py`. Strict-equality (catches
     both unreplaced `"TODO"` placeholders and post-rename drift in one check).
     Additionally verify `PROJECT_OWNER` is not `"TODO"`:
     `grep -n '"TODO"' src/lib/analytics*.ts`. Fix any failures directly.
   - (f) After fix budget exhausted: any remaining missing events are listed in the PR
     description under a "Known gaps" section. Do not block the pipeline for these.
4. **Design tokens** (if archetype is `web-app`): verify `src/app/globals.css`
   contains a non-empty `--primary` custom property
5. **Favicon & OG image** (if archetype is `web-app`): verify `src/app/icon.tsx`
   and `src/app/opengraph-image.tsx` exist and export a default function returning
   `ImageResponse`. Fix directly if missing.
6. **Fake door integration** (if `externals-decisions.json` has non-empty `fake_doors`):
   for each fake door entry, verify the parent page.tsx contains both an import
   statement with `component_export_name` and a JSX render tag `<ComponentExportName`.
   Fix directly if missing.

If any check fails: fix directly (budget: 2 fix attempts).
If still failing after 2 attempts: list all remaining errors and their file locations. Ask the user whether to (a) continue and fix later, or (b) stop and investigate now.

Write intermediate artifact:
```bash
PAYLOAD=$(python3 -c "
import json
result = {
    'analytics_wired': True,   # or 'skipped' if stack.analytics absent
    'design_tokens': True,     # or 'skipped' if not web-app
    'favicon_og': True,        # or 'skipped' if not web-app
    'fake_doors': True         # or 'skipped' if no fake doors
}
# Set to 'skipped' for checks that don't apply to the current archetype/stack
print(json.dumps(result))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/bootstrap-design-validated.json \
  --payload "$PAYLOAD" \
  --skill bootstrap
```

**POSTCONDITIONS:**
- Analytics wired (if applicable) or marked skipped
- Design tokens verified (web-app) or marked skipped
- Favicon & OG verified (web-app) or marked skipped
- Fake doors integrated or marked skipped
- `.runs/bootstrap-design-validated.json` written

**VERIFY:**
```bash
python3 -c "import sys, json; sys.path.insert(0, '.claude/scripts/lib'); from verify_helpers import unstamped_values; d=json.load(open('.runs/bootstrap-design-validated.json')); assert all(v in (True, 'skipped') for v in unstamped_values(d)), f'failed checks: {d}'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 13a
```

**NEXT:** Read [state-13b-content-seo-check.md](state-13b-content-seo-check.md) to continue.
