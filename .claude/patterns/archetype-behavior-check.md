# Archetype Behavior Check

Product archetypes determine how capabilities map to code structure. When
scanning context, updating specs, implementing features, or scoping verification,
branch on the archetype from `experiment/experiment.yaml` `type` field
(default: `web-app`).

## Canonical Source Hierarchy

1. **CLAUDE.md Archetype-Feature Matrix** — feature inclusion/exclusion master (yes/no/conditional)
2. **`.claude/archetypes/<type>.md` frontmatter** — constraint master (required_stacks, excluded_stacks, required_experiment_fields)
3. **This file** — derived quick-lookup index for inline branching decisions

When this file and an archetype file disagree, the archetype file wins.

## Archetype Mapping

### web-app (default)

- **Capabilities map to**: pages derived from `golden_path`
- **Code structure**: `src/app/<page>/page.tsx` (one folder per page)
- **Includes**: landing page, Fake Door variants, CTA/conversion focus
- **Verification agents**: design-critic, ux-journeyer, design-consistency-checker (full visual pipeline)
- **Analytics**: client-side + server-side

### service

- **Capabilities map to**: API endpoints (route handlers)
- **Code structure**: `src/app/api/<endpoint>/route.ts`
- **Skip**: pages, landing page, Fake Door, golden_path
- **Spec field**: `endpoints` (not `golden_path`)
- **Verification agents**: skip design-critic, ux-journeyer, design-consistency-checker
- **Analytics**: server-side only

### cli

- **Capabilities map to**: subcommand modules
- **Code structure**: `src/commands/<command>.ts`
- **Skip**: pages, API routes, landing page, Fake Door, golden_path
- **Spec field**: `commands` (not `golden_path`)
- **Verification agents**: skip design-critic, ux-journeyer, design-consistency-checker
- **Analytics**: server-side only, must be opt-in (consent guard on `trackServerEvent`)

## Quick-Reference Table

> Canonical inline block — embed or reference this table in files with archetype branching.

| Concern | web-app | service | cli |
|---------|---------|---------|-----|
| Primary unit | page (`src/app/<page>/page.tsx`) | endpoint (`src/app/api/<ep>/route.ts`) | command (`src/commands/<cmd>.ts`) |
| Spec field | `golden_path` | `endpoints` | `commands` |
| Skip | — | pages, landing, Fake Door, golden_path | pages, API routes, landing, Fake Door, golden_path |
| Visual agents | design-critic, ux-journeyer, consistency-checker | skip | skip |
| Analytics | client + server | server only | server only, opt-in |
| Browser tests | Playwright | skip | skip |
| Trace field | `pages_wired` + `api_routes_wired` | `api_routes_wired` | `commands_wired` |
| Phase A (core scaffold) | run (layout, 404, error, favicon, OG, sitemap, robots, llms.txt) | skip | skip |
| Design tokens check | verify `--primary` in globals.css | skip | skip |
| Favicon + OG image check | verify icon.tsx + opengraph-image.tsx | skip | skip |
| Content/SEO checks | content quality, CTA, hrefs, tokens, SEO baseline | skip | skip |
| Performance + a11y agents | performance-reporter, accessibility-scanner | skip | skip |
| Consent guard | none | none | opt-in consent on `trackServerEvent` |
| npm cleanup on teardown | skip | skip | `npm deprecate` reminder |

> State-specific logic takes precedence over this summary.

## Compound Dimensions

These dimensions depend on archetype AND a secondary variable. The archetype
component is in the Quick-Reference Table; the compound condition must be
evaluated inline by consuming files.

### Surface type resolution (archetype + stack.surface + hosting)

1. If `stack.surface` is set explicitly in experiment.yaml → use it
2. If archetype `excluded_stacks` includes `hosting` → `detached`
3. If `stack.services[0].hosting` present → `co-located`
4. If `stack.services[0].hosting` absent → `none`

| archetype | excluded hosting | hosting present | surface |
|-----------|-----------------|-----------------|---------|
| web-app | no | yes | co-located |
| web-app | no | no | none |
| service | no | yes | co-located |
| service | no | no | none |
| cli | yes | — | detached |

### Deploy gate (archetype + surface)

| archetype | surface | result |
|-----------|---------|--------|
| web-app | co-located | full deploy |
| web-app | detached | surface-only deploy |
| service | co-located | full deploy (API health check) |
| service | none | stop — manual deploy required |
| cli | detached | surface-only deploy |
| cli | none | stop — use `npm publish` |

### Distribute gate (archetype + surface)

- surface = `none` → stop with archetype-specific guidance
- surface ≠ `none` → proceed regardless of archetype
- For CLI archetype, the surface URL IS the target URL

## Usage Points

This branching applies at four stages of every skill:

1. **Context scanning** (read-context states): scan pages, endpoints, or commands
   depending on archetype
2. **Spec updates** (update-specs states): update golden_path, endpoints, or
   commands field in experiment.yaml
3. **Implementation** (implement states): create page folders, API routes, or
   command modules; CLI analytics requires consent guard
4. **Verification** (verify states): scope visual agents to web-app only; skip
   design pipeline for service/cli

## Canonical Contract Heading

Every markdown file in `.claude/procedures/`, `.claude/agents/`,
`.claude/skills/*/state-*.md`, or `.claude/patterns/` that **semantically
branches on archetype** MUST include a canonical `## Archetype Gate` H2
heading immediately above (or wrapping) the branching block.

The heading is the **machine-checkable contract** that this file participates
in archetype-aware execution. It is enforced by `scripts/consistency-check.sh`
Check 23 (subcheck 23e).

### Why H2 (not HTML comment, not H3)

- **Versus H3**: H3 is for sub-section nesting; H2 establishes a top-level
  contract section that linters can target with a single regex
  (`^## Archetype Gate$`).
- **Versus HTML comment**: H2 renders in documentation tools and is searchable
  by humans reading source files; HTML comments are invisible in renders.
- **Safe inside state files**: The verify-linter section parser
  (`.claude/scripts/verify-linter.sh:122-159`) only treats `**UPPERCASE:**`
  markers as section boundaries — H2 headings are inert. Existing state files
  already use H2 sub-sections (e.g., `bootstrap/state-5-present-plan.md:2`,
  `audit/state-1-parallel-analysis.md`), so this is not a precedent change.

### Minimal contract

```markdown
## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app: <one-line summary> | service: <one-line summary> | cli: <one-line summary>

[inline branching code follows here OR — for interleaved files — a list of
file:line references to each conditional point]
```

## Canonical Branch Shapes

These shapes are **informative, not enforced**. The contract enforces only the
heading + REF presence (Linter Contract below). Shape choice is a documentation
aid for authors and reviewers.

### Shape 1: web-app-only

Used when the procedure/agent only does meaningful work for `web-app`;
service and cli skip entirely.

```markdown
## Archetype Gate

> REF: Archetype branching — see `archetype-behavior-check.md`.
> web-app: run | service: skip | cli: skip

If archetype is **not** `web-app`, skip all checks and report `verdict: "skipped"`.
```

Examples: `procedures/accessibility-scanner.md`, `agents/performance-reporter.md`.

### Shape 2: all-three

Three distinct execution paths, one per archetype.

```markdown
## Archetype Gate

> REF: Archetype branching — see `archetype-behavior-check.md`.
> web-app: process pages | service: process endpoints | cli: process commands

### web-app
[steps for web-app]

### service
[steps for service]

### cli
[steps for cli]
```

Examples: `procedures/scaffold-pages.md`, `procedures/plan-validation.md`.

### Shape 3: web-app + service

cli skips, web-app and service have separate handling.

```markdown
## Archetype Gate

> REF: Archetype branching — see `archetype-behavior-check.md`.
> web-app: <handling> | service: <handling> | cli: skip
```

### Shape 4: subset-per-archetype

Each archetype runs a different subset of named checks (not separate paths,
but a filtered list).

```markdown
## Archetype Gate

> REF: Archetype branching — see `archetype-behavior-check.md`.
> web-app: D1–D6 | service: D1, D2, D3, D5 (skip D4) | cli: D1, D2 only
```

Examples: `agents/security-defender.md`, `agents/security-attacker.md`.

### Shape 5: interleaved-per-step

Conditional points scattered across multiple steps of a procedure. The
`## Archetype Gate` heading sits at file top and **enumerates each conditional
point** by `file:line` so reviewers can audit drift.

```markdown
## Archetype Gate

> REF: Archetype branching — see `archetype-behavior-check.md`.
> web-app: full pipeline | service: skip pages, run API tests | cli: skip pages, run command tests
> Conditional points: [Step 5c (line N), Step 7 (line N), Step 8 (line N), ...]
```

Examples: `procedures/wire.md`, `procedures/scaffold-libs.md`.

## Canonical Summary Lines

Verbatim labeled lines for files citing Quick-Reference Table rows via
`row "<X>"` syntax. Each line below is canonical — embedding files MUST
copy the exact text. Drift detection is enforced by Check 23h (see
**Linter Contract** below). Run `make sync-archetype-summaries` to
propagate canonical edits to embedding files.

### Slug derivation (informative)

Slugs in subsections below are explicit — do NOT derive at lint time.
When adding a new row, derive the slug as: lowercase the row name,
replace `[^a-z0-9]` with `-`, collapse `-` runs, trim leading/trailing
`-`. List the derived slug verbatim in the new subsection so it cannot
drift.

### Rows

11 of 14 Quick-Reference Table rows are listed below — every row currently
cited by at least one BRANCHING / REFERENCE_ONLY file. Rows `Skip`,
`Analytics`, `Browser tests` are intentionally omitted (no current
citation). Add a subsection here when the first state file cites them.

#### Primary unit
slug: `primary-unit`
> [primary-unit] web-app: page (`src/app/<page>/page.tsx`) | service: endpoint (`src/app/api/<ep>/route.ts`) | cli: command (`src/commands/<cmd>.ts`)

#### Spec field
slug: `spec-field`
> [spec-field] web-app: `golden_path` | service: `endpoints` | cli: `commands`

#### Visual agents
slug: `visual-agents`
> [visual-agents] web-app: design-critic, ux-journeyer, consistency-checker | service: skip | cli: skip

#### Trace field
slug: `trace-field`
> [trace-field] web-app: `pages_wired` + `api_routes_wired` | service: `api_routes_wired` | cli: `commands_wired`

#### Phase A (core scaffold)
slug: `phase-a`
> [phase-a] web-app: run (layout, 404, error, favicon, OG, sitemap, robots, llms.txt) | service: skip | cli: skip

#### Design tokens check
slug: `design-tokens`
> [design-tokens] web-app: verify `--primary` in globals.css | service: skip | cli: skip

#### Favicon + OG image check
slug: `favicon-og`
> [favicon-og] web-app: verify icon.tsx + opengraph-image.tsx | service: skip | cli: skip

#### Content/SEO checks
slug: `content-seo`
> [content-seo] web-app: content quality, CTA, hrefs, tokens, SEO baseline | service: skip | cli: skip

#### Performance + a11y agents
slug: `perf-a11y`
> [perf-a11y] web-app: performance-reporter, accessibility-scanner | service: skip | cli: skip

#### Consent guard
slug: `consent-guard`
> [consent-guard] web-app: none | service: none | cli: opt-in consent on `trackServerEvent`

#### npm cleanup on teardown
slug: `npm-cleanup`
> [npm-cleanup] web-app: skip | service: skip | cli: `npm deprecate` reminder

## Reference Mechanism

The contract is **heading + REF colocated within the heading's section**:

1. The `## Archetype Gate` heading must appear in the file
2. A REF line referencing `archetype-behavior-check.md` must appear within
   the heading's section (between the `## Archetype Gate` and the next H2)

### Per file-type guidance

**Procedures** — heading at top of the procedure body, just below the `# Title`:
```markdown
# Procedure: Wire

## Archetype Gate
> REF: ...

## Step 1
```

**Agents** — heading near top, after the `## Instructions` section if present:
```markdown
# Agent

## Instructions

## Archetype Gate
> REF: ...
```

**State files** — heading **inside** `**ACTIONS:**` section (between
`**ACTIONS:**` and `**POSTCONDITIONS:**`), so the section parser still
captures ACTIONS content correctly:
```markdown
**ACTIONS:**

## Archetype Gate
> REF: ...

[ACTIONS steps follow]

**POSTCONDITIONS:**
```

**Patterns** — heading inline with the document's existing H2 hierarchy.

## Linter Contract

Enforcement: `scripts/consistency-check.sh` Check 23 (CI-wired via
`.github/workflows/ci.yml:141-147` and `Makefile:42`).

### Subchecks

- **23a** — This file (`archetype-behavior-check.md`) has a Quick-Reference Table section
- **23b** — Quick-Reference Table has ≥14 data rows
- **23c** — This file has a Compound Dimensions section
- **23d** — `.claude/hooks/lib-state.sh` has `get_archetype` utility function
- **23e** — Every file in `ARCHETYPE_BRANCHING_FILES` array contains `^## Archetype Gate$`
- **23f** — Every file in `ARCHETYPE_BRANCHING_FILES` + `ARCHETYPE_REFERENCE_ONLY_FILES`
  contains a reference to `archetype-behavior-check.md`
- **23g** — BLOCKING: word-boundary scan for files mentioning
  `\b(web-app|cli)\b|archetype.*service|stack\.type` that are not in either
  curated list. Each match must be classified into BRANCHING, REFERENCE_ONLY,
  or carry an explicit `<!-- archetype-gate-exempt: <reason> -->` marker. This
  is what makes the contract un-fatigueable: new files cannot accumulate WARNs
  that go unread.
- **23h** — Row-citing REFs must embed verbatim canonical labeled lines.
  Scope: BRANCHING + REFERENCE_ONLY files whose REF cites
  `row "<X>"` or `rows "<X>", "<Y>"` syntax, EXCLUDING REFs containing
  `Compound Dimensions` substring. Sub-rules:
  - **Slug-existence**: every cited row name must have a `#### <Row>`
    subsection in `## Canonical Summary Lines` (catches typos and renames)
  - **Multi-row count**: in the contiguous blockquote group following REF,
    one `> [<slug>] ...` line must exist per cited row (count match)
  - **Verbatim match**: each cited row's `> [<slug>] ...` line must equal
    the canonical line (whitespace-collapsed comparison)
  - **Slug uniqueness**: the canonical Summary Lines section must not have
    two `#### <Row>` subsections producing the same slug
  Files with bare `Quick-Reference Table.` REFs (no row cited) and Compound
  Dimensions REFs are out of 23h scope. To migrate a bare-REF file into
  23h coverage: update its REF to `row "<X>"` syntax, then run
  `make sync-archetype-summaries` to embed the canonical line.

### Exempt mechanism

When a file matches the substring regex but is genuinely not archetype-related
(e.g., uses 'cli' as a substring of 'click', uses 'service' inside 'service role'),
and classifying it into BRANCHING/REFERENCE_ONLY would be misleading, add this
HTML comment marker to the file body (typically near the H1 title):

```html
<!-- archetype-gate-exempt: <one-line reason> -->
```

The reason is human-readable and auditable. Example:
```html
<!-- archetype-gate-exempt: 'cli' substring matches 'click-driven', UX testing pattern -->
```

23g skips files carrying this marker. The marker is greppable so reviewers can
audit every exemption in one pass: `grep -rn 'archetype-gate-exempt:' .claude/`.

Use sparingly — prefer classifying into BRANCHING or REFERENCE_ONLY when the
file actually maps to either category. Exempt is for genuine substring false
positives only.

### File classification

`ARCHETYPE_BRANCHING_FILES` — files that semantically branch on archetype
and require both the `## Archetype Gate` heading and the REF.

`ARCHETYPE_REFERENCE_ONLY_FILES` — files that mention archetype strings but
do not have semantic branching (e.g., shell scripts, generic stack files,
overview patterns). They require the REF only — no heading.

### Adding a new archetype-branching file

When a new file (procedure / agent / state) is added that branches on
archetype:

1. Add `## Archetype Gate` heading + REF line per the **Reference Mechanism**
   section above
2. Append the file path to `ARCHETYPE_BRANCHING_FILES` in
   `scripts/consistency-check.sh`
3. **If the new file's branching aligns with a Quick-Reference Table row**:
   cite it via `row "<X>"` (or `rows "<X>", "<Y>"`) syntax in the REF, then
   run `make sync-archetype-summaries` to embed the canonical labeled line.
   23h enforces verbatim match thereafter.
4. **If the branching is compound / Shape 4 / custom semantics**: keep the
   REF bare (`Quick-Reference Table.` with no row name) — the file stays
   outside 23h scope, with structural checks 23e/23f still gating it.
5. Run `bash scripts/consistency-check.sh` to confirm Check 23 (all subchecks
   23a-23h) passes
6. If `make lint-template` produces `DRIFT_DECLARED_VS_PROSE` because of a
   `coherence-allow scope=[...]` pragma, update the pragma in the same commit

### Adding a new archetype (e.g., `mobile`)

When experiment.yaml grows a new archetype value:

1. Add a new column to the Quick-Reference Table above (e.g., `| mobile |`
   alongside `web-app | service | cli`)
2. Update the `## Archetype Mapping` sub-sections (`### web-app`, `### service`,
   `### cli`, plus a new `### mobile`)
3. **For each row in `## Canonical Summary Lines` whose subsection exists**:
   extend the canonical labeled line with the new archetype column (e.g.,
   `> [phase-a] web-app: ... | service: skip | cli: skip | mobile: <text>`).
   Do NOT change existing slugs; the slug is canonical and does not depend
   on the archetype set.
4. Run `make sync-archetype-summaries` to propagate the extended canonical
   lines to all 30+ embedding files in 23h scope.
5. Update Check 23g's word-boundary regex if `mobile` introduces new
   identifying tokens beyond what existing patterns catch
6. Audit each file in `ARCHETYPE_BRANCHING_FILES` (including bare-REF files
   outside 23h scope) and add `mobile` handling — for bare-REF files, the
   handling is freely worded; for row-citing files, sync handles it
7. Run `bash scripts/consistency-check.sh` to confirm all of Check 23
   (especially 23h) still passes after the canonical extension
