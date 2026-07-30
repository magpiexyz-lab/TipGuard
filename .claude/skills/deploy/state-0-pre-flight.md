# STATE 0: PRE_FLIGHT

**PRECONDITIONS:**
- Git repository exists in working directory
- No branch or PR required (deploy is infrastructure-only)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Compound Dimensions "Surface type resolution" + "Deploy gate".
> web-app: full deploy (host + database) | service: API health check or stop if surface=none | cli: surface-only deploy or stop
> Conditional points: Step 5 (surface resolution + per-archetype routing), Step 5a.1 (surface-only path)
> Shape: interleaved-per-step

1. Verify `package.json` exists. If not, stop: "No app found. Run `/bootstrap` first."
2. Verify on `main` branch with clean working tree (`git status --porcelain` is empty). If not, stop: "Switch to main with a clean working tree before deploying."
3. Run `npm run build` to verify the app builds locally. If it fails, stop: "Fix build errors before deploying."
3a. If `stack.testing` is present: run the test command from the testing stack file (e.g., `npm test`). If tests fail, stop: "Tests are failing. Run `/verify` to fix test failures before deploying."
3b. **Update mode detection:** If `.runs/deploy-manifest.json` exists, read it and enter **update mode**:
    1. Set `deploy_mode = "update"` (stored in deploy-context.json).
    1a. **Staleness check:** Compare manifest `name` to experiment.yaml `name` and manifest `archetype` to experiment.yaml `type`. If either differs, stop: "The deploy manifest is from a different experiment or a prior version (manifest: `<manifest.name>`/`<manifest.archetype>`, current: `<experiment.name>`/`<experiment.type>`). Run `/teardown` first to remove old resources, then `/deploy` again to set up for the current experiment."
    2. Diff `experiment.yaml` stack against manifest to compute:
       - `added_services`: stack categories present in experiment.yaml but absent from manifest (e.g., added `stack.payment: stripe` since last deploy)
       - `removed_services`: stack categories present in manifest but absent from experiment.yaml (e.g., removed `stack.analytics`)
       - `unchanged_services`: stack categories present in both
    3. Report to user:
       "Previous deploy detected (deployed_at: <timestamp>). Running in **update mode**:
       - Redeploy latest code to hosting provider
       - Run DB migrations (idempotent)
       - Sync environment variables (upsert)
       - Added services: [list, or 'none']
       - Removed services: [list — will be marked orphaned, or 'none']
       - Unchanged services: [list — health check only]
       Reply **continue** to proceed, or run `/teardown` first to start fresh."
    4. Wait for user confirmation.
    If `.runs/deploy-manifest.json` does NOT exist:
    1. **Check for prior deployment:** Run the hosting provider's inspect command (e.g., `npx vercel inspect --json 2>/dev/null`) to detect whether the app is already deployed. If the command returns valid project data (project name, URL, alias): warn the user: "Your app appears to be already deployed (found: `<project-url>`), but no deploy manifest exists. This typically happens when `make deploy` was used instead of `/deploy`. Running `/deploy` now will create the manifest and synchronize lifecycle tracking. Any infrastructure already provisioned will be detected and reused (not duplicated)." Then set `deploy_mode = "initial"` and proceed normally — the deploy workflow will reconcile with existing infrastructure.
    2. If no prior deployment detected: set `deploy_mode = "initial"` and proceed.
3c. **Dependency audit:** Run `npm audit --audit-level=critical`. If critical vulnerabilities are found:
    "Critical npm vulnerabilities detected:
    <npm audit output>
    Reply **continue** to deploy anyway, or fix vulnerabilities first with `npm audit fix`."
    Wait for user confirmation. If `npm audit` reports no critical vulnerabilities, continue without further prompts.
4. Read `experiment/experiment.yaml` — extract `name`, `type` (default `web-app`), `stack.database` (if present), optional `stack.payment`, and optional `deploy` section.
5. Read the archetype file at `.claude/archetypes/<type>.md`. Resolve surface type per the archetype's capabilities (REF: `.claude/patterns/archetype-behavior-check.md` Compound Dimensions "Surface type resolution" + "Deploy gate"): if `stack.surface` is set in experiment.yaml, use it. Otherwise infer from archetype and stack configuration — `none` (pure API/CLI with no surface), `detached` (excluded hosting), or `co-located` (hosting present). For `co-located`/`detached` inference, verify `stack.services` is a non-empty list (if not, stop: "Missing `stack.services` in experiment.yaml. Run `/bootstrap` to set up your project.") then check `stack.services[0].hosting` — present -> `co-located`; absent -> `detached`. If the archetype's `excluded_stacks` includes `hosting`:
   - If surface is `detached`: this is a surface-only deployment — skip Steps 0.6–0.10 (no hosting/database infrastructure), Steps 1 and 3–4 (no infrastructure provisioning). Present a simplified plan in Step 2 (surface deployment only), then proceed directly to Step 5a.1.
   - If surface is `none`: stop: "The /deploy skill does not apply to CLI tools with no surface. To distribute your CLI: run `npm publish` (Node.js CLIs) or create a GitHub Release with binary artifacts (compiled CLIs). After publishing, run `/iterate` to analyze adoption metrics."
   If the archetype is `service` and surface is `none`: stop: "This is a pure API service with no user-facing surface. The /deploy skill requires a hosting target. Deploy your API manually to your hosting provider of choice, or add `surface: co-located` to experiment.yaml `stack` to use hosting-based deployment. Note: `/iterate` can still analyze your funnel with manual numbers — run it after deploying. To enable `/distribute` and `/teardown` later, create `.runs/deploy-manifest.json` manually with all service keys matching your experiment.yaml `stack`: `{\"name\": \"<experiment name>\", \"archetype\": \"service\", \"surface_type\": \"none\", \"canonical_url\": \"<your-api-base-url>\", \"deployed_at\": \"<ISO 8601 timestamp>\", \"stripe\": {\"webhook_endpoint_url\": \"<url>\"}}`. Omit keys for services not in your stack. Include all services present in experiment.yaml so `/teardown` can clean them up."
   If `stack.surface` is set in experiment.yaml and the archetype's `excluded_stacks` includes `hosting` and surface is `co-located`: stop: "The `<archetype>` archetype excludes the `hosting` stack, so `surface: co-located` is invalid. Set `stack.surface: detached` for a detached marketing surface, or remove the `surface` field to use the default."
   If the archetype's `excluded_stacks` does not include `hosting`: verify `stack.services` is a non-empty list — if not, stop: "Missing `stack.services` in experiment.yaml. Run `/bootstrap` to set up your project." Then extract `stack.services[0].hosting`.
   The deploy workflow comes from the hosting stack file. For services, browser-based health checks don't apply — use the API health endpoint instead.
> **Surface-only gate:** If the archetype's `excluded_stacks` includes `hosting` and surface is `detached` (resolved in step 5 above), skip Steps 0.6–0.10, Step 1, and Steps 3–4 — proceed to Step 2 (simplified plan), then directly to Step 5a.1. Surface-only deployments for archetypes without hosting have no hosting/database infrastructure.

6. **Hosting prerequisites** (skip for surface-only deployments — see gate in step 5)**:** Read the hosting stack file at `.claude/stacks/hosting/<stack.services[0].hosting>.md` -> `## Deploy Interface > Prerequisites`. Execute each check:
   - Run `install_check` — if not found, stop with `install_fix` instructions
   - Run `auth_check` — if fails, stop with `auth_fix` instructions
7. **Database prerequisites** (skip for surface-only deployments; also skip if `stack.database` is absent)**:** Read the database stack file at `.claude/stacks/database/<stack.database>.md` -> `## Deploy Interface > Prerequisites`. Execute each check:
   - Run `install_check` — if not found, stop with `install_fix` instructions
   - Run `auth_check` — if fails, stop with `auth_fix` instructions
   - If the database has no Prerequisites section (e.g., sqlite), skip
8. **Payment prerequisites:** If `stack.payment: stripe`: `which stripe` — if not found, warn: "Stripe CLI not installed. Webhook will need manual setup. Install: `brew install stripe/stripe-cli/stripe` (macOS) or see https://stripe.com/docs/stripe-cli." If found: `stripe whoami` — if fails, stop: "Run `stripe login` first (one-time per machine)."
9. **Compatibility check** (skip for surface-only deployments)**:** Read the database stack file's `## Deploy Interface > Hosting Requirements > incompatible_hosting`. If the current `stack.services[0].hosting` value appears in the list, stop with the reason from the stack file (e.g., "SQLite is incompatible with Vercel: serverless has no persistent filesystem").
10. Check external service CLIs: For each stack file in `.claude/stacks/*/` that contains a `## CLI Provisioning` section (search all category directories — e.g., `ai/`, `telephony/`, `external/` — excluding stack-declared categories like `database/`, `auth/`, `analytics/`, `payment/`, `email/`, `framework/`, `hosting/`, `testing/`, `ui/`), read `## CLI Provisioning`. If a CLI is specified:
   - `which <cli>` — record `cli_status: not_installed` (with install command) if not found
   - If found, run auth check — record `cli_status: not_authed` if fails
   - If both pass — record `cli_status: ready`
   - If no `## CLI Provisioning` section found — treat as no CLI (stack file predates CLI metadata)
   - Do NOT stop for missing external CLIs — record status for display in Step 2.

Merge deploy-specific fields into context.
Substitute `DEPLOY_MODE` with `"initial"` or `"update"` (from step 3b). For initial mode, all service arrays are empty. For update mode, populate from step 3b diff results:
```bash
bash .claude/scripts/init-context.sh deploy '{"deploy_mode":"initial","added_services":[],"removed_services":[],"unchanged_services":[]}'
```
- `deploy_mode`: set to `"update"` when `.runs/deploy-manifest.json` existed (step 3b); otherwise keep `"initial"`
- `added_services`, `removed_services`, `unchanged_services`: populate from step 3b diff results (empty arrays for initial mode)

**POSTCONDITIONS:**
- `package.json` exists <!-- enforced by agent behavior, not VERIFY gate -->
- On `main` branch with clean working tree <!-- enforced by agent behavior, not VERIFY gate -->
- `npm run build` succeeds <!-- enforced by agent behavior, not VERIFY gate -->
- experiment.yaml read and parsed <!-- enforced by agent behavior, not VERIFY gate -->
- Archetype file read and surface type resolved <!-- enforced by agent behavior, not VERIFY gate -->
- All prerequisite checks passed (or appropriate stops issued) <!-- enforced by agent behavior, not VERIFY gate -->
- `.runs/deploy-context.json` exists

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/deploy-context.json')); assert d.get('deploy_mode') in ('initial','update'), 'deploy_mode=%s' % d.get('deploy_mode')"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh deploy 0
```

**NEXT:** Read [state-1-config-gather.md](state-1-config-gather.md) to continue.
