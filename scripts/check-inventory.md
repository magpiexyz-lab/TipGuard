# Check Inventory

Scannable reference listing all automated checks by name, grouped by validator.
87 active checks consolidated into 83 inventory rows.
Checks 3 and 7 are archetype-aware — they read `required_experiment_fields` and `excluded_stacks` from archetype frontmatter.

Last updated: 2026-05-10

## Validation philosophy

Automated checks enforce invariants that prevent **silent failures** in generated
code: structural correctness, cross-file synchronization, behavioral contracts,
and reference integrity. Checks that regex-match natural-language prose for specific
phrasing are out of scope — phrasing quality in prose consumed by an LLM reader is
better enforced by the scoped LLM review (`scripts/scoped-review-prompt.md`).

## validate-frontmatter.py

| Name | Description |
|------|-------------|
| Require stack frontmatter keys | Every stack file must have all required keys (assumes, packages, files, env, ci_placeholders, clean, gitignore) |
| Resolve assumes entries to existing stack files | Every `assumes` entry must point to an existing `.claude/stacks/<path>.md` |
| Require archetype frontmatter keys | Every archetype file must have all required keys (description, required_stacks, optional_stacks, excluded_stacks, required_experiment_fields, build_command) |
| Require skill frontmatter keys | Every skill file must have all required keys (type, reads, stack_categories, requires_approval, references, branch_prefix, modifies_specs) |
| Verify referenced file paths exist | Every `references` path in skill frontmatter must exist on disk |
| Require verify.md in code-writing skill references | Code-writing skills must include verify.md in their `references` list |
| Require branch.md in code-writing skill references | Code-writing skills must include branch.md in their `references` list |
| Match CLAUDE.md Rule 0 skill list to filenames | The parenthetical skill list in Rule 0 must match actual skill filenames |
| Verify ci_placeholders keys in ci.yml | Union of all `ci_placeholders` keys must appear in `.github/workflows/ci.yml` |
| Verify ci_placeholders values in gitleaks allowlist | All `ci_placeholders` values must be matched by a `.gitleaks.toml` allowlist pattern |
| Verify skill branch_prefix values in CLAUDE.md Rule 1 | Every skill `branch_prefix` value must appear as an allowed prefix in CLAUDE.md Rule 1 branch naming convention |
| Require observe.md in code-writing skill and deploy.md references | Code-writing skills and deploy.md must include observe.md in their `references` list |

## validate-semantics.py

| Name | Description |
|------|-------------|
| Verify import completeness in TSX templates | JSX components used in code blocks have matching imports |
| Verify Makefile target guards | npm/node targets guard on package.json existence |
| Validate fixture structure | Test fixtures have required keys, valid idea.name, correct assertions |
| Verify frontmatter-content sync | Code block headers match `files` frontmatter; Makefile clean lines match `clean` frontmatter |
| Verify conditional dependency guards | References to optional stack categories have conditional guards within 150 chars |
| Verify required fields consistency | Required experiment.yaml fields match between Makefile and validate-semantics.py |
| Verify fixture stack coverage | Every stack file is covered by at least one fixture; mandatory categories present in all fixtures |
| Verify tool and prereq validity | Tool names referenced in skill prose are in the known tools list |
| Verify env loading outside Next.js runtime | Non-`src/` templates using `process.env` load env config |
| Validate warning differentiation | Makefile validate target differentiates clean pass from pass with warnings |
| Verify hardcoded provider names match assumes | Code blocks using provider-specific or framework-specific identifiers (e.g., `@next/`) must have matching `assumes` declaration |
| Verify prose file references in reads frontmatter | Spec files (CLAUDE.md, experiment/EVENTS.yaml) referenced in skill prose must appear in `reads` frontmatter |
| Verify fixture coverage for stack file branching | Conditional stack paths (`when stack.X is NOT Y`) must have fixture coverage for the alternate branch |
| Verify stack fallback when assumes not met | Stack files with optional-category `assumes` must have a fallback section for absent dependencies. Also checks framework assumes for shared-category stacks (database, auth, analytics, payment, email) — these must have fallbacks since the framework value can differ across service archetypes |
| Verify Makefile deploy hosting guard | Deploy target using provider-specific commands must check `stack.hosting` |
| Verify change skill validates payment-auth dependency | change.md must validate that `stack.auth` is present when adding `payment` to experiment.yaml stack |
| Verify stack file env vars in prose match frontmatter declarations | Environment Variables prose sections mentioning env var names must have those vars declared in frontmatter `env.server` or `env.client` |
| Verify change skill validates payment requires database | change.md Feature constraints must validate that `payment` in the stack requires `database` to also be present |
| Verify fixture coverage for testing with partial assumptions | Testing fixtures must not only cover all-met and none-met assumes scenarios — at least one partial-met fixture (e.g., auth present, database absent) is required |
| Verify Makefile help text doesn't hard-code optional env var names | Makefile target help comments (`## ...` text) must not contain specific environment variable names that are conditional on stack configuration |
| Verify stack file packages in prose match frontmatter declarations | Packages prose sections with `npm install` commands must have those packages declared in frontmatter `packages.runtime` or `packages.dev` |
| Verify bootstrap validates payment requires database | bootstrap.md Validate experiment.yaml section must validate that `stack.payment` requires `stack.database` to also be present |
| Verify testing CI template includes payment env vars | If ci.yml e2e job contains Stripe env vars, the testing stack CI Job Template must also reference them |
| Verify testing no-auth fallback includes CI job template | Testing stack No-Auth Fallback section must contain a YAML code block with an `e2e:` job definition |
| Verify change skill Test type permits adding testing to experiment.yaml | change.md Test type constraints must address adding `testing` to experiment.yaml stack section |
| Verify testing env frontmatter excludes assumes-dependent vars | Testing stack env frontmatter with optional assumes and a fallback must not unconditionally declare provider-specific env vars |
| Verify auth page templates contain post-auth redirects | Auth stack signup/login code blocks must contain `router.push` or `redirect` after auth success — a bare TODO comment fails |
| Verify change skill assumes validation matches bootstrap assumes validation | change.md assumes validation must include value-matching language, not just category-existence checks |
| Verify change skill validates payment dependencies before plan phase | At least one payment dependency stop message must appear before the plan phase marker in change.md |
| Verify trackServerEvent calls match analytics stack signature | `trackServerEvent()` calls in stack file code blocks must not pass an object literal as the 2nd argument (distinctId expects a string) |
| Verify analytics stack files include Dashboard Navigation section | Every `.claude/stacks/analytics/*.md` file must contain a `## Dashboard Navigation` heading (case-insensitive) |
| Verify change skill revalidates testing assumes for all change types | change.md preconditions step must contain testing assumes validation that is NOT gated by the Test-type classification |
| Verify analytics stack files include Test Blocking section | Every `.claude/stacks/analytics/*.md` file must contain a `## Test Blocking` heading (case-insensitive) |
| Verify skill prose event names exist in experiment/EVENTS.yaml | Backtick-wrapped snake_case tokens in skill prose appearing near event/fire context must exist in experiment/EVENTS.yaml, be defined in a YAML code block within the same skill, or reference "from/in experiment/EVENTS.yaml" within 100 chars |
| Verify stack files with fallback sections annotate conditional files in frontmatter | Stack files with fallback sections listing assumes-dependent files in `files` frontmatter must include a `# conditional` annotation |
| Verify no-auth CI template includes commented database placeholder env vars | If the full-auth CI Job Template in the testing stack includes database-related env var names, the No-Auth CI Job Template must also contain them (commented or uncommented) |
| Verify Makefile validate warns about bootstrap-excluded stack categories | Makefile `validate` target must check for `testing` in experiment.yaml `stack` and warn that bootstrap rejects it |
| Verify change skill classification precedes classification-dependent checks | In change.md, the step heading containing "Classify" must appear before any step heading whose body contains "classified as" or "is a Fix" or "is NOT Test" |
| Verify ads.yaml schema | If `experiment/ads.yaml` exists: channel-aware validation — universal keys (campaign_name, project_name, landing_url, budget, targeting, conversions, guardrails, thresholds) required for all channels; google-ads requires keywords + ads with RSA constraints and guardrails.max_cpc_cents; twitter requires tweets (≥2, ≤280 chars); reddit requires posts (≥2, headline ≤300 chars); budget within limits; thresholds.expected_activations is int >= 0, go_signal and no_go_signal are non-empty strings |
| Verify ads.yaml campaign_name matches experiment.yaml name | `campaign_name` in ads.yaml must start with experiment.yaml `name` |
| Verify distribute skill prose event names | distribute.md must contain a YAML code block defining the `feedback_submitted` event (added to experiment/EVENTS.yaml `events` map during Step 7c) |
| Verify distribution docs references exist | If distribute.md or any `.claude/stacks/distribution/*.md` file contains a backtick-wrapped `docs/*.md` reference, that file must exist on disk |
| Verify distribute skill validates analytics stack in experiment.yaml | distribute.md preconditions section (Step 1) must validate that `stack.analytics` is present in experiment.yaml before proceeding |
| Verify distribute skill validates experiment/EVENTS.yaml events structure | distribute.md preconditions section (Step 1) must validate that experiment/EVENTS.yaml `events` is a well-formed dict |
| Verify trackServerEvent calls are awaited in stack file code blocks | `trackServerEvent()` calls in stack file code blocks (excluding function definitions) must be preceded by `await` on the same line |
| Verify Supabase CLI commands use correct flag syntax | Code blocks containing `supabase projects delete` must include the `--project-ref` flag |
| Verify procedure files have production branch | Feature/Upgrade/Fix procedure files must contain `quality: production` or `quality.*production` |
| Verify production sections reference TDD | Production sections in procedure files must reference `tdd.md` or `patterns/tdd` |
| Verify production sections reference implementer | Feature and Upgrade production sections must reference `implementer.md`, `agents/implementer`, or `implementer agent` |
| Verify change production precondition checks testing | change.md `quality:production` block must validate `stack.testing` within nearby context |
| Verify bootstrap validates variants structure and archetype | bootstrap.md Step 3 (Validate experiment.yaml) must contain variant validation logic (structure) and restrict variants to web-app archetype |
| Verify agent tool consistency | implementer.md must have Edit/Write/Bash tools; spec-reviewer.md must not have Edit/Write and must disallow them |
| Verify framework-archetype compatibility in bootstrap and change | Both bootstrap.md and change.md must validate that web-app requires nextjs and cli requires commander |
| Verify settings.json hook paths resolve to existing files | Every hook `command` path in `.claude/settings.json` must point to an existing `.sh` file |
| Verify agent-prompt-footer directive matches hook grep | Directive marker in `agent-prompt-footer.md` must appear as grep pattern in `skill-agent-gate.sh` |
| Verify conditional packages not listed unconditionally in prose | Stack files with fallback sections that skip packages must not list those packages in an unconditional `npm install` in the `## Packages` section |
| Verify playwright-archetype compatibility in bootstrap and change | Both bootstrap.md and change.md must validate that playwright testing is incompatible with service/cli archetypes |
| Verify audit/review scope covers template-source directories | Every Glob/Read pattern in `.claude/skills/audit/state-1-parallel-analysis.md` and `.claude/skills/review/state-2a-review-scan.md` must (a) resolve to ≥1 file on disk, (b) cover every required template-source directory in BOTH skills, and (c) reference each canonical individual file (`agent-prompt-footer.md`, `settings.json`, `Makefile`) in at least one skill. Adding a new template-source directory therefore requires updating both skills' "Files to read" lists |

## consistency-check.sh

21 active checks consolidated into 13 rows. Three checks removed (scripts #8, #11, #12). Checks #3 and #13 scan commands, agents, and procedures.

| Name | Description | Scripts |
|------|-------------|---------|
| Forbid event name enumerations in rules and skills | CLAUDE.md and skill files must not enumerate event names inline | #1, #2 |
| Forbid hardcoded analytics paths and constants in reference files | Skills, agents, procedures, CLAUDE.md, and PR template must not hardcode analytics import paths or constant names | #3, #6, #9 |
| Forbid framework-specific terms in rules and skills | CLAUDE.md and skill files must not use framework-specific directives or terms (agents excluded — they may reference these in inspection rules) | #4, #5 |
| Forbid hardcoded framework paths in change skill | change.md must not hardcode API or types paths | #7 |
| Require verify.md references in code-writing skill content | Code-writing skill content (not just frontmatter) must reference verify.md | #10 |
| Forbid hardcoded analytics provider names in skill section headings | Skill, agent, and procedure files must not contain `PostHog` (case-insensitive) in `###` section headings — provider names belong in the analytics stack file | #13 |
| Verify lib.sh function calls have space before arguments | Hook scripts (excluding lib.sh) must not call lib.sh functions with the argument concatenated to the function name (e.g., `func"$arg"` instead of `func "$arg"`) | #14 |
| Verify STATE_ID regex character class matches across hooks | state-completion-gate.sh and phase-boundary-gate.sh must use the same character class for STATE_ID extraction from advance-state.sh commands | #15 |
| Verify verify.md STATE 5 branches on testing framework type | state-5-e2e-tests.md must reference both playwright and vitest test runners, not hardcode a single framework | #16 |
| Warn on weak non-STATE-0 postconditions | Non-STATE-0 entries in state-registry.json using `test -f` without `python3` or `grep` content validation get a WARN (non-blocking) | #17 |
| Warn on gate-keeper prompts missing Verify criteria | Gate-keeper spawn instructions must include explicit `Verify:` criteria — prompts without verification instructions get a WARN (non-blocking) | #18 |
| Forbid bash 4+ parameter expansion in shell files | Hook + script files must not use `${var^^}` / `${var,,}` (bash 4+) — fails silently on macOS default bash 3.2; use `tr` instead (recurrence guard for #1141) | #25 |
| Require shadcn-primitive filter on `@/components/` extraction | Skill/agent files that regex-extract `@/components/` imports must reference `@/components/ui/` or `@/components/magicui/` as a filter — otherwise auto-generated shadcn primitives get bundled into thin-wrapper / claim-candidate sets (recurrence guard for #1154) | #26 |
| Require clientIpFromHeaders helper for rate-limit examples | Stack-file code blocks under `.claude/stacks/**/*.md` that read `headers.get("x-forwarded-for")` must do so inside a code block that also defines `function clientIpFromHeaders` (the canonical helper). All call sites must use the helper instead — Vercel's proxy appends the verified client IP as the LAST XFF entry; raw reads let attackers rotate prefix to bypass per-IP rate caps (recurrence guard for #1361) | #27 |

## Cross-validator overlaps

Two checks appear in both `validate-frontmatter.py` and `consistency-check.sh`:

- **verify.md references**: frontmatter validator checks the `references` list (structural); consistency checker greps the file content (belt-and-suspenders)
- **branch.md references**: frontmatter validator checks the `references` list for code-writing skills; consistency checker verifies via frontmatter type detection

These overlaps are intentional — they catch different failure modes (metadata vs. content) and provide redundancy.

## Self-Tests

Validators are self-tested via `pytest scripts/`. Tests run in CI before validators execute.
- `test_validate_frontmatter.py` — unit tests for all 11 frontmatter checks
- `test_validate_semantics.py` — unit tests for 20 extracted check functions + subprocess integration test
- `test_consistency_check.py` — subprocess tests for 6 consolidated consistency checks

## Pending

| Name | Dimension | Target validator | Status |
|------|-----------|-----------------|--------|
| *(none)* | | | |

## Rejected

| Name | Reason | Date |
|------|--------|------|
| Verify TODO resolution coverage | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
| Verify error message actionability | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
| Verify branch context in recovery messages | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
| Verify destructive recovery save-first guidance | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
| Verify sequential numbering in enumerated lists | Cosmetic formatting check: no silent failure risk | 2026-02-15 |
| Verify skill stack_categories documents exclusions | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
| Verify abandon-branch cleanup guidance | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
| Verify multi-turn resumption guidance | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
| Verify analytics stack files document test-blocking endpoint pattern | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
| Verify bootstrap documents conditional file-creation for interdependent stacks | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
| Verify testing template selection documents assumes-check branching | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
| Verify bootstrap lists placeholder-constant replacements for stack templates | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
| Verify migration numbering documents concurrent-branch behavior | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
| Verify analysis-only skills check for spec file existence | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
| Verify install-failure recovery specifies retry scope | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
| Verify bootstrap validates stack assumes dependencies | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
| Verify Makefile deploy error names the command to replace | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
| Verify bootstrap rejects excluded stack categories | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
| Verify stack file prose flags silent TODOs distinctly from build-failing TODOs | Prose-phrasing check: regex-matches natural language for specific wording | 2026-02-15 |
