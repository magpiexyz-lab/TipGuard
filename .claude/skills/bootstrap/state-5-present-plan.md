# STATE 5: PRESENT_PLAN

**PRECONDITIONS:**
- Preconditions checked, fresh start path (STATE 4 POSTCONDITIONS met, not resuming)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Primary unit".
> [primary-unit] web-app: page (`src/app/<page>/page.tsx`) | service: endpoint (`src/app/api/<ep>/route.ts`) | cli: command (`src/commands/<cmd>.ts`)

Present the plan in plain language the user can verify:

```
## What I'll Build

**[If web-app] Pages:**
- Landing Page (/) — [purpose from experiment.yaml]
- [Page Name] (/route) — [purpose from experiment.yaml]
- ...

**[If service] Endpoints:**
- [Endpoint Name] (/api/route) — [purpose from experiment.yaml]
- ...

**[If cli] Commands:**
- [Command Name] — [purpose from experiment.yaml]
- ...

**Behaviors:**
- [b-NN: behavior description] -> built in [file(s)]
- [b-NN: behavior description] -> built in [file(s)]
- ...

**Variants (if experiment.yaml has `variants` AND archetype is web-app):**
- [slug] — "[headline]" -> /v/[slug]
- [slug] — "[headline]" -> /v/[slug]
- Root `/` renders: [first variant slug]

**Database Tables (if any):**
- [table name] — stores [what]
- ...

**Non-Stack External Dependencies (decided in STATE 12):**

Stack-managed services (anything declared under experiment.yaml `stack` and resolved to a `.claude/stacks/<category>/<value>.md` file — e.g., `stack.payment: stripe`, `stack.analytics: posthog`, `stack.database: supabase`) do NOT appear in this section. They are integrated unconditionally by `scaffold-libs` from the corresponding stack template; their credentials and integration mode are not user decisions at STATE 5. List ONLY services discovered by `scaffold-externals` (STATE 12) that have no stack file.

If every external integration is stack-managed (the common case), write:

> **None — all features use stack-managed services.**

Otherwise, list each non-stack external using these examples as the shape:

- Twilio (SMS) — `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` — **core** — must integrate (credentials at bootstrap or /deploy)
- OpenAI (when not in `stack`, e.g., a one-off summarization endpoint) — `OPENAI_API_KEY` — **non-core** — Fake Door (default) / Skip / Full Integration

Core = removing it prevents users from validating the thesis. Decisions are finalized in STATE 12 (`scaffold-externals` produces `.runs/externals-decisions.json`); STATE 5 is a forward-looking summary, not the decision point.

**Analytics Events:**
- [For each event in experiment/EVENTS.yaml events map (filtered by requires/archetypes), show: event_name on Page Name]

**[If web-app] Golden Path (from experiment.yaml):**
| Step | Page | Event |
|------|------|-------|
| 1. [step] | [page] | [event] |
Target: [target_clicks] clicks

If experiment.yaml has no `golden_path` field: derive one from behaviors + experiment/EVENTS.yaml events map,
present it in the plan, and write it back to experiment.yaml after approval (STATE 7).

**[If service] API Flow (from experiment.yaml `endpoints`):**
| Step | Endpoint | Method | Event |
|------|----------|--------|-------|
| 1. [step] | [endpoint] | [method] | [event] |

**[If cli] Command Flow (from experiment.yaml `commands`):**
| Step | Command | Event |
|------|---------|-------|
| 1. [step] | [command] | [event] |

**System/Cron Behaviors (from experiment.yaml):**
| Behavior | Actor | Trigger | Then |
|----------|-------|---------|------|
| [b-NN] | [actor] | [trigger] | [then] |

If no behaviors have `actor: system` or `actor: cron`: "None defined — all behaviors are user-initiated."

**Activation mapping:**
- experiment.yaml thesis: [thesis]
- activate event action value: "[concrete_action]" (e.g., "created_invoice") — or "N/A — all behaviors are descriptive, activate will be omitted" if no behavior involves an interactive user action

**Tests (if stack.testing present):**
- Test runner: [testing stack value]
- [If web-app] Template path: Full templates (all assumes met) | No-Auth Fallback (assumes unmet: [list])
- [If web-app] Smoke tests for: [list each page name]
- [If web-app] Funnel test: landing -> [activate action] -> login -> [core value pages]
- [If service] Endpoint smoke tests for: /api/health, [list each endpoint]
- [If cli] Command smoke tests for: --version, --help, [list each command] --help

**Technical Decisions:**
- Data model: [for each table — key columns, relationships, RLS approach]
- API patterns: [REST conventions, error shape, pagination approach if applicable]
- Auth flow: [if stack.auth present — signup -> verify -> session approach]
- State management: [client-side approach — server components vs client state]
- (Or: "Standard defaults — no notable architectural decisions for this MVP")

**Questions:**
- [any ambiguities — or "None"]
```

**POSTCONDITIONS:**
- Plan displayed to user with all required sections
- `.runs/current-plan.md` exists (plan is the artifact)

**VERIFY:**
```bash
test -f .runs/current-plan.md && test -s .runs/current-plan.md && grep -q 'Behaviors' .runs/current-plan.md
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 5
```

**NEXT:** Read [state-6-user-approval.md](state-6-user-approval.md) to continue.
