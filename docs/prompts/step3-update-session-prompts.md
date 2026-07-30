# Step 3 Prompt: Update session-prompts.md with Portfolio Intelligence + Distribution Gaps

## Context

`docs/ux-design.md` and `docs/assayer-product-design.md` have been updated with Portfolio Intelligence features and distribution gap fixes:
- **Assayer Score** (0-100) on Lab experiment cards, sorted by score
- **AI Insight** card with cross-experiment recommendations
- **Budget Allocation** tab with sliders (Team plan)
- **Mobile Lab** with NEEDS ATTENTION grouping
- **Comparison** enhanced with Score + AI Recommendation
- **Portfolio Notification** email template
- **Distribution Plan Generator** — AI-recommended channels + budgets for Phase F
- **Distribution ROI** — "$X spent → Y.Zx signal" on verdict page
- **Confidence Bands** — explicit computation logic for scorecard dimensions
- **3 new DB tables/columns**, **7 new API routes**, **3 new cron jobs**

Your job: update `docs/assayer-session-prompts.md` to ensure these features are built. Expand existing sessions — do NOT add new sessions.

## Instructions

Read these files first:
1. `docs/ux-design.md` — find all sections marked with Portfolio Intelligence changes (Lab, Comparison, Notifications, Mobile, Pricing)
2. `docs/assayer-product-design.md` — find all sections with Portfolio Intelligence (Data Model, API, Cron, Billing, Assayer Score) AND Distribution Plan Generator AND Distribution ROI
3. `docs/assayer-session-prompts.md` — the file you WILL modify

Then modify ONLY `docs/assayer-session-prompts.md`.

## Strategy: Expand 6 Existing Sessions

Do NOT add new sessions. Features distribute across existing sessions by natural scope:

| New Feature | Belongs In | Reason |
|-------------|-----------|--------|
| `assayer_score` column + `portfolio_insights` table + `budget_allocations` table | **Session 3** (DB schema) | All DB schema in one session |
| Lab cards with ★ Score + sorting + AI Insight card + Budget tab + Compare enhancement | **Session 7** (Lab + Verdict + Compare + Settings) | All Lab UI in one session |
| Portfolio Intelligence billing gates (Pro/Team checks) | **Session 8** (Billing + Operations) | All billing in one session |
| Distribution Plan Generator (plan-generator.ts + API route + budget algorithm) | **Session 10** (Distribution System) | Distribution logic belongs with adapters |
| Score computation cron + AI Insight cron + auto-rebalance cron + Portfolio Notification + Distribution ROI + Confidence Bands | **Session 11** (Metrics Cron + Alerts + Verdict Engine + Notifications) | All crons and computation in one session |
| Mobile Lab NEEDS ATTENTION grouping + Portfolio Health in header | **Session 12a** (Mobile Components) | All mobile in one session |

## Changes to Each Session

### Session 3 — Append to prompt

After the existing DB schema instructions, add:

```
## Portfolio Intelligence Tables

Add these to the same migration file:

1. Add columns to `experiments` table:
   - `assayer_score integer CHECK (assayer_score BETWEEN 0 AND 100)` — computed score for portfolio ranking
   - `score_updated_at timestamptz` — last score computation timestamp

2. Create `portfolio_insights` table:
   - `id uuid PRIMARY KEY`
   - `user_id uuid REFERENCES auth.users(id)`
   - `insight_json jsonb NOT NULL` — AI-generated recommendations (see product-design.md for schema)
   - `portfolio_health integer NOT NULL CHECK (portfolio_health BETWEEN 0 AND 100)`
   - `top_experiment_id uuid REFERENCES experiments(id)`
   - `created_at`, `dismissed_at`, `applied_at` timestamps
   - RLS policy: user_isolation (same pattern as experiments)
   - Index on user_id + active insights (WHERE dismissed_at IS NULL AND applied_at IS NULL)

3. Create `budget_allocations` table:
   - `id uuid PRIMARY KEY`
   - `user_id uuid REFERENCES auth.users(id)`
   - `allocation_json jsonb NOT NULL` — allocation per experiment (see product-design.md for schema)
   - `source text NOT NULL CHECK (source IN ('ai_recommended', 'user_custom', 'auto_rebalance'))`
   - `applied_at timestamptz`
   - RLS policy: user_isolation
```

**Update Session 3 output contract** to add:
```
DB output:
  - portfolio_insights table (columns: id, user_id, insight_json, portfolio_health, top_experiment_id, created_at, dismissed_at, applied_at)
  - budget_allocations table (columns: id, user_id, allocation_json, source, applied_at)
  - experiments.assayer_score column (integer, 0-100, nullable)
  - experiments.score_updated_at column (timestamptz, nullable)
```

### Session 7 — Append to prompt

After the existing Lab + Compare instructions, add:

```
## Portfolio Intelligence UI

### Lab Enhancement

1. RUNNING experiment cards:
   - Add `★ {assayer_score}` display in top-right corner of each card
   - Add compressed dimension ratios: `R {reach}x D {demand}x M {monetize}x`
   - Sort RUNNING group by assayer_score DESC (highest first)
   - Status label derived from score: 80-100 ON TRACK, 60-79 PROMISING, 40-59 LOW !, 20-39 DANGER, 0-19 CRITICAL
   - Score is NULL when no data → show "—" and sort last

2. AI Insight card:
   - Conditionally render between RUNNING and VERDICT READY groups
   - Visible when: user has 2+ RUNNING experiments AND portfolio_insights has a non-dismissed, non-applied record
   - Fetch from GET /api/portfolio/insight
   - Display: numbered recommendations from insight_json
   - [Apply suggestions ->] → POST /api/portfolio/insight/:id/apply → refresh Lab
   - [Dismiss] → POST /api/portfolio/insight/:id/dismiss → hide card
   - Styled with gold accent border (using existing gold design token)
   - Plan gate: hidden for Free/PAYG users (check user plan)

3. Budget tab (Team plan only):
   - Add [Experiments] [Budget] tab switcher in Lab header
   - [Budget] tab visibility: Team plan users only
   - Budget overview: total allocated / total available with progress bar
   - Table: Experiment | Spent | Remaining | Score | Status with spend progress bars
   - AI Budget Optimizer: CURRENT → RECOMMENDED columns with reasoning text
   - [Apply Rebalance ->] → POST /api/portfolio/budget/allocate
   - [Customize] expands linked percentage sliders constrained to 100%
   - Fetch from GET /api/portfolio/budget

### Compare Enhancement

4. Add Score row (★ XX) as first data row in comparison table
5. Add CPA row ($ per activation) after existing metrics
6. Add AI RECOMMENDATION section below table:
   - Fetch latest portfolio_insight
   - Display top_experiment highlight + numbered recommendations
   - [Apply All ->] [Apply #1 only] [Dismiss] buttons

### API Routes (implement alongside UI)

6. `GET /api/portfolio/insight` — return latest active insight for user
7. `POST /api/portfolio/insight/:id/apply` — execute recommendations (Pro+ gate)
8. `POST /api/portfolio/insight/:id/dismiss` — mark dismissed
9. `GET /api/portfolio/budget` — return budget allocation (Team gate)
10. `POST /api/portfolio/budget/allocate` — apply custom allocation (Team gate)
```

**Update Session 7 output contract** to add:
```
File output:
  - src/app/lab/page.tsx: exports Lab page with ★ Score on cards, AI Insight card, Budget tab
  - src/components/portfolio-insight-card.tsx: exports PortfolioInsightCard component
  - src/components/budget-allocation.tsx: exports BudgetAllocation component (sliders)
  - src/app/api/portfolio/insight/route.ts: exports GET handler
  - src/app/api/portfolio/insight/[id]/apply/route.ts: exports POST handler
  - src/app/api/portfolio/insight/[id]/dismiss/route.ts: exports POST handler
  - src/app/api/portfolio/budget/route.ts: exports GET handler
  - src/app/api/portfolio/budget/allocate/route.ts: exports POST handler
```

### Session 8 — Append to prompt

After the existing billing instructions, add:

```
## Portfolio Intelligence Billing Gates

Add plan-based access control for portfolio features:

1. AI Insight card: visible only for Pro and Team plans
   - GET /api/portfolio/insight: return null for Free/PAYG
   - POST /api/portfolio/insight/:id/apply: reject with 403 for Free/PAYG

2. Budget tab: visible only for Team plan
   - GET /api/portfolio/budget: reject with 403 for non-Team
   - POST /api/portfolio/budget/allocate: reject with 403 for non-Team

3. Assayer Score on Lab cards: visible for ALL plans (no gate)

4. Update the plan comparison data to include "Portfolio Intelligence" row:
   - Free: --
   - PAYG: --
   - Pro: Score + AI Insight
   - Team: Score + AI Insight + Budget Optimizer
```

**Update Session 8 output contract** to add:
```
  - Plan gate middleware covers /api/portfolio/* routes
  - Settings billing page shows Portfolio Intelligence in plan comparison
```

### Session 11 — Append to prompt

After the existing Metrics Cron + Verdict Engine instructions, add:

```
## Portfolio Intelligence Crons

### 1. Assayer Score Computation (runs with existing 15-minute metrics cron)

Add to the existing metrics sync cron:

After syncing PostHog metrics for each experiment, compute Assayer Score:
- Read latest experiment_metric_snapshots for reach, demand, monetize, retain dimensions
- Apply formula from product-design.md "Assayer Score (Portfolio Ranking)" section
- Write score to experiments.assayer_score and experiments.score_updated_at
- Skip experiments with no metric data (leave score as NULL)

### 2. AI Insight Generation (new daily cron)

New cron job (daily, e.g., 06:00 UTC):
- For each user with 2+ RUNNING experiments:
  - Collect: experiment name, assayer_score, funnel_scores, budget_spent, activations, best_channel, days_elapsed, days_total for each RUNNING experiment
  - Call Anthropic API (claude-sonnet-4-6) with structured output schema (PortfolioInsight)
  - Write result to portfolio_insights table
  - If previous non-dismissed insight exists, auto-dismiss it (replaced by new)
- Cost per user: ~$0.05 (Sonnet, ~2K input + 500 output tokens)

### 3. Auto-Rebalance (new daily cron, Team plan only)

New cron job (daily, after insight generation):
- For Team plan users with auto-rebalance enabled (setting in user preferences):
  - Read latest portfolio_insight
  - If insight contains type='rebalance' recommendations:
    - Apply Thompson Sampling: sample from Beta(1+activations, 1+signups-activations) per experiment
    - Normalize to percentages, compute recommended allocation
    - Compare with current allocation — if drift > 10%, write new budget_allocation and apply
    - Log the rebalance to budget_allocations table with source='auto_rebalance'
- For users without auto-rebalance enabled: insight is written as recommendation only (applied manually via UI)

### 4. Portfolio Notification (extend existing notification dispatch)

Add to the daily notification dispatch:
- When a new portfolio_insight is generated for a user:
  - Send Portfolio Update email with:
    - ★ Portfolio Health score
    - Per-experiment row: name, score, trend (compare with previous day's score), status
    - Top suggested action
    - [Open Lab ->] deep link
  - Use the email template from ux-design.md Notifications section
```

**Update Session 11 output contract** to add:
```
File output:
  - src/app/api/cron/compute-scores/route.ts: exports POST handler (cron)
  - src/app/api/cron/generate-insights/route.ts: exports POST handler (cron)
  - src/app/api/cron/auto-rebalance/route.ts: exports POST handler (cron)
  - src/lib/assayer-score.ts: exports computeAssayerScore(experiment) → number
  - src/lib/portfolio-insight.ts: exports generatePortfolioInsight(userId) → PortfolioInsight
  - src/lib/thompson-sampling.ts: exports computeAllocation(experiments) → BudgetAllocation
  - Email template: portfolio-update (in notification templates)
```

### Session 12a — Append to prompt

After the existing mobile component instructions, add:

```
## Mobile Lab Enhancement

1. Add Portfolio Health Score (★ XX) to the right side of the mobile Lab header
2. Replace state-based grouping (RUNNING/VERDICT/COMPLETED) with urgency-based grouping:
   - "NEEDS ATTENTION": experiments where score < 20 OR status = verdict_ready OR budget fully spent
   - "ON TRACK": all other running experiments
   - "COMPLETED": completed/archived experiments (collapsed by default)
3. NEEDS ATTENTION cards: include inline action buttons [Kill & Free Budget] [View ->]
4. ON TRACK cards: compressed layout — name + ★ score + one-line status only
5. Pull-to-refresh on Lab page triggers score recomputation via POST /api/portfolio/compute-scores
```

### Session 10 — Append to prompt

After the existing distribution adapter instructions, add:

```
## Distribution Plan Generator

Read docs/assayer-product-design.md "Distribution Plan Generator" subsection.

### 1. Plan Generator Service

Create `src/lib/distribution/plan-generator.ts`:

export async function generateDistributionPlan(experiment, user): Promise<DistributionPlan>

Logic:
1. Determine budget range from experiment level:
   - L1 (Pitch): 5000-15000 cents ($50-150)
   - L2 (Prototype): 20000-50000 cents ($200-500)
   - L3 (Product): 50000-200000 cents ($500-2000)
   Use midpoint as default. Clamp to user's PAYG balance if insufficient.

2. Determine channel priority from experiment type + target_user:
   - B2B SaaS: google-ads 40%, email-resend 25%, twitter-organic 20%, reddit-organic 15%
   - Consumer App: meta-ads 35%, twitter-ads 20%, reddit-organic 25%, email-resend 20%
   - Developer Tool: reddit-organic 35%, twitter-organic 30%, google-ads 20%, email-resend 15%
   - Default: google-ads 40%, meta-ads 30%, twitter-ads 15%, organic 15%
   Infer type from experiment.yaml target_user keywords (e.g., "developer" → Developer Tool, "business" / "B2B" → B2B SaaS).

3. Filter by plan tier:
   - Free/PAYG: remove paid channels (google-ads, meta-ads, twitter-ads), redistribute budget to organic
   - Pro/Team: all channels available

4. Filter by connected channels:
   - Query oauth_tokens for user's connected channels
   - Unconnected channels: set available = false, include requires_connect message

5. Generate creative per available channel:
   - Read experiment name, description, thesis, variants
   - Read the landing page source to extract actual headline (message match)
   - For each channel: generate headlines + descriptions within channel format constraints
   - Use channel stack files (.claude/stacks/distribution/<channel>.md) for format limits

### 2. API Route

POST /api/experiments/:id/distribution/plan
  - Auth: required
  - Calls generateDistributionPlan(experiment, user)
  - Returns DistributionPlan (see product-design.md for interface)
  - Called by Session 6a Phase F UI when user reaches Distribution Approval Gate

### 3. Phase-Gated Budget Progression

When returning plan for an experiment that has completed a previous /iterate cycle:
  - Read the latest verdict from experiment_decisions
  - If verdict = SCALE and previous budget was Phase 1 range → suggest Phase 2 budget
  - If verdict = REFINE → maintain budget, optimize channel mix based on best_channel from metrics
  - If verdict = KILL/PIVOT → suggest $0 (stop spend)
  - Include reasoning in DistributionPlan.reasoning field
```

**Update Session 10 output contract** to add:
```
  - src/lib/distribution/plan-generator.ts: exports generateDistributionPlan(experiment, user) → DistributionPlan
  - src/app/api/experiments/[id]/distribution/plan/route.ts: exports POST handler
```

### Session 11 — Append additional items to prompt

In addition to the Portfolio Intelligence cron additions already specified above, append these two items after them:

```
## Distribution ROI Computation

Add to the verdict generation logic (after computing per-dimension ratios):

When generating a verdict for an experiment:
1. Query distribution_campaigns for the experiment: SUM(spend_cents), per-channel breakdown
2. Query PostHog activate event count for the experiment
3. Compute:
   - total_spend_cents = SUM(distribution_campaigns.spend_cents)
   - total_activations = COUNT(activate events)
   - cpa_cents = total_spend_cents / max(total_activations, 1)
   - signal_ratio = weighted average of dimension ratios (same weights as Assayer Score)
   - best_channel = channel with lowest CPA (most activations per dollar)
4. Write to experiment_decisions.distribution_roi (jsonb):
   { total_spend_cents, total_activations, cpa_cents, signal_ratio,
     display: "$X spent → Y.Zx signal", best_channel, channel_breakdown[] }
5. Session 7 verdict page reads this field and displays:
   - ROI summary line: "$47 spent → 3.2x signal"
   - Channel breakdown table: Channel | Spend | Activations | CPA
   - Best channel highlight

## Confidence Bands — Explicit Computation

Expand the existing scorecard ratio computation with explicit confidence band logic:

After computing each dimension's ratio, also compute its confidence level:

1. Count total events relevant to the dimension:
   - REACH: total ad impressions + organic visits
   - DEMAND: total landing page visits
   - ACTIVATE: total signups (only if L2+)
   - MONETIZE: total CTA clicks (only if L1+ with pricing)
   - RETAIN: total return visits (only if L3+)

2. Map event count to confidence level:
   - < 30 events: 'insufficient' — ratio shown with ⚠ marker, excluded from verdict logic
   - 30-100 events: 'directional' — ratio shown with ~ marker, used in verdict but flagged
   - 100-500 events: 'reliable' — ratio shown normally
   - 500+ events: 'high' — ratio shown with ✓ marker

3. Store in experiment_metric_snapshots alongside each dimension:
   { dimension: 'reach', ratio: 1.9, confidence: 'reliable', event_count: 523 }

4. Dimensions unavailable at current level:
   - L1: ACTIVATE and RETAIN → set to { ratio: null, confidence: 'unavailable' }
   - L2: RETAIN → set to { ratio: null, confidence: 'unavailable' }
   - 'unavailable' dimensions are NOT 'insufficient' — they display as "-- (requires L2)" not "⚠"

5. Guard clause uses confidence levels:
   - If ALL measured dimensions are 'insufficient' → no verdict (guard clause triggers)
   - If REACH is 'insufficient' → no verdict (need minimum traffic data)
```

**Update Session 11 output contract** to add (in addition to Portfolio Intelligence entries):
```
  - Distribution ROI computation integrated into verdict generation
  - experiment_decisions.distribution_roi jsonb field populated on verdict
  - Confidence bands stored in experiment_metric_snapshots per dimension
```

### Progress Tracking Table — Update descriptions

Update the Notes column for affected sessions:

```
| Session | Status | PR / Commit | Notes |
|---------|--------|-------------|-------|
| 3 | TODO | — | DB schema + RLS + Auth + Core CRUD + Portfolio tables |
| 7 | TODO | — | Lab + Verdict + Compare + Settings + Portfolio Intelligence UI + Distribution ROI display |
| 8 | TODO | — | Billing + Operations + Portfolio plan gates |
| 10 | TODO | — | Distribution System (6 Adapters) + Distribution Plan Generator |
| 11 | TODO | — | Metrics Cron + Alerts + Verdict Engine + Notifications + Portfolio crons + Distribution ROI + Confidence Bands |
| 12a | TODO | — | CSS Tokens + 6 Mobile Components + Mobile Lab NEEDS ATTENTION |
```

Only change the Notes column. Do not change Status or any other column.

## Rules

- Do NOT add new sessions. Only expand existing Sessions 3, 7, 8, 10, 11, 12a.
- Append new content at the END of each session's prompt (after existing instructions), clearly labeled with `## Portfolio Intelligence` or `## Distribution Plan Generator` or `## Distribution ROI Computation` or `## Confidence Bands` heading as appropriate.
- Do NOT modify existing instructions within any session — only append.
- Update output contracts by ADDING new entries, never removing existing ones.
- Follow the existing contract format: `File output:` with `path: exports description` per line.
- Follow the existing prompt style: imperative mood, specific file paths, clear verification criteria.
- Reference the correct source documents (ux-design.md for UI, product-design.md for technical spec).
- Update the progress tracking table Notes column only.

## Verification

After editing, verify:
1. Session 3 mentions all 3 new DB items (assayer_score column, portfolio_insights table, budget_allocations table)
2. Session 7 mentions all 5 UI components (Lab Score, AI Insight card, Budget tab, Compare enhancement, 5 API routes)
3. Session 8 mentions plan gates for Portfolio Intelligence
4. Session 10 mentions Distribution Plan Generator (plan-generator.ts, POST /api/.../distribution/plan, budget algorithm, channel priority)
5. Session 11 mentions all 4 Portfolio Intelligence cron additions (Score computation, Insight generation, Auto-rebalance, Portfolio notification)
6. Session 11 mentions Distribution ROI computation (formula, storage in experiment_decisions.distribution_roi, channel breakdown)
7. Session 11 mentions Confidence Bands (4 levels, event count thresholds, 'unavailable' for level-gated dimensions, guard clause integration)
8. Session 12a mentions mobile NEEDS ATTENTION grouping
9. Progress tracking table has updated Notes for sessions 3, 7, 8, 10, 11, 12a
10. No new sessions were added (total session count unchanged)
11. All output contracts include both existing AND new file entries
12. Search for "Distribution Plan Generator" — should appear in Session 10
13. Search for "Distribution ROI" — should appear in Session 11 (and Session 7 Notes)
14. Search for "Confidence Bands" — should appear in Session 11
