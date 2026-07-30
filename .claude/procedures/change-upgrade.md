# /change: Upgrade Implementation


<!-- archetype-reference-only: REF .claude/patterns/archetype-behavior-check.md — 'service' in 'external service' / 'service stack file' is generic, not archetype-conditional -->

> Invoked by change.md Step 6 when type is Upgrade.
> Read the full change skill at `.claude/commands/change.md` for lifecycle context.

## Prerequisites from change.md

- experiment.yaml and experiment/EVENTS.yaml have been read (Step 2)
- Change classified as Upgrade (Step 3)
- Preconditions checked (Step 4)
- Plan approved (Phase 1)
- Specs updated (Step 5)

## Implementation

1. **ON-TOUCH check** -- follow `patterns/on-touch-check.md` for files in the upgrade plan. Write unit tests BEFORE upgrade code.
2. Generate TDD tasks for the integration per `patterns/tdd.md`. Link each task to its behavior ID(s) from experiment.yaml and include the behavior's `tests` array entries — the implementer must generate an `it()` assertion for each entry. Tasks should cover:
   - Credential storage/retrieval
   - Webhook signature validation (if applicable)
   - Error recovery (timeout, rate limit, invalid response)
   - Happy path end-to-end
3. Spawn implementer agents (same procedure as Feature production path, including step 6 trace writing)
4. **Merge worktree changes with verification** -- follow `procedures/worktree-merge-verification.md` (include consistency scan if 2+ agents).
5. Continue to Step 7
- Read or generate the service's stack file — first search `.claude/stacks/*/<service-slug>.md` (any category directory). If a pre-built file exists, use it. If not found, generate to `.claude/stacks/external/<service-slug>.md` using the procedure in `.claude/procedures/scaffold-externals.md` (Step 6), including checking Known Service Quirks before generating
- Replace the Fake Door component with real UI that calls the actual API route
- Replace any stub route (501/503) with the full integration logic using the service's API
- Remove `fake_door: true` from the `activate` event call — keep the same event name (`activate`) and `action` value for analytics continuity. The post-upgrade `track("activate", { action, service })` call MUST NOT introduce PII (`email`, `phone`, `name`) as event properties either — see `.claude/stacks/analytics/posthog.md` § "Never include PII in analytics event properties". If the upgrade adds a real lead-capture flow with email collection, the email is persisted server-side via the new `/api/leads/<action>` route + `leads` table; analytics receives only the non-PII action signal.
- Add the service's env vars to `.env.example`
- Ask the user for credential values and add to `.env.local`
- Verify the end-to-end user flow after the upgrade: UI → API route → external service
