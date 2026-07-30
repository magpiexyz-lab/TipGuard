# Assayer — Product Design Document

> **Domain**: assayer.io — "Know if it's gold before you dig."
>
> This document is the technical specification for implementing the UX defined in `docs/ux-design.md`.
> When this document and the UX design conflict, `ux-design.md` wins.

---

## 1. Levels & Archetypes

```
Idea → Spec → Asset → Traffic → Behavior → Insight → Decision → Next Experiment
```

### Levels

| Level | Name | Funnel dimensions | Shared stack added |
|-------|------|-------------------|-------------------|
| L1 | **Pitch** | REACH + DEMAND + MONETIZE(signal) | Next.js + hosting + PostHog + shadcn + Playwright |
| L2 | **Prototype** | + ACTIVATE + MONETIZE(functional) | + Supabase |
| L3 | **Product** | + RETAIN | + Auth (+ Stripe if monetize) |

Levels are nested: L2 includes L1, L3 includes L2. Upgrade without rebuild.

### Archetype x Level Matrix

| | L1 (Pitch) | L2 (Prototype) | L3 (Product) |
|--|-----------|----------------|-------------|
| **web-app** | Landing page + variants + analytics | + functional pages + DB | + auth + payments |
| **service** | Landing page + API docs + "Get API Key" CTA | + real API routes + DB | + auth + rate limit + billing |
| **cli** | Landing page + npx stub (opens browser) | + real CLI commands + backend API + DB | + auth token + cloud sync + billing |

**All archetypes at L1 are the same: a Next.js landing page.** Differentiation starts at L2.

> **Agent experiments** use `type: web-app` with `hosting: railway` and `ai: anthropic`.
> An "AI agent" is a web-app whose core behavior is an AI invocation (execution route + results page).
> `/spec` detects agent-like ideas and generates appropriate behaviors and stack choices — no separate archetype needed.

### Stack Principles

- **Runtime is always Next.js.** API routes serve as backend. No Hono/Express during validation.
- **Hosting varies by need.** Vercel (default) for most experiments. Railway for long-running tasks and real-time (persistent runtime). Determined at `/spec` time from behavior analysis.
- **`type` controls generation, not stack.** All archetypes use the same stack structure. `type` determines what `/bootstrap` creates (pages, routes, artifacts).
- **Code grows from L1 to production without rewrite.** Same runtime across all levels. Switching hosting (Vercel → Railway) is a config change, not a code change.

Deployed at `exp-name.assayer.io`.

---

## 2. Architecture

### System Boundaries

```
┌─────────────────────────────────────────────────────────────────────┐
│  BROWSER (Client)                                                    │
│                                                                      │
│  Landing/Assay ─── SSE (spec stream) ──────────> Vercel API          │
│  Experiment Page ── Supabase Realtime (WebSocket) ── Supabase        │
│  Lab / Compare ─── REST ───────────────────────> Vercel API          │
└──────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  EDGE (Vercel / Next.js App Router)                                  │
│                                                                      │
│  /api/spec/stream ──── SSE (anonymous OK) ──> Anthropic API          │
│  /api/experiments/* ── REST (auth required) ── Supabase               │
│  /api/skills/* ─────── Cloud Run Jobs trigger                        │
│  /api/operations/* ── billing gate + completion handler               │
│  /api/billing/* ──── subscribe, top-up, usage, portal                │
│  /api/distribution/* ─ ad platform APIs                              │
│  /api/notifications/* ─ Resend API                                   │
└──────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  ASYNC WORKERS                                                       │
│                                                                      │
│  Cloud Run Jobs ─── Agent SDK runs skills (/bootstrap, /deploy, etc) │
│                 ─── Events → Supabase Realtime                       │
│                 ─── Results → Supabase tables                        │
│                                                                      │
│  Vercel Cron ─── 15min: metrics sync (PostHog + ad platforms)        │
│              ─── 15min: assayer score computation                     │
│              ─── 15min: alert condition detection                    │
│              ─── 1h: anonymous spec cleanup                          │
│              ─── daily: notification dispatch                        │
│              ─── daily: portfolio insight generation (Sonnet)         │
│              ─── daily: auto-rebalance (Team plan, with gate)        │
│              ─── weekly: cost-monitor (margin + hit rate + auto-fix) │
└──────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  EXTERNAL SERVICES                                                   │
│                                                                      │
│  Supabase ─── DB + Auth + Realtime + RLS + Vault                     │
│  PostHog ──── behavior events (experiment landing pages)             │
│  Anthropic ── AI spec generation + iterate analysis                  │
│  Stripe ───── Subscriptions (Pro/Team) + Checkout (PAYG top-up)       │
│               + Customer Portal (manage sub) + Webhooks               │
│  Resend ───── notification emails (scorecard templates)              │
│  Google Ads API, Meta Marketing API, X API v2, Reddit API            │
│  Vercel ───── hosting (platform + experiments)                       │
│  Sentry ───── error tracking + performance monitoring                │
│  Google Cloud Run ── skill execution compute                         │
└──────────────────────────────────────────────────────────────────────┘
```

### Hosting Model

```
Assayer Platform       →  Vercel (assayer.io) + Supabase
Skill Execution        →  Cloud Run Jobs (Docker, scale-to-zero)
Experiment (default)   →  Vercel (exp-name.assayer.io)
Experiment (long-running) →  Railway (exp-name.assayer.io)
```

All experiments share one PostHog project. `global_properties` distinguishes by experiment.

### Skill Execution Model

```
.claude/commands/*.md (single source of logic)
         |
    +---------+
    v         v
  CLI      Agent SDK
(internal) (Cloud Run Jobs)
              ^
              |
       Vercel API route
              ^
              |
           Web UI
         (assayer.io)

Shared reasoning rules:
  .claude/patterns/spec-reasoning.md
         |
    +---------+
    v         v
  spec.md   /api/spec/stream
  (CLI)     (Vercel, direct Anthropic call)
```

- Internal: Claude Code CLI → skill directly
- External: Web UI → Vercel API → Cloud Run Jobs → Agent SDK → same skill
- All skills use the same execution path — no "simplified API version"
- **Exception: `/spec` on web** — uses direct Anthropic API call from Vercel (not Cloud Run) to avoid cold start latency (5-30s). Shared reasoning rules in `spec-reasoning.md` prevent prompt drift between CLI and web paths.

### Shared Reasoning Rules (`spec-reasoning.md`)

`/spec` is the only skill with two execution shells: CLI (interactive, with STOP points) and web (streaming, no interaction). To prevent prompt drift:

- `.claude/patterns/spec-reasoning.md` contains the core AI reasoning logic: pre-flight research dimensions, hypothesis generation rules, variant differentiation criteria, funnel threshold derivation, and stack selection rules.
- `spec.md` (CLI) imports these rules and wraps them with interactive STOP points.
- `/api/spec/stream` (web) imports these rules and wraps them with `>>>EVENT:` output format instructions.
- **Single source of truth**: when reasoning logic changes, edit `spec-reasoning.md` once — both paths update automatically.

### Skills are Stateless Transformers

Skills return JSON. Caller handles persistence. Exception: `/bootstrap`, `/deploy`, `/distribute`, `/teardown` have side effects.

AI-calling skills (`/spec`, `/iterate`): validate with zod, retry once on parse failure, typed error on second failure.

### Interactive Skill Architecture

Skills have three categories of interactive points:

1. **Pre-collection** — Web UI gathers all inputs (idea text, level, change description, credentials) before invoking the skill. Zero round trips.
2. **Credential injection** — Platform pre-configures credentials as environment variables in the Cloud Run container. Skills check env vars before prompting.
3. **Approval gates** — Skill runs until it hits a gate (deploy plan, bootstrap plan), pauses, and resumes when the user approves via web UI.

### Compute Layer: Cloud Run Jobs

Why Jobs over Services: batch-job semantics match "run skill to completion"; scale-to-zero between executions; 24hr max timeout (self-imposed budget per skill); per-execution env var overrides via `overrides.containerOverrides[].env`.

**Triggering:** Vercel API route → `POST /apis/run.googleapis.com/v2/.../jobs:run` with execution-specific env vars (experiment ID, skill name, user credentials). All skills go through this single path.

### Docker Image

| Layer | Contents |
|-------|----------|
| Base | `node:20-slim` |
| System deps | `git`, `curl`, `jq` |
| CLIs | `vercel`, `@railway/cli`, `supabase`, `claude-code` (Agent SDK) |
| Template | Pre-loaded `mvp-template` `.claude/` directory |
| Entrypoint | `skill-runner.js` |

### Workspace Lifecycle

1. Container starts from Docker image
2. Clone experiment repo (existing) or copy mvp-template (new)
3. Generate `experiment/experiment.yaml` from Supabase data
4. Inject env vars (API keys, Supabase URL, user credentials)
5. Agent SDK runs skill (e.g., `/bootstrap`, `/deploy`)
6. Git push results to experiment repo
7. Parse skill output → write structured data to Supabase
8. Container destroyed (scale-to-zero)

> `experiment.yaml` is a temporary derived artifact inside the container — Supabase is the source of truth.

### Skill Execution Streaming

Cloud Run Job writes events to Supabase Realtime channel `exec:{execution_id}`. Browser subscribes directly — no Vercel involvement in long-lived connections.

Event types:

| Type | Payload | Purpose |
|------|---------|---------|
| `log` | `{ line: string, ts: number }` | Stream skill output to UI |
| `status` | `{ status: "running" \| "paused" \| "completed" \| "failed" }` | Update execution state |
| `gate` | `{ gate_type: string, prompt: string }` | Trigger approval UI |
| `progress` | `{ pct: number, phase: string, preview_url?: string }` | Update progress bar + preview |

### Approval Gate Pattern

1. Job hits gate → writes `status='paused'` + `gate_type` to `skill_executions`
2. Job polls Supabase every 5s for status change
3. User approves via Web UI → writes `status='running'` to `skill_executions`
4. Job detects change → resumes skill execution
5. 30min timeout with no approval → `status='timed_out'`

Why polling over webhooks: simpler implementation, no inbound networking required for Cloud Run Jobs, 5s latency is acceptable for human-in-the-loop gates.

### Agent SDK

```typescript
import { query, resumeSession } from "@anthropic-ai/claude-agent-sdk";
import { createClient } from "@supabase/supabase-js";

const supabase = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_KEY!);
const executionId = process.env.EXECUTION_ID!;
const channel = supabase.channel(`exec:${executionId}`);

// 1. Run skill
const session = await query({
  cwd: workspacePath,
  prompt: "/bootstrap",
  allowedTools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent"],
});

// 2. Stream output to Supabase Realtime
for await (const event of session.events) {
  await channel.send({ type: "broadcast", event: "log", payload: { line: event.text, ts: Date.now() } });
}

// 3. Approval gate — update status, poll for resume
if (session.status === "waiting_for_input") {
  await supabase.from("skill_executions").update({ status: "paused", gate_type: "deploy_plan" }).eq("id", executionId);
  await channel.send({ type: "broadcast", event: "gate", payload: { gate_type: "deploy_plan", prompt: session.gatePrompt } });

  // Poll for approval (5s interval, 30min timeout)
  const approved = await pollForApproval(supabase, executionId, { intervalMs: 5000, timeoutMs: 1800000 });
  if (!approved) process.exit(1);

  const resumed = await resumeSession({ sessionId: session.id, input: "approve" });
}

// 4. Write results to Supabase
await supabase.from("skill_executions").update({ status: "completed", completed_at: new Date().toISOString() }).eq("id", executionId);
```

> API shape is illustrative — verify against latest SDK docs.

Runtime: Docker on Cloud Run Jobs (Node.js 20+, all CLIs pre-loaded). Scale-to-zero, 24hr max timeout (self-imposed per-skill budget).

### Authentication

| Method | Provider | Notes |
|--------|----------|-------|
| Email + password | Supabase Auth | TOTP 2FA required |
| Google OAuth | Supabase Auth | `openid email profile` |
| GitHub OAuth | Supabase Auth | Standard |

Login OAuth (Supabase Auth) is independent from API OAuth (Google/Meta Ads). API tokens encrypted via Supabase Vault in `oauth_tokens` table.

### Distribution Adapter Architecture

```
                         /distribute skill
                               |
                    +-----------+-----------+
                    |     Adapter Interface  |
                    |  publish() measure()   |
                    |  manage()              |
                    +-----------+-----------+
                               |
          +--------+--------+--+--+--------+--------+
          |        |        |     |        |        |
   twitter-  reddit-  email-  google-  meta-   twitter-
   organic   organic  resend  ads      ads     ads
     (free)   (free)  (free)  (paid)   (paid)  (paid)
```

**6 adapters, 2 tiers:**

| Adapter | Tier | Channel Type | API | Status |
|---------|------|-------------|-----|--------|
| `twitter-organic` | Free | Social post | X API v2 | Phase 1 |
| `reddit-organic` | Free | Community post | Reddit API | Phase 1 |
| `email-resend` | Free | Email campaign | Resend API | Phase 1 |
| `google-ads` | Paid | Search ads | Google Ads API | Phase 1 |
| `meta-ads` | Paid | Social ads | Meta Marketing API | Phase 1 |
| `twitter-ads` | Paid | Social ads | X Ads API | Phase 1 |

**Adapter interface:**

```typescript
interface DistributionAdapter {
  // Create campaign/post on the platform
  publish(config: AdsYaml, credentials: OAuthTokens): Promise<{ campaign_id: string; campaign_url: string }>;
  // Fetch latest metrics from the platform
  measure(campaign_id: string, credentials: OAuthTokens): Promise<DistributionMetrics>;
  // Pause, resume, or update a campaign
  manage(campaign_id: string, action: 'pause' | 'resume' | 'update', credentials: OAuthTokens): Promise<void>;
}
```

Each adapter's stack file (`.claude/stacks/distribution/<adapter>.md`) defines format constraints, targeting model, policy restrictions, config schema, and API procedures.

**MCC / Partner billing model (paid ads):**

Assayer creates a sub-account under its MCC (Manager Client Center), user provides their own billing. Assayer manages campaigns programmatically; the user's credit card is charged directly by the ad platform.

- **Google Ads**: MCC creates child customer account → user links payment method
- **Meta Ads**: Business Manager creates ad account → user adds payment method
- **Twitter Ads**: user's own ads account → Assayer accesses via OAuth

### Distribution Plan Generator

The Distribution Plan Generator produces a recommended multi-channel distribution
strategy for Phase F (Distribution Approval Gate). It runs when a user clicks
"Continue to Distribution" after Content Check / Walkthrough.

**API Route:**

```
POST /api/experiments/:id/distribution/plan
  - Generates a recommended distribution plan for the experiment
  - Inputs: experiment level, type, target_user, description, thesis, user plan tier, connected channels
  - Output: DistributionPlan (see schema below)
  - Auth: required
```

```typescript
interface DistributionPlan {
  experiment_id: string;
  recommended_channels: Array<{
    channel: string;              // adapter name (e.g., 'google-ads', 'twitter-organic')
    budget_cents: number;         // recommended budget for this channel
    allocation_pct: number;       // percentage of total budget
    rationale: string;            // one-line explanation
    tier: 'organic' | 'paid';
    available: boolean;           // false if not connected or plan doesn't allow
    requires_plan?: string;       // 'pro' | 'team' if plan-gated
  }>;
  total_budget_cents: number;
  duration_days: number;          // from experiment config or default 14
  creative: Array<{
    channel: string;
    headlines: string[];
    descriptions: string[];
    preview_text: string;         // rendered preview for the channel
  }>;
  reasoning: string;              // explanation of budget/channel choices
}
```

**Budget Recommendation Algorithm:**

1. Determine budget range from experiment level:
   - L1 (Pitch):    5000-20000 cents ($50-200) — minimal viable signal
   - L2 (Prototype): 20000-50000 cents ($200-500) — funnel validation
   - L3 (Product):  50000-200000 cents ($500-2000) — scale verification
   Default to midpoint of range. User can adjust in Phase F [Edit Plan].

2. Determine channel priority from experiment type + target_user:
   - B2B SaaS:      Google Ads (40%) + Email (25%) + Twitter organic (20%) + Reddit organic (15%)
   - Consumer App:  Meta Ads (35%) + Twitter Ads (20%) + Reddit organic (25%) + Email (20%)
   - Developer Tool: Reddit organic (35%) + Twitter organic (30%) + Google Ads (20%) + Email (15%)
   - Default:       Google Ads (40%) + Meta Ads (30%) + Twitter Ads (15%) + Organic (15%)

3. Filter by plan tier:
   - Free/PAYG: remove all paid channels, redistribute to organic channels
   - Pro/Team: all channels available

4. Filter by connected channels:
   - Only include channels where user has valid oauth_tokens
   - Unconnected channels appear as available: false with connect prompt

5. Generate creative per channel:
   - Use experiment name, description, thesis, and variants to generate
     ad copy / tweet thread / Reddit post matching each channel's format constraints
   - Follow message match rules (ad headlines derived from landing page headline)

**Phase-Gated Budget Progression:**

When an experiment completes an /iterate cycle:
  - If verdict = SCALE and current phase = 1 → suggest Phase 2 budget (2x-3x increase)
  - If verdict = SCALE and current phase = 2 → suggest Phase 3 budget
  - If verdict = REFINE → maintain current budget, optimize channel mix
  - If verdict = KILL/PIVOT → suggest stopping spend

This progression is surfaced through the AI Insight card (Portfolio Intelligence)
for users with multiple experiments, or via notification for single-experiment users.

**Metrics sync:**

A 15-minute Vercel Cron syncs all active `distribution_campaigns` rows:
1. Query each campaign's platform API via the adapter's `measure()` method
2. Upsert metrics (impressions, clicks, spend, conversions) into `distribution_campaigns`
3. Aggregate into `experiment_metric_snapshots` for scorecard consumption
4. Check alert conditions (budget exhausted, metrics stale, dimension dropping)
5. `POST /api/experiments/:id/distribution/sync` forces an immediate sync (bypasses 15min cache)

### Cost Model

**Per-Operation Cost (All Opus 4.6 + Prompt Caching)**

| Operation | Turns | P50 Cost | P75 Cost | Price | P50 Margin |
|-----------|-------|----------|----------|-------|-----------|
| Create L1 | ~35 | $5.65 | $7.00 | $10 | 43% |
| Create L2 | ~45 | $9.22 | $11.50 | $15 | 38% |
| Create L3 | ~60 | $15.81 | $19.00 | $25 | 37% |
| Change | ~25 | $3.69 | $5.50 | $6 | 38% |
| Small fix | ~10 | $1.12 | $1.50 | $2 | 44% |
| Spec gen | ~15 | $2.50 | $3.50 | Free | -- |
| Auto-fix | ~20 | $2.82 | $4.00 | Free | -- |
| Classifier | 1 | $0.006 | $0.006 | Free | -- |

Compute cost is negligible (~$0.003/execution, Cloud Run Jobs scale-to-zero) — AI tokens dominate.

Anonymous spec generation (~$2.50/call, P50) is rate-limited to 3 per session token per 24h. Free accounts: unlimited (no monthly quota), rate-limited to 5 per account per 24h.

**Token Budget Hard Limits:**

| Operation | Input Budget | ≈ Cost Cap | Exceeded → |
|-----------|-------------|-----------|-----------|
| Create L1 | 6M tokens | ~$9 | "Continue for $10?" |
| Create L2 | 10M tokens | ~$14 | "Continue for $15?" |
| Create L3 | 16M tokens | ~$22 | "Continue for $15?" |
| Change | 5M tokens | ~$7 | "Continue for $6?" |
| Small fix | 1.5M tokens | ~$2.50 | "Upgrade to Change ($6)?" |

**Caching Math:**

Opus 4.6: $5/MTok input, $25/MTok output, $0.50/MTok cache read, $6.25/MTok cache write.

Agentic sessions resend system prompt + accumulated context each turn. With prompt caching:
- System prompt (~20K tokens): cache WRITE on turn 1, cache READ on turns 2..T
- Conversation prefix: cache READ (same prefix as previous turn)
- New content per turn (~6-8K): cache WRITE
- Result: 70-80% of input tokens are cache reads at 10% of base price

**Subscription Unit Economics:**

| Scenario | COGS | Revenue | Margin |
|----------|------|---------|--------|
| Normal Pro (3 creates, 8 changes, 4 fixes) | $61.66 | $99 | 38% |
| Heavy Pro (3 creates, 10 changes, 5 fixes) | $84.46 | $99 | 15% |
| Extreme Pro (3+2 creates, 15 changes, 8 fixes) | $131.10 | $165 (w/ overage) | 21% |

**Hosting Cost:**

Fixed infrastructure: Vercel Pro $20/mo + Supabase Pro $25/mo + domain ~$1/mo = $46/mo.
Per-experiment marginal cost: $0.10-$2.00/mo (traffic-dependent).
At $5/mo/experiment, hosting is 60-98% margin. Break-even: 10 paid experiments.

**Portfolio Intelligence Billing:**

| Feature | Cost | Billing |
|---------|------|---------|
| Assayer Score computation | Free (server-side, no AI cost) | Computed for all users |
| AI Insight generation | ~$0.05 per generation (Sonnet, ~2K tokens) | Included in platform cost |
| Auto-rebalance computation | Free (server-side math, no AI cost) | Server-side only |
| Insight applies (ad platform changes) | No additional charge | Already covered by experiment hosting |

**Plan gating:**

| Plan | Features |
|------|----------|
| Free/PAYG | Assayer Score visible on Lab cards (computed for all) |
| Pro | + AI Insight card + [Apply suggestions] + Portfolio Notification |
| Team | + Budget tab + Custom allocation sliders + Auto-rebalance toggle |

### Billing & Metering Architecture

#### System Components

```
User action (Create/Change/Fix)
  │
  ▼
Operation Classifier (Haiku, ~$0.001)
  │ → { type: change | small_fix, price }
  ▼
Billing Gate (/api/operations/authorize)
  │ → Check: subscription pool remaining? OR PAYG balance sufficient?
  │ → Create operation_ledger row (status: authorized)
  ▼
Skill Execution (Cloud Run Jobs, Opus 4.6)
  │ → Token budget enforced at AI client level
  │ → ai_usage rows linked to operation_ledger
  ▼
Completion Handler (/api/operations/complete)
  │ → Update operation_ledger (actual cost, status)
  │ → Subscriber: decrement pool counter
  │ → PAYG: deduct from prepaid balance
  ▼
Internal Cost Monitoring
  → PostHog server event: skill_cost { billed, actual_cost, margin_pct }
```

#### Stripe Integration Model

- **Subscriptions** (Pro/Team): Stripe Subscription with recurring Price objects
- **PAYG**: Prepaid credit balance (user tops up via Stripe Checkout one-time payment)
- **Overage** (subscriber exceeds pool): Same as PAYG — deducts from prepaid balance or triggers top-up prompt
- **No Stripe Meters needed** for MVP — prepaid balance is simpler than post-paid metering
- **Customer Portal**: Stripe-hosted portal for subscription management, invoices, payment method

#### Token Budget Enforcement

- Budget set per operation type on the `operation_ledger` row at authorization time
- AI client (`src/lib/ai.ts`) checks cumulative tokens against budget before each API call
- Soft limit (warning logged, continues): 80% of budget
- Hard limit (graceful stop): 100% of budget → user offered "Continue for $X?"
- Partial results preserved — skill checkpoints before budget exhaustion

#### Operation Classifier

- Model: Haiku 4.5 ($1/$5 per MTok) — single API call, ~3K tokens, ~$0.006
- Input: skill name + user's natural language description + affected behaviors from spec
- Output: `{ type: "change" | "small_fix", confidence, reasoning }`
- Fallback: confidence < 0.7 → default to "change" (higher price, protects margin)
- Not needed for creates (level known) or spec gen (always free)

#### Cost Monitoring (Internal)

Weekly automated check:

| Metric | Yellow | Red | Action |
|--------|--------|-----|--------|
| Blended margin | <20% | <10% | Review pricing |
| Single operation type margin | <10% | <0% | Adjust price or optimize prompt |
| Hard limit hit rate | >3% | >5% | Optimize skill efficiency |
| Auto-fix rate | >10% | >20% | Improve /bootstrap quality |

---

## 3. User Journey & Data Flows

The user journey follows the UX design's emotional arc: Curiosity → Awe → Investment → Confidence → Trust → Anticipation → Control → Clarity → Action. Each phase maps to a specific data flow. The Confidence phase (Quality Gate + Walkthrough, L2/L3 only) ensures users never spend ad budget on broken experiments.

### Flow 1: Idea → Spec (anonymous, no auth)

The landing page presents one input field. Clicking "Test it" starts an SSE stream — the Assay page fills in progressively as AI generates.

```
Browser                    Vercel API                  Anthropic
  │                            │                           │
  │ POST /api/spec/stream      │                           │
  │ {idea, level, session_token,│                          │
  │  regenerate_token?}         │                          │
  │ ─────────────────────────> │                           │
  │                            │ Rate-limit check:         │
  │                            │ anonymous_specs count     │
  │                            │ for session_token < 3/24h │
  │                            │                           │
  │                            │ Call Claude (structured   │
  │                            │ output, streaming)        │
  │                            │ ─────────────────────────>│
  │                            │                           │
  │  SSE: {type:"preflight",   │ <── stream chunk          │
  │        dim:"market",       │                           │
  │        status:"pass"}      │                           │
  │ <────────────────────────  │                           │
  │  [frontend: market ✓]      │                           │
  │                            │                           │
  │  SSE: {type:"hypothesis",  │ <── stream chunk          │
  │        id:"h-01", ...}     │                           │
  │ <────────────────────────  │                           │
  │  [frontend: card fades in] │                           │
  │                            │                           │
  │  SSE: {type:"variant",     │ <── stream chunk          │
  │        slug:"time-saver"}  │                           │
  │ <────────────────────────  │                           │
  │                            │                           │
  │  SSE: {type:"complete",    │                           │
  │        spec: {...}}        │                           │
  │ <────────────────────────  │                           │
  │                            │ Upsert anonymous_specs    │
  │                            │  with full spec_data      │
```

**Request body:** `{ idea: string, level?: 1|2|3, session_token: string, regenerate_token?: string }`. When `regenerate_token` is present, the previous `anonymous_specs` row is replaced (skips rate limit count).

**Spec stream protocol** — structured JSON events over SSE:

```typescript
type SpecStreamEvent =
  | { type: 'meta'; name: string; level: number; experiment_type: string }
  | { type: 'cost'; build_cost: number; ad_budget: number; estimated_days: number }
  | { type: 'preflight'; dimension: 'market' | 'problem' | 'competition' | 'icp';
      status: 'pass' | 'caution' | 'fail'; summary: string; confidence: string }
  | { type: 'preflight_opinion'; text: string }
  | { type: 'hypothesis'; id: string; category: string; statement: string;
      metric: { formula: string; threshold: number; operator: 'gt'|'gte'|'lt'|'lte' };
      priority_score: number; experiment_level: number; depends_on: string[] }
  | { type: 'variant'; slug: string; headline: string; subheadline: string;
      cta: string; pain_points: string[]; promise: string; proof: string;
      urgency: string | null }
  | { type: 'funnel'; available_from: Record<string, string> }
  | { type: 'complete'; spec: FullSpecData; anonymous_spec_id: string }
  | { type: 'input_too_vague' }
  | { type: 'error'; message: string };
```

Why SSE over WebSocket: single-direction flow (server → client), natively supported by Next.js Route Handlers, lighter weight than Supabase Realtime for this use case.

Why structured JSON over plain text: frontend needs to know "this is a hypothesis" vs "this is a variant" to render into the correct UI region.

### `>>>EVENT:` Streaming Protocol

Claude generates text with embedded `>>>EVENT:` markers. The Vercel API route parses these markers into structured SSE events.

**Why `>>>EVENT:` text markers over `tool_use`:** tool_use requires round-trip calls (Claude emits tool call → server processes → sends result back → Claude continues). For spec generation, the flow is single-direction — Claude generates everything in one pass. Text markers avoid round-trip overhead and are natively compatible with streaming.

**System prompt output format (injected into Claude's instructions):**

```
You MUST emit structured events as single-line JSON, each prefixed with ">>>EVENT: ".
Between events you may include reasoning text (ignored by the parser).

>>>EVENT: {"type":"meta","name":"ai-invoice-tool","level":1,"experiment_type":"web-app"}

>>>EVENT: {"type":"cost","build_cost":150,"ad_budget":200,"estimated_days":7}

>>>EVENT: {"type":"preflight","dimension":"market","status":"pass","summary":"...","confidence":"high"}

>>>EVENT: {"type":"preflight_opinion","text":"I found 15+ funded competitors..."}

>>>EVENT: {"type":"hypothesis","id":"h-01","category":"reach","statement":"...","metric":{"formula":"cta_click / visit_landing","threshold":0.02,"operator":"gte"},"priority_score":90,"experiment_level":1,"depends_on":[]}

>>>EVENT: {"type":"variant","slug":"time-saver","headline":"...","subheadline":"...","cta":"...","pain_points":["..."],"promise":"...","proof":"...","urgency":null}

>>>EVENT: {"type":"funnel","available_from":{"reach":"L1","demand":"L1","activate":"L2","monetize":"L1","retain":"L3"}}

>>>EVENT: {"type":"complete","spec":{<full experiment.yaml as JSON>},"anonymous_spec_id":"asp_abc123"}
```

**API route parser (`/api/spec/stream`):**

```typescript
// Parse Claude's text stream for >>>EVENT: markers (single-line format)
const lines = buffer.split('\n');
for (const line of lines) {
  if (line.startsWith('>>>EVENT:')) {
    try {
      const jsonStr = line.slice('>>>EVENT:'.length).trim();
      const parsed = JSON.parse(jsonStr);

      if (parsed.type === 'complete') {
        fullSpec = parsed.spec;
      }

      // Send as SSE
      controller.enqueue(
        encoder.encode(`data: ${JSON.stringify(parsed)}\n\n`)
      );
    } catch {
      // JSON parse failed — skip this line
    }
  }
}
```

### Inference-Mode Input Handling

On the web, there are **no follow-up questions**. This follows Axiom A (value before commitment) — asking questions before showing value violates the core UX promise.

Instead, the system prompt instructs Claude to:
1. **Infer aggressively** — fill in missing dimensions (target user, problem, solution shape) from context
2. **Mark inferences** — tag inferred values with `[inferred]` so users can see what was assumed
3. **Never block** — even with minimal input ("uber for dogs"), generate a complete spec

If the input is genuinely too vague to produce meaningful output (e.g., single word with no context), emit `input_too_vague` event. Frontend shows a gentle prompt to add more detail — but this should be rare (<5% of inputs).

### Frontend specReducer

The frontend uses a reducer pattern to accumulate streaming events into progressive UI state:

```typescript
export function specReducer(state: SpecState, event: SpecStreamEvent): SpecState {
  switch (event.type) {
    case 'meta':              return { ...state, meta: event };
    case 'cost':              return { ...state, cost: event };
    case 'preflight':         return { ...state, preflight: [...state.preflight, event] };
    case 'preflight_opinion': return { ...state, preflightOpinion: event.text };
    case 'hypothesis':        return { ...state, hypotheses: [...state.hypotheses, event] };
    case 'variant':           return { ...state, variants: [...state.variants, event] };
    case 'funnel':            return { ...state, funnel: [...state.funnel, event] };
    case 'complete':          return { ...state, status: 'complete', fullSpec: event.spec, anonymousSpecId: event.anonymous_spec_id };
    case 'input_too_vague':   return { ...state, status: 'too_vague' };
    case 'error':             return { ...state, status: 'error', error: event.message };
    default:                  return state;
  }
}
```

Each event type maps to a UI region on the Assay page. Cards fade in as events arrive — the spec materializes in its final form, not behind a loading spinner.

### Data Flow Timeline (~25-30 seconds)

```
 0s   POST /api/spec/stream
 1s   >>>EVENT:meta       → header renders (name, level, type)
 2s   >>>EVENT:cost       → cost badge appears
 3-8s >>>EVENT:preflight  → 4 dimension checks animate (✓/✗/!)
 9s   >>>EVENT:preflight_opinion → AI opinion text fades in
10-18s >>>EVENT:hypothesis → 5-10 hypothesis cards fade in one by one
19-25s >>>EVENT:variant    → 3-5 variant cards with headline/CTA
26-28s >>>EVENT:funnel     → 4 funnel threshold rows
29s   >>>EVENT:complete   → full spec payload, "Create & Launch" activates
```

Progressive rendering means users see value within 3 seconds. By 10s they're reading hypotheses. The wait feels like watching AI work, not waiting for a loading bar.

### Spec Stream Error Handling

| Scenario | Handling |
|----------|---------|
| Claude API timeout | SSE error event → frontend shows "AI analysis timed out. Try again." + [Retry] |
| Claude output format error (unparseable EVENT) | Skip that event, continue processing. If `complete` event arrives → normal finish. If `complete` also missing → error |
| Rate limit (3/24h) | 429 response → frontend shows "Sign up for unlimited specs" + login CTA (this is itself a conversion opportunity) |
| Input too vague | Claude outputs `input_too_vague` event → frontend falls back to Landing page with improvement suggestions |
| Network disconnect | Frontend detects SSE disconnect → shows "Connection lost" + [Retry] (same session_token, does not consume new quota) |
| Supabase write failure | Degrade gracefully: spec not stored server-side, kept in frontend memory only. After login, use frontend data to create experiment |

### Flow 2: Signup Gate → Spec Recovery

When an unauthenticated user clicks "Create & Launch" or edits a field, the signup gate triggers. After auth, the spec is recovered from server-side storage.

```
Browser                    Vercel API                  Supabase
  │                            │                           │
  │ [User clicks edit/launch]  │                           │
  │ → Signup modal appears     │                           │
  │ → User signs up/logs in    │                           │
  │                            │                           │
  │ POST /api/spec/claim       │                           │
  │ {session_token}            │                           │
  │ ─────────────────────────> │                           │
  │                            │ Find anonymous_specs      │
  │                            │ by session_token          │
  │                            │ ──────────────────────>   │
  │                            │                           │
  │                            │ Create experiment +       │
  │                            │ hypotheses + variants     │
  │                            │ from spec_data            │
  │                            │ ──────────────────────>   │
  │                            │                           │
  │                            │ Delete anonymous_specs    │
  │                            │ row                       │
  │                            │ ──────────────────────>   │
  │                            │                           │
  │ 200 {experiment_id}        │                           │
  │ <────────────────────────  │                           │
  │                            │                           │
  │ [Same page, now editable,  │                           │
  │  "Create & Launch" active] │                           │
```

`session_token` is a browser-generated UUID stored in a cookie. Server-side `anonymous_specs` has 24h TTL with hourly cleanup cron. This survives tab refreshes and browser restarts without requiring client-side storage for the expensive AI output.

### Flow 3: Build → Deploy → Distribute (three-phase launch)

Clicking "Create & Launch" triggers a three-phase flow. Each phase uses the skill execution infrastructure.

```
Browser              Vercel API           Cloud Run Job          Supabase
  │                      │                     │                    │
  │ POST /api/skills/    │                     │                    │
  │  execute             │                     │                    │
  │  {skill:"bootstrap"} │                     │                    │
  │ ──────────────────> │                     │                    │
  │                      │ Create             │                    │
  │                      │ skill_executions   │                    │
  │                      │ (status: pending)  │                    │
  │                      │ ──────────────────────────────────────> │
  │                      │                     │                    │
  │                      │ Trigger Cloud Run   │                    │
  │                      │ ──────────────────> │                    │
  │                      │                     │ Agent SDK runs     │
  │                      │                     │ /bootstrap         │
  │                      │                     │                    │
  │ <═══════════════════════════════════════════ Realtime event:    │
  │  [Supabase Realtime:                        {type:"progress",  │
  │   exec:{id} channel]                        pct:30,            │
  │                      │                      preview_url:...}   │
  │  [frontend: variant  │                     │                    │
  │   preview renders]   │                     │                    │
  │                      │                     │                    │
  │ <═══════════════════════════════════════════ {type:"progress",  │
  │                      │                      pct:100,            │
  │  [frontend: "Your    │                      phase:"deployed"}  │
  │   experiment is live"]│                     │                    │
  │                      │                     │ Update experiment  │
  │                      │                     │ status → active    │
  │                      │                     │ ───────────────>   │
  │                      │                     │                    │
  │  [auto-transition to │                     │                    │
  │   Distribution Gate] │                     │                    │
```

**Build preview strategy:**
- During build (before deploy): frontend renders variant data into a local template preview (immediate, approximate)
- After deploy completes: switches to iframe of real `exp-name.assayer.io` (accurate)
- Variant carousel fills the wait — users browse their 3 variants instead of watching logs

**Channel Setup** (first-time only): if user has no connected channels, the Channel Setup screen appears between Deploy and Distribution Approval. Free channels (Twitter, Reddit) recommended first.

**Distribution Approval Gate**: after deploy completes, the distribution plan appears for review. User sees per-channel budget, creative preview (ad copy, tweet thread, Reddit post), and "Google/Meta bill you directly" trust copy. [Launch Distribution] resumes the paused skill execution.

### Flow 4: Metrics Sync + Scorecard + Alerts

A 15-minute Vercel Cron drives the metrics pipeline:

```
Vercel Cron (every 15 minutes)
  │
  │ 1. Query all experiments WHERE status IN ('active', 'verdict_ready')
  │
  │ 2. For each experiment:
  │    ├── PostHog API → behavior metrics (signups, CTA clicks, page views)
  │    ├── Google Ads API → ad metrics (impressions, clicks, spend, CTR)
  │    ├── Meta Ads API → ad metrics
  │    └── Twitter/Reddit → organic metrics (if API available)
  │
  │ 3. Write to experiment_metric_snapshots (time-series)
  │
  │ 4. Compute scorecard ratios:
  │    ├── REACH  = actual_CTR / threshold_CTR → ratio
  │    ├── DEMAND = actual_signup_rate / threshold → ratio
  │    ├── ACTIVATE = actual_activation_rate / threshold → ratio
  │    ├── MONETIZE = actual_pricing_clicks / threshold → ratio
  │    └── RETAIN = actual_return_rate / threshold → ratio
  │
  │ 5. Detect alert conditions:
  │    ├── spend / budget > 0.9 → budget_exhausted alert
  │    ├── dimension ratio declining > 10% → dimension_dropping alert
  │    ├── last_sync > 26h → metrics_stale alert
  │    ├── ad account suspended → ad_account_suspended alert
  │    └── Create experiment_alerts rows (unresolved)
  │
  │ 6. Detect verdict conditions:
  │    ├── Sufficient data + experiment duration reached
  │    ├── Run decision_framework (top-down bottleneck walk)
  │    ├── Write experiment_decisions row
  │    ├── Update experiment status → verdict_ready
  │    └── Trigger verdict_ready notification
  │
  │ 7. Dispatch pending notifications via Resend
```

**Scorecard computation** (per funnel dimension):

| Dimension | Measured via | Source | Available from |
|-----------|-------------|--------|---------------|
| **REACH** | Ad CTR, impressions, CPC | Distribution campaigns + PostHog | L1+ |
| **DEMAND** | CTA rate, signup rate, engagement | PostHog | L1+ |
| **ACTIVATE** | Activation rate, time-to-value | PostHog | L2+ |
| **MONETIZE** | Pricing interaction, payment intent | PostHog | L1+ (signal), L2+ (functional) |
| **RETAIN** | Return visits, repeat usage, churn | PostHog | L3+ |

**Confidence bands**: <30 events `insufficient`, 30-100 `directional`, 100-500 `reliable`, 500+ `high`.

### Assayer Score (Portfolio Ranking)

Assayer Score is a composite 0-100 score per experiment that enables cross-experiment ranking.
Computed every 15 minutes by the metrics cron. NULL when no iterate data exists.

**Formula:**

```
raw = (Signal × Confidence × Efficiency) / Risk
assayer_score = min(round(raw), 100)
```

**Components:**

**Signal (0-100):**

```
0.30 × reach_score + 0.30 × demand_score + 0.20 × monetize_score + 0.10 × retain_score + 0.10 × growth_score

Each dimension_score = min(actual / threshold, 1.0) × 100
Source: experiment_metric_snapshots (latest) mapped to funnel dimensions
If dimension not available at current level, excluded and weights renormalized
```

**Confidence (0-1):**

```
sample_factor × freshness_factor

sample_factor: <30 visits → 0.3, 30-100 → 0.6, 100-500 → 0.8, 500+ → 1.0
freshness_factor: <3 days → 1.0, 3-7 → 0.9, 7-14 → 0.7, >14 → 0.5
```

**Efficiency (0-10):**

```
If activations > 0: 1 / max(CAC / benchmark_CAC, 0.1)
If activations == 0: 0.1
CAC = budget_spent / activations
benchmark_CAC: $100 (configurable per experiment_type)
```

**Risk (0.1-1.0):**

```
max((estimated_remaining_cost - budget_spent) / max_budget, 0.1)
max_budget: $500 (from distribution config)
estimated_remaining_cost: derived from level ($500 for L1, $1000 for L2, $2000 for L3)
```

**Score-to-status mapping** (used in Lab cards):

| Score | Status |
|-------|--------|
| 80-100 | ON TRACK |
| 60-79 | PROMISING |
| 40-59 | LOW ! |
| 20-39 | DANGER |
| 0-19 | CRITICAL |

**Auto-rebalance note:** The daily auto-rebalance cron runs Thompson Sampling across experiments, generates a recommended allocation, and applies it ONLY if the user has enabled auto-rebalance in Settings. Otherwise, it writes to `portfolio_insights` as a recommendation.

### Flow 5: Verdict → Return Flows

When metrics sync detects verdict conditions (or user clicks "Analyze Now"), the decision framework runs:

| Condition | Decision |
|-----------|----------|
**Guard clause (no verdict issued):**
- Total clicks < 100
- Experiment duration < 50% of estimated_days
- When guard triggers on user "Analyze Now": show inline directional signal, not a verdict page

| Condition | Decision |
|-----------|----------|
| All tested dimensions >= 1.0 | SCALE |
| Any top-funnel (REACH or DEMAND) < 0.5 | KILL |
| 2+ dimensions < 0.8 | PIVOT |
| 1+ dimensions < 1.0 but fewer than 2 below 0.8 | REFINE |

**Two-tier verdict:** Tier 1 is a guard clause — if insufficient data (<100 clicks or <50% experiment duration), return null (no verdict yet). Tier 2 uses per-dimension ratio analysis: SCALE / KILL / PIVOT / REFINE based on failure pattern.

**Dependency-aware verdicts:** Per-hypothesis verdicts respect `depends_on[]` — if a parent hypothesis is REJECTED, dependent hypotheses are marked BLOCKED.

**REFINE return flow:**

```
Verdict Page [Apply Changes & Re-test]
  │
  ├── Create experiment_rounds (round_number = N+1)
  │   ├── spec_snapshot = frozen spec from Round N
  │   ├── parent_round_id = Round N ID
  │   └── ai_fix_suggestion = AI's fix for bottleneck
  │
  ├── Update experiment status → draft
  │
  └── Redirect to /assay?experiment={experiment_id}&round=N+1&mode=edit
      ├── Frontend highlights bottleneck dimension
      ├── AI fix pre-filled into corresponding hypothesis
      └── "Create & Launch" starts new round
```

**PIVOT return flow:**

```
Verdict Page [Start New Experiment with Pivot]
  │
  ├── Current experiment → status = archived, decision = pivot
  │
  ├── Create new experiment
  │   ├── parent_experiment_id = original experiment ID
  │   └── idea_text = AI-suggested pivot direction
  │
  └── Redirect to / (Landing, idea pre-filled with pivot context)
```

**UPGRADE return flow (SCALE/REFINE verdict):**

```
Verdict Page [Upgrade to L2]  (only shown when experiment_level < 3)
  │
  ├── Navigate to /assay?idea={idea_text}&type={type}&level={level+1}&upgrade_from={experiment_id}
  │
  ├── Assay page detects upgrade_from param
  │   └── Shows "Upgrading from L{level}" indicator
  │
  ├── User reviews L2 spec → [Create & Launch]
  │
  ├── POST /api/spec/claim { session_token, upgrade_from }
  │   ├── Create new experiment with parent_experiment_id = upgrade_from
  │   └── Original experiment status → completed (graduated)
  │
  └── Redirect to /launch/{new_experiment_id}
```

**Lab shows lineage:** Round 1 → Round 2 (REFINE), Original → Pivot (PIVOT), L1 → L2 (UPGRADE). Users can trace the full decision trail.

### Distribution ROI

Distribution ROI is computed during the verdict process and displayed on the verdict page.
It answers: "Was the ad spend worth it?"

**Computation** (runs as part of verdict generation in metrics cron):

```
total_spend_cents = SUM(distribution_campaigns.spend_cents) for this experiment
total_clicks = SUM(distribution_campaigns.clicks) for this experiment
cpc_cents = total_spend_cents / max(total_clicks, 1)
total_activations = COUNT(activate events from PostHog) for this experiment
cpa_cents = total_spend_cents / max(total_activations, 1)
signal_ratio = weighted average of all dimension ratios (same weights as Assayer Score Signal)
roi_display = "{$spent} spent . {clicks} clicks . {$cpc}/click -> {activations} activations . {$cpa}/activation . {signal_ratio}x signal"
```

**Storage:**

Written to `experiment_decisions.distribution_roi` (jsonb):

```json
{
  "total_spend_cents": 4700,
  "total_clicks": 502,
  "cpc_cents": 9,
  "total_activations": 8,
  "cpa_cents": 588,
  "signal_ratio": 3.2,
  "display": "$47 spent . 502 clicks . $0.09/click -> 8 activations . $5.88/activation . 3.2x signal",
  "best_channel": "google-ads",
  "best_channel_cpa_cents": 425,
  "channel_breakdown": [
    { "channel": "google-ads", "spend_cents": 3200, "clicks": 350, "cpc_cents": 9, "activations": 6, "cpa_cents": 533 },
    { "channel": "meta-ads", "spend_cents": 1500, "clicks": 152, "cpc_cents": 10, "activations": 2, "cpa_cents": 750 }
  ]
}
```

**When displayed on verdict page:**

- SCALE verdict: "$200 spent . 502 clicks . $0.40/click -> 8 activations . 3.2x signal — Google Ads worked, Meta didn't"
- KILL verdict: "$420 spent . 34 clicks . $12.35/click -> 0 activations. You saved ~3 months of building."
- Show channel breakdown table: Channel | Spend | Activations | CPA
- Highlight best-performing channel

---

## 4. Skills

### 10 Experiment Skills

| # | Skill | Transition | Status |
|---|-------|-----------|--------|
| 1 | `/spec` | Idea + level → experiment.yaml | **New** |
| 2 | `/bootstrap` | experiment.yaml → code | Existing |
| 3 | `/change` | Modify code | Existing |
| 4 | `/verify` | Build + test gate | Existing |
| 5 | `/deploy` | Code → live URL | Existing |
| 6 | `/distribute` | Live → traffic (ad copy, UTM, budget) | **Enhanced** |
| 7 | `/iterate` | Data → scorecard + per-hypothesis verdicts | **Enhanced** |
| 8 | `/teardown` | Remove infra + archive | **Enhanced** |
| 9 | `/harden` | MVP → production quality | Existing |
| 10 | `/retro` | End-of-experiment feedback | Existing |

Supporting (unchanged): `/review`, `/rollback`

### Flow

```
/spec → /bootstrap → /verify → /deploy → /distribute
                                               |
                                          traffic flows
                                               |
                                           /iterate
                                          /    |    \
                                       SCALE REFINE  KILL
                                         |     |      |
                                    (graduate) |      /teardown
                                               |
                                      +--------+--------+
                                      | Same level:     |
                                      |  /change        |
                                      |  → /distribute  |
                                      |                 |
                                      | Upgrade level:  |
                                      |  /spec (L+1)    |
                                      |  → /bootstrap   |
                                      |  → /deploy      |
                                      +-----------------+
                      PIVOT = KILL current + new /spec
```

### `/spec` — Idea + Level → experiment.yaml

**Model:** Opus | **Input:** `{ idea: string, level?: 1|2|3 }` | **Output:** `experiment/experiment.yaml`

**experiment.yaml schema** (7 sections):

```yaml
# 1. Identity
name: ai-invoice-tool                    # kebab-case
type: web-app                            # web-app | service | cli
level: 1                                 # 1 (Pitch), 2 (Prototype), 3 (Product)
status: draft
# quality: production                    # Build config — toggles TDD, implementer, spec review

# 2. Intent
description: |                           # 2-3 sentences for landing page copy
  Freelancers waste hours on manual invoicing. An AI tool that generates
  professional invoices from time logs in under 60 seconds.
thesis: "Freelancers want AI-generated invoices"
target_user: "Solo freelancers, US/EU"
distribution: "Google Ads targeting freelancer invoice keywords"
hypotheses:                               # inline, not in separate manifest
  - id: h-01
    category: demand
    statement: "Freelancers actively search for AI invoice tools"
    metric:
      formula: "signup_complete / visit_landing"
      threshold: 0.05
      operator: gte
    priority_score: 90                   # 0-100
    experiment_level: 1
    depends_on: []
  # ... 5-10 hypotheses

# 3. Behaviors (unified: user + system actors)
behaviors:
  - id: b-01
    given: "A freelancer lands on the pitch page"
    when: "They read the headline and subheadline"
    then: "They understand the value proposition within 5 seconds"
    tests:
      - "Landing page renders without errors"
      - "Headline matches active variant"
    hypothesis_id: h-01
    level: 1
  # System behavior
  - id: b-05
    actor: system                         # system | cron (default: user)
    trigger: "stripe webhook checkout.session.completed"
    given: "A Stripe checkout session completes"
    when: "Webhook is received"
    then: "Invoice marked paid, freelancer notified"
    tests:
      - "invoices table has status='paid'"
    hypothesis_id: h-03
    level: 3

# 4. Journey
golden_path:
  - step: "Visit landing page"
    event: visit_landing
    page: landing
  - step: "Click CTA"
    event: cta_click
    page: landing
  - step: "Complete signup"
    event: signup_complete
    page: landing
target_clicks: 3

# 5. Variants (3-5 A/B messaging angles)
variants:
  - slug: time-saver
    headline: "Save 5 Hours Every Week on Invoicing"
    subheadline: "AI generates professional invoices from your time tracking data"
    cta: "Start Free Trial"
    pain_points: ["Manual invoicing wastes hours", "Formatting inconsistencies"]
    promise: "Professional invoices in seconds"
    proof: "Used by 500+ freelancers"
    urgency: null

# 6. Funnel
# Dimension thresholds are derived from the highest-priority hypothesis per category.
funnel:
  available_from:
    reach: L1
    demand: L1
    activate: L2
    monetize: L1
    retain: L3
  decision_framework:
    scale: "All tested dimensions >= 1.0"
    kill: "Any top-funnel (REACH or DEMAND) < 0.5"
    pivot: "2+ dimensions < 0.8"
    refine: "1+ dimensions < 1.0 but fewer than 2 below 0.8"

# 7. Stack + Deploy
services:
  - name: app
    runtime: nextjs                      # always Next.js for validation
    hosting: vercel                      # or railway (long-running, real-time)
    ui: shadcn
    testing: playwright
database: supabase                       # L2+ (shared across services)
auth: supabase                           # L3 (shared)
# auth_providers: [google]               # OAuth providers
analytics: posthog                       # shared
# payment: stripe                        # L3 if monetize
deploy:
  url: null
  repo: null
```

**`/spec` phases:**

1. **Parse** — idea text + level (default 1). Validate >= 20 chars.
2. **Input sufficiency** — Assess 3 dimensions (target user, problem, solution shape). Each: present / inferable / missing.
   - **CLI mode:** All present → zero delay. 1 missing → one follow-up round with "proceed" escape. 2-3 missing → ask user to elaborate.
   - **Web mode (inference):** Never ask follow-up questions. Infer all missing dimensions aggressively, marking inferred values with `[inferred]`. If genuinely too vague (<5% of inputs), emit `input_too_vague` event.
3. **Pre-flight research** — 4 dimensions: market, problem, competition, ICP. Verdict per dimension (pass/caution/fail). On 2+ failures: emit `preflight_opinion` with strong caution, then continue generating full spec. The spec always completes — Assayer is a consultant, not a gatekeeper. CLI mode: STOP point shows caution + "Continue? [Y/n]" (default Y). Web mode: caution appears inline as the spec materializes.
4. **Hypotheses** — 5-10 across demand/reach/activate/monetize/retain. Filter by level. Priority 0-100. L1: reach+demand+monetize(signal) required. L2: +monetize(functional). L3: +retain. Pre-flight research-type activate hypotheses are still resolved at spec time.
5. **Behaviors** — given/when/then + `tests[]` array. User behaviors default. System behaviors: `actor: system` + `trigger` field.
6. **Variants** — 3-5 angles, >30% headline word difference. L3 + monetize: add `pricing_amount`, `pricing_model`.
7. **Stack/funnel** — Stack from level (Section 1 table). Hosting from type + behavior analysis. Funnel thresholds from highest-priority hypothesis per dimension.

**Manifest:** `.runs/spec-manifest.json` with research, hypotheses. For `/iterate`. Not user-facing.

### `/iterate` — Scorecard + Per-Hypothesis Verdicts

Per hypothesis: parse `metric.formula`, compute from event counts, compare with `metric.threshold` using `metric.operator`.
Verdict: CONFIRMED / REJECTED / INCONCLUSIVE.

**Funnel stage mapping:** Each event in experiment/EVENTS.yaml has a `funnel_stage` tag (reach, demand, activate, monetize, retain) that directly maps it to the corresponding validation dimension. No separate mapping table is needed — the dimension is explicit on each event definition.

---

## 5. API & Data Flow

### Routes

```
# Anonymous spec generation (no auth required)
POST   /api/spec/stream                      — SSE stream, anonymous spec generation
POST   /api/spec/claim                       — claim anonymous spec after signup

# Experiments (auth required)
GET    /api/experiments                      — list (paginated, grouped by status)
GET    /api/experiments/:id                  — get single (includes latest round data)
POST   /api/experiments                      — create (from claimed spec)
PATCH  /api/experiments/:id                  — update status/url/decision
DELETE /api/experiments/:id                  — soft delete (archived_at)

# Experiment sub-resources
POST   /api/experiments/:id/hypotheses       — store (mode: append|replace)
GET    /api/experiments/:id/hypotheses       — list
POST   /api/experiments/:id/variants          — store variants
GET    /api/experiments/:id/variants          — list variants
POST   /api/experiments/:id/insights         — store scorecard + decision
GET    /api/experiments/:id/insights         — list history
POST   /api/experiments/:id/research         — store research results
GET    /api/experiments/:id/research         — list

# Rounds (multi-round experiments)
GET    /api/experiments/:id/rounds           — list all rounds
POST   /api/experiments/:id/rounds           — create new round (REFINE flow)

# Metrics
POST   /api/experiments/:id/metrics/sync     — force sync from PostHog + ad platforms
                                              ?force_verdict=true triggers verdict engine ("Analyze Now")
GET    /api/experiments/:id/metrics          — cached scorecard + per-channel metrics
GET    /api/experiments/:id/metrics/export   — export metric snapshots as CSV (Post-Mortem download)

# Skill execution
POST   /api/skills/execute                   — trigger skill on Cloud Run Jobs
GET    /api/skills/:id                       — execution status + events
POST   /api/skills/:id/approve               — approve gate (resume job)
POST   /api/skills/:id/cancel                — cancel running execution

# Distribution
GET    /api/experiments/:id/distribution        — list distribution campaigns
POST   /api/experiments/:id/distribution/plan   — generate recommended distribution plan
POST   /api/experiments/:id/distribution/sync   — force sync metrics from ad platform
POST   /api/experiments/:id/distribution/manage — pause/resume/adjust campaigns

# Alerts
GET    /api/experiments/:id/alerts           — list unresolved alerts
PATCH  /api/experiments/:id/alerts/:alertId  — resolve/dismiss alert

# Comparison
GET    /api/experiments/compare              — side-by-side scorecard for multiple experiments (requires: pro+)
                                              (?ids=uuid1,uuid2,uuid3)

# Billing & Operations (auth required)
POST   /api/operations/authorize             — classify + quota check + authorize
POST   /api/operations/complete              — finalize billing after skill execution
POST   /api/operations/:id/extend            — extend budget-exceeded operation (new charge + resume)
GET    /api/billing/usage                    — current period usage summary
POST   /api/billing/subscribe               — create Stripe subscription checkout
POST   /api/billing/topup                    — create PAYG top-up checkout ($10-$500)
POST   /api/billing/portal                   — create Stripe Customer Portal session

# Notifications
GET    /api/notifications                    — list user's notifications (paginated)
PATCH  /api/notifications/:id               — mark as read
POST   /api/notifications/mark-all-read     — batch mark all unread as read

# Webhooks
POST   /api/webhooks/stripe                  — 5 event types:
                                               checkout.session.completed (topup OR subscription)
                                               customer.subscription.created
                                               customer.subscription.updated (pool reset on cycle change)
                                               customer.subscription.deleted
                                               invoice.payment_failed
```

### Portfolio Intelligence API

```
POST /api/portfolio/compute-scores
  - Triggered by 15-minute cron
  - Computes Assayer Score for all active experiments for all users
  - Updates experiments.assayer_score and experiments.score_updated_at
  - No auth required (cron-only, protected by cron secret)

GET /api/portfolio/insight
  - Returns the latest non-dismissed portfolio_insight for the authenticated user
  - Returns null if user has < 2 running experiments
  - Auth: required

POST /api/portfolio/insight/generate
  - Triggered by daily cron
  - For each user with 2+ running experiments where at least one has 30+ visits: calls Anthropic API (Sonnet) to generate insight
  - Writes to portfolio_insights table
  - No auth required (cron-only)

POST /api/portfolio/insight/:id/apply
  - Marks insight as applied
  - Executes each recommendation:
    - type='kill': sets experiment status to 'completed', decision to 'kill'
    - type='scale': updates experiment budget via distribution adapter
    - type='rebalance': creates budget_allocation record, updates experiment budgets
  - Auth: required, Pro+ plan

POST /api/portfolio/insight/:id/dismiss
  - Marks insight as dismissed (dismissed_at = now)
  - Auth: required

GET /api/portfolio/budget
  - Returns current budget allocation across all running experiments
  - Auth: required, Team plan

POST /api/portfolio/budget/allocate
  - Applies a custom budget allocation
  - Validates: all percentages sum to 100, all experiment_ids belong to user, all experiments are running
  - Writes to budget_allocations table
  - Updates each experiment's budget via distribution adapter
  - Auth: required, Team plan
```

> Distribution campaigns are created by the `/distribute` skill (via `POST /api/skills/execute`), not via a dedicated creation route. The skill handles channel selection, creative generation, approval gates, and API campaign creation end-to-end.

Pagination: `?page=1&limit=20` (max 100). Sub-resource POST: `mode=append` (default) or `mode=replace`.

### Error Schema

```json
{ "error": { "code": "validation_error", "message": "...", "details": {} } }
```

Codes: `validation_error`, `not_found`, `unauthorized`, `rate_limited`, `ai_error`, `internal_error`.

### Skill Execution Flow

```
Web UI → POST /api/skills/execute
  → Create skill_executions row (status: pending)
  → Cloud Run Jobs API (trigger with env overrides)
  → Container starts (status: running)
    → Events → Supabase Realtime (exec:{id})
    → Gate? → status: paused → poll Supabase for approval
    → User approves → status: running → resumes → completes
  → Results → Supabase tables
  → Container destroyed
```

---

## 6. Data Model

```sql
-- Anonymous specs (temporary, TTL 24h)
CREATE TABLE anonymous_specs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_token text NOT NULL UNIQUE,
  spec_data jsonb NOT NULL,
  preflight_results jsonb,
  idea_text text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL DEFAULT now() + interval '24 hours'
);

CREATE INDEX idx_anonymous_specs_session ON anonymous_specs(session_token);
CREATE INDEX idx_anonymous_specs_expires ON anonymous_specs(expires_at);

-- Experiments
CREATE TABLE experiments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id),
  name text NOT NULL,
  experiment_type text NOT NULL DEFAULT 'web-app'
    CHECK (experiment_type IN ('web-app', 'service', 'cli')),
  idea_text text NOT NULL,
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'active', 'paused', 'verdict_ready', 'completed', 'archived')),
  experiment_level integer CHECK (experiment_level IN (1, 2, 3)),
  current_round integer NOT NULL DEFAULT 1,
  stimulus_format text,
  estimated_days integer DEFAULT 0,
  recommended_ad_budget numeric DEFAULT 0,
  variable_being_tested text,
  budget numeric DEFAULT 0,
  budget_spent numeric DEFAULT 0,
  started_at timestamptz,
  ended_at timestamptz,
  decision text CHECK (decision IN ('scale', 'refine', 'pivot', 'kill')),
  decision_reasoning text,
  parent_experiment_id uuid REFERENCES experiments(id),
  deployed_url text,
  repo_url text,
  vercel_project_id text,
  archived_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  -- Portfolio Intelligence: Assayer Score (computed, cached)
  assayer_score integer CHECK (assayer_score BETWEEN 0 AND 100),
  score_updated_at timestamptz
);

-- Score is recomputed by the 15-minute metrics cron. Range 0-100.
-- NULL means no data yet (experiment has no iterate-manifest).

CREATE INDEX idx_experiments_user_id ON experiments(user_id);
CREATE INDEX idx_experiments_status ON experiments(status) WHERE archived_at IS NULL;

ALTER TABLE experiments ENABLE ROW LEVEL SECURITY;
CREATE POLICY experiments_user_isolation ON experiments
  FOR ALL USING (auth.uid() = user_id);

-- Experiment rounds (multi-round REFINE support)
CREATE TABLE experiment_rounds (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  experiment_id uuid NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
  round_number integer NOT NULL DEFAULT 1,
  parent_round_id uuid REFERENCES experiment_rounds(id),
  spec_snapshot jsonb NOT NULL,
  decision text CHECK (decision IN ('scale', 'refine', 'pivot', 'kill')),
  bottleneck_dimension text,
  bottleneck_ratio numeric,
  ai_fix_suggestion text,
  started_at timestamptz,
  ended_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(experiment_id, round_number)
);

CREATE INDEX idx_experiment_rounds_experiment_id ON experiment_rounds(experiment_id);

ALTER TABLE experiment_rounds ENABLE ROW LEVEL SECURITY;
CREATE POLICY experiment_rounds_user_isolation ON experiment_rounds
  FOR ALL USING (
    experiment_id IN (SELECT id FROM experiments WHERE user_id = auth.uid())
  );

-- Hypotheses
CREATE TABLE hypotheses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  experiment_id uuid NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
  round_number integer NOT NULL DEFAULT 1,
  hypothesis_key text NOT NULL,
  category text NOT NULL
    CHECK (category IN ('demand', 'reach', 'activate', 'monetize', 'retain')),
  statement text NOT NULL,
  test_method text,
  metric_formula text,
  metric_threshold numeric,
  metric_operator text CHECK (metric_operator IN ('gt', 'gte', 'lt', 'lte')),
  estimated_cost numeric DEFAULT 0,
  priority_score integer DEFAULT 0 CHECK (priority_score BETWEEN 0 AND 100),
  result text,
  experiment_level integer CHECK (experiment_level IN (1, 2, 3)),
  automation_type text NOT NULL DEFAULT 'experiment'
    CHECK (automation_type IN ('research', 'experiment', 'manual')),
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'testing', 'passed', 'failed', 'skipped', 'blocked')),
  resolved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(experiment_id, round_number, hypothesis_key)
);

> **Note:** Pre-flight research-type activate hypotheses are resolved during `/spec` AI research (automation_type = 'research', status set to 'passed' or 'failed' at spec time) and are excluded from `/iterate` verdict computation.

CREATE INDEX idx_hypotheses_experiment_id ON hypotheses(experiment_id);
ALTER TABLE hypotheses ENABLE ROW LEVEL SECURITY;
CREATE POLICY hypotheses_user_isolation ON hypotheses
  FOR ALL USING (
    experiment_id IN (SELECT id FROM experiments WHERE user_id = auth.uid())
  );

-- Hypothesis dependencies
CREATE TABLE hypothesis_dependencies (
  hypothesis_id uuid NOT NULL REFERENCES hypotheses(id) ON DELETE CASCADE,
  depends_on_id uuid NOT NULL REFERENCES hypotheses(id) ON DELETE CASCADE,
  PRIMARY KEY (hypothesis_id, depends_on_id),
  CHECK (hypothesis_id != depends_on_id)
);

-- Research results
CREATE TABLE research_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  experiment_id uuid NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
  hypothesis_id uuid REFERENCES hypotheses(id) ON DELETE SET NULL,
  query text NOT NULL,
  summary text NOT NULL,
  sources text[] DEFAULT '{}',
  confidence text NOT NULL DEFAULT 'medium'
    CHECK (confidence IN ('high', 'medium', 'low')),
  verdict text NOT NULL
    CHECK (verdict IN ('confirmed', 'rejected', 'inconclusive')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_research_results_experiment_id ON research_results(experiment_id);

ALTER TABLE research_results ENABLE ROW LEVEL SECURITY;
CREATE POLICY research_results_user_isolation ON research_results
  FOR ALL USING (
    experiment_id IN (SELECT id FROM experiments WHERE user_id = auth.uid())
  );

-- Variants
CREATE TABLE variants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  experiment_id uuid NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
  round_number integer NOT NULL DEFAULT 1,
  slug text NOT NULL,
  headline text NOT NULL,
  subheadline text,
  cta text NOT NULL,
  pain_points text[],
  promise text,
  proof text,
  urgency text,
  pricing_amount numeric,
  pricing_model text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(experiment_id, round_number, slug)
);

CREATE INDEX idx_variants_experiment_id ON variants(experiment_id);

ALTER TABLE variants ENABLE ROW LEVEL SECURITY;
CREATE POLICY variants_user_isolation ON variants
  FOR ALL USING (
    experiment_id IN (SELECT id FROM experiments WHERE user_id = auth.uid())
  );

-- Experiment metric snapshots (time-series, from PostHog + ad platforms)
CREATE TABLE experiment_metric_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  experiment_id uuid NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
  round_number integer NOT NULL DEFAULT 1,
  -- Scorecard ratios (computed)
  reach_ratio numeric,
  reach_actual text,
  reach_threshold text,
  reach_sample_size integer,
  reach_confidence text,
  demand_ratio numeric,
  demand_actual text,
  demand_threshold text,
  demand_sample_size integer,
  demand_confidence text,
  activate_ratio numeric,
  activate_actual text,
  activate_threshold text,
  activate_sample_size integer,
  activate_confidence text,
  monetize_ratio numeric,
  monetize_actual text,
  monetize_threshold text,
  monetize_sample_size integer,
  monetize_confidence text,
  retain_ratio numeric,
  retain_actual text,
  retain_threshold text,
  retain_sample_size integer,
  retain_confidence text,
  -- Per-channel traffic
  channel_metrics jsonb NOT NULL DEFAULT '{}',
  -- Aggregate traffic
  total_clicks integer DEFAULT 0,
  total_spend_cents integer DEFAULT 0,
  avg_cpc_cents integer DEFAULT 0,
  -- Source tracking
  posthog_synced_at timestamptz,
  distribution_synced_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_metric_snapshots_experiment ON experiment_metric_snapshots(experiment_id, created_at DESC);

ALTER TABLE experiment_metric_snapshots ENABLE ROW LEVEL SECURITY;
CREATE POLICY metric_snapshots_user_isolation ON experiment_metric_snapshots
  FOR ALL USING (
    experiment_id IN (SELECT id FROM experiments WHERE user_id = auth.uid())
  );

-- Experiment decisions (verdict history from /iterate)
CREATE TABLE experiment_decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  experiment_id uuid NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
  round_number integer NOT NULL DEFAULT 1,
  decision text NOT NULL CHECK (decision IN ('scale', 'refine', 'pivot', 'kill')),
  reach_ratio numeric,
  reach_confidence text,
  reach_sample_size integer,
  demand_ratio numeric,
  demand_confidence text,
  demand_sample_size integer,
  activate_ratio numeric,
  activate_confidence text,
  activate_sample_size integer,
  monetize_ratio numeric,
  monetize_confidence text,
  monetize_sample_size integer,
  retain_ratio numeric,
  retain_confidence text,
  retain_sample_size integer,
  bottleneck_dimension text,
  bottleneck_recommendation text,
  distribution_roi jsonb,
  reasoning text,
  next_steps text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_experiment_decisions_experiment_id ON experiment_decisions(experiment_id);

ALTER TABLE experiment_decisions ENABLE ROW LEVEL SECURITY;
CREATE POLICY experiment_decisions_user_isolation ON experiment_decisions
  FOR ALL USING (
    experiment_id IN (SELECT id FROM experiments WHERE user_id = auth.uid())
  );

-- Experiment alerts (persistent until resolved)
CREATE TABLE experiment_alerts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  experiment_id uuid NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
  alert_type text NOT NULL
    CHECK (alert_type IN ('deploy_failed', 'ad_account_suspended',
           'post_removed', 'budget_exhausted', 'metrics_stale',
           'dimension_dropping', 'bug_auto_fixed')),
  channel text,
  message text NOT NULL,
  severity text NOT NULL DEFAULT 'warning'
    CHECK (severity IN ('info', 'warning', 'critical')),
  resolved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_experiment_alerts_experiment ON experiment_alerts(experiment_id)
  WHERE resolved_at IS NULL;

ALTER TABLE experiment_alerts ENABLE ROW LEVEL SECURITY;
CREATE POLICY experiment_alerts_user_isolation ON experiment_alerts
  FOR ALL USING (
    experiment_id IN (SELECT id FROM experiments WHERE user_id = auth.uid())
  );

-- Notifications (email + browser push)
CREATE TABLE notifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id),
  experiment_id uuid REFERENCES experiments(id) ON DELETE SET NULL,
  trigger_type text NOT NULL
    CHECK (trigger_type IN ('experiment_live', 'first_traffic',
           'mid_experiment', 'verdict_ready', 'budget_alert',
           'dimension_dropping', 'bug_auto_fixed', 'portfolio_update')),
  channel text NOT NULL DEFAULT 'email'
    CHECK (channel IN ('email', 'browser_push')),
  scorecard_snapshot jsonb,
  sent_at timestamptz,
  read_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_notifications_user ON notifications(user_id, created_at DESC);

ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
CREATE POLICY notifications_user_isolation ON notifications
  FOR ALL USING (auth.uid() = user_id);

-- AI usage tracking
CREATE TABLE ai_usage (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id),
  experiment_id uuid REFERENCES experiments(id) ON DELETE SET NULL,
  skill_name text NOT NULL,
  category text NOT NULL DEFAULT 'analysis'
    CHECK (category IN ('analysis', 'implementation')),
  model text NOT NULL,
  input_tokens integer NOT NULL DEFAULT 0,
  output_tokens integer NOT NULL DEFAULT 0,
  cost_usd numeric NOT NULL DEFAULT 0,
  latency_ms integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_ai_usage_user_id ON ai_usage(user_id);
CREATE INDEX idx_ai_usage_experiment_id ON ai_usage(experiment_id);

ALTER TABLE ai_usage ENABLE ROW LEVEL SECURITY;
CREATE POLICY ai_usage_user_isolation ON ai_usage
  FOR ALL USING (auth.uid() = user_id);

-- User billing (plan + PAYG balance)
CREATE TABLE user_billing (
  user_id uuid PRIMARY KEY REFERENCES auth.users(id),
  plan text NOT NULL DEFAULT 'payg'
    CHECK (plan IN ('payg', 'pro', 'team')),
    -- Free tier = 'payg' with zero balance + lifetime experiment limit enforced in app logic. Settings UI renders Free as a separate column but it maps to this same 'payg' row.
  stripe_customer_id text UNIQUE,
  stripe_subscription_id text,
  subscription_status text DEFAULT 'none'
    CHECK (subscription_status IN ('none','active','past_due','canceled')),
  creates_used integer NOT NULL DEFAULT 0,
  modifications_used integer NOT NULL DEFAULT 0,
  hosting_used integer NOT NULL DEFAULT 0,
  pool_resets_at timestamptz,
  payg_balance_cents integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE user_billing ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_billing_user_isolation ON user_billing
  FOR ALL USING (auth.uid() = user_id);

-- Operation ledger (billing records per skill execution)
CREATE TABLE operation_ledger (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id),
  experiment_id uuid REFERENCES experiments(id) ON DELETE SET NULL,
  skill_execution_id uuid REFERENCES skill_executions(id),
  operation_type text NOT NULL
    CHECK (operation_type IN ('create_l1','create_l2','create_l3',
                              'change','small_fix','hosting','spec_gen')),
  price_cents integer NOT NULL,
  billing_source text NOT NULL
    CHECK (billing_source IN ('pool','payg','free')),
  status text NOT NULL DEFAULT 'authorized'
    CHECK (status IN ('authorized','completed','failed','refunded')),
  token_budget integer,
  actual_tokens_used integer,
  actual_cost_usd numeric,
  classifier_output jsonb,
  parent_operation_id uuid REFERENCES operation_ledger(id),  -- budget extension chaining
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);

CREATE INDEX idx_operation_ledger_user_created ON operation_ledger(user_id, created_at DESC);
CREATE INDEX idx_operation_ledger_billing ON operation_ledger(user_id, billing_source, status)
  WHERE status IN ('authorized', 'completed');

ALTER TABLE operation_ledger ENABLE ROW LEVEL SECURITY;
CREATE POLICY operation_ledger_user_isolation ON operation_ledger
  FOR ALL USING (auth.uid() = user_id);

-- Link ai_usage to operation_ledger
ALTER TABLE ai_usage ADD COLUMN operation_id uuid REFERENCES operation_ledger(id);

-- Skill executions (Cloud Run Jobs tracking)
CREATE TABLE skill_executions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  experiment_id uuid REFERENCES experiments(id) ON DELETE SET NULL,
  user_id uuid NOT NULL REFERENCES auth.users(id),
  skill_name text NOT NULL,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'running', 'paused', 'completed', 'failed', 'timed_out')),
  input_params jsonb DEFAULT '{}',
  cloud_run_execution_id text,
  gate_type text,
  error_message text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_skill_executions_user_id ON skill_executions(user_id);
CREATE INDEX idx_skill_executions_experiment_id ON skill_executions(experiment_id);
CREATE INDEX idx_skill_executions_status ON skill_executions(status) WHERE status IN ('pending', 'running', 'paused');

ALTER TABLE skill_executions ENABLE ROW LEVEL SECURITY;
CREATE POLICY skill_executions_user_isolation ON skill_executions
  FOR ALL USING (auth.uid() = user_id);

-- OAuth tokens (for distribution channel connections)
CREATE TABLE oauth_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id),
  provider text NOT NULL,
  access_token text NOT NULL,                   -- encrypted via Supabase Vault
  refresh_token text,                           -- encrypted via Supabase Vault
  expires_at timestamptz,
  scopes text[],
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(user_id, provider)
);

ALTER TABLE oauth_tokens ENABLE ROW LEVEL SECURITY;
CREATE POLICY oauth_tokens_user_isolation ON oauth_tokens
  FOR ALL USING (auth.uid() = user_id);

-- Distribution campaigns (created by /distribute skill)
CREATE TABLE distribution_campaigns (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  experiment_id uuid NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
  round_number integer NOT NULL DEFAULT 1,
  channel text NOT NULL
    CHECK (channel IN ('twitter-organic', 'reddit-organic', 'email-resend', 'google-ads', 'meta-ads', 'twitter-ads')),
  campaign_name text NOT NULL,
  campaign_id text,
  campaign_url text,
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'paused', 'active', 'completed', 'failed')),
  creative jsonb NOT NULL DEFAULT '{}',
  targeting jsonb NOT NULL DEFAULT '{}',
  utm_source text NOT NULL,
  utm_medium text NOT NULL,
  utm_campaign text NOT NULL,
  budget_cents integer DEFAULT 0,
  spend_cents integer DEFAULT 0,
  impressions integer DEFAULT 0,
  clicks integer DEFAULT 0,
  conversions integer DEFAULT 0,
  ctr numeric,
  cpc_cents integer,
  metrics_synced_at timestamptz,
  ads_yaml jsonb,
  started_at timestamptz,
  ended_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_distribution_campaigns_experiment_id ON distribution_campaigns(experiment_id);
CREATE INDEX idx_distribution_campaigns_status ON distribution_campaigns(status) WHERE status IN ('draft', 'paused', 'active');

ALTER TABLE distribution_campaigns ENABLE ROW LEVEL SECURITY;
CREATE POLICY distribution_campaigns_user_isolation ON distribution_campaigns
  FOR ALL USING (
    experiment_id IN (SELECT id FROM experiments WHERE user_id = auth.uid())
  );

-- Portfolio Intelligence: AI-generated cross-experiment recommendations
CREATE TABLE portfolio_insights (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id),
  insight_json jsonb NOT NULL,
  portfolio_health integer NOT NULL CHECK (portfolio_health BETWEEN 0 AND 100),
  top_experiment_id uuid REFERENCES experiments(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  dismissed_at timestamptz,
  applied_at timestamptz
);

CREATE INDEX idx_portfolio_insights_user ON portfolio_insights(user_id);
CREATE INDEX idx_portfolio_insights_active ON portfolio_insights(user_id)
  WHERE dismissed_at IS NULL AND applied_at IS NULL;

ALTER TABLE portfolio_insights ENABLE ROW LEVEL SECURITY;
CREATE POLICY portfolio_insights_user_isolation ON portfolio_insights
  FOR ALL USING (auth.uid() = user_id);
```

`insight_json` schema:

```typescript
interface PortfolioInsight {
  portfolio_health: number;        // 0-100
  top_experiment: string;          // experiment name
  recommendations: Array<{
    type: 'scale' | 'kill' | 'rebalance' | 'wait';
    experiment_id: string;
    experiment_name: string;
    action: string;                // human-readable action
    reason: string;                // one-line reasoning
    amount_cents?: number;         // for rebalance type
    from_experiment_id?: string;   // for rebalance type
  }>;
  next_check: string;             // ISO 8601
}
```

```sql
-- Portfolio Intelligence: Budget allocation history
CREATE TABLE budget_allocations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id),
  allocation_json jsonb NOT NULL,
  source text NOT NULL CHECK (source IN ('ai_recommended', 'user_custom', 'auto_rebalance')),
  applied_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE budget_allocations ENABLE ROW LEVEL SECURITY;
CREATE POLICY budget_allocations_user_isolation ON budget_allocations
  FOR ALL USING (auth.uid() = user_id);
```

`allocation_json` schema:

```typescript
interface BudgetAllocation {
  total_budget_cents: number;
  allocations: Array<{
    experiment_id: string;
    experiment_name: string;
    amount_cents: number;
    percentage: number;            // 0-100, all must sum to 100
    previous_amount_cents: number; // for diff display
  }>;
}
```

```sql
-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER experiments_updated_at BEFORE UPDATE ON experiments
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER hypotheses_updated_at BEFORE UPDATE ON hypotheses
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER variants_updated_at BEFORE UPDATE ON variants
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER oauth_tokens_updated_at BEFORE UPDATE ON oauth_tokens
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER distribution_campaigns_updated_at BEFORE UPDATE ON distribution_campaigns
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

### Status Transitions

**Experiment:** `draft → active → verdict_ready → completed → archived`

- `draft → active`: `/deploy` succeeds
- `active → paused`: user action
- `paused → active`: user resumes
- `active → verdict_ready`: `/iterate` or metrics cron produces verdict
- `verdict_ready → completed`: user views and acknowledges verdict
- `verdict_ready → draft`: REFINE flow (new round, same experiment)
- `completed → archived`: `/teardown` or user action
- `* → archived`: KILL or PIVOT (auto-archive original)

**Skill Execution:** `pending → running → paused → running → completed` | `running → failed` | `paused → timed_out`

**Distribution Campaign:** `draft → paused → active → completed` | `draft → failed` | `active → paused`

- `draft`: `/distribute` skill generates ads.yaml
- `draft → paused`: campaign created on platform via API
- `paused → active`: user enables after verifying conversion tracking
- `active → completed`: campaign end date reached or budget exhausted
- `* → failed`: API creation error or platform rejection

**Hypothesis:** `pending → testing → passed/failed/skipped/blocked`

- `pending → testing`: experiment becomes `active`
- `testing → passed/failed`: `/iterate` verdict
- `testing → blocked`: parent hypothesis in `depends_on[]` is REJECTED
- `* → skipped`: user manually skips

### Pages (Assayer Platform)

```yaml
pages:
  - name: landing        # One input field, "Test it" → spec stream (no auth)
  - name: assay          # Spec materializing + review/edit + pre-flight (no auth for generation)
  - name: launch         # Build preview + deploy progress + distribution approval gate
  - name: experiment     # Scorecard hero + traffic + live assessment + alert banners + folded details
  - name: verdict        # Full-screen verdict moment (SCALE/REFINE/PIVOT/KILL + Distribution ROI)
  - name: lab            # Portfolio grouped: Running / Verdict Ready / Completed
  - name: compare        # Side-by-side experiment comparison (2+ experiments)
  - name: settings       # Account, distribution channels (OAuth), billing
```

---

## 7. Notification System

### Triggers

| # | Trigger | Message | Timing | Data |
|---|---------|---------|--------|------|
| 1 | Experiment live | "Your experiment is live. First traffic expected in ~2h." | Immediate after deploy | Deploy URL |
| 2 | First traffic milestone | "48 clicks so far. REACH at 1.2x — early signal positive." | ~24h | Mini scorecard |
| 3 | Mid-experiment | "200 clicks reached. Here's your mid-experiment snapshot:" | ~Day 3 | Full scorecard snapshot |
| 4 | Verdict ready | "Your verdict is ready. Tap to see." | When /iterate produces verdict | Verdict type + scorecard |
| 5 | Budget alert | "Google Ads budget 90% spent. Add budget or continue organic?" | When threshold hit | Spend/budget ratio |
| 6 | Dimension dropping | "MONETIZE trending down — 0.72x → 0.65x. Consider adjusting pricing." | When decline detected | Dimension + trend |
| 7 | Bug auto-fixed | "AI Invoice Tool: signup form bug detected and fixed (12 visitors affected)" | On auto-fix completion | Fix description + affected visitor count |
| 8 | Portfolio insight ready | "Portfolio insight ready: 2 experiments compared. Tap to view." | When 2+ running experiments | Insight summary |

### Implementation

- **Channel:** Email (required, via Resend) + browser push (opt-in)
- **Template:** Every email contains a mini scorecard — enough to decide "do I need to act?" without opening the app
- **Detection:** Triggers 2, 3, 5, 6 detected during metrics sync cron. Trigger 1 detected on skill execution completion. Trigger 4 detected when experiment status transitions to `verdict_ready`
- No in-app notification center — email + push covers ambient awareness without over-engineering

---

## 8. Alert System

Errors appear as alert banners at the top of the Experiment Page — not separate screens. Each banner has a one-line description and recommended action. The experiment continues where possible.

| # | Alert Type | Banner Text | Actions |
|---|-----------|------------|---------|
| 1 | `deploy_failed` | "Deploy failed — code scaffolding error" | [Retry Deploy] [View Logs] |
| 2 | `ad_account_suspended` | "Google Ads: account suspended by Google" | [Check Google Ads] — other channels continue |
| 3 | `post_removed` | "Reddit post removed by moderators" | [Repost to different subreddit] [Ignore] |
| 4 | `budget_exhausted` | "Ad budget spent — 3 days remaining" | [Add $X budget] [Continue organic only] |
| 5 | `metrics_stale` | "Data stale (last sync: 26h ago)" | [Force Sync] [View status] |
| 6 | `dimension_dropping` | "MONETIZE trending down — 0.72x → 0.65x" | [Analyze Now] [View details] |
| 7 | `bug_auto_fixed` | "Signup form bug detected and fixed (12 visitors affected)" | [View details] |

Alerts persist in `experiment_alerts` until resolved. Channel-specific failures are isolated — if Google Ads is suspended, Twitter and Reddit continue.

---

## 9. Build Order

| # | What | Method | Depends On |
|---|------|--------|-----------|
| 0 | Infrastructure setup | manual | — |
| 1 | Extract `spec-reasoning.md` from `/spec` skill + create `spec.md` | direct file creation | #0 |
| 1.5 | Build `/api/spec/stream` route (imports `spec-reasoning.md` rules, `>>>EVENT:` parser) | direct file creation | #1 |
| 2 | Enhance `iterate.md` (per-hypothesis verdicts) | direct edit | — |
| 3 | Minor updates to `distribute.md` | direct edit | #1 |
| 4 | Update Assayer `experiment.yaml` | manual edit | #1-2 |
| 5 | `/bootstrap` Assayer platform | /bootstrap | #4 |
| 6 | `/change`: error schema + API key auth | /change | #5 |
| 6.5 | `/change`: anonymous spec endpoint (`/api/spec/stream` + `anonymous_specs` table) | /change | #6 |
| 6.7 | `/change`: seed data | /change | #6 |
| 7 | `/change`: experiments + hypotheses + rounds CRUD | /change | #6 |
| 8 | `/change`: research + variants + metrics + spec claim endpoint | /change | #6 |
| 8.5 | `/change`: skill execution infrastructure (Cloud Run Jobs + Docker + skill-runner) | /change | #6 |
| 8.6 | `/change`: approval gates + Supabase Realtime streaming | /change | #8.5 |
| 8.7 | `/change`: distribution campaigns table + API routes | /change | #6 |
| 8.8 | `/change`: distribution adapter infrastructure (6 adapters) | /change | #8.7 |
| 9 | `/change`: landing → assay → launch flow (anonymous spec + signup gate + build preview) | /change | #6.5, #7-8, #8.6 |
| 9.5 | `/change`: alert system (`experiment_alerts` table + banner UI) | /change | #7 |
| 9.6 | `/change`: notification system (`notifications` table + Resend integration) | /change | #7, #9.5 |
| 10 | `/change`: lab (portfolio view, state-grouped) + experiment page (scorecard hero) + verdict page (full-screen) | /change | #7-8, #9.5 |
| 10.5 | `/change`: experiment comparison view | /change | #10 |
| 11 | `/change`: metrics sync cron (PostHog + ad platforms, 15min) + alert detection | /change | #7, #8.7, #9.5 |
| 12 | `/harden` + `/verify` | /harden, /verify | #9-11 |
| 13 | `/deploy` | /deploy | #12 |
| 14 | First real experiment | manual | #13 |

**Parallelism:** #2+#3 parallel with #1. #7+#8 parallel. #8.5+#8.6 sequential. #8.7+#8.8 sequential (parallel with #8.5+#8.6). #9.5+#9.6 sequential (parallel with #10). Then #10+#10.5+#11 parallel.

### Skill-to-Skill Data Flow

```
/spec        → writes experiment/experiment.yaml + .runs/spec-manifest.json
/bootstrap   → reads experiment/experiment.yaml
/iterate     → reads .runs/spec-manifest.json → writes .runs/iterate-manifest.json
```

Manifests are workspace artifacts committed to experiment repos. Supabase is the persistent layer — manifests are regenerated from Supabase data when containers start.

### Data Sync Protocol

Supabase = sole source of truth. No dual-source-of-truth problem.

- **Before execution:** Supabase → generate `experiment.yaml` (container-local, ephemeral)
- **After execution:** Parse skill output → write to Supabase tables (experiments, hypotheses, variants, etc.)
- **CLI path:** Local dev only. User runs skills directly. No automatic platform sync in V1.

### Infrastructure (Day 0)

| What |
|------|
| Supabase project (platform DB + Auth) |
| Google OAuth + GitHub OAuth apps (for Supabase Auth) |
| PostHog project (shared for platform + experiments) |
| Stripe account + test products (Pro/Team Price IDs: `STRIPE_PRO_PRICE_ID`, `STRIPE_TEAM_PRICE_ID`) |
| Resend account + domain verification |
| assayer.io domain + wildcard DNS + SSL → Vercel |
| Vercel Pro account |
| Google Cloud project + Cloud Run API enabled |
| Artifact Registry (Docker image repository) |
| GCP Service Account for Vercel → Cloud Run invocation |
| Sentry (Next.js integration) |
| GitHub Actions CI (build + lint + test) |

### Future Additions (build when triggered)

| Feature | Trigger |
|---------|---------|
| `/assay` orchestrator | Users ask for "one command" |
| Auto-sequencing | 20+ experiments in DB |
| Benchmark database | 100+ experiments in DB |
| Organic adapter auto-posting | Manual posting bottleneck after 5+ experiments |
| In-app notification center | Email open rate drops below 20% |
| PostHog project sharding | 100+ experiments, perf degrades |

### Platform API Access Timeline

| Platform | Test Access | Production Access |
|----------|------------|-------------------|
| Google Ads | Immediate (test account) | Basic access ~1 week |
| Meta Ads | Immediate (test account) | App review ~2 weeks |
| X Ads API | Developer portal | Approval ~1 week |

---

## 10. Constraints

- Opus 4.6 for all AI skills. Quality over cost.
- **Per-operation token budgets** (not per-user daily limits): Create L1 6M, L2 10M, L3 16M, Change 5M, Small fix 1.5M input tokens. Hard limit → user offered "continue for $X?"
- AI skills: zod validation, retry once, typed error on second failure.
- Show sample size alongside every metric. Never auto-decide with <100 clicks.
- User can preview and edit AI content before deployment.
- `spec-reasoning.md` is the single source of truth for AI spec generation logic. Both CLI (`spec.md`) and web (`/api/spec/stream`) import it. Never duplicate reasoning rules.
- Web spec generation uses inference mode — no follow-up questions, aggressive inference with `[inferred]` markers. `input_too_vague` event is the only fallback (<5% of inputs).
- Rate limit `/api/spec/stream` (anonymous: 3/24h per session_token; free accounts: 5/24h per user_id). Vercel serverless has no shared memory — spec/stream rate limiting uses `anonymous_specs` table row count (DB-backed). General API rate limiting uses a dual strategy: critical routes (auth, billing) use Supabase-backed `rate_limit_entries` table (~5ms overhead); non-critical routes use per-instance in-memory Map with 60s cleanup (acceptable cold-start reset).
- **Billing gate** (`/api/operations/authorize`) required before every billable skill execution. No skill runs without authorized `operation_ledger` row. Exception: auto-fix operations use `billing_source='free'` with `price_cents=0` — the cron creates the `operation_ledger` row directly and triggers Cloud Run via `triggerCloudRunJob()` using service role key.
- **Past-due subscription gate**: billing gate checks `subscription_status` — if `past_due`, pool access is blocked (PAYG balance still usable). Error code: `subscription_past_due`.
- **Stripe webhook idempotency**: every webhook handler deduplicates by `event.id` via `stripe_webhook_events` table before processing. Prevents double-charging on network retries.
- **OAuth token refresh**: distribution adapters call `getValidToken()` before every platform API call. If access token expired, auto-refresh via refresh token. If refresh fails (revoked), create `ad_account_suspended` alert for that channel and skip it — other channels continue independently.
- **Operation classifier** (Haiku) determines Change vs Small fix. Default to Change on low confidence.
- **PAYG balance**: atomic decrement via Supabase RPC to prevent race conditions.
- **Pool reset**: triggered by Stripe `customer.subscription.updated` webhook when `current_period_start` changes.
- Cloud Run budget: $50/mo alert, $100/mo hard limit.

---

## 11. UX Reference

> Full UX specification is in `docs/ux-design.md`. This section provides CLI output examples for internal development reference.

### CLI — After /spec

```
/spec "AI-powered invoice tool for freelancers"

Pre-flight checks                                    4/4 passed
------------------------------------------------------------------
[ok] Market exists        Freelancer invoicing: $4.2B TAM          (confidence: high)
[ok] Problem validated    340+ forum threads                       (confidence: high)
[ok] Competitors found    None use AI generation                   (confidence: medium)
[ok] ICP identifiable     Solo freelancers, US/EU                  (confidence: high)

Level: L1 Pitch (default)
Build: $150  Ad budget: $200  Time: 7 days

Hypotheses:
  REACH      "Ad CTR > 2% for freelancer invoice keywords"  -> CTR
  DEMAND     "Freelancers search for invoice automation"     -> signup rate
  MONETIZE   "Freelancers will pay $19/mo"                   -> pricing clicks

Behaviors (3):
  b-01  Given a freelancer lands -> they understand the value prop      (L1)
  b-02  Given interest -> CTA click enters signup flow                  (L1)
  b-03  Given pricing shown -> they interact with pricing options       (L1)

Variants (3):
  "time-saver"    Save 5 Hours Every Week on Invoicing
  "ai-magic"      Your AI Invoicing Assistant
  "cost-cutter"   Cut Invoicing Costs by 80%

Wrote experiment/experiment.yaml
Run /bootstrap to scaffold, or edit experiment.yaml first to adjust.
To test at L2/L3, run: /spec "AI-powered invoice tool" --level 2
```

### CLI — After /iterate

```
RESULTS -- Experiment #1 (L1 Pitch)
=============================================

Funnel scorecard:
  REACH      1.90  ##################..  CTR 3.8% / 2.0%         (high -- 523 impressions)
  DEMAND     1.34  ################....  6.7% signup / 5.0%      (high -- 523 visitors)
  ACTIVATE   --    (not tested -- requires L2)
  MONETIZE   0.65  #############.......  4.5% clicks / 7.0%      (directional -- 89 clicks)
  RETAIN     --    (not tested -- requires L3)

! Bottleneck: MONETIZE (ratio 0.65). Pricing click rate 4.5% vs 7.0% threshold.
  Consider: test lower price points or add value justification.

Hypothesis verdicts:
  REACH      CTR 3.8% vs 2.0% threshold     PASS  (high -- 523 impressions)
  DEMAND     6.7% signup vs 5.0%             PASS  (high -- 523 visitors)
  MONETIZE   4.5% pricing clicks vs 7.0%     FAIL  (directional -- 89 clicks)

VERDICT: REFINE (bottleneck MONETIZE at 0.65)
Recommended: Adjust pricing/value prop, then upgrade to L2 for deeper engagement data
```
