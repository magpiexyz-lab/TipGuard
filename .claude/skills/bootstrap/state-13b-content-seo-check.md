# STATE 13b: CONTENT_SEO_CHECK

**PRECONDITIONS:**
- Analytics and design checks pass (STATE 13a POSTCONDITIONS met)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Content/SEO checks".
>
> [content-seo] web-app: content quality, CTA, hrefs, tokens, SEO baseline | service: skip | cli: skip
>
> State-specific logic below takes precedence.

Run content quality and SEO verification checks:

7. **Content quality floor** (web-app only): discover all pages via filesystem scan
   (`find src/app -name 'page.tsx' | grep -v '/api/'`). For each discovered page, read page.tsx and check:
   - File has >=30 lines of JSX content (not just imports and boilerplate)
   - No `>TODO` or `"TODO:` patterns in rendered JSX strings
   - No sections consisting of only placeholder text or empty containers
   If any check fails: fix directly (budget: 1 attempt). WARN if unfixed.
8. **CTA presence** (web-app, landing only): verify landing page source (`src/app/page.tsx`
   or `src/components/landing-content.tsx`) contains at least one `<Button` or `<Link`
   element with non-empty text content. If missing: add a primary CTA to the hero section.
   Budget: 1 fix attempt.
9. **Internal href audit** (web-app only): extract all `href="/..."` values from all
   page files (`grep -roh 'href="/[^"]*"' src/app/*/page.tsx`). For each internal path,
   verify the target route has a corresponding page directory under `src/app/` or is a
   defined API route under `src/app/api/`. Exclude external URLs (`href="http`) and
   **scaffold-wire-owned auth routes** — `/auth/callback` and `/auth/reset-password`
   are created by scaffold-wire in STATE 14 (AFTER this state runs), so the directories
   do not exist yet at audit time. The auth stack file owns them and their ownership
   is documented in `.claude/skills/bootstrap/state-11c-page-scaffold.md`. Treat both
   as expected-missing.
   If broken links found (excluding those scaffold-wire exceptions): fix the href to
   point to the correct route. Budget: 1 fix attempt.
10. **Cross-page token consistency** (web-app only): grep all page.tsx files for
   Tailwind arbitrary color values (`text-\[#`, `bg-\[#`, `border-\[#`). If any page uses
   arbitrary hex color values not traceable to the visual brief, replace with theme token
   classes (`text-primary`, `bg-secondary`, etc.). Budget: 1 fix attempt.
11. **SEO baseline** (web-app only):
   - Verify `src/app/layout.tsx` exports `metadata` with non-empty `title` and `description` (`grep -q 'export const metadata' src/app/layout.tsx`)
   - Verify `src/app/sitemap.ts` exists (`test -f src/app/sitemap.ts`)
   - Verify `src/app/robots.ts` exists (`test -f src/app/robots.ts`)
   - Verify `public/llms.txt` exists (`test -f public/llms.txt`)
   - Verify JSON-LD present in landing page or layout (`grep -rl 'application/ld+json' src/app/layout.tsx src/app/page.tsx src/components/landing-content.tsx 2>/dev/null`)
   Budget: 1 fix attempt.

If any check fails: the bootstrap lead fixes directly (it has full file access
as coordinator). Budget: 2 fix attempts.
If still failing after 2 attempts: list all remaining errors and their file locations. Ask the user whether to (a) continue to wire phase and fix later, or (b) stop and investigate now.

Update checkpoint in `.runs/current-plan.md` frontmatter to `phase2-wire`.

Check off in `.runs/current-plan.md`: `- [x] Merged checkpoint validation passed`

**Scaffold trace audit** (informational -- does not block BG2):
```bash
python3 -c "
import json, glob
expected = ['scaffold-setup','scaffold-init','scaffold-libs','scaffold-landing','scaffold-wire']
traces = {}
for f in glob.glob('.runs/agent-traces/scaffold-*.json'):
    name = f.split('/')[-1].replace('.json','')
    if '-' in name and name.startswith('scaffold-pages'):
        continue
    try:
        d = json.load(open(f))
        traces[name] = d.get('status','unknown')
    except:
        traces[name] = 'error'
missing = [a for a in expected if a not in traces]
incomplete = [a for a,s in traces.items() if s != 'complete' and a in expected]
print(f'Scaffold audit: {len(traces)}/{len(expected)} traces found')
if missing: print(f'  Missing: {missing}')
if incomplete: print(f'  Incomplete: {incomplete}')
if not missing and not incomplete: print('  All scaffold agents completed with traces')
"
```

**POSTCONDITIONS:**
- Content quality checks pass (web-app) or skipped (service/cli) <!-- enforced by agent behavior, not VERIFY gate -->
- SEO baseline verified (web-app) or skipped (service/cli) <!-- enforced by agent behavior, not VERIFY gate -->
- Checkpoint updated to `phase2-wire`

**VERIFY:**
```bash
grep -q 'Merged checkpoint validation passed' .runs/current-plan.md
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 13b
```

**NEXT:** Read [state-13c-bg2-gate.md](state-13c-bg2-gate.md) to continue.
