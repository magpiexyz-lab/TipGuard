# Step 2 Prompt: Update product-design.md with Portfolio Intelligence

## Context

We've just updated `docs/ux-design.md` with Portfolio Intelligence features (Assayer Score on Lab cards, AI Insight recommendations, Budget Allocation tab). Now we need to add the corresponding technical specification to `docs/assayer-product-design.md` so the two documents are consistent.

## Instructions

Read these files first (do NOT modify ux-design.md):
1. `docs/ux-design.md` — the just-updated UX source of truth (read the new Lab, Comparison, Budget, Mobile, Notification sections)
2. `docs/assayer-product-design.md` — the file you WILL modify
3. `docs/portfolio-distribution-design.md` — reference for technical details (Part 3: Technical Implementation + Assayer Score formula)
4. `docs/mvp-budget-playbook.md` — reference for the Assayer Score formula details and funnel benchmarks

Then modify ONLY `docs/assayer-product-design.md`. Do not create new files. Do not modify any other file.

## Changes Required

### 1. Data Model (Section 6) — Add 3 items

Find `## 6. Data Model`.

**A. Add `assayer_score` columns to the `experiments` table:**

After the existing `experiments` table definition, add:
```sql
-- Portfolio Intelligence: Assayer Score (computed, cached)
ALTER TABLE experiments ADD COLUMN assayer_score integer CHECK (assayer_score BETWEEN 0 AND 100);
ALTER TABLE experiments ADD COLUMN score_updated_at timestamptz;
```

Add a comment explaining: Score is recomputed by the 15-minute metrics cron. Range 0-100. NULL means no data yet (experiment has no iterate-manifest).

**B. Add `portfolio_insights` table** after the experiments-related tables:

```sql
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

Define the `insight_json` schema:
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

**C. Add `budget_allocations` table:**

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

Define the `allocation_json` schema:
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

### 2. API Routes (Section 5) — Add portfolio routes

Find `## 5. API & Data Flow`.

Add a new subsection `### Portfolio Intelligence API`:

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
  - For each user with 2+ running experiments: calls Anthropic API (Sonnet) to generate insight
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

### 3. Assayer Score Computation — New subsection

Add a new subsection after the Scorecard Computation section (or within it). Title: `### Assayer Score (Portfolio Ranking)`.

Content:

```
Assayer Score is a composite 0-100 score per experiment that enables cross-experiment ranking.
Computed every 15 minutes by the metrics cron. NULL when no iterate data exists.

Formula:
  raw = (Signal × Confidence × Efficiency) / Risk
  assayer_score = min(round(raw), 100)

Components:

Signal (0-100):
  0.30 × reach_score + 0.30 × demand_score + 0.20 × monetize_score + 0.10 × retain_score + 0.10 × growth_score
  Each dimension_score = min(actual / threshold, 1.0) × 100
  Source: experiment_metric_snapshots (latest) mapped to funnel dimensions
  If dimension not available at current level, excluded and weights renormalized

Confidence (0-1):
  sample_factor × freshness_factor
  sample_factor: <30 visits → 0.3, 30-100 → 0.6, 100-500 → 0.8, 500+ → 1.0
  freshness_factor: <3 days → 1.0, 3-7 → 0.9, 7-14 → 0.7, >14 → 0.5

Efficiency (0-10):
  If activations > 0: 1 / max(CAC / benchmark_CAC, 0.1)
  If activations == 0: 0.1
  CAC = budget_spent / activations
  benchmark_CAC: $100 (configurable per experiment_type)

Risk (0.1-1.0):
  max((estimated_remaining_cost - budget_spent) / max_budget, 0.1)
  max_budget: $500 (from distribution config)
  estimated_remaining_cost: derived from level ($500 for L1, $1000 for L2, $2000 for L3)

Score-to-status mapping (used in Lab cards):
  80-100: ON TRACK
  60-79:  PROMISING
  40-59:  LOW !
  20-39:  DANGER
  0-19:   CRITICAL
```

### 4. Cron Jobs (Section 2, Architecture) — Add to existing cron table

Find the Vercel Cron section in the Architecture. Add these entries:

```
Vercel Cron ─── 15min: metrics sync (PostHog + ad platforms)
            ─── 15min: assayer score computation              ← NEW
            ─── 15min: alert condition detection
            ─── 1h: anonymous spec cleanup
            ─── daily: notification dispatch
            ─── daily: portfolio insight generation (Sonnet)   ← NEW
            ─── daily: auto-rebalance (Team plan, with gate)   ← NEW
            ─── weekly: cost-monitor
```

For the auto-rebalance cron, add a note: "Auto-rebalance runs Thompson Sampling across experiments, generates a recommended allocation, and applies it ONLY if the user has enabled auto-rebalance in Settings. Otherwise, it writes to portfolio_insights as a recommendation."

### 5. Billing Impact — Add to billing section

Find the billing/pricing section. Add:

```
Portfolio Intelligence billing:
  - Assayer Score computation: free (server-side, no AI cost)
  - AI Insight generation: ~$0.05 per generation (Sonnet, ~2K tokens)
  - Auto-rebalance computation: free (server-side math, no AI cost)
  - Insight applies that trigger ad platform changes: no additional charge (already covered by experiment hosting)

Plan gating:
  - Free/PAYG: Assayer Score visible on Lab cards (computed for all)
  - Pro: + AI Insight card + [Apply suggestions] + Portfolio Notification
  - Team: + Budget tab + Custom allocation sliders + Auto-rebalance toggle
```

### 7. Distribution Plan Generator — New subsection

Find `### Distribution Adapter Architecture` (Section 2). After it, add a new subsection:

Title: `### Distribution Plan Generator`

Content:

```
The Distribution Plan Generator produces a recommended multi-channel distribution
strategy for Phase F (Distribution Approval Gate). It runs when a user clicks
"Continue to Distribution" after Content Check / Walkthrough.

API Route:

POST /api/experiments/:id/distribution/plan
  - Generates a recommended distribution plan for the experiment
  - Inputs: experiment level, type, target_user, description, thesis, user plan tier, connected channels
  - Output: DistributionPlan (see schema below)
  - Auth: required

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

Budget Recommendation Algorithm:

1. Determine budget range from experiment level:
   - L1 (Pitch):    5000-15000 cents ($50-150) — minimal viable signal
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

Phase-Gated Budget Progression:

When an experiment completes an /iterate cycle:
  - If verdict = SCALE and current phase = 1 → suggest Phase 2 budget (2x-3x increase)
  - If verdict = SCALE and current phase = 2 → suggest Phase 3 budget
  - If verdict = REFINE → maintain current budget, optimize channel mix
  - If verdict = KILL/PIVOT → suggest stopping spend

This progression is surfaced through the AI Insight card (Portfolio Intelligence)
for users with multiple experiments, or via notification for single-experiment users.
```

Also add the new API route to the existing API route list (the `# Distribution` section in the route table):

```
# Distribution
GET    /api/experiments/:id/distribution        — list distribution campaigns
POST   /api/experiments/:id/distribution/plan   — generate recommended distribution plan  ← NEW
POST   /api/experiments/:id/distribution/sync   — force sync metrics from ad platform
POST   /api/experiments/:id/distribution/manage — pause/resume/adjust campaigns
```

### 8. Distribution ROI — Add to verdict/metrics sections

Find the verdict section (Flow 5) where it discusses the verdict page output. Add:

```
### Distribution ROI

Distribution ROI is computed during the verdict process and displayed on the verdict page.
It answers: "Was the ad spend worth it?"

Computation (runs as part of verdict generation in metrics cron):

  total_spend_cents = SUM(distribution_campaigns.spend_cents) for this experiment
  total_activations = COUNT(activate events from PostHog) for this experiment
  cpa_cents = total_spend_cents / max(total_activations, 1)
  signal_ratio = weighted average of all dimension ratios (same weights as Assayer Score Signal)
  roi_display = "{$spent} spent → {signal_ratio}x signal"

Storage:
  Written to experiment_decisions.distribution_roi (jsonb):
  {
    "total_spend_cents": 4700,
    "total_activations": 8,
    "cpa_cents": 588,
    "signal_ratio": 3.2,
    "display": "$47 spent → 3.2x signal",
    "best_channel": "google-ads",
    "best_channel_cpa_cents": 425,
    "channel_breakdown": [
      { "channel": "google-ads", "spend_cents": 3200, "activations": 6, "cpa_cents": 533 },
      { "channel": "meta-ads", "spend_cents": 1500, "activations": 2, "cpa_cents": 750 }
    ]
  }

When displayed on verdict page:
  - SCALE verdict: "Google Ads worked, Meta didn't" — actionable channel guidance
  - KILL verdict: "$47 spent → 0 activations. You saved ~3 months of building."
  - Show channel breakdown table: Channel | Spend | Activations | CPA
  - Highlight best-performing channel
```

### 9. Consistency Check with ux-design.md

After making all changes, verify these cross-document invariants:

| UX Spec (ux-design.md) | Technical Spec (product-design.md) | Must Match |
|-------------------------|-----------------------------------|------------|
| Lab cards show ★ Score | experiments.assayer_score column exists | ✅ |
| AI Insight shows when 2+ running | /api/portfolio/insight returns null when < 2 | ✅ |
| Budget tab is Team plan only | /api/portfolio/budget requires Team plan | ✅ |
| [Apply suggestions] is Pro+ | /api/portfolio/insight/:id/apply requires Pro+ | ✅ |
| Score range 0-100 | CHECK constraint on assayer_score | ✅ |
| Portfolio Notification has ★ health | portfolio_insights.portfolio_health exists | ✅ |
| Comparison shows Score + CPA | Both derivable from experiments + metric_snapshots | ✅ |
| Mobile NEEDS ATTENTION = score < 20 OR verdict_ready | Matches score-to-status mapping | ✅ |
| Phase F shows AI-recommended channels + budgets | POST /api/experiments/:id/distribution/plan exists | ✅ |
| Verdict page shows "$X spent → Y.Zx signal" | experiment_decisions.distribution_roi exists | ✅ |
| Budget range adapts to experiment level | Plan Generator has L1/L2/L3 budget ranges | ✅ |

## Rules

- Keep all existing content that is not explicitly mentioned above. Do NOT remove or rewrite existing sections.
- Follow the same SQL style (lowercase keywords, snake_case names) as existing tables.
- Follow the same markdown structure (## for sections, ### for subsections) as the existing document.
- All new tables must have RLS policies matching the pattern of existing tables.
- API routes follow the existing `/api/` path convention.
- Do not add UI wireframes — that's ux-design.md's job.
- Do not reference portfolio-distribution-design.md or mvp-budget-playbook.md in the output — product-design.md should be self-contained.

## Verification

After editing, verify:
1. `experiments` table has `assayer_score` and `score_updated_at` columns
2. `portfolio_insights` table exists with RLS
3. `budget_allocations` table exists with RLS
4. 6 new API routes documented under Portfolio Intelligence API
5. Assayer Score formula is fully specified
6. Cron table has 3 new entries
7. Billing section covers all portfolio features
8. No SQL syntax errors in table definitions
9. Distribution Plan Generator subsection exists with `DistributionPlan` interface and budget algorithm
10. `POST /api/experiments/:id/distribution/plan` added to the Distribution routes list
11. Distribution ROI subsection exists with computation formula, storage schema, and display rules
12. `experiment_decisions.distribution_roi` jsonb schema is defined
