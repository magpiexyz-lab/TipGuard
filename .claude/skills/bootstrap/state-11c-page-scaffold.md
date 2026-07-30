# STATE 11c: PAGE_SCAFFOLD

**PRECONDITIONS:**
- Lib verify done (STATE 11b POSTCONDITIONS met — `.runs/b1-verify-result.json` exists with `type_check.passed=true`)
- Type-check passes
- `src/lib/` contains >=1 `.ts` file

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Phase A (core scaffold)".
>
> [phase-a] web-app: run (layout, 404, error, favicon, OG, sitemap, robots, llms.txt) | service: skip | cli: skip

#### Phase B2 (pages + landing -- web-app only)

Service and cli archetypes skip Phase B2 — proceed to STATE TRACKING to advance state immediately. (Per `patterns/archetype-behavior-check.md`)

Only after B1 manifest verification AND type-check checkpoint pass. Spawn `scaffold-pages` agents for golden_path pages (excluding landing -- handled by scaffold-landing), using the **batching policy** below. The skill-agent-gate hook enforces this ordering: scaffold-pages and scaffold-landing are blocked until `.runs/agent-traces/scaffold-libs.json` exists with status "completed".

Each agent prompt (single page or batched group):
- Single-page assignment: "Create page: `<page_name>` at route `<route>`."
- Batched assignment: "Create pages: `<page_1>` at `<route_1>`, `<page_2>` at `<route_2>` [, `<page_3>` at `<route_3>`]."
- Write ONLY to `src/app/<page_name>/` for each assigned page -- do NOT write to `src/components/` or `src/lib/`
- Write one trace per page as `scaffold-pages-<page_name>.json` (even when batched -- the merge script and post-fan-out verification depend on per-page traces)
- Read context files: `experiment/experiment.yaml`, `experiment/EVENTS.yaml`,
  `.runs/current-plan.md`, archetype file,
  framework/UI stack files, `.claude/patterns/design.md`,
  `.runs/current-visual-brief.md`, `.runs/image-manifest.json`
- Follow CLAUDE.md Rules 3, 4, 6, 7, 9

**Scope guard -- MANDATORY DERIVATION**: Compute the canonical page list by calling `derive_scope_pages()` from `.claude/scripts/lib/derive_pages.py`:

```bash
python3 .claude/scripts/lib/derive_pages.py scope < experiment/experiment.yaml
```

The output is the canonical SET of pages that must exist on disk: the union of `golden_path[*].page`, `behaviors[*].pages`, and auth-derived pages (login/signup if stack.auth is set), with `landing` excluded (scaffold-landing owns it). Write the returned list as a numbered list below before spawning any agents. Spawn scaffold-pages agents for EXACTLY these pages -- no more, no fewer. Use the batching policy to determine agent grouping. BG2 check 3b will independently re-derive via the same function and BLOCK if actual count exceeds expected count; BG2 check 3c additionally enforces that every behavior.pages reference exists on disk.

**Phase A ownership exception (#1187)**: pages whose `src/app/<page>/page.tsx` was authored by Phase A (state-11) are listed in `.runs/gate-verdicts/phase-a-sentinel.json`'s `files` array — most commonly `src/app/v/[slug]/page.tsx` for variant-bearing experiments. These pages are out of scope for scaffold-pages spawning because Phase A already wrote them; the trace owner is `phase-a-sentinel.json`, not a scaffold-pages-`<page>`.json. Before spawning, exclude any page whose `page.tsx` appears in the sentinel:

```bash
# Filter scaffold-pages spawn list against Phase A ownership.
python3 -c "
import json
sentinel = json.load(open('.runs/gate-verdicts/phase-a-sentinel.json')) if __import__('os').path.exists('.runs/gate-verdicts/phase-a-sentinel.json') else {}
phase_a_files = set(sentinel.get('files', []))
# Page X is Phase-A-owned iff src/app/<X>/page.tsx is in sentinel.files
"
```

The post-fan-out trace verification (below) accepts EITHER ownership form: a `scaffold-pages-<page>.json` trace OR an entry in `phase-a-sentinel.json.files` mapping to that page's `page.tsx`.

> **Why this changed (#1024 fix):** Previously this state read `golden_path` directly and explicitly forbade the `pages:` field. That made any behavior referencing a page outside `golden_path` (e.g., admin, dashboard, portfolio, public invoice page) get backend + RLS + tests scaffolded by scaffold-wire but its frontend page silently blocked, causing 404 traps after deploy. The canonical derivation now reads `behaviors[*].pages` (REQUIRED for web-app + actor:user) so every user-referenced page gets scaffolded. See `.claude/templates/experiment-yaml.md` for schema.

**Auth-derived page exception**: `derive_scope_pages()` already adds `login` and `signup` when `stack.auth` is set, so they appear in the canonical list automatically. Do NOT include scaffold-wire-owned routes (`auth/callback`, `auth/reset-password`) — those are created in STATE 14.

**Pre-fan-out: write behavior-contract artifact (#1387)**:

Before spawning any scaffold-pages agents, derive the structured page-keyed contract from `experiment.yaml.behaviors[*].tests[*]` (directive tokens `[audit:<kind>=<arg>]<prose>`) and persist it via the canonical writer. The artifact is read by each agent's slice and by the post-fan-out auditor (`behavior_contract_auditor.py`).

```bash
PAYLOAD=$(python3 .claude/scripts/lib/behavior_contract_builder.py --emit-payload)
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/scaffold-pages-contracts.json \
  --payload "$PAYLOAD" \
  --skill bootstrap
```

This MUST run synchronously BEFORE any subagent spawn — re-spawn paths (rate-limit recovery) read the same file, and identity-stamped `run_id` enables drift detection in the post-fan-out audit.

**Batching policy:**
- **6 or fewer pages** (excluding landing): spawn one agent per page.
- **More than 6 pages**: MAY batch into groups of 2-3 pages per agent. Group adjacent golden_path pages together (pages that share functional context). Each batched agent MUST still write a separate `scaffold-pages-<page_name>.json` trace for EACH page it creates. The per-page trace contract is non-negotiable -- the merge script and post-fan-out verification depend on it.
- Auth-derived pages (login, signup) SHOULD get their own agent (not batched with product pages) because they follow the auth stack template.

**Page subagents (per batching policy):**
- subagent_type: scaffold-pages
- prompt per agent: Tell the subagent to:
  1. Read `.claude/procedures/scaffold-pages.md` and execute all steps
  2. Create the assigned page(s):
     - Single-page: `<page_name>` at route `<route>`.
     - Batched: `<page_1>` at `<route_1>`, `<page_2>` at `<route_2>` [, `<page_3>` at `<route_3>`].
     For each page: write ONLY to `src/app/<page_name>/` -- do NOT write to `src/components/` or `src/lib/`.
     Write one trace per page as `scaffold-pages-<page_name>.json`.
  3. Read `.runs/scaffold-pages-contracts.json[<page_name>]` for required behavior contracts (#1387 Input Contract — see `.claude/agents/scaffold-pages.md` Input section). State-11c runs `behavior_contract_auditor.py` post-fan-out against this contract.
  4. Read context files: `experiment/experiment.yaml`, `experiment/EVENTS.yaml`,
     `.runs/current-plan.md`, archetype file,
     framework/UI stack files, `.claude/patterns/design.md`,
     `.runs/current-visual-brief.md`, `.runs/image-manifest.json`
  5. Follow CLAUDE.md Rules 3, 4, 6, 7, 9

**Landing subagent (if surface != none):**
- subagent_type: scaffold-landing
- prompt: Tell the subagent to:
  1. Read `.claude/procedures/scaffold-landing.md` and execute all steps
  2. Read context files: `experiment/experiment.yaml`, `experiment/EVENTS.yaml`,
     `.runs/current-plan.md`, `.claude/archetypes/<type>.md`,
     framework/UI/surface stack files,
     `.claude/patterns/design.md`, `.claude/patterns/messaging.md`,
     `.runs/current-visual-brief.md`, `.runs/image-manifest.json`,
     `src/app/globals.css` (theme tokens from init phase)
  3. Follow CLAUDE.md Rules 3, 4, 6, 7, 9

Wait for all B2 subagents to return.

After all return, merge per-page traces into `scaffold-pages.json` via the dedicated merge script (extracted from this state's prior inline `json.dump`, mirroring the #1045 resolution for design-critic):

```bash
python3 .claude/scripts/merge-scaffold-pages-traces.py
```

The script (`.claude/scripts/merge-scaffold-pages-traces.py`) is allowlisted in `agent-trace-write-guard.sh` (see `ALLOWED_REGEX_MERGE_SCAFFOLD_PAGES`). It composes the aggregate from `.runs/agent-traces/scaffold-pages-*.json` with `pages_created`, `files_created[]`, `issues[]`, and `run_id` from `.runs/bootstrap-context.json`. Exits non-zero if no per-page traces exist.

**Post-fan-out trace verification** (before proceeding):
Verify each subagent produced its expected output:
- `test -f .runs/agent-traces/scaffold-libs.json` (already verified in STATE 11b)
- For each page in `derive_scope_pages()`: ownership is satisfied by EITHER `test -f .runs/agent-traces/scaffold-pages-<page>.json` OR the page's `src/app/<page>/page.tsx` appearing in `.runs/gate-verdicts/phase-a-sentinel.json`'s `files` array (Phase A authorship — #1187). Run the dual check:
  ```bash
  python3 -c "
  import json, os
  sentinel = json.load(open('.runs/gate-verdicts/phase-a-sentinel.json')) if os.path.exists('.runs/gate-verdicts/phase-a-sentinel.json') else {}
  phase_a_files = set(sentinel.get('files', []))
  pages = open('/dev/stdin').read().split()  # pages from derive_scope_pages
  missing = []
  for p in pages:
      trace_ok = os.path.exists(f'.runs/agent-traces/scaffold-pages-{p}.json')
      phase_a_ok = f'src/app/{p}/page.tsx' in phase_a_files
      if not (trace_ok or phase_a_ok):
          missing.append(p)
  if missing:
      raise SystemExit('pages without ownership trace or Phase A authorship: ' + ','.join(missing))
  print('post-fan-out ownership: OK')
  " <<< \"$(python3 .claude/scripts/lib/derive_pages.py scope < experiment/experiment.yaml)\"
  ```
- Landing subagent reported completion: `test -f .runs/agent-traces/scaffold-landing.json && python3 -c "import json;d=json.load(open('.runs/agent-traces/scaffold-landing.json'));assert d.get('status')=='completed';print('scaffold-landing trace: OK')"`. If trace missing: log "WARN: scaffold-landing did not write trace -- continuing with file-based verification".

If any trace is missing or output was truncated: note the gap for STATE 13 to address.

**Post-fan-out disk audit** (verify files actually exist on disk -- traces alone are not proof):
- For each page in `derive_scope_pages()` (landing already excluded): run `test -f src/app/<page_name>/page.tsx`.
  If the file is missing but the trace file exists (agent claimed success):
  - Re-create the page file directly as the bootstrap lead (budget: 1 attempt per page)
  - Use the trace's metadata and experiment.yaml context to generate the page
- If surface != none: run `test -f src/app/page.tsx` (or variant: `test -f src/components/landing-content.tsx`).
  If missing: re-create directly (budget: 1 attempt).
- Log any re-created files in the process checklist for visibility.

**Post-fan-out: behavior-contract audit (#1387)**:

After all subagents return and per-page traces merge, run the static audit. This reads `.runs/scaffold-pages-contracts.json` (via `unstamped_items`), greps each page's .tsx for required references, and writes:
- `.runs/behavior-implementation-audit.json` — verdict (uncovered_count=0 → pass)
- `.runs/behavior-verifier-static-stubs.json` — runtime annotations for `/verify` behavior-verifier B7 (load-bearing trustworthy check for fetch-with-stub-fallback patterns that Layer 4a static heuristics may miss)

```bash
python3 .claude/scripts/lib/behavior_contract_auditor.py
```

State-11c VERIFY (see state-registry.json) asserts `uncovered_count == 0`. Phase A sentinel exemption (#1187) is respected: pages with sentinel ownership are skipped by the auditor.

**Post-fan-out: sitemap.ts authorship (#1387)**:

After the audit, the lead writes `src/app/sitemap.ts` consuming both `derive_scope_pages()` for static slugs and `dynamic_public_pages()` for dynamic-segment instance enumeration. Authorship MOVED from Phase A (state-11) to here so fixture data declared in `experiment.yaml.behaviors[*].dynamic_segments` can be consumed.

```bash
# Generate src/app/sitemap.ts importing the canonical accessors. The
# emitter MUST iterate dynamic_public_pages() for fixture-slug enumeration.
# When dynamic_public_pages() returns entries with concrete_url=None
# (filesystem scan found no matching route), the emitter SKIPS those —
# the auditor surfaces them as findings.
python3 .claude/scripts/lib/emit-sitemap.py
```

The emitter is deterministic given the same `experiment.yaml` — re-running with no input changes yields byte-identical `src/app/sitemap.ts`.

Check off in `.runs/current-plan.md` for each completed B2 subagent:
- `- [x] scaffold-pages completed`
- `- [x] scaffold-landing completed` (or mark N/A if surface=none)
- `- [x] behavior_contract_auditor completed`

**POSTCONDITIONS:**
- All subagents returned completion reports <!-- enforced by agent behavior, not VERIFY gate -->
- Page/route files created per archetype (web-app: layout.tsx; service: api/; cli: index.ts)
- Landing page created (if surface != none) <!-- enforced by agent behavior, not VERIFY gate -->

**VERIFY:**
```bash
python3 -c "import json,os,glob; a=json.load(open('.runs/bootstrap-context.json')).get('archetype','web-app'); assert (a!='web-app' or os.path.isfile('src/app/layout.tsx')), 'web-app missing layout.tsx'; assert (a!='service' or os.path.isdir('src/app/api')), 'service missing api/'; assert (a!='cli' or any(os.path.isfile(f) for f in ['src/index.ts','src/cli.ts'])), 'cli missing entry'" && python3 .claude/scripts/validate-scaffold-recommendations-schema.py && python3 .claude/scripts/verify-state-11c-behavior-audit.py && python3 .claude/scripts/validate-self-check-score-schema.py
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 11c
```

**NEXT:** Read [state-12-externals-decisions.md](state-12-externals-decisions.md) to continue.
