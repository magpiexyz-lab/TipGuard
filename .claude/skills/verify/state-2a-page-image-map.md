# STATE 2a: PAGE_IMAGE_MAP

**PRECONDITIONS:** STATE 2 complete (Phase 1 parallel agents). Context
`archetype` and `scope` known.

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Visual agents".
> [visual-agents] web-app: design-critic, ux-journeyer, consistency-checker | service: skip | cli: skip

Produce two operational artifacts that state-3a Stage-1 consumes to spawn
per-page design-critic agents with the right per-page metadata. This state
is the canonical source of truth for (a) the design-critic page set and
(b) per-page static image-render classification (#1042).

1. **Skip gate** — run only when the design-critic will be spawned:
   - `archetype == "web-app"` AND `scope ∈ {"full", "visual"}`.
   - Otherwise, write empty `not_applicable:true` artifacts for downstream
     idempotency and advance the state.

2. **Write `.runs/design-page-set.json`** — canonical page list for Stage-1
   spawns. Each entry carries:
   - `name` — page slug (matches trace filename `design-critic-<name>.json`)
   - `route_pattern` — literal route from filesystem (e.g., `/quote/[id]`)
   - `test_url` — concrete URL safe for `page.goto()` (dynamic segments
     substituted with synthetic IDs: `[id]`→nil UUID, `[slug]`→`demo-fixture-slug`, etc.)
   - `source_files` — enumerated `.tsx`/`.jsx` files under the page folder
   - `dynamic_segments` — list of captured segment names (empty for static routes)

   Excludes `landing` from the `pages` array; landing is exposed via the
   sibling `landing` field (writable by state-2a, consumed by state-3a Stage 1
   for landing-critic spawn). Landing has full read-write access to
   `.runs/image-candidates.json` per design-critic.md, while non-landing
   critics get read-only context — this is why landing must NOT be a peer in
   `pages` (different sidecar semantics + different trace schema). See #1143.

3. **Write `.runs/page-image-map.json`** — static image-render classifier
   output. Two-layer analysis:
   - **Layer 1** grep each source file for `<Image`, `next/image`,
     `<img`, `public/images/`, `empty-state`.
   - **Layer 2** follow one-level imports resolving to `src/components/**`
     or `src/lib/**`; grep the imported file for the same patterns.

   Landing is force-classified `has_images=true, detected_via="landing-hardcoded"`
   (owns global slots: hero/features/logo/og-photo/empty-state).

4. **Python helper** — both artifacts come from
   `.claude/scripts/lib/derive_pages.py`:

   ```bash
   COMBINED=$(python3 - <<'PYEOF'
   import datetime, json, os, sys
   # Resolve repo root via CLAUDE_PROJECT_DIR (authoritative under hooks)
   # with a getcwd() fallback for direct invocation.
   PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
   sys.path.insert(0, os.path.join(PROJECT_DIR, ".claude", "scripts"))
   os.chdir(PROJECT_DIR)
   import yaml
   from lib.derive_pages import (
       derive_landing_for_design_critic,
       derive_page_images,
       derive_page_set_for_design_critic,
   )
   ctx = json.load(open(".runs/verify-context.json"))
   needs_dc = (
       ctx.get("archetype") == "web-app"
       and ctx.get("scope") in ("full", "visual")
   )
   now = datetime.datetime.now(datetime.timezone.utc).strftime(
       "%Y-%m-%dT%H:%M:%SZ"
   )
   if not needs_dc:
       design_page_set = {
           "generated_at": now,
           "not_applicable": True,
           "pages": [],
           "landing": None,
       }
       page_image_map = {
           "generated_at": now,
           "source_page_set": ".runs/design-page-set.json",
           "not_applicable": True,
           "pages": {},
       }
       print("design-page-set.json + page-image-map.json: not_applicable", file=sys.stderr)
   else:
       exp = yaml.safe_load(open("experiment/experiment.yaml"))
       pages = derive_page_set_for_design_critic(exp, ".")
       landing = derive_landing_for_design_critic(".")
       image_map = derive_page_images(pages, ".", include_landing=True)
       design_page_set = {"generated_at": now, "pages": pages, "landing": landing}
       page_image_map = {
           "generated_at": now,
           "source_page_set": ".runs/design-page-set.json",
           "pages": image_map,
       }
       n_images = sum(1 for v in image_map.values() if v["has_images"])
       print(
           f"design-page-set.json: {len(pages)} pages "
           f"(landing={'yes' if landing else 'no'}); "
           f"page-image-map.json: {n_images}/{len(image_map)} classified has_images=true",
           file=sys.stderr,
       )
   print(json.dumps({"design_page_set": design_page_set, "page_image_map": page_image_map}))
   PYEOF
   )
   PAYLOAD_PAGES=$(echo "$COMBINED" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin)['design_page_set']))")
   PAYLOAD_IMAGES=$(echo "$COMBINED" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin)['page_image_map']))")
   bash .claude/scripts/lib/write-gate-artifact.sh \
     --path .runs/design-page-set.json \
     --payload "$PAYLOAD_PAGES" \
     --skill verify
   bash .claude/scripts/lib/write-gate-artifact.sh \
     --path .runs/page-image-map.json \
     --payload "$PAYLOAD_IMAGES" \
     --skill verify
   ```

5. **Downstream contract**: state-3a Stage-1 MUST read
   `design-page-set.json` for the spawn list (no filesystem re-scan) and
   MUST pass each page's `has_images` into its spawn prompt so the agent
   knows whether `image_issues_for_landing` emission is mandatory.

**POSTCONDITIONS:**

- `.runs/design-page-set.json` exists with valid schema (`generated_at`,
  `pages` array, `landing` dict-or-null, or `not_applicable:true`).
- `.runs/page-image-map.json` exists with valid schema (`generated_at`,
  `source_page_set`, `pages` map or `not_applicable:true`).

**VERIFY:**
```bash
python3 -c "import json; ps=json.load(open('.runs/design-page-set.json')); pim=json.load(open('.runs/page-image-map.json')); assert 'pages' in ps and 'pages' in pim, 'design-page-set.json / page-image-map.json malformed'; assert ps.get('not_applicable') or isinstance(ps['pages'], list), 'pages field must be a list'; assert ps.get('not_applicable') or 'landing' in ps, 'landing field missing in design-page-set.json (state-2a #1143)'; assert ps.get('not_applicable') or ps.get('landing') is None or isinstance(ps.get('landing'), dict), 'landing field must be null or dict (state-2a #1143)'; assert pim.get('not_applicable') or pim.get('source_page_set')=='.runs/design-page-set.json', 'page-image-map.json missing source_page_set linkage'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh verify 2a
```

**NEXT:** Read [state-3a-design-agents.md](state-3a-design-agents.md) to continue.
