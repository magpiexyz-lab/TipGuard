# /change Plan Templates

> Used by change.md Phase 1 to present the plan to the user.
> Each template corresponds to a change type classified in Step 3.
> "How" and "Approaches" sections use exploration results from plan-exploration.md.
> After drafting, run plan-validation.md — flagged items appear in Questions prefixed with "[Validation]".

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app: pages + golden_path | service: endpoints | cli: commands
> Conditional points: line 30 (Spec field row), line 32 (Golden Path impact), line 53 (Component Tree), line 58 (Data Flow), lines 127-129 (Upgrade How — per-archetype examples)
> Shape: interleaved-per-step

## Feature Plan Template

```
## What I'll Add

**Feature:** [description from $ARGUMENTS]
**Complexity:** Simple (single layer) | Multi-layer (spans pages + API + DB)

**New pages/endpoints/commands (if any):**
- [Page Name] (/route) — [purpose]

**Files I'll create or modify:**
- [file] — [what changes]

**New database tables (if any):**
- [table] — stores [what]

**New analytics events (if any):**
- [event_name] — fires when [trigger]

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Spec field".
>
> [spec-field] web-app: `golden_path` | service: `endpoints` | cli: `commands`

**Golden Path impact:** (web-app: pages, service: endpoints, cli: commands — skip if archetype has no golden_path)
- Current: [show current golden_path from experiment.yaml, or "not defined"]
- After this change: [updated path if flow changes, or "unchanged"]

**System/Cron Behaviors impact:**
- Current: [show current behaviors with `actor: system/cron` from experiment.yaml, or "none defined"]
- After this change: [new system/cron behavior if adding webhook/admin/cron, or "unchanged"]

### How (Multi-layer only — skip for Simple)

**Data Model:** (skip if no database changes)
- [table]: [key columns with types] — RLS: [policy summary]
- Indexes: [columns indexed and why, or "primary key only"]
- [Note existing tables from exploration if relevant]
- Done when: [one-line, e.g., "migration applies, types compile, RLS blocks unauthenticated reads"]

**API Contract:**
- `[METHOD] /api/[route]` — req: `{ [fields] }` → res: `{ [shape] }` | `4xx: { error: string }`
- [Pagination: cursor/offset if list endpoint, or omit]
- Done when: [one-line, e.g., "route returns 200 with valid input, 422 with missing fields"]

**Component Tree:** (web-app only — skip for service/cli)
- [PageComponent] → [ChildComponent] → [GrandchildComponent]
- Reuses: [existing components found during exploration, or "none"]
- Done when: [one-line, e.g., "page renders with mock data, components receive props"]

**Data Flow:** (web-app: UI flow, service: request flow, cli: command flow)
1. Entry: [how user discovers feature — nav link, CTA, URL, redirect | API endpoint | command invocation]
2. [interaction step] → [component/route/handler] → [what happens]
3. [next step] → [component/route/handler] → [what happens]
4. Terminal: [success state — confirmation, redirect, data displayed | response returned | output printed]
5. Error path: [trigger] → [error response] → [recovery — toast, inline, redirect | error code | stderr message]
- Done when: [one-line, e.g., "user can complete full flow from entry to confirmation"]

### Approaches (Multi-layer only — skip for Simple)

| | Option A: [name] | Option B: [name] |
|---|---|---|
| Approach | [1-2 sentences] | [1-2 sentences] |
| Pros | [bullets] | [bullets] |
| Cons | [bullets] | [bullets] |
| Effort | [relative: less/more] | [relative: less/more] |

**Recommendation:** [Option X] because [1-sentence reason].

### Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| [what could go wrong] | [consequence] | [prevention/fallback] |
| ... | ... | ... |

(2-5 items. For Simple features with no notable risks, write "Low risk — isolated, single-layer change.")

### Edge Cases (Multi-layer only — skip for Simple)

| Input/State | Expected Behavior |
|-------------|-------------------|
| [empty state — no data yet] | [what the UI/API shows] |
| [boundary — max length, zero, negative] | [validation or handling] |
| [concurrent — double submit, race condition] | [idempotency or guard] |
| [missing data — deleted reference, expired token] | [graceful degradation] |

(3-7 items. Focus on states a real user hits in the first week.)

### Acceptance Criteria
> These criteria will be validated at PR time.

- [ ] AC1: [verifiable behavior extracted from "What I'll Add"]
- [ ] AC2: [next verifiable behavior]
- [ ] AC3: [additional behavior if multi-layer]

**Questions:**
- [any ambiguities, or "None"]
- [if new library needed: "This feature needs [library]. Should I add it?"]
- [any items flagged by plan-validation.md, prefixed with "[Validation]"]
```

## Upgrade Plan Template

```
## Upgrade: [feature name]

**Current state:** Fake Door / Stub
**Target state:** Full integration with [service name]
**Credentials needed:** [env vars + how to obtain]

**Files to modify:**
- [file] — [what changes]

**Analytics changes:** Remove `fake_door: true` from activate event (now fires as real activation)

### How

**Integration Architecture** (adapt to archetype):
- web-app: Client → [API route] → [service SDK/REST call] → [response handling]
- service: [endpoint] → [service SDK/REST call] → [response]
- cli: [command] → [service SDK/REST call] → [output]
- Auth: [how the service authenticates — API key / OAuth / webhook signature]
- Done when: [one-line, e.g., "API route calls service, returns transformed response, handles auth"]

**Error Handling Strategy:**
- Timeout: [approach — e.g., 10s timeout, show retry button]
- Rate limit: [approach — e.g., exponential backoff, queue]
- Invalid response: [approach — e.g., fallback UI, error toast]
- Service down: [approach — e.g., graceful degradation, cached data]
- Done when: [one-line, e.g., "each error path shows user-friendly message, no unhandled rejections"]

### Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| [what could go wrong] | [consequence] | [prevention/fallback] |
| ... | ... | ... |

(2-5 items.)

### Edge Cases

| Input/State | Expected Behavior |
|-------------|-------------------|
| [empty state — no data yet] | [what the UI/API shows] |
| [boundary — max length, zero, negative] | [validation or handling] |
| [concurrent — double submit, race condition] | [idempotency or guard] |
| [missing data — deleted reference, expired token] | [graceful degradation] |

(3-7 items. Focus on states a real user hits in the first week.)

### Acceptance Criteria
> These criteria will be validated at PR time.

- [ ] AC1: [verifiable behavior from integration architecture]
- [ ] AC2: [error handling behavior]

**Questions:**
- [any ambiguities, or "None"]
- [any items flagged by plan-validation.md, prefixed with "[Validation]"]
```

## Fix Plan Template

```
## Bug Diagnosis

**Bug:** [description from $ARGUMENTS]

**Triage Summary** (from Step 0 exploration):
- Symptoms: [observed symptoms from triage, or "not available — user provided root cause directly"]
- Leading hypothesis: [H1 from triage, or "identified during exploration"]

**Root Cause Chain:**
1. [surface symptom — what the user sees, from triage symptoms]
2. [immediate cause — which code path produces it, from triage hypothesis confirmation]
3. [root cause — why that code path is wrong]

**Files affected:**
- [file] — [what's wrong]

**Fix approach:** [what you'll change, minimal diff]

**Blast Radius:**
- Files that import from affected files: [list, or "none — isolated"]
- Analytics events on affected pages: [list, or "none"]
- Tests that cover affected code: [list, or "none"]

**Regression Risk:** [Low/Medium/High] — [1-sentence justification]

### Acceptance Criteria
- [ ] AC1: [the bug is fixed — specific observable behavior]
- [ ] AC2: [regression does not occur — related functionality still works]
```

## Polish Plan Template

```
## Planned Changes

1. **[Page/Component]**: [what you'll change] — [why this improves things for target_user]
2. ...

### Acceptance Criteria
> These criteria will be validated at PR time.

- [ ] AC1: [observable improvement for change 1]
- [ ] AC2: [observable improvement for change 2]
```

## Analytics Plan Template

```
## Audit Report

### Events
| Event | Funnel Stage | Expected Location | Status | Issue |
|-------|-------------|-------------------|--------|-------|
| [event from experiment/EVENTS.yaml events map] | [funnel_stage] | [page] | ✅/❌/⚠️ | [issue or —] |

### Suggested Events (if any)
- [event_name] — fires when [trigger] (add to events map with funnel_stage)

### Acceptance Criteria
- [ ] AC1: [event wiring or fix verified]
- [ ] AC2: [global properties attached correctly]
```

## Test Plan Template

```
## Smoke Test Plan

**Funnel Steps:**
| # | Event | Route | Browser Actions | Selectors |
|---|-------|-------|-----------------|-----------|
| 1 | [event] | [route] | [actions] | [selectors from app code] |

**Skipped:** retain_return (requires 24h delay)

**Activation Detail:**
- thesis: [from experiment.yaml]
- Activation test: [what the test will do]

**Files to Create/Modify:**
- [list of files]

**Template path:** Full templates (all assumes met) | No-Auth Fallback (assumes unmet: [list unmet category/value pairs])

### Acceptance Criteria
- [ ] AC1: [smoke test file created and covers funnel step]
- [ ] AC2: [activation test verifies thesis behavior]
```
