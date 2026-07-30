# Assayer UX Design — World-Champion User Flow

> "Know if it's gold before you dig."
>
> This document defines the complete user experience for Assayer.
> It is the UX source of truth — session prompts and implementation derive from this.
> When this document and `docs/assayer-product-design.md` conflict, this document wins.

---

## First Principles

### What Assayer Is

Strip away all SaaS packaging. Assayer is a **verdict machine**.

- Input: an uncertain idea ("Should I build this?")
- Output: a certain verdict (SCALE / REFINE / PIVOT / KILL)

A real-world assayer (metallurgist) takes a rock sample, runs chemical tests, and tells you whether it's gold. You don't need to understand chemistry — you need an answer.

The core UX metric is not "page count" or "feature coverage" but **time and cognitive cost from uncertainty to certainty**.

### Three Axioms

**Axiom A: Value before commitment.**
Users should see what Assayer can do before being asked to sign up. Let AI perform first — signup is the gate to save results. Think Midjourney: you see the image's impact, then you pay.

**Axiom B: Process is product.**
Assayer's core value is not just the final SCALE/KILL verdict — it's the **AI analysis process itself**. Watching AI research your market, generate hypotheses, design variants educates users in scientific validation thinking. Hiding this behind a loading spinner is a crime.

**Axiom C: Experiments are stories, not database records.**
Every experiment has a clear narrative arc: birth (spec) → test (data) → verdict. The UX should reflect this narrative structure, not lay all information in equal-weight tabs.

### The Moat

```
Lovable:   Idea → Code → Deploy → [user figures it out]
Replit:    Idea → Code → Deploy → [user figures it out]
Assayer:   Idea → Code → Deploy → Distribute → Measure → Verdict
                                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                  This entire segment is the moat
```

No competitor automates Deploy → Distribute → Measure → Verdict. The UX must make this loop visible, controllable, and understandable.

### The Control Model

Assayer has a strict separation between what users control and what the platform controls:

| Users control (the Spec) | Platform controls (the Implementation) |
|--------------------------|----------------------------------------|
| Hypotheses | Code, HTML, CSS |
| Variant messaging | Layout, component structure |
| Funnel thresholds | Analytics instrumentation |
| Behaviors (given/when/then) | A/B split routing |
| Distribution channel selection | Ad platform API calls |

**Users describe WHAT to test. The platform decides HOW to build and measure it.** This is the chemist/assayer relationship — the client brings the rock, the assayer runs the test. The client never touches the spectrometer.

This principle governs every post-build interaction. Users never edit code. They edit the spec — or describe what's wrong in natural language — and the platform translates that into code changes.

---

## Emotional Arc

World-champion UX designs emotions, not features.

```
Curiosity → Awe → Investment → Confidence → Trust → Anticipation → Control → Clarity → Action
    |         |        |            |          |          |             |         |        |
 Landing   AI Spec   Edit      Quality     Distribute   Deploy     Watch      Verdict  Next
                     Spec      Gate +      Approval     Live       Traffic             Step
                               Walkthrough
```

- **Curiosity**: one input field + "Know if it's gold"
- **Awe**: watching AI dissect your idea in real-time — most users have never seen AI analyze a business idea like this
- **Investment**: editing hypotheses and variants — collaborating with AI, not passively receiving
- **Confidence**: Quality Gate shows every feature works; Walkthrough lets users verify with their own eyes. Users know what they're shipping.
- **Trust**: seeing distribution plan + "Google/Meta bill you directly"
- **Anticipation**: experiment is live, traffic is flowing
- **Control**: daily check-ins with real-time per-channel data — not a black hole
- **Clarity**: the verdict arrives — whether SCALE or KILL, you finally know
- **Action**: upgrade, adjust, or test the next idea

---

## Pricing & Plans

### First-Principles Pricing

Assayer's value is proportional to the number of **verdicts** a user gets. A verdict saves weeks to months of building the wrong thing ($10K-$300K value). Pricing axioms:

1. **Value = verdicts, not tool access.** Charge aligned with verdict delivery (unchanged)
2. **PAYG as default entry → subscription as volume discount.** $10 first experiment beats $99 subscription barrier. Users upgrade naturally when monthly spend exceeds subscription value
3. **All-Opus AI quality → operation-level pricing covers costs.** Every skill runs on Opus 4.6. Per-operation pricing absorbs the higher token cost transparently
4. **Three-layer protection: structural constraints → token budgets → operation pricing.** Structural limits (spec-locked behaviors, round boundaries) prevent runaway scope. Token budgets cap compute per operation. Operation pricing ensures every execution is individually profitable

### Pricing Model: PAYG + Subscription

**PAYG (default, no commitment):**

| Operation | Price |
|-----------|-------|
| Spec generation | Free |
| Create L1 (Pitch) | $10 |
| Create L2 (Prototype) | $15 |
| Create L3 (Product) | $25 |
| Change (code modification) | $6 |
| Small fix (bug fix, tweak) | $2 |
| Content edit (text only) | Free |
| Auto-fix (platform obligation) | Free |
| Hosting (per active experiment) | $5/mo |

**Subscriptions (volume discount):**

| | **Free** | **PAYG** | **Pro $99/mo** | **Team $299/mo** |
|--|---------|---------|---------------|-----------------|
| Spec generation | Unlimited | Unlimited | Unlimited | Unlimited |
| Create experiments | 1 (lifetime) | per-operation | 3/mo (any level) | 10/mo |
| Modifications | -- | per-operation | 15/mo (pooled) | 60/mo (pooled) |
| Content edits | Free | Free | Free | Free |
| Auto-fix | Free | Free | Free | Free |
| Hosting | 30 days | $5/mo | 3 included | 10 included |
| Paid distribution | -- | -- | Yes | Yes |
| Portfolio Intelligence | Score | Score | Score + AI Insight | Score + AI Insight + Budget Optimizer |
| Team seats | 1 | 1 | 1 | 5 |
| Overage | -- | N/A | PAYG rates | PAYG 90% |
| Priority build | -- | -- | -- | Yes |

> Spec generation has no monthly quota (unlimited). Anti-abuse rate limits apply: anonymous sessions are limited to 3/24h, free accounts to 5/24h. These limits prevent automated abuse, not normal usage.

### Modifications Pool

Change + Small fix draw from the same pool (15 for Pro, 60 for Team). The system classifier determines type; the user doesn't choose. No separate quotas = no unfair overage when one type runs out.

### Operation Classifier

Before execution, AI (Haiku, ~$0.001) classifies the modification as Change ($6) or Small fix ($2). The user sees the price before confirming. Default to Change on ambiguity (protects margin).

### Plan Design Rationale

**Free tier gives one COMPLETE experiment, not a crippled trial.** A user can go from idea → spec → build → deploy → distribute (free channels) → verdict. This is the cheapest CAC in SaaS — a KILL verdict on their first experiment sells the product better than any marketing.

**Spec generation is nearly unlimited** because it costs ~$2.50 (P50) and is the Midjourney "first image" moment — the strongest conversion driver. At 3/24h anonymous rate limit, max acquisition cost is ~$7.50/session — cheaper than any paid ad click.

**PAYG as default entry point.** $10 for a first L1 experiment < $99 subscription barrier. Users naturally upgrade at ~$90/mo spend when the subscription becomes the better deal.

**Pro at $99/mo.** 3 creates + 15 mods = $120 PAYG value (18% savings). Margin: 38% normal usage, 15% heavy usage. The price reflects all-Opus quality — every operation runs on the best model.

**Paid distribution channels (Google/Meta Ads) are the Pro upgrade trigger.** Free/PAYG users run experiments with organic traffic. When organic isn't enough (REACH doesn't hit threshold), the system naturally suggests "unlock paid channels to reach more people." The upgrade motivation is data-driven, not feature-gated.

**Auto-fix is always free.** The platform caused the bug, the platform pays to fix it. This is a trust-building principle.

**Creates tiered by level.** L1 ($10) vs L3 ($25) reflects the ~3x cost difference in AI compute. Makes quick L1 pitch tests cheap — encouraging the portfolio approach.

### Pricing UX

How prices appear in the interface:

- **Pre-modification**: show classification + price + remaining quota (subscribers)
- **Experiment page footer**: `Modifications: 11/15 used this month` (subscribers only, low-key)
- **Near quota exhaustion**: warning + upgrade CTA
- **Free operations** (content edits, auto-fix, spec gen): no cost indicator shown

### PAYG → Pro Conversion Ladder

Month 1: $29 PAYG spend → Month 2: $56 → Month 3: $91 → system suggests "Pro is $99 with more included" → natural upgrade. The platform tracks cumulative PAYG spend and surfaces the upgrade prompt when subscription becomes cheaper.

### Plan Visibility in UX

Plans are NOT promoted on the landing page or during spec generation. They appear:
- **Signup Gate**: "Free plan includes 1 complete experiment" (reassurance, not upsell)
- **Settings → Billing**: full plan comparison + PAYG balance display
- **Natural upgrade triggers**: when the user hits a plan limit, the data suggests paid channels would help, or PAYG spend exceeds Pro value

---

## Information Architecture

```
Landing (no auth)
  +-> The Assay (no auth) -- spec materializes in final form
      |   (same screen: generates → becomes editable)
      |   +-> Pre-flight caution (if AI detects concerns)
      |       |-> [Proceed anyway] continues to launch
      |       +-> [Adjust idea & re-check] returns to idea input
      +-> Signup Gate -- triggered on edit or launch
          +-> Build & Launch (level-dependent flow)
              |
              |   L1: Build → Deploy → Content Check → Distribution
              |   L2/L3: Build → Quality Gate → Deploy → Walkthrough → Distribution
              |
              +-> Channel Setup (if first time)
                  +-> Distribution Approval Gate
                      +-> Distribution Live
                          +-> Experiment Live
                              |-> Funnel Scorecard (hero)
                              |-> Traffic Overview
                              |-> Live Assessment
                              |-> Alert Banners (error/edge states)
                              |-> Details: Hypotheses, Variants,
                              |    Distribution, Raw Data, History
                              |-> [Request Change] (natural language)
                              +-> Verdict (full-screen moment)
                                  |-> Distribution ROI
                                  +-> Next action
                                      |-> REFINE: return to Assay (edit mode, Round N)
                                      +-> PIVOT: return to Landing (pre-filled)

Lab (Your Lab)
  |-> Running (sorted by Assayer Score)
  |     |-> Per-experiment card (★ Score + R/D/M ratios)
  |     +-> AI Insight (when 2+ running, 30+ visits)
  |-> Verdict Ready (needs attention)
  |-> Completed (historical verdicts)
  |-> Linked rounds (Round 1 → Round 2)
  |-> Pivot lineage (Original → Pivot)
  |-> [Budget] tab (Team plan)
  |     |-> Portfolio budget overview
  |     |-> AI Budget Optimizer
  |     +-> Custom allocation sliders
  +-> [+ New Idea]

Settings
  |-> Account
  |-> Distribution Channels (OAuth management)
  |-> Billing / Plan
  +-> Connected Accounts (login OAuth)

Notifications (email + optional browser push)
  |-> Experiment live
  |-> First traffic milestone (~24h)
  |-> Mid-experiment snapshot (~Day 3)
  |-> Verdict ready
  |-> Budget alert
  |-> Dimension dropping
  |-> Bug auto-fixed (L2/L3)
  +-> Portfolio insight ready (when 2+ running)
```

---

## Screen-by-Screen Specification

### Screen 1: Landing — "One sentence for one answer"

```
+--------------------------------------------------------------+
|                                                              |
|           Know if it's gold before you dig.                  |
|                                                              |
|    Describe your idea -> AI designs the experiment ->        |
|    code deploys -> traffic flows from 6 channels ->          |
|    you get a verdict in days, not months.                    |
|                                                              |
|  +--------------------------------------------------------+  |
|  |  Describe your business idea...                        |  |
|  |                                                        |  |
|  |                                          [Test it ->]  |  |
|  +--------------------------------------------------------+  |
|                                                              |
|  Or try:  [AI resume builder]  [Meal prep planner]           |
|                                                              |
|  312 ideas tested . 67 confirmed worth building              |
|                                                              |
+--------------------------------------------------------------+
```

**Design decisions:**

- **One input field is the entire above-the-fold.** Not hero + feature grid + pricing + testimonials. One input field. Because Assayer's value proposition can be proven in a single interaction.
- **No login required.** Type idea -> see AI analysis immediately. Signup gate comes after results.
- **Sub-tagline mentions "6 channels"** — makes the automation concrete. Users don't need to understand Google Ads API. They need to know "Assayer handles my traffic."
- **Bottom numbers are social proof** — directly demonstrating the core function is being used.
- **Type/Level selectors** fold into "Advanced options", defaulting to web-app + L1. 90% of first-time users don't need to change these.
- **No pricing on this page.** The landing page sells the experience, not the plan. Pricing appears after the user has seen value (Axiom A).

---

### Screen 2: The Assay — Output Materializing in Final Form

When the user clicks "Test it", they don't see a streaming text log or a loading spinner. They see **the Review & Edit page itself, starting empty and filling in as AI generates.**

The spec stream and the review screen are the SAME screen. This follows the Midjourney/Figma principle: show the output materializing in its final form, not a log of the process generating it.

#### During generation (no auth required)

```
+--------------------------------------------------------------+
|  Assaying: "AI-powered invoice tool for freelancers"         |
|                                                              |
|  [name appearing...]  .  L1 Pitch  .  web-app                |
|  Build: ~$___  .  Ad budget: ~$___  .  ~_ days               |
|                                                              |
|  PRE-FLIGHT                                                  |
|  ok Market   ok Problem   [..] Competition   [ ] ICP         |
|              ^ checkmarks appear one by one with micro-animation
|                                                              |
|  HYPOTHESES                                                  |
|  +--REACH----"Ad CTR > 2%"---> CTR-----------P:90---+  <fade in
|  +--DEMAND---[generating...]--------------------------+  <pulse
|  +--[empty card slot]--------------------------------+  <waiting
|                                                              |
|  VARIANTS                                                    |
|  +----------+  +----------+  +----------+                    |
|  | [empty]  |  | [empty]  |  | [empty]  |  <- slots waiting  |
|  +----------+  +----------+  +----------+                    |
|                                                              |
|  [Regenerate] (disabled)       [Create & Launch ->] (disabled)|
+--------------------------------------------------------------+
```

As AI streams, the page fills in progressively:
1. Pre-flight checkmarks light up one by one (ok / caution / fail)
2. Hypothesis cards fade in from skeleton to real content
3. Variant cards fill from empty shells to full headline + subheadline + CTA
4. Cost estimates appear as AI calculates them
5. Edit icons [e] are grayed out during generation

#### Generation complete (still no auth)

```
+--------------------------------------------------------------+
|  ai-invoice-tool  .  L1 Pitch  .  web-app                   |
|  Build: ~$150  .  Ad budget: ~$200  .  ~7 days               |
|                                                              |
|  PRE-FLIGHT ------------------------------------- 4/4 passed |
|  ok Market  ok Problem  ok Competition  ok ICP               |
|                                                              |
|  HYPOTHESES ------------------------------------- 3 generated|
|  +----------------------------------------------------------+|
|  | REACH    "Ad CTR > 2%"              -> CTR          [e] |||
|  | DEMAND   "Signup rate > 5%"         -> signups      [e] |||
|  | MONETIZE "Pricing clicks > 7%"      -> clicks       [e] |||
|  |                                      [+ Add]            |||
|  +----------------------------------------------------------+|
|                                                              |
|  VARIANTS --------------------------------------- 3 generated|
|  +------------+  +------------+  +------------+             |
|  | time-saver |  |  ai-magic  |  | cost-cutter|             |
|  | "Save 5    |  | "Your AI   |  | "Cut Costs |             |
|  |  Hours..." |  |  Invoice.." |  |  by 80%"  |             |
|  +------------+  +------------+  +------------+             |
|                                                              |
|  -- Generation complete. Edit anything, or launch. ----------|
|                                                              |
|  WHAT HAPPENS NEXT                                           |
|  1. Code scaffolded & deployed (~2 min)                      |
|  2. Distribution launched across connected channels          |
|  3. Data flows in automatically                              |
|  4. Verdict in ~7 days                                       |
|                                                              |
|  [Regenerate]                        [Create & Launch ->]    |
+--------------------------------------------------------------+
```

#### Pre-flight caution or failure

Not every idea passes pre-flight cleanly. When AI analysis finds a concern, the user sees it **before** launch — with a professional opinion and options.

```
+--------------------------------------------------------------+
|  AI Invoice Tool                              [Edit title]    |
|                                                              |
|  PRE-FLIGHT CHECK                                            |
|                                                              |
|  ok  Market           Large addressable market               |
|  ok  Problem          Real pain validated (340+ forum threads)|
|  ok  ICP              Solo freelancers, US/EU — identifiable  |
|  !!  Competition      15+ funded competitors detected         |
|                                                              |
|  -- AI Opinion -------------------------------------------- |
|                                                              |
|  "I found 15+ funded competitors in this space. Your         |
|   differentiation ('automatic line-item categorization')     |
|   is shared by at least 8 of them. This doesn't mean         |
|   you shouldn't test — but your variant messaging must       |
|   find an angle competitors haven't claimed."                |
|                                                              |
|  [Adjust idea & re-check]           [Proceed anyway ->]      |
|                                                              |
+--------------------------------------------------------------+
```

**Design decisions:**

- **Assayer is a consultant, not a vending machine.** It gives professional opinions but never blocks. [Proceed anyway] is always available.
- **Cautions, not errors.** The label is "!!" not "FAIL" — because market validation is the whole point of running the experiment.
- **AI opinion is conversational.** Not a data dump. A sentence a human advisor would say.
- **[Adjust idea & re-check]** returns to the idea input with the competition context visible, so the user can refine their angle.

At this point, clicking [Create & Launch ->] or editing any field triggers the **signup gate** (Screen 3) if not authenticated. After auth, the user returns to this exact screen with edit icons active and the "Create & Launch" button ready.

**Why this is better than a separate stream screen + review screen:**

- **Zero screen transitions.** The user watches their spec materialize on the page they'll use to edit it. When generation finishes, they're already oriented — no cognitive overhead.
- **"Process is product" is preserved.** Users still watch AI research their market and generate hypotheses — but the output appears in its final layout, not as a throwaway text log.
- **Builds familiarity during the wait.** By the time generation completes, users already know where hypotheses are, where variants are, and what they can edit.
- **The Figma model:** AI output appears on your canvas. When it's done, you're already in edit mode.

---

### Screen 3: Signup Gate — "Save your experiment"

Triggered when an unauthenticated user tries to edit a field or click "Create & Launch".

```
+--------------------------------------------------------------+
|                                                              |
|  ok Pre-flight passed. Your experiment spec is ready.        |
|                                                              |
|  Sign up to save this experiment and start testing.          |
|  Your free account includes 1 complete experiment.           |
|                                                              |
|  [Continue with Google]                                      |
|  [Continue with GitHub]                                      |
|  -- or --                                                    |
|  [email] [password] [Sign up ->]                             |
|                                                              |
|  Already have an account? [Sign in]                          |
|                                                              |
+--------------------------------------------------------------+
```

At this point the user has already watched their entire spec materialize. They sign up not to "try it out" but to **save and launch value that already exists**. This is a fundamentally different psychological motivation. Conversion rate will be much higher.

After auth, the user returns to the same spec page — now fully editable with "Create & Launch" active.

**Design decisions:**

- All AI-generated fields have an edit icon [e] — click to inline edit.
- "Regenerate" re-calls AI (re-runs the materialization). "Create & Launch" persists and starts the launch flow.
- **"Your free account includes 1 complete experiment"** — reassurance, not upsell. The user knows they're getting the real thing.
- **"What happens next"** section previews the automation pipeline so users know what to expect.
- **Button says "Create & Launch"**, not "Create Experiment". In the automated loop, creating and launching are one action. But there's a safety net: distribution has an approval gate (next screen).
- Information density is high but well-layered: pre-flight -> hypotheses -> variants -> next steps, importance descending top-to-bottom.
- Users should be able to scan everything in 30 seconds and decide whether to edit.

---

### Screen 5: Build & Launch — Level-Dependent Flow

Clicking "Create & Launch" triggers the launch flow. **The flow adapts based on experiment level** because the risk profile is fundamentally different:

- **L1 (Pitch):** A landing page. Almost nothing can go wrong. Speed matters most.
- **L2 (Prototype):** Functional pages + DB. Code bugs can produce invalid data. Verification matters.
- **L3 (Product):** Auth + payments. Bugs can waste real money and break trust. Maximum verification.

```
L1:    Build → Deploy → Content Check → Distribution Approval → Live

L2:    Build → Quality Gate → Deploy → Walkthrough → Distribution Approval → Live
                ↑        |
                +- Fix --+

L3:    Build → Quality Gate → Deploy → Walkthrough → Distribution Approval → Live
                ↑        |              ↑        |
                +- Fix --+              +- Fix --+
```

#### Phase A: Build & Deploy — Experiment Materializing

The same "output materializing in final form" principle from Screen 2. Users don't see terminal output — they see **their experiment taking shape in a live preview**.

```
+--------------------------------------------------------------+
|  Building your experiment...                                 |
|                                                              |
|  +--------------------------------------------------------+  |
|  |                                                        |  |
|  |          [LIVE PREVIEW: variant "time-saver"]          |  |
|  |                                                        |  |
|  |     "Save 5 Hours Every Week on Invoicing"             |  |
|  |                                                        |  |
|  |     Your AI assistant generates professional           |  |
|  |     invoices from time logs in seconds.                |  |
|  |                                                        |  |
|  |     [Get Started Free]                                 |  |
|  |                                                        |  |
|  +--------------------------------------------------------+  |
|                                                              |
|  [< time-saver]  [ai-magic]  [cost-cutter >]   <- carousel  |
|                                                              |
|  ============================================== 78%          |
|  Deploying to ai-invoice-tool.assayer.io...                  |
|                                                              |
|  ok Experiment saved                                         |
|  ok Landing page scaffolded (3 variants)                     |
|  .. Deploying to production...                               |
|                                                              |
|  [v View build logs]                                         |
|                                                              |
+--------------------------------------------------------------+
```

Uses Supabase Realtime streaming (`exec:{execution_id}` channel) to show Cloud Run Job progress and update the preview as assets become available.

**Why this is better than terminal output:**

- **Users see what they're shipping.** The landing page preview shows the actual output — headlines, CTAs, value prop — not deployment logs. This builds confidence ("that looks right") and excitement ("I made that").
- **Variant carousel fills the wait.** Instead of watching logs scroll, users browse their 3 variants. By the time deploy finishes, they've already reviewed their messaging angles.
- **Progress bar, not a log.** A simple progress bar communicates "how long" without cognitive load. Technical users who want logs can expand "View build logs".

#### Phase B (L2/L3 only): Quality Gate

For L2/L3 experiments, the system automatically verifies every behavior before deployment. Each behavior in the spec has a `tests[]` array — the Quality Gate runs these tests and shows results.

```
+--------------------------------------------------------------+
|  Building your experiment...                                 |
|                                                              |
|  +--- VARIANT PREVIEW (carousel) ---------------------------+|
|  |  "Save 5 Hours Every Week on Invoicing"                  ||
|  |  [Get Started Free]                                      ||
|  +----------------------------------------------------------+|
|  [< time-saver]  [ai-magic]  [cost-cutter >]                |
|                                                              |
|  BUILD                                                       |
|  ok  Code scaffolded (4 pages, 6 API routes, 3 tables)       |
|  ok  Dependencies installed                                  |
|                                                              |
|  QUALITY GATE                                                |
|  ok  Landing page renders                                    |
|  ok  Signup flow completes                                   |
|  ..  Invoice generation                          testing...  |
|  --  Dashboard renders                           queued      |
|  --  Payment checkout                            queued      |
|                                                              |
|  ============================================== 45%          |
+--------------------------------------------------------------+
```

**Auto-fix loop:** When a test fails, AI automatically diagnoses and fixes the issue — no user intervention required.

```
+--------------------------------------------------------------+
|  QUALITY GATE                                                |
|  ok  Landing page renders                                    |
|  ok  Signup flow completes                                   |
|  !!  Invoice generation: API returns 500      [Details v]    |
|                                                              |
|  AI is diagnosing the issue...                               |
|  > Supabase query references non-existent column 'amount'    |
|  > Fixing: add 'amount' column to invoices table migration   |
|  > Re-testing...                                             |
|                                                              |
|  ============================================ retry 1/3      |
+--------------------------------------------------------------+
```

Auto-fix succeeded:

```
|  ok  Invoice generation: fixed (auto)          [View fix]    |
```

Auto-fix failed (after 3 attempts):

```
|  !!  Invoice generation: couldn't auto-fix     [Details v]   |
|                                                              |
|  Options:                                                    |
|  [Simplify feature]  AI implements a simpler version         |
|  [Skip feature]      Launch without this; affects MONETIZE   |
|                      testing but REACH + DEMAND still valid  |
|  [Describe fix]      Tell AI what's wrong in your words      |
+--------------------------------------------------------------+
```

**Three fallback options (no code editing, ever):**

| Option | What it does | User needs |
|--------|-------------|------------|
| **Simplify** | AI re-implements with reduced complexity | Nothing — fully automatic |
| **Skip** | Feature disabled; system marks affected hypotheses | Nothing — one click |
| **Describe fix** | User explains the problem in natural language, AI re-attempts | A sentence describing what's wrong |

**Design principle:** The user never touches code. If auto-fix fails and "Describe fix" also fails, Assayer contacts the user for manual investigation — but this should be extremely rare (<2% of L2 builds).

Quality Gate passes → deploy begins automatically.

#### Phase C (L1): Content Check

After deploy completes for an L1 experiment, the user sees the live site with an optional content editing step. This is NOT a website builder — it's a text verification layer constrained to spec fields.

```
+--------------------------------------------------------------+
|  Your experiment is live.                                    |
|                                                              |
|  +--------------------------------------------------------+  |
|  |                                                        |  |
|  |          [LIVE PREVIEW: variant "time-saver"]          |  |
|  |                                                        |  |
|  |     "Save 5 Hours Every Week on Invoicing"       [e]   |  |
|  |                                                        |  |
|  |     Your AI assistant generates professional     [e]   |  |
|  |     invoices from time logs in seconds.                |  |
|  |                                                        |  |
|  |     [Get Started Free]                           [e]   |  |
|  |                                                        |  |
|  +--------------------------------------------------------+  |
|                                                              |
|  [< time-saver]  [ai-magic]  [cost-cutter >]                |
|                                                              |
|  ok Live at ai-invoice-tool.assayer.io          [Visit ->]   |
|                                                              |
|  Looks good?  [Continue to Distribution ->]                  |
|               [Review & edit content]                        |
|                                                              |
+--------------------------------------------------------------+
```

**Content Check is optional.** 90% of users will click [Continue to Distribution]. But for the 10% who notice a typo or want to tweak wording, it's available.

> **Content edits are always free** — no AI token cost, just a database update. This is intentional: users should never hesitate to fix a typo.

**What can be edited vs. what cannot:**

| Can edit | Cannot edit |
|----------|------------|
| Headline text | Layout / spacing |
| Subheadline text | Colors / fonts |
| CTA button text | Component structure |
| Pain points text | Analytics instrumentation |
| Promise / Proof text | A/B split logic |
| | Images / icons |
| | CSS styles |

**How it works:** Clicking [e] on any text element opens an inline text editor. The edit updates the corresponding field in the `variants` table. The landing page loads text content from the variants API, so changes are reflected in ~2 seconds — **zero rebuild, zero redeploy.**

Edited fields show an `(edited)` badge. When editing one variant's text, the system prompts: "You edited variant 'time-saver'. Review the other 2 variants too?" to prevent A/B contamination.

**Why not a full page editor:** Giving users HTML/CSS control would turn Assayer into Lovable — a building tool, not a validation system. Content Check is Assayer's "inpainting" — a constrained, local fix, not an open canvas.

#### Phase D (L2/L3): Walkthrough

After deploy completes for L2/L3 experiments, the user walks through the golden_path on their actual live experiment. The Quality Gate proved the code works — the Walkthrough proves it matches the user's intent.

```
+--------------------------------------------------------------+
|  Your experiment is live at ai-invoice-tool.assayer.io       |
|                                                              |
|  Walk through your experiment before driving traffic:        |
|                                                              |
|  GOLDEN PATH                                                 |
|  1. Visit landing page                         [Open ->]     |
|     ok Confirmed                                             |
|                                                              |
|  2. Click CTA & sign up                        [Open ->]     |
|     .. Waiting for your confirmation                         |
|                                                              |
|  3. Generate first invoice                      Locked       |
|  4. View dashboard                              Locked       |
|  5. See pricing page                            Locked       |
|                                                              |
|  [Skip walkthrough -- looks good]                            |
+--------------------------------------------------------------+
```

User clicks [Open ->] → new tab opens to the actual experiment page → user interacts with it → returns to confirm or flag an issue.

If a step doesn't look right:

```
|  2. Click CTA & sign up                        [Open ->]     |
|     What's wrong?                                            |
|     +------------------------------------------------------+ |
|     | The signup form asks for phone number but I only     | |
|     | want email + password                                | |
|     +------------------------------------------------------+ |
|     [Fix this ->]                                            |
```

[Fix this] triggers a micro-`/change`: AI interprets the description → modifies code → re-tests → redeploys → user re-verifies. The user never sees code — only the result.

> Walkthrough fixes are classified as Small fix ($2) or Change ($6) by the operation classifier. The user sees the price before confirming. Content-only issues (typo, wording) use the same inline text editing as L1's Content Check — always free, zero rebuild. This capability is available on the experiment page for all levels, not just during the L1 launch flow.

**Walkthrough is optional.** Power users who trust the Quality Gate can click [Skip walkthrough]. But first-time L2/L3 users need this safety net — they're about to spend real money on ads.

**The Walkthrough also catches spec-intent gaps.** Quality Gate verifies "code matches spec." Walkthrough verifies "spec matches what the user actually wanted." These are different failure modes:

| Failure type | Example | Caught by |
|-------------|---------|-----------|
| Code bug | Form crashes on submit | Quality Gate |
| Spec-intent gap | "I wanted PDF export, not plain text" | Walkthrough |
| Cosmetic mismatch | "This headline feels wrong" | Content Check (L1) / Walkthrough (L2+) |

#### Phase E: Channel Setup (first-time only)

New users who haven't connected any distribution channels see this between deploy verification and distribution approval:

```
+--------------------------------------------------------------+
|                                                              |
|  ok Code deployed to ai-invoice-tool.assayer.io              |
|                                                              |
|  Connect channels to start driving traffic:                  |
|                                                              |
|  RECOMMENDED (free, instant)                                 |
|  [ ] Twitter/X    Post threads to #buildinpublic             |
|  [ ] Reddit       Share on r/SaaS, r/startups                |
|  [ ] Email        Campaign via Resend                        |
|                                                              |
|  PAID (reach more people faster)          Pro plan required   |
|  [ ] Google Ads   Search ads . ~$0.15/click                  |
|  [ ] Meta Ads     Interest targeting . ~$0.30/click          |
|  [ ] Twitter Ads  Promoted tweets . ~$0.20/click             |
|                                                              |
|  Each takes ~60 seconds to connect.                          |
|                                                              |
|  [Connect Twitter ->]  (start with the easiest)              |
|                                                              |
|  [Skip -- I'll drive traffic myself]                         |
|                                                              |
+--------------------------------------------------------------+
```

**Design decisions:**

- **Free channels recommended first** — lower friction, indie hackers often have no ad budget.
- **Paid channels show "Pro plan required"** for Free/PAYG users — a natural, contextual upgrade prompt.
- **[Skip] must exist** — some users want to control their own traffic. Assayer doesn't force automation.
- **"Each takes ~60 seconds"** — sets expectation, reduces perceived effort.

#### Phase F: Distribution Approval Gate

After deploy (and Content Check / Walkthrough), AI has generated a distribution strategy. The page transitions to an approval gate:

```
+--------------------------------------------------------------+
|                                                              |
|  ok Live at ai-invoice-tool.assayer.io                       |
|                                                              |
|  === DISTRIBUTION PLAN ====================================  |
|                                                              |
|  AI recommends 4 channels for 7 days:                        |
|                                                              |
|  PAID                                                        |
|  +-------------+----------+----------------------------+    |
|  | Google Ads  | $120     | 8 keywords . search ads   |    |
|  | Meta Ads    | $80      | interest targeting . FB    |    |
|  +-------------+----------+----------------------------+    |
|  Total ad spend: $200 (billed directly by Google/Meta)       |
|                                                              |
|  ORGANIC                                                     |
|  +-------------+----------------------------------------+   |
|  | Twitter/X   | 5-tweet thread . #buildinpublic        |   |
|  | Reddit      | r/SaaS + r/startups . Show format      |   |
|  | Email       | 3-email sequence via Resend             |   |
|  +-------------+----------------------------------------+   |
|                                                              |
|  [Preview Creative v]                                        |
|                                                              |
|  -----------------------------------------------------------  |
|  You'll review all ad copy before it goes live.              |
|  Google/Meta bill you directly -- Assayer never touches      |
|  your ad budget.                                             |
|                                                              |
|  [Edit Plan]                [Launch Distribution ->]         |
|                                                              |
+--------------------------------------------------------------+
```

**[Preview Creative v]** expands to show:

```
  GOOGLE ADS PREVIEW -----------------------------------------------
  Headlines: "Save 5 Hours on Invoicing" | "AI Invoice Tool" | ...
  Descriptions: "Generate professional invoices from time logs..."
  Keywords: "freelancer invoice tool" [exact], "ai invoicing" [phrase]

  TWITTER THREAD PREVIEW -------------------------------------------
  1/5 "I spent 3 months building an app nobody wanted. Then I found..."
  2/5 "The problem: 90% of startup founders validate by asking friends..."
  3/5 ...

  REDDIT POST PREVIEW (r/SaaS) ------------------------------------
  Title: "Show r/SaaS: I built an AI tool that generates experiment
          specs from a 2-sentence idea"
  Body: [preview]

  [Edit any field]
```

**Design principles:**

- **"Google/Meta bill you directly"** — eliminates the biggest trust concern. Users' money doesn't flow through Assayer.
- **All creative is previewable and editable** — users won't blindly trust AI-generated ad copy. But 90% will just click Launch.
- **Organic and Paid separated** — different psychological commitment. Organic is free and low-risk. Paid costs money.
- For Free/PAYG plans, only organic channels appear — paid channels show as locked with upgrade prompt.

#### Phase G: Distribution Live (confirmation)

After user clicks "Launch Distribution":

```
+--------------------------------------------------------------+
|                                                              |
|  Your experiment is live and distributing.                   |
|                                                              |
|  ai-invoice-tool.assayer.io                       [Visit ->] |
|                                                              |
|  ok Google Ads    Campaign created . pending review (~1h)    |
|  ok Meta Ads      Campaign live                              |
|  ok Twitter/X     Thread published                           |
|  ok Reddit        Posted to r/SaaS, r/startups               |
|                                                              |
|  What happens now:                                           |
|  . Traffic flows in from 4 channels                          |
|  . Metrics sync every 15 minutes                             |
|  . You'll get a verdict in ~7 days                           |
|  . We'll notify you at milestones (100 clicks, etc.)         |
|                                                              |
|  [Go to experiment ->]                                       |
|                                                              |
+--------------------------------------------------------------+
```

---

### Screen 6: Experiment Page — Scorecard as Hero

The main experiment page. Users come back daily. They want ONE answer: **are we on track?**

```
+--------------------------------------------------------------+
|  AI Invoice Tool          ACTIVE    Day 3/7    L1 Pitch      |
|  ai-invoice-tool.assayer.io                       [Visit ->] |
|                                                              |
| === FUNNEL SCORECARD ======================================= |
|                                                              |
|  REACH     ################....  1.90x  PASS                |
|            CTR 3.8% / 2.0%      523 imp (high)              |
|                                                              |
|  DEMAND    ##############......  1.34x  PASS                |
|            6.7% signup / 5.0%   502 visitors (high)     |
|                                                              |
|  ACTIVATE  ....................  --     (requires L2)        |
|                                                              |
|  MONETIZE  #############.......  0.65x  LOW ! (signal)      |
|            4.5% clicks / 7.0%   89 clicks (directional)     |
|                                                              |
|  RETAIN    ....................  --     (requires L3)        |
|                                                              |
| === TRAFFIC ================================================ |
|                                                              |
|  502 clicks . $62 spent . $0.12 avg CPC                     |
|                                                              |
|  Google Ads   ############..  312 clicks  $52  CTR 3.8%     |
|  Twitter/X    ######........  112 clicks   --  free          |
|  Reddit       ####..........   56 clicks   --  free          |
|  Email        ##............   22 clicks   --  free          |
|                                                              |
|  Budget: $62 / $200 (31%)        [Pause All] [Adjust v]     |
|                                                              |
| === LIVE ASSESSMENT ======================================== |
|  Bottleneck: MONETIZE at 0.65x                              |
|  Best channel: Google Ads ($0.17/click, 3.8% CTR)           |
|  Projected: REFINE -- 4 more days for confidence            |
|                                                              |
|  [Analyze Now]  [Upgrade to L2]  [Request Change]           |
|                                                              |
| --- Details -------------------------------------------------|
|  [Hypotheses (3)]  [Variants (3)]  [Distribution]           |
|  [Raw Data]  [History]                                      |
|                                                              |
+--------------------------------------------------------------+
```

**Design decisions:**

1. **Scorecard first — user sees the answer, then scrolls to evidence.** The daily question is "am I on track?" — the scorecard answers it. Traffic is supporting evidence, viewed when a dimension is failing.
2. **Per-channel mini bar chart.** One glance to see which channel is working. No need to drill in.
3. **Budget progress.** How much spent / total. If nearly exhausted, user must decide: add more or stop.
4. **[Pause All] [Adjust v]** — users can manage distribution directly here, no separate page needed.
5. **Live Assessment includes "Best channel".** Not just telling you the bottleneck, but which channel is most efficient. Key input for REFINE decisions.
6. **[Request Change]** — opens the Change Request flow (see below).
7. **Details fold below.** Hypotheses, Variants, Distribution, Raw Data, History are second-tier information — click to expand. Most daily check-ins don't need these.

**Why not tabs?** Tabs imply equal-weight information. But 90% of visits only look at the scorecard. Putting hypotheses detail in a tab suggests it's as important as the scorecard — it's not.

**Action buttons change by state:**
- Active: [Pause] [Analyze Now] [Upgrade] [Request Change]
- Completed: [View Verdict] [Archive]
- Draft: [Deploy]

#### Change Request (on Experiment Page)

[Request Change] opens a natural-language change interface. The user describes what they want changed — never touches code.

**Before distribution (no traffic yet):**

```
+--------------------------------------------------------------+
|  Change Request                                              |
|                                                              |
|  What do you want to change?                                 |
|  +----------------------------------------------------------+|
|  | Change pricing from $19/mo to $9/mo and add a            ||
|  | "first month free" option                                 ||
|  +----------------------------------------------------------+|
|                                                              |
|  AI analysis:                                                |
|  . Update variant pricing_amount: $19 -> $9                  |
|  . Add "first month free" CTA variant                       |
|  . Modify pricing page component                            |
|  . Update hypothesis H3 threshold                           |
|  . Classification: Code change ($6)                          |
|  . Modifications: 11/15 remaining this month                 |
|  . Estimated time: ~90 seconds                              |
|                                                              |
|  [Apply Change  $6] ·························· [Cancel]      |
+--------------------------------------------------------------+
```

Flow: user describes change → AI shows impact analysis → user approves → /change → /verify → redeploy → return to experiment page.

**During active experiment (traffic is flowing):**

```
+--------------------------------------------------------------+
|  Change Request                                              |
|                                                              |
|  What do you want to change?                                 |
|  +----------------------------------------------------------+|
|  | Change pricing from $19/mo to $9/mo                       ||
|  +----------------------------------------------------------+|
|                                                              |
|  !! This experiment has been live for 3 days (142 clicks).   |
|                                                              |
|  Changing pricing will start a NEW ROUND because:            |
|  . 142 visitors saw $19/mo pricing                           |
|  . New visitors will see $9/mo pricing                       |
|  . Mixing this data would invalidate MONETIZE measurement    |
|                                                              |
|  Round 1 data will be preserved for comparison.              |
|                                                              |
|  [Start Round 2 with this change ->]            [Cancel]     |
+--------------------------------------------------------------+
```

**Core principle:** Feature changes during an active experiment = new Round. This protects data integrity — you can't change the test conditions while measuring. The system forces a clean data boundary.

#### Runtime Auto-Fix (L2/L3, automatic)

Not all bugs surface during the Quality Gate. Some appear only under real traffic (concurrency issues, edge-case inputs, real OAuth callbacks). The system detects these automatically.

> **Auto-fixes are always free to the user** — the platform caused the bug, the platform pays to fix it. This is a trust-building principle: users are never charged for Assayer's mistakes.

**Detection:** The 15-minute metrics sync cron checks for anomalies:
- DEMAND ratio = 0.0x with 50+ clicks → signup flow likely broken
- ACTIVATE ratio = 0.0x with 20+ signups → core action flow likely broken
- MONETIZE ratio = 0.0x with 30+ signups → payment page likely broken
- Any page returning 5xx errors in PostHog data

**Response (fully automatic, no user action):**
1. Metrics sync cron creates `operation_ledger` row (billing_source='free', price_cents=0) and `skill_executions` row
2. Triggers Cloud Run Job internally via `triggerCloudRunJob()` (shared function, service role key — not user JWT)
3. Cloud Run runs Playwright tests against the live experiment, simulating the golden_path
4. Identifies the failing step
5. AI diagnoses root cause
6. Applies fix via /change
7. Re-verifies
8. Redeploys
9. On completion: updates `operation_ledger` (free → no charge), creates `bug_auto_fixed` alert + notification (immediate, not batched)
10. If auto-fix fails after 3 retries: creates `dimension_dropping` alert, notifies user for manual action
11. Notifies user via email:

```
+--------------------------------------------------------------+
|                                                              |
|  Assayer                                                     |
|                                                              |
|  AI Invoice Tool -- Bug Auto-Fixed                           |
|                                                              |
|  Issue: Signup form validation rejected email addresses      |
|         containing "+" characters (e.g., user+test@gmail.com)|
|  Fix:   Updated email validation regex                       |
|  Impact: ~12 visitors may have been affected (3h window)     |
|                                                              |
|  Data note: Metrics from 14:00-17:00 UTC may be slightly    |
|  suppressed. /iterate will account for this when calculating |
|  your verdict.                                               |
|                                                              |
|  [View details]  [View experiment]                           |
|                                                              |
+--------------------------------------------------------------+
```

**Design principle:** The user doesn't need to do anything. Bug detected → bug fixed → user notified. The affected time window is flagged so /iterate can weight the data correctly.

---

### Screen 7: Verdict — The Most Important Screen

When /iterate produces a verdict, or the user clicks "Analyze Now", this should be a **full-screen moment**.

#### SCALE

```
+--------------------------------------------------------------+
|                                                              |
|                                                              |
|                        ^ SCALE                               |
|                                                              |
|            AI Invoice Tool passed all                        |
|            tested funnel dimensions.                         |
|                                                              |
|     REACH    1.90x ok     DEMAND    1.34x ok                |
|     ACTIVATE -- (L2)      MONETIZE  1.12x ok                |
|     RETAIN   -- (L3)                                        |
|                                                              |
|     --- DISTRIBUTION ROI ----------------------------        |
|     $200 spent . 502 clicks . $0.40/click                    |
|     -> 8 activations . $25/activation . 3.2x signal          |
|     Best:  Google Ads -- $0.17/click, 6 activations          |
|     Worst: Meta Ads -- $0.89/click, 2 activations            |
|                                                              |
|     Recommendation for L2:                                   |
|     . Double Google Ads budget ($240)                        |
|     . Cut Meta Ads, redistribute to Twitter Ads              |
|     . Continue Reddit organic (free, 56 clicks)              |
|                                                              |
|     [Upgrade to L2 ->]     [View Full Report]                |
|                                                              |
|     523 impressions . 89 signups . 7 days . $262             |
|                                                              |
|                                                              |
+--------------------------------------------------------------+
```

#### KILL

```
+--------------------------------------------------------------+
|                                                              |
|                                                              |
|                        x KILL                                |
|                                                              |
|            Meal Prep Planner failed                          |
|            top-funnel validation.                            |
|                                                              |
|     REACH    0.41x x      DEMAND    1.12x ok                |
|     ACTIVATE -- (L2)      MONETIZE  0.92x ok                |
|     RETAIN   -- (L3)                                        |
|                                                              |
|     The market signal is too weak.                           |
|     Ad CTR 0.82% vs 2.0% threshold means                    |
|     this audience doesn't respond to this framing.           |
|                                                              |
|     --- DISTRIBUTION ROI ----------------------------        |
|     $420 spent . 34 clicks . $12.35/click                    |
|     -> 0 activations . No signal.                            |
|     All channels underperformed.                             |
|                                                              |
|     You saved approximately 3 months of building.            |
|     This is a good outcome.                                  |
|                                                              |
|     [Archive & Start New Experiment ->]                      |
|     [View Post-Mortem]                                       |
|                                                              |
|     2,340 impressions . 34 clicks . 14 days . $420           |
|                                                              |
|                                                              |
+--------------------------------------------------------------+
```

**"You saved approximately 3 months of building. This is a good outcome."** — This single sentence is the concentrated UX philosophy of the entire product. Assayer's value is not just finding good ideas but **quickly eliminating bad ones**. KILL is not failure — it's saving. World-champion UX must communicate this.

**Distribution ROI in verdict** is critical: the verdict is not just "should you continue" but **"how to continue better."** Telling users "Google Ads worked, Meta didn't" is 10x more useful than just saying "SCALE."

#### REFINE

```
+--------------------------------------------------------------+
|                                                              |
|                                                              |
|                        ~ REFINE                              |
|                                                              |
|            AI Invoice Tool has signal                        |
|            but one dimension needs work.                     |
|                                                              |
|     REACH    1.90x ok     DEMAND    1.34x ok                |
|     ACTIVATE -- (L2)      MONETIZE  0.65x !                 |
|     RETAIN   -- (L3)                                        |
|                                                              |
|     Bottleneck: MONETIZE at 0.65x                            |
|     Pricing click rate 4.5% vs 7.0% threshold.              |
|     Consider: test lower price points or add                 |
|     value justification on landing page.                     |
|                                                              |
|     --- DISTRIBUTION ROI ----------------------------        |
|     $200 spent . 502 clicks . $0.40/click                    |
|     -> 8 activations . $25/activation . 3.2x signal          |
|     Best:  Google Ads -- $0.17/click, 6 activations          |
|                                                              |
|     Recommendation:                                          |
|     . Adjust pricing/value prop on landing page              |
|     . Re-run /distribute with same budget                    |
|     . Consider upgrading to L2 for engagement data           |
|                                                              |
|     [Apply Changes & Re-test ->]  [Upgrade to L2 ->]        |
|     [View Full Report]                                       |
|                                                              |
+--------------------------------------------------------------+
```

#### PIVOT

```
+--------------------------------------------------------------+
|                                                              |
|                                                              |
|                        <-> PIVOT                             |
|                                                              |
|            SaaS Analytics Dashboard has                      |
|            weak signal across the board.                     |
|                                                              |
|     REACH    0.62x !      DEMAND    0.55x !                 |
|     ACTIVATE -- (L2)      MONETIZE  0.78x !                 |
|     RETAIN   -- (L3)                                        |
|                                                              |
|     Three dimensions are below threshold but above           |
|     kill zone (0.5). The idea has some resonance             |
|     but needs a fundamentally different angle                |
|     or audience.                                             |
|                                                              |
|     Consider:                                                |
|     . Change target audience (B2B -> B2C or reverse)         |
|     . Reframe the value proposition entirely                 |
|     . Test with different keywords/channels                  |
|                                                              |
|     [Start New Experiment with Pivot ->]                     |
|     [View Post-Mortem]  [Archive]                            |
|                                                              |
+--------------------------------------------------------------+
```

#### Post-Mortem (KILL and PIVOT verdicts only)

[View Post-Mortem] is not a separate route — it renders as a tab on `/verdict/[id]` (`?tab=postmortem`).

```
+--------------------------------------------------------------+
|  AI Invoice Tool — Post-Mortem            [Scorecard] [Post-Mortem]  |
|                                                              |
|  --- FINAL SCORECARD ---                                     |
|  REACH    0.42x !    DEMAND    0.38x !                       |
|  ACTIVATE -- (L2)    MONETIZE  0.29x !                       |
|  RETAIN   -- (L3)                                            |
|                                                              |
|  --- PER-CHANNEL ROI ---                                     |
|  Channel          Spend    Clicks  Conv.  CPA               |
|  Google Ads       $210     18      2      $105.00            |
|  Meta Ads         $180     12      0      --                 |
|  Twitter Organic  --       4       1      --                 |
|                                                              |
|  --- AI ANALYSIS ---                                         |
|  The core problem was insufficient market demand for...      |
|  [full AI-generated failure analysis from verdict reasoning] |
|                                                              |
|  --- ROUND TIMELINE --- (if multi-round)                     |
|  Round 1: REACH 0.55x → Round 2: REACH 0.42x (declining)    |
|                                                              |
|  [Download CSV]                                              |
|                                                              |
+--------------------------------------------------------------+
```

**Content sections:**
- **Final Scorecard**: snapshot of all dimension ratios at experiment end
- **Per-Channel ROI Table**: spend, clicks, conversions, CPA per distribution channel
- **AI Analysis**: AI-generated failure analysis (from `experiment_decisions.reasoning`)
- **Round Timeline**: if multi-round (REFINE history), shows key metric changes across rounds
- **Data Export**: [Download CSV] exports `experiment_metric_snapshots` raw data via `/api/experiments/:id/metrics/export`

Post-Mortem transforms "failure" into "learning". KILL says "you saved 3 months"; Post-Mortem says "here's exactly what you learned."

---

### Screen 7a: Return Flows — REFINE & PIVOT

The verdict isn't the end — it's a decision point. REFINE and PIVOT both route users back into the creation flow, but with context preserved.

#### REFINE Return Flow

[Apply Changes & Re-test] returns to Screen 2 in **edit mode** with the bottleneck dimension highlighted and AI's suggested fix pre-filled. Previous experiment data is preserved as "Round 1" for comparison.

```
+--------------------------------------------------------------+
|  AI Invoice Tool  (Round 2)                   [Edit title]    |
|                                                              |
|  Round 1 verdict: REFINE (MONETIZE at 0.65x)                |
|  AI applied fix: adjusted pricing page variants              |
|                                                              |
|  HYPOTHESES ------------------------------------ 4 generated |
|  H1: "Indie devs will pay for automated invoicing"    [Edit] |
|  H2: "Time-saving is the primary value driver"        [Edit] |
|  H3: "Free trial converts better than freemium"       [Edit] |
|  H4: "Lower price point ($9/mo) improves MONETIZE" *  [Edit] |
|      * AI-suggested fix for MONETIZE bottleneck              |
|                                                              |
|  VARIANTS --------------------------------------- 3 generated|
|  +------------+  +------------+  +------------+             |
|  | time-saver |  | affordable |  | risk-free  |             |
|  | "Save 5    |  | "Just $9/  |  | "Free for  |             |
|  |  Hours..." |  |  month..." |  |  30 days"  |             |
|  +------------+  +------------+  +------------+             |
|                                                              |
|  [Regenerate]                        [Create & Launch ->]    |
+--------------------------------------------------------------+
```

- **Round indicator** ("Round 2") appears in the header so users always know where they are in the iteration cycle.
- **AI pre-fills the fix.** The bottleneck dimension's hypothesis is updated with AI's suggestion, but fully editable.
- **"Create & Launch"** starts a new round — same experiment, new deployment. The full level-dependent launch flow (Quality Gate for L2+, Content Check for L1) runs again.
- **Lab shows linked rounds:** "AI Invoice Tool (Round 2)" with a link back to Round 1's data.

#### PIVOT Return Flow

[Start New Experiment with Pivot] returns to the **Landing page** (Screen 1) with the idea input pre-filled.

- AI adds pivot context: "Pivoted from: [original idea]. AI suggestion: [new angle]"
- The new experiment is linked to the original in Lab ("Pivoted from Meal Prep Planner")
- The original experiment is auto-archived with its verdict preserved
- Users can see the full lineage: Original → Pivot → Pivot, building a decision trail

#### Analyze Now — Insufficient Data (Guard Clause)

When a user clicks "Analyze Now" but the guard clause triggers (< 100 clicks or < 50% experiment duration), no verdict page is shown. Instead, an inline dialog appears on the experiment page:

```
+--------------------------------------------------------------+
|  ⚠ Not Enough Data Yet                              [Close]  |
|                                                              |
|  52/100 clicks needed  •  Day 2/7 (29%)                     |
|                                                              |
|  Directional signal (NOT a verdict):                         |
|                                                              |
|    REACH     1.90x  ↑  on track                             |
|    DEMAND    1.34x  ↑  on track                             |
|    ACTIVATE  --        (requires L2)                         |
|    MONETIZE  0.65x  ↓  weak signal                          |
|                                                              |
|  Check back in ~3 days for reliable data.                    |
|                                                              |
+--------------------------------------------------------------+
```

- This is a toast/dialog overlay, not a navigation — the user stays on the experiment page
- "Directional signal" framing prevents users from acting on unreliable data
- Shows concrete progress toward verdict readiness (clicks needed, days remaining)

---

### Screen 8: Lab (Dashboard) — Portfolio View

Users with multiple experiments see them as an investment portfolio. Not called "Dashboard" — called **"Your Lab"** to reinforce the scientific validation metaphor.

```
+--------------------------------------------------------------+
|  Your Lab    [Experiments]  [Budget]            [+ New Idea]  |
|                                                              |
|  RUNNING (3)                          sorted by Assayer Score|
|  +---------------------+  +---------------------+           |
|  | AI Invoice Tool  ★89|  | Task Manager     ★54|           |
|  |                     |  |                     |           |
|  | R 1.9x D 1.3x M .7x|  | R .9x D .6x M ---  |           |
|  | Day 3/7    ON TRACK |  | Day 5/14    LOW !   |           |
|  | 4 ch · $62 · 502 cl |  | 2 ch · $180 · 90 cl|           |
|  | L1 Pitch            |  | L2 Proto            |           |
|  +---------------------+  +---------------------+           |
|                                                              |
|  +---------------------+                                    |
|  | Crypto Widget    ★12|                                    |
|  | R .4x D .3x M ---   |                                    |
|  | Day 10/14  DANGER   |                                    |
|  | 1 ch · $200 · 34 cl |                                    |
|  +---------------------+                                    |
|                                                              |
|  == AI INSIGHT ============================================= |
|  "AI Invoice Tool has the strongest signal (89). Consider    |
|   doubling its ad budget. Crypto Widget shows no demand      |
|   signal after 200 clicks — consider killing it to free      |
|   $280 for better-performing experiments."                   |
|  [Apply suggestions ->]                        [Dismiss]     |
|                                                              |
|  VERDICT READY (1)                                           |
|  +---------------------+                                    |
|  | Meal Prep Planner   |                                    |
|  |                     |                                    |
|  | KILL x    0.41x     |                                    |
|  | Top-funnel failed   |                                    |
|  | [View Verdict ->]   |                                    |
|  +---------------------+                                    |
|                                                              |
|  COMPLETED (3)                                               |
|  +----------+ +----------+ +----------+                     |
|  | Exp #4   | | Exp #5   | | Exp #6   |                     |
|  | SCALE ^  | | REFINE ~ | | KILL x   |                     |
|  +----------+ +----------+ +----------+                     |
|                                                              |
+--------------------------------------------------------------+

  [Budget] tab (Team plan only):

+--------------------------------------------------------------+
|  Your Lab    [Experiments]  [Budget]            [+ New Idea]  |
|                                                              |
|  PORTFOLIO BUDGET                                            |
|                                                              |
|  Total allocated: $442 / $500          Remaining: $58        |
|  =========================================......             |
|                                                              |
|  +-- EXPERIMENT ----+-- SPENT --+-- REMAINING --+-- SCORE --+|
|  | AI Invoice Tool  |  $62      |  $138         |  ★ 89    ||
|  | Task Manager     |  $180     |  $120         |  ★ 54    ||
|  | Crypto Widget    |  $200     |  $0 (spent)   |  ★ 12    ||
|  +------------------+-----------+---------------+-----------+|
|                                                              |
|  == AI BUDGET OPTIMIZER ==================================== |
|                                                              |
|  CURRENT              →    RECOMMENDED                       |
|  AI Invoice:  $200         AI Invoice:  $380 (+$180)         |
|  Task Mgr:    $300         Task Mgr:    $120 (-$180)         |
|  Crypto:      $200         Crypto:      $0   (kill)          |
|                                                              |
|  [Apply Rebalance ->]                          [Customize]   |
|                                                              |
+--------------------------------------------------------------+
```

**Design decisions:**

1. **Grouped by state, not by time.** RUNNING -> VERDICT READY -> COMPLETED. Users first see "what needs my attention."
2. **Each card shows ONE number: bottleneck ratio.** Not 5 metrics — the most critical one. This is Robinhood's approach — your portfolio homepage shows total return, not each stock's P/E ratio.
3. **"VERDICT READY" is a separate group.** When /iterate produces a verdict, the experiment card moves from RUNNING to VERDICT READY with a prominent visual cue. This creates an "opening a present" moment.
4. **Channel count + spend on each card** — at-a-glance distribution status.
5. **Assayer Score (★) is the sort key for RUNNING experiments.** Cards ordered by score descending — highest-signal experiments appear first, visually communicating priority.
6. **AI Insight appears only with sufficient data.** Requires 2+ RUNNING experiments AND at least one with 30+ visits. Prevents premature cross-experiment advice.
7. **Budget tab is Team-only.** Portfolio budget overview, AI Budget Optimizer, and custom allocation sliders are gated to Team plan ($299/mo).
8. **Three compressed dimension ratios per card** (`R 1.9x D 1.3x M .7x`) — richer than a single bottleneck ratio but still fits one line. Lets users spot which dimension is weak without opening the experiment.
9. **Dual-label system: score-status vs verdict-labels.** Lab cards use score-status labels (ON TRACK / PROMISING / LOW ! / DANGER / CRITICAL) derived from the Assayer Score range, for health monitoring at a glance. Mobile Glance mode and notifications use verdict-labels (SCALE / REFINE / KILL) for action orientation — mobile users need to know "what should I do?" not "how is it?". Both are derived from the same Assayer Score but serve different cognitive purposes.

#### Empty state

```
+--------------------------------------------------------------+
|  Your Lab                                     [+ New Idea]   |
|                                                              |
|                                                              |
|             No experiments yet.                              |
|                                                              |
|     Every founder has ideas.                                 |
|     The difference is knowing which one to build.            |
|                                                              |
|     [Test your first idea ->]                                |
|                                                              |
|                                                              |
+--------------------------------------------------------------+
```

Empty states are the MOST important states. First-time user sees dashboard with zero experiments. That's the most common state — it should be inspiring, not blank.

---

### Screen 9: Settings

Minimal. Nobody wants to spend time here.

```
+--------------------------------------------------------------+
|  Settings                                                    |
|                                                              |
|  ACCOUNT --------------------------------------------------- |
|  Email: user@example.com                                     |
|  [Change Password]                                           |
|                                                              |
|  CONNECTED ACCOUNTS (login) -------------------------------- |
|  ok Google     user@gmail.com               [Disconnect]     |
|  ok GitHub     @username                    [Disconnect]     |
|                                                              |
|  DISTRIBUTION CHANNELS ------------------------------------- |
|  Organic                                                     |
|  ok Twitter/X     @username connected       [Disconnect]     |
|  ok Reddit        u/username connected      [Disconnect]     |
|  ok Resend        API key ...8f2a           [Update Key]     |
|                                                              |
|  Paid Ads                                                    |
|  ok Google Ads    MCC sub-account active    [Manage]         |
|     Meta Ads      Not connected             [Connect ->]     |
|     Twitter Ads   Not connected             [Connect ->]     |
|                                                              |
|  PLAN & BILLING -------------------------------------------- |
|  Current: Pro ($99/mo)                                       |
|  Creates: 1/3 used · Modifications: 11/15 used              |
|  PAYG balance: $24.00                                        |
|  Next billing: April 12, 2026                                |
|  [Manage Subscription]  [View Invoices]                      |
|                                                              |
|  +----------------------------------------------------------+|
|  |  Free     PAYG      [Pro]      Team                      ||
|  |  $0       per-op    $99/mo    $299/mo                     ||
|  |  1 exp    unlimited  3+15/mo   10+60/mo                   ||
|  |  free ch  free ch    all ch    all ch + 5 seats           ||
|  +----------------------------------------------------------+|
|                                                              |
+--------------------------------------------------------------+
```

**Critical distinction:** "Connected Accounts" (Google/GitHub OAuth for login) is SEPARATE from "Distribution Channels" (OAuth for posting/ads). They are different OAuth grants with different scopes. The UI must make this clear.

**Plan comparison** is inline, not a separate page. Users upgrading want to compare at a glance. [Manage Subscription] handles Stripe customer portal for payment method, cancellation, etc.

---

### Experiment Comparison

If Assayer's variant #3 promises "Run 5 Experiments, Build the Winner", the product MUST let users compare experiments side-by-side.

```
+--------------------------------------------------------------+
|  Compare Experiments                    [Export CSV]          |
|                                                              |
|              AI Invoice  Task Mgr    Crypto Widget           |
|  Score        ★ 89       ★ 54        ★ 12                   |
|  REACH        1.90x ok    0.89x !     0.41x x               |
|  DEMAND       1.34x ok    0.55x !     0.32x x               |
|  ACTIVATE     -- (L1)     1.05x ok    -- (L1)               |
|  MONETIZE     0.65x !     -- (L2)     -- (L1)               |
|  RETAIN       -- (L1)     -- (L2)     -- (L1)               |
|  -----------------------------------------------------------  |
|  Verdict      on track    behind      danger                 |
|  Confidence   reliable    directional insufficient           |
|  Ad Spend     $62         $180        $200                   |
|  CPA          $7.75       $60         --                     |
|  Best Channel Google Ads  Twitter     --                     |
|                                                              |
|  == AI RECOMMENDATION ==================================== = |
|                                                              |
|     ★ AI Invoice Tool is your strongest bet.                 |
|                                                              |
|     1. Kill Crypto Widget → save $280 remaining budget       |
|     2. Move saved budget to AI Invoice → Google Ads          |
|     3. Give Task Manager 5 more days before deciding         |
|                                                              |
|     [Apply All ->]    [Apply #1 only]    [Dismiss]           |
|                                                              |
+--------------------------------------------------------------+
```

This view upgrades Assayer from "validation tool" to "decision engine."

Triggered when user has 2+ experiments. Accessible from the Lab. Available on Pro and Team plans.

---

## Error & Edge States

Errors appear as **alert banners** at the top of the Experiment Page (Screen 6) — not separate screens. Each banner has a one-line description and recommended action. The experiment continues where possible.

```
+--------------------------------------------------------------+
|  !! Deploy failed -- code scaffolding error                  |
|     [Retry Deploy]  [View Logs]                              |
+--------------------------------------------------------------+
|  AI Invoice Tool          ACTIVE    Day 3/7    L1 Pitch      |
|  ...                                                         |
```

### Defined alert types

| # | Alert Type | Banner Text | Actions |
|---|-----------|------------|---------|
| 1 | Deploy failed | "Deploy failed -- code scaffolding error" | [Retry Deploy] [View Logs] |
| 2 | Ad account suspended | "Google Ads: account suspended by Google" | [Check Google Ads] -- other channels continue |
| 3 | Organic post removed | "Reddit post removed by moderators" | [Repost to different subreddit] [Ignore] |
| 4 | Budget exhausted | "Ad budget spent -- 3 days remaining" | [Add $X budget] [Continue organic only] |
| 5 | Metrics stale | "Data stale (last sync: 26h ago)" | [Force Sync] [View status] |
| 6 | Dimension dropping | "MONETIZE trending down -- 0.72x -> 0.65x" | [Analyze Now] [View details] |
| 7 | Bug auto-fixed (L2/L3) | "Signup form bug detected and fixed (12 visitors affected)" | [View details] |

**Design principles for errors:**

- **Informational, not blocking.** The experiment continues where possible. Users are informed, not stopped.
- **Banners, not modals.** Modals demand attention and block interaction. Banners persist until resolved but don't interrupt the user's flow.
- **One action, clearly recommended.** The primary action button is always the most common fix. Secondary actions are available but de-emphasized.
- **Channel-specific failures are isolated.** If Google Ads is suspended, Twitter and Reddit continue. The banner shows which channel is affected, not a generic "distribution error."
- **Auto-fixed bugs get a green-tinted banner** (informational, not alarming). The system already fixed the problem — the user just needs to know it happened.

```
+--------------------------------------------------------------+
|  !! Google Ads: account suspended by Google                  |
|     [Check Google Ads]  Twitter/X + Reddit continue normally |
+--------------------------------------------------------------+

+--------------------------------------------------------------+
|  !! Ad budget spent -- 3 days remaining in experiment        |
|     [Add $50 budget]  [Continue organic only]                |
+--------------------------------------------------------------+

+--------------------------------------------------------------+
|  ok Signup form bug detected and auto-fixed (3h ago)         |
|     ~12 visitors affected. Data adjusted.    [View details]  |
+--------------------------------------------------------------+
```

---

## Notifications & Re-engagement

**Channel:** Email (required) + browser push (opt-in). No in-app notification center — that's over-engineering for MVP.

### Defined touchpoints

| # | Trigger | Message | Timing |
|---|---------|---------|--------|
| 1 | Experiment live | "Your experiment is live. First traffic expected in ~2h." | Immediate |
| 2 | First traffic milestone | "48 clicks so far. REACH at 1.2x -- early signal positive." | ~24h |
| 3 | Mid-experiment | "200 clicks reached. Here's your mid-experiment snapshot:" | ~Day 3 |
| 4 | Verdict ready | "Your verdict is ready. Tap to see." | When /iterate produces verdict |
| 5 | Budget alert | "Google Ads budget 90% spent. Add budget or continue organic?" | When threshold hit |
| 6 | Dimension dropping | "MONETIZE trending down -- 0.72x -> 0.65x. Consider adjusting pricing." | When decline detected |
| 7 | Bug auto-fixed (L2/L3) | "We detected and fixed an issue with your experiment." | After auto-fix completes |
| 8 | Portfolio insight ready | "Portfolio Update: {N} experiments. ★ {top_name} leads at {score}." | Daily (when 2+ running) |

### Email template wireframe

Every notification contains a **mini scorecard** — enough information to decide "do I need to act?" without opening the app.

```
+--------------------------------------------------------------+
|                                                              |
|  Assayer                                                     |
|                                                              |
|  AI Invoice Tool -- Mid-experiment snapshot                   |
|                                                              |
|  REACH     ########........  1.2x  ok    200 clicks          |
|  DEMAND    ######..........  0.9x  !     34 signups          |
|  ACTIVATE  ....              --          (requires L2)        |
|  MONETIZE  ....              --          (not yet measured)   |
|  RETAIN    ....              --          (requires L3)        |
|                                                              |
|  Best channel: Google Ads (3.8% CTR, $0.12/click)           |
|  Bottleneck: DEMAND at 0.9x -- close to threshold            |
|                                                              |
|  [View Full Experiment ->]                                   |
|                                                              |
|  Day 3/7 . $62 spent . 200 clicks                           |
|                                                              |
+--------------------------------------------------------------+
```

#### Portfolio Update email template

When AI Insight generates cross-experiment recommendations (2+ running experiments), a Portfolio Update email is sent daily.

```
+--------------------------------------------------------------+
|                                                              |
|  Assayer                                                     |
|                                                              |
|  Portfolio Update — 3 experiments                            |
|                                                              |
|  ★ 72 Portfolio Health                                       |
|                                                              |
|  AI Invoice Tool  ★89  ↑  SCALE signal strengthening        |
|  Task Manager     ★54  →  Holding, needs 5 more days        |
|  Crypto Widget    ★12  ↓  Recommend: Kill                    |
|                                                              |
|  Suggested action:                                           |
|  Kill Crypto Widget → free $280 → add to AI Invoice          |
|                                                              |
|  [Open Lab ->]                                               |
|                                                              |
+--------------------------------------------------------------+
```

**Design principles for notifications:**

- **Scorecard snapshots, not "click here" spam.** Every notification contains enough information to decide whether action is needed. The link to the app is secondary.
- **Ambient awareness, not interruption.** The user should know experiment status from their inbox without context-switching into the app.
- **Declining dimensions trigger proactive alerts.** Don't wait for the verdict — if MONETIZE drops from 0.72x to 0.65x, tell the user now while they can still adjust.

---

## Responsive & Mobile Design

### Context Model

Assayer users operate in fundamentally different modes depending on device. Designing "responsive" doesn't mean shrinking — it means recognizing that **mobile is a different task context**.

| Mode | Viewport | Posture | Task | Session Length |
|------|----------|---------|------|----------------|
| **Glance Mode** | < 768px (mobile) | One-handed, standing/walking | Status check: "Is my experiment still running? Any verdicts?" | < 15 seconds |
| **Work Mode** | ≥ 1024px (desktop) | Sit-down, keyboard + mouse | Deep analysis: create experiments, review scorecards, adjust distribution | 2–15 minutes |
| **Transition Mode** | 768–1023px (tablet) | Two-handed, lap or table | Desktop layout with touch-friendly targets | 1–5 minutes |

**Key insight:** A mobile user checking their experiment at a coffee shop needs the verdict and scorecard ratios — not the full variant carousel. Information hierarchy must shift by context, not just reflow.

### Breakpoint Strategy

Breakpoints follow Tailwind defaults. The table below defines what changes at each threshold:

| Token | Width | Layout Changes | Nav Model | Particles | Hover | Animation |
|-------|-------|----------------|-----------|-----------|-------|-----------|
| **< sm** | < 640px | Single column, stacked cards, full-width CTAs | Bottom tab bar + minimal top bar | OFF | OFF | Reduced distances (8px), halved stagger |
| **sm** | ≥ 640px | Inline CTAs, step indicator labels visible | Bottom tab bar | OFF | OFF | Reduced distances |
| **md** | ≥ 768px | Multi-column grids (2-col), top nav appears | Top nav (current) | ON | ON | Full distances, full stagger |
| **lg** | ≥ 1024px | Full desktop density, sidebar affordances | Top nav | ON | ON | Full animation system |
| **xl** | ≥ 1280px | `max-w-7xl` centered with breathing room | Top nav | ON | ON | Full animation system |

**Rules:**
- Canvas particle background is **disabled below `md`** — battery drain and jank on mobile GPUs are not worth the aesthetic
- Hover effects (`hover:`) only activate at `md+` — below that, use `:active` states on `@media (pointer: coarse)`
- All touch targets are minimum **44×44px** (WCAG 2.5.5 AAA)
- Below `sm`, stagger delays are **halved** (30ms vs 60ms desktop) and translateY distances are **reduced** (8px vs 20px)

### Navigation Model

**Desktop (≥ md):** Current top navigation bar — unchanged. Logo left, nav links center, user avatar right.

**Mobile (< md):** Bottom tab bar + simplified top bar.

```
Mobile Navigation Structure:

+--------------------------------------------------+
|  [⚗️ Assayer]                           [Avatar]  |  ← Simplified top bar
|                                                    |     Logo + auth only
+--------------------------------------------------+
|                                                    |
|                                                    |
|                  Page Content                      |
|                                                    |
|                                                    |
+--------------------------------------------------+
|                                                    |
|    🧪 Lab        ✨ New        ⚙️ Settings         |  ← Bottom tab bar
|                                                    |     56px + safe-area
+--------------------------------------------------+
```

**Bottom tab bar specifications:**
- Height: `56px + env(safe-area-inset-bottom)`
- Background: `bg-background/90 backdrop-blur-xl border-t border-border`
- Three tabs: **Lab** (experiments list), **New** (create experiment), **Settings**
- Active tab: primary color icon + label; inactive: muted icon, no label
- Hidden when software keyboard is open (detected via `visualViewport` API resize events)
- Restored with 100ms delay after keyboard dismissal to prevent layout flash
- Z-index: 50 (above page content, below modals/sheets)

**Top bar (mobile):**
- Height: `48px + env(safe-area-inset-top)`
- Logo left (links to Lab), avatar/sign-in right
- No navigation links (moved to bottom tab bar)

### Touch Interaction Model

| Gesture | Target | Action | Feedback |
|---------|--------|--------|----------|
| **Tap** | Cards, buttons, links | Navigate / trigger action | `scale(0.98) + opacity-80`, 100ms |
| **Long press** | Lab experiment card | Show quick actions (Archive, View Verdict) | Haptic + scale(1.02) + shadow elevation |
| **Swipe left** | Lab experiment card | Reveal archive action (red) | Card slides to reveal action strip |
| **Pull to refresh** | Lab list, Scorecard | Refresh data | Custom indicator with Assayer spinner |
| **Horizontal scroll** | Tab strips, variant carousel | Navigate between items | Snap scrolling with momentum |
| **Bottom sheet drag** | Sheet handle | Expand/collapse/dismiss | Velocity-based snap to detents |

**Touch target rules:**
- Minimum size: 44×44px (even if visual element is smaller, pad the hit area)
- Spacing between adjacent targets: minimum 8px
- Active state: `scale(0.98)` + subtle opacity dim, applied via `:active` on `@media (pointer: coarse)`
- No double-tap-to-zoom: `touch-action: manipulation` on interactive elements

### Per-Page Mobile Wireframes

#### Landing Page (Mobile)

The landing page in Glance Mode is about **one thing:** get the user to type their idea.

```
+------------------------------------------+
|  [⚗️ Assayer]              [Sign In]     |
+------------------------------------------+
|                                          |
|  ┌──────────────────────────────────┐    |
|  │     Static gradient mesh hero    │    |  ← No canvas particles
|  │     (CSS gradient, not <canvas>) │    |     on mobile
|  │                                  │    |
|  │   Know if it's gold              │    |  ← text-4xl (not text-6xl)
|  │   before you dig.                │    |
|  │                                  │    |
|  │  ┌──────────────────────────┐    │    |
|  │  │ Describe your idea...    │    │    |  ← Full-width input
|  │  └──────────────────────────┘    │    |
|  │  ┌──────────────────────────┐    │    |
|  │  │    Run Free Assay →      │    │    |  ← Full-width CTA, h-14
|  │  └──────────────────────────┘    │    |     (48px min touch)
|  └──────────────────────────────────┘    |
|                                          |
|  ── Pain Points ─────────────────────    |
|                                          |
|  ┌──────────────────────────────────┐    |  ← Vertical stack
|  │ "I spent 3 months building..."   │    |     (not sticky 2-column)
|  └──────────────────────────────────┘    |
|  ┌──────────────────────────────────┐    |
|  │ "My last product had 0 users..." │    |
|  └──────────────────────────────────┘    |
|  ┌──────────────────────────────────┐    |
|  │ "I keep second-guessing..."      │    |
|  └──────────────────────────────────┘    |
|                                          |
|  ── How It Works ────────────────────    |
|                                          |
|  ┌──────────────────────────────────┐    |
|  │  1. Describe → [icon]           │    |  ← Vertical timeline
|  │  Brief explanation               │    |     (not horizontal)
|  ├──────────────────────────────────┤    |
|  │  2. AI Assays → [icon]          │    |
|  │  Brief explanation               │    |
|  ├──────────────────────────────────┤    |
|  │  3. Get Verdict → [icon]        │    |
|  │  Brief explanation               │    |
|  └──────────────────────────────────┘    |
|                                          |
|  ── Stats ───────────────────────────    |
|                                          |
|  ┌────────────┐  ┌────────────┐         |  ← 2×2 grid preserved
|  │  47 ideas  │  │  $2.1M     │         |     (numbers are punchy)
|  │  tested    │  │  saved     │         |
|  └────────────┘  └────────────┘         |
|  ┌────────────┐  ┌────────────┐         |
|  │  12 min    │  │  89%       │         |
|  │  avg time  │  │  accuracy  │         |
|  └────────────┘  └────────────┘         |
|                                          |
|  ── Pricing ─────────────────────────    |
|                                          |
|  Single-column plan cards                |
|  (horizontal scroll on sm+)             |
|                                          |
|  [Footer]                                |
+------------------------------------------+
```

**Key mobile adaptations:**
- Canvas particles → static CSS gradient mesh (saves battery, eliminates jank)
- Headline: `text-4xl` (not `text-6xl`) — must be readable without zooming
- CTA button: full-width, `h-14` (56px) for comfortable thumb tap
- Pain points: vertical stack (desktop's sticky two-column doesn't work one-handed)
- How It Works: vertical timeline (horizontal steps require too much scrolling context)
- Stats grid: 2×2 preserved (compact numbers work well on mobile)

#### The Assay / New Experiment (Mobile)

The creation flow must feel **fast and focused** on mobile — one step visible at a time.

```
+------------------------------------------+
|  [← Back]   New Experiment   [Cancel]    |
+------------------------------------------+
|                                          |
|  ┌──────────────────────────────────┐    |
|  │ Describe your idea...            │    |
|  │                                  │    |
|  │                                  │    |
|  │                                  │    |
|  └──────────────────────────────────┘    |
|                                          |
|  ── AI Spec Review ──────────────────    |
|                                          |
|  ▼ Hypothesis          [✓ verified]     |  ← Accordion sections
|    Content hidden when collapsed         |     One open at a time
|                                          |
|  ▶ Target Audience     [✓ verified]     |  ← Collapsed
|                                          |
|  ▶ Success Metrics     [✓ verified]     |  ← Collapsed
|                                          |
|  ▶ Risk Assessment     [⟳ checking]    |  ← Collapsed
|                                          |
|  ── Variants ────────────────────────    |
|                                          |
|  ┌────────────┐ ┌────────────┐          |
|  │ Variant A  │ │ Variant B  │  →       |  ← Horizontal snap-scroll
|  │            │ │            │          |     280px card width
|  │ Control    │ │ Test       │          |     Scroll indicator dots
|  │            │ │            │          |
|  └────────────┘ └────────────┘          |
|                      · ●                |  ← Dot indicators
|                                          |
+------------------------------------------+
|  ┌──────────────────────────────────┐    |  ← Sticky bottom bar
|  │       Save & Generate →          │    |     with safe-area padding
|  └──────────────────────────────────┘    |
+------------------------------------------+
|    🧪 Lab        ✨ New       ⚙️ Settings  |
+------------------------------------------+
```

**Key mobile adaptations:**
- Spec review sections: accordion (one expanded at a time) instead of all-visible list
- Variant cards: horizontal snap-scroll carousel (280px cards) with dot indicators
- Generate/Save button: sticky at bottom with `pb-safe` padding above tab bar
- Full-screen AI generation overlay with progress steps (same as desktop, but fills viewport)

#### Experiment Detail (Mobile)

The scorecard is the hero — it must be **immediately visible** without scrolling.

```
+------------------------------------------+
|  [← Lab]    Experiment Name    [...]     |
+------------------------------------------+
|                                          |
|  ┌──────────────────────────────────┐    |
|  │  Verdict: SCALE                  │    |  ← If verdict exists,
|  │  ████████████████████  3.2x      │    |     show prominently
|  └──────────────────────────────────┘    |
|                                          |
|  ── Scorecard ───────────────────────    |
|                                          |
|  REACH                                   |
|  ████████████████░░░░  1.2x  ✓          |  ← Full-width vertical bars
|                                          |     (not 2×2 grid)
|  DEMAND                                  |
|  ██████████░░░░░░░░░░  0.9x  !          |
|                                          |
|  ACTIVATE                                |
|  ░░░░░░░░░░░░░░░░░░░░  --              |
|                                          |
|  MONETIZE                                |
|  ░░░░░░░░░░░░░░░░░░░░  --              |
|                                          |
|  RETAIN                                  |
|  ░░░░░░░░░░░░░░░░░░░░  --              |
|                                          |
+------------------------------------------+
|  Scorecard | Variants | Distribution     |  ← Horizontal scrollable
|  ─────────                               |     pill tabs (sticky)
+------------------------------------------+
|                                          |
|  [Tab content here]                      |
|                                          |
+------------------------------------------+
|    🧪 Lab        ✨ New       ⚙️ Settings  |
+------------------------------------------+
```

**Key mobile adaptations:**
- Scorecard dimensions: full-width vertical bars (desktop's 2×2 grid is too cramped on mobile)
- Tab strip: horizontal scrollable pills, sticky below the top bar
- Variants tab: same horizontal carousel as creation flow
- Overflow actions (Deploy, Archive, Share): moved to bottom sheet triggered by `[...]` menu button
- Distribution tab: simplified channel list with expandable details

#### Lab / Dashboard (Mobile)

The Lab is a **status board** on mobile — glanceable experiment health. Experiments are grouped by urgency (NEEDS ATTENTION first), not just state.

```
+------------------------------------------+
|  [Assayer]                     [Avatar]   |
+------------------------------------------+
|                                          |
|  Your Lab              Portfolio: ★ 72   |
|                                          |
|  ↓ Pull to refresh (triggers score recalc)|
|                                          |
|  NEEDS ATTENTION (1)                     |
|  +--------------------------------------+|
|  | Crypto Widget         ★ 12  CRITICAL||
|  | 0 activations · $200 spent          ||
|  | AI recommends: Kill                  ||
|  | [Kill & Free Budget] [View ->]      ||
|  +--------------------------------------+|
|                                          |
|  ON TRACK (2)                            |
|  +--------------------------------------+|
|  | AI Invoice Tool      ★ 89  SCALE    ||
|  | 8 activations · $62 spent           ||
|  +--------------------------------------+|
|  +--------------------------------------+|
|  | Task Manager          ★ 54  REFINE  ||
|  | 3 activations · $180 spent          ||
|  +--------------------------------------+|
|                                          |
+------------------------------------------+
|              [＋]                         |
|   Lab        New        Settings         |
+------------------------------------------+
```

**Key mobile adaptations:**
- **Portfolio Health Score (★ XX) in page header** — one number summarizes all experiments
- **Grouped by urgency, not state:** NEEDS ATTENTION first (score < 20 OR verdict ready OR budget exhausted), ON TRACK second
- **NEEDS ATTENTION cards show inline action buttons** — [Kill & Free Budget] [View ->] directly on card, no detail page needed
- **ON TRACK cards compressed** — name + score + one-line status only; no action needed = no actions shown
- **Pull-to-refresh triggers score recalculation** — long-pull fetches latest analytics and recomputes Assayer Scores
- FAB (floating action button): positioned above tab bar for quick experiment creation
- Long-press on card: quick action sheet (Archive, View Verdict, Share)

#### Settings (Mobile)

```
+------------------------------------------+
|  [← Back]        Settings                |
+------------------------------------------+
|                                          |
|  Account | Billing | Preferences    →    |  ← Scrollable tab strip
|  ────────                                |
|                                          |
|  ── Account ─────────────────────────    |
|                                          |
|  Email: user@example.com    [Edit]       |
|  Password: ••••••••         [Edit]       |
|                                          |
|  ── Billing ─────────────────────────    |
|                                          |
|  Current plan: Free                      |
|                                          |
|  ┌──────────────────────────────────┐    |
|  │  Free                            │    |  ← Single-column stack
|  │  1 experiment                    │    |     (not side-by-side)
|  │  $0/mo                          │    |
|  │  [Current Plan]                  │    |
|  └──────────────────────────────────┘    |
|                                          |
|  ┌──────────────────────────────────┐    |
|  │▌ Pro  ⭐ Recommended             │    |  ← Amber left border
|  │▌ 3 creates + 15 mods/mo         │    |     on recommended plan
|  │▌ $99/mo                         │    |
|  │▌ [Upgrade →]                    │    |
|  └──────────────────────────────────┘    |
|                                          |
|  ┌──────────────────────────────────┐    |
|  │  Team                            │    |
|  │  10 creates + 60 mods/mo        │    |
|  │  $299/mo                        │    |
|  │  [Upgrade →]                    │    |
|  └──────────────────────────────────┘    |
|                                          |
+------------------------------------------+
|    🧪 Lab        ✨ New       ⚙️ Settings  |
+------------------------------------------+
```

**Key mobile adaptations:**
- Tab strip: horizontally scrollable (not stacked vertically)
- Pricing plans: single-column stack (side-by-side comparison doesn't fit)
- Recommended plan: amber left border accent (consistent with Lab card pattern)

#### Verdict Page (Mobile)

The verdict is a **full-screen ceremony** — the most emotional moment in Assayer.

```
+------------------------------------------+
|                                          |
|                                          |
|                                          |
|                                          |
|              [⚗️ icon]                   |  ← Springs in (ease-spring)
|                                          |
|              SCALE                       |  ← text-5xl, centered
|                                          |     Fills viewport initially
|           Your idea has                  |
|           market signal.                 |
|                                          |
|                                          |
+------------------------------------------+
|                                          |  ← Scroll to reveal details
|  ── Dimension Breakdown ─────────────    |
|                                          |
|  REACH                                   |
|  ████████████████░░░░  1.2x  ✓          |  ← Full-width vertical bars
|                                          |
|  DEMAND                                  |
|  ██████████████░░░░░░  1.1x  ✓          |
|                                          |
|  ACTIVATE                                |
|  ████████████░░░░░░░░  1.05x ✓          |
|                                          |
|  MONETIZE                                |
|  ████████████░░░░░░░░  1.0x  ✓          |
|                                          |
|  ── ROI Summary ─────────────────────    |
|                                          |
|  $47 spent → 3.2x signal                |
|  vs. 3 months + $15K building blind      |
|                                          |
|  ── What's Next ─────────────────────    |
|                                          |
|  ┌──────────────────────────────────┐    |
|  │       Start Building →           │    |  ← Full-width, stacked
|  └──────────────────────────────────┘    |
|  ┌──────────────────────────────────┐    |
|  │       Run Another Assay          │    |
|  └──────────────────────────────────┘    |
|  ┌──────────────────────────────────┐    |
|  │       Share Results              │    |
|  └──────────────────────────────────┘    |
|                                          |
+------------------------------------------+
|    🧪 Lab        ✨ New       ⚙️ Settings  |
+------------------------------------------+
```

**Key mobile adaptations:**
- Verdict word: `text-5xl` centered, fills the initial viewport (scroll to see details)
- Icon animation preserved (springs in) — this is the emotional peak
- Dimension bars: full-width vertical (same as experiment detail)
- Action buttons: stacked vertically, full-width
- "You saved 3 months" (KILL verdict): centered and prominent, not tucked in a corner
- No particles/confetti on mobile (battery) — verdict color gradient background instead

### Safe Areas & Viewport

Modern mobile devices have notches, dynamic islands, home indicators, and rounded corners. Assayer must respect all of them.

**CSS custom properties (set in `globals.css`):**

```css
:root {
  --safe-top: env(safe-area-inset-top);
  --safe-bottom: env(safe-area-inset-bottom);
  --safe-left: env(safe-area-inset-left);
  --safe-right: env(safe-area-inset-right);
  --tab-bar-height: 56px;
  --mobile-bottom-offset: calc(var(--tab-bar-height) + var(--safe-bottom));
}
```

**Viewport rules:**
- Meta tag: `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`
- Full-screen layouts use `100dvh` (dynamic viewport height), **never** `100vh` (which ignores mobile browser chrome)
- `overscroll-behavior-y: contain` on `body` to prevent pull-to-navigate on iOS
- Scroll containers use `-webkit-overflow-scrolling: touch` for momentum scrolling

**Keyboard handling:**
- When software keyboard opens: hide bottom tab bar immediately
- When keyboard closes: restore tab bar with 100ms delay (prevents layout flash)
- Detection: `visualViewport` API `resize` event — viewport height decrease > 150px indicates keyboard
- Sticky bottom bars (Save button, etc.): reposition to sit above keyboard when active

### Mobile Performance

| Optimization | Desktop | Mobile (< md) | Reason |
|-------------|---------|----------------|--------|
| Canvas particles | ON | **OFF** | Battery drain, GPU jank on low-end devices |
| Scroll-reveal translateY | 20px | **8px** | Smaller movement = less compositing work |
| Scroll-reveal duration | 600ms | **400ms** | Shorter = fewer dropped frames |
| Stagger delay per item | 60ms | **30ms** | Faster sequence completion |
| `pulse-glow` animation | ON | **OFF** | Constant repainting kills battery |
| Hover effects | ON | **OFF** | Not applicable to touch; use `:active` instead |
| Image loading | Eager above fold | **Lazy all** | Mobile bandwidth constraints |
| Skeleton shimmer | Full | **Simplified** | Reduce simultaneous GPU layers |

**Touch-specific performance:**
- `:active` feedback via `@media (pointer: coarse)` — no JS event listeners for basic press feedback
- `touch-action: manipulation` on all interactive elements (prevents 300ms tap delay)
- `will-change` set dynamically on animation trigger, removed on `animationend`
- Intersection Observer thresholds: `[0.15]` on mobile (vs `[0.1]` desktop) — less eager triggering

### Responsive Patterns (Reusable)

These named patterns are used across pages. Each pattern has a Tailwind implementation.

**Pattern A: Responsive Container**
```
Container with responsive padding and max-width:
- Mobile: px-4 (16px sides)
- sm: px-6 (24px sides)
- md: px-8 (32px sides)
- lg: max-w-7xl mx-auto px-8
```
Usage: Every page's outermost content wrapper.

**Pattern B: Card Padding**
```
Cards with responsive internal padding:
- Mobile: p-4
- md: p-6
- lg: p-8
```
Usage: All card components (experiment cards, pricing cards, spec sections).

**Pattern C: Responsive Heading**
```
Heading that scales with viewport:
- Mobile: text-2xl font-bold
- sm: text-3xl
- md: text-4xl
- lg: text-5xl
```
Usage: Page titles, section headers, verdict word.

**Pattern D: Scrollable Tab Strip**
```
Horizontal scrollable tabs for mobile:
- Mobile: flex overflow-x-auto scrollbar-hide snap-x snap-mandatory gap-2
- md: flex gap-4 (no scroll, all visible)
Each tab: snap-start flex-shrink-0 px-4 py-2 rounded-full
```
Usage: Experiment detail tabs, settings tabs.

**Pattern E: Sticky Action Bar**
```
Bottom-fixed action bar for primary CTA:
- Mobile: fixed bottom-0 left-0 right-0 p-4 pb-safe bg-background/90
         backdrop-blur-xl border-t border-border z-40
- md: static (inline button)
Offset: mb-[var(--mobile-bottom-offset)] on page content to prevent overlap
```
Usage: Save/Generate button on Assay page, primary CTA on any form page.

**Pattern F: Bottom Sheet Trigger**
```
Secondary actions in a bottom sheet:
- Mobile: [...] button triggers bottom sheet with action list
- md: inline dropdown menu or visible buttons
Sheet: rounded-t-2xl bg-background, drag handle, snap detents (40%/80%/closed)
```
Usage: Experiment overflow actions (Deploy, Archive, Share), long-press quick actions.

### New Components Required

| Component | File Path | Purpose |
|-----------|-----------|---------|
| `MobileTabBar` | `src/components/mobile-tab-bar.tsx` | Bottom navigation with Lab/New/Settings tabs |
| `MobileBottomSheet` | `src/components/mobile-bottom-sheet.tsx` | Draggable bottom sheet for secondary actions |
| `ScrollableTabStrip` | `src/components/scrollable-tab-strip.tsx` | Horizontal scrollable pill tabs |
| `CardCarousel` | `src/components/card-carousel.tsx` | Snap-scroll horizontal card carousel with dot indicators |
| `PullToRefresh` | `src/components/pull-to-refresh.tsx` | Custom pull-to-refresh with Assayer spinner |
| `StickyActionBar` | `src/components/sticky-action-bar.tsx` | Bottom-fixed CTA bar with safe-area padding |

### New CSS Utilities

Add to `globals.css`:

```css
/* Safe area padding utilities */
.pb-safe { padding-bottom: env(safe-area-inset-bottom); }
.pt-safe { padding-top: env(safe-area-inset-top); }
.mb-tab { margin-bottom: var(--mobile-bottom-offset); }

/* Hide scrollbar for scrollable tab strips */
.scrollbar-hide {
  -ms-overflow-style: none;
  scrollbar-width: none;
}
.scrollbar-hide::-webkit-scrollbar { display: none; }

/* Touch feedback for coarse pointers */
@media (pointer: coarse) {
  .touch-feedback:active {
    transform: scale(0.98);
    opacity: 0.8;
    transition: transform 100ms ease-out, opacity 100ms ease-out;
  }
}

/* Reduced motion: disable decorative animations */
@media (prefers-reduced-motion: reduce) {
  .animate-pulse-glow,
  .animate-float,
  .animate-ambient-pulse { animation: none !important; }

  .scroll-reveal {
    opacity: 1 !important;
    transform: none !important;
    transition: none !important;
  }
}
```

---

## Animation Timing System

### Timing Vocabulary

Every animation in Assayer uses a named duration token and a named easing token. No magic numbers — if you can't name the duration, you haven't designed the animation.

#### Duration Tokens

| Token | Value | Use Case |
|-------|-------|----------|
| `--dur-instant` | 50ms | Hover color changes, focus ring |
| `--dur-micro` | 100ms | Touch feedback (`:active` press), tooltip show |
| `--dur-fast` | 150ms | Button state changes, icon swaps, dropdown open |
| `--dur-normal` | 250ms | Most UI transitions: tab switch, accordion, fade |
| `--dur-emphasis` | 400ms | Content reveals, card entrances, scroll-reveal |
| `--dur-dramatic` | 600ms | Scorecard bar fills, spec section materializing |
| `--dur-ceremony` | 900ms | Verdict icon spring, verdict word reveal |
| `--dur-ambient` | 3000ms | Pulse-glow cycle, shimmer loop |
| `--dur-float` | 4000ms | Ambient float animation cycle |

**Rule:** No animation (except ambient loops) should exceed `--dur-ceremony` (900ms). If it takes longer than 900ms, it's a choreography sequence (multiple animations composed), not a single animation.

#### Easing Tokens

| Token | CSS Value | Character | Use Case |
|-------|-----------|-----------|----------|
| `--ease-out-expo` | `cubic-bezier(0.16, 1, 0.3, 1)` | Fast attack, gentle settle | **Signature entrance curve.** All fade-ups, slide-ins, content reveals |
| `--ease-out-back` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | Slight overshoot, playful | Checkmark pop, badge entrance, pre-flight check icons |
| `--ease-in-out-sine` | `cubic-bezier(0.37, 0, 0.63, 1)` | Smooth, symmetric | Ambient loops: pulse-glow, float, shimmer |
| `--ease-out-quart` | `cubic-bezier(0.25, 1, 0.5, 1)` | Fast start, smooth end | Data fills: scorecard bars, counters, progress indicators |
| `--ease-in-expo` | `cubic-bezier(0.7, 0, 0.84, 0)` | Slow start, fast exit | **Exits only.** Elements leaving the viewport |
| `--ease-spring` | `linear(0, 0.009, 0.035 2.1%, 0.141, 0.281 6.7%, 0.723 12.9%, 0.938 16.7%, 1.017, 1.077, 1.121, 1.149 24.3%, 1.159, 1.163, 1.161, 1.154 29.9%, 1.129 32.8%, 1.051 39.6%, 1.017 43.1%, 0.991, 0.977 51%, 0.974 53.8%, 0.975 57.1%, 0.997 69.8%, 1.003 76.9%, 1)` | Bouncy, physical | Verdict icon entrance, state change celebrations |

**Rule:** Entrances use `ease-out-*` (fast in, settle). Exits use `ease-in-*` (slow out, accelerate away). Ambient uses `ease-in-out-*` (symmetric). Never use `ease-in-*` for entrances — it feels sluggish.

#### Stagger Timing

```
--stagger-item: 60ms    /* Delay between consecutive items */
--stagger-max: 8        /* Maximum items before capping */
--stagger-cap: 480ms    /* 60ms × 8 = total max stagger */
```

**Rule:** If a list has more than 8 items, items 9+ all animate at the 480ms mark (the cap). This prevents a 20-item list from taking 1200ms to complete.

### Animation Categories

#### Category 1: Entrances

| Animation | Duration | Easing | Properties | Description |
|-----------|----------|--------|------------|-------------|
| `fade-up` | `--dur-emphasis` (400ms) | `--ease-out-expo` | `opacity 0→1, translateY 20px→0` | Primary entrance. Cards, sections, content blocks |
| `fade-in` | `--dur-normal` (250ms) | `--ease-out-expo` | `opacity 0→1` | Subtle entrance. Text, labels, secondary elements |
| `scale-in` | `--dur-fast` (150ms) | `--ease-out-back` | `opacity 0→1, scale 0.8→1` | Attention entrance. Icons, badges, checkmarks |
| `slide-right` | `--dur-emphasis` (400ms) | `--ease-out-expo` | `opacity 0→1, translateX -20px→0` | Lateral entrance. Tab content, carousel items |

#### Category 2: Exits

| Animation | Duration | Easing | Properties | Description |
|-----------|----------|--------|------------|-------------|
| `fade-out` | `--dur-fast` (150ms) | `--ease-in-expo` | `opacity 1→0` | Default exit. Always faster than entrance |
| `fade-down` | `--dur-normal` (250ms) | `--ease-in-expo` | `opacity 1→0, translateY 0→10px` | Weighted exit. Cards being dismissed |

**Rule:** Exits are always **faster** than their corresponding entrance. Entrance at 400ms → exit at 150–250ms. Users don't need to watch things leave.

#### Category 3: State Changes

| Animation | Duration | Easing | Properties | Description |
|-----------|----------|--------|------------|-------------|
| `color-shift` | `--dur-normal` (250ms) | `--ease-out-expo` | `color, background-color, border-color` | Status changes, theme transitions |
| `morph` | `--dur-emphasis` (400ms) | `--ease-out-expo` | `width, height, border-radius` | Container resizing, layout shifts |
| `swap` | `--dur-normal` (250ms) | crossfade | `opacity` (old out, new in) | Skeleton → content, loading → loaded |

#### Category 4: Feedback

| Animation | Duration | Easing | Properties | Description |
|-----------|----------|--------|------------|-------------|
| `press` | `--dur-micro` (100ms) | `--ease-out-expo` | `scale 1→0.98, opacity 1→0.8` | Touch/click feedback |
| `hover-lift` | `--dur-fast` (150ms) | `--ease-out-expo` | `translateY 0→-2px, shadow elevation` | Desktop hover on cards |
| `glow` | `--dur-normal` (250ms) | `--ease-out-expo` | `box-shadow` | Focus state, active input |

#### Category 5: Ambient

| Animation | Duration | Easing | Properties | Description |
|-----------|----------|--------|------------|-------------|
| `pulse-glow` | `--dur-ambient` (3000ms) | `--ease-in-out-sine` | `opacity 0.5→1→0.5` | Live experiment indicator, active status |
| `float` | `--dur-float` (4000ms) | `--ease-in-out-sine` | `translateY 0→-10px→0` | Particle movement, decorative elements |
| `shimmer` | `--dur-ambient` (3000ms) | `linear` | `background-position` | Skeleton loading state |

### Choreography Sequences

Individual animations compose into choreographed sequences for key moments. These are the most complex animations in Assayer and define its personality.

#### Sequence A: Spec Materializing (~3200ms total)

The moment AI-generated spec content appears on the Assay page. Each section materializes in a deliberate order that mirrors how a human would read the spec.

```
Timeline (milliseconds):

t=0        Skeleton placeholders visible (shimmer running)
           │
t=0        Experiment name crossfades from skeleton (swap, 250ms)
           │
t=200      Pre-flight check icons pop in sequentially
           │  Each icon: scale-in, 150ms, ease-out-back
           │  Stagger: 300ms between icons (slower than standard — builds anticipation)
           │  3 icons = completes at t=200 + 150 + 600 = t=950
           │
t=1500     Hypothesis cards stagger in
           │  Each card: fade-up, 400ms, ease-out-expo
           │  Stagger: 60ms between cards (standard --stagger-item)
           │  4 cards = completes at t=1500 + 400 + 180 = t=2080
           │
t=2300     Variant cards fill in
           │  Each card: fade-up, 400ms, ease-out-expo
           │  Stagger: 100ms between cards (slightly slower — variants are important)
           │  2 cards = completes at t=2300 + 400 + 100 = t=2800
           │
t=2800     Cost counters animate to final values
           │  Counter: number rolls from 0 to final, 400ms, ease-out-quart
           │
t=3200     Edit icons fade in, action buttons appear
           │  fade-in, 250ms, ease-out-expo
           │  Sequence complete
```

**Emotional intent:** Deliberate, building — the AI is "thinking and assembling." The staggered reveals make the spec feel like it's being crafted, not dumped.

#### Sequence B: Verdict Reveal (~3600ms total)

The most emotionally significant animation in Assayer. This is the payoff — the moment the user gets their answer.

```
Timeline (milliseconds):

t=0        Previous page content exits
           │  fade-out, 150ms, ease-in-expo
           │
t=300      Dark/colored container fades in
           │  Background color matches verdict: green(SCALE), amber(REFINE),
           │  blue(PIVOT), red(KILL)
           │  fade-in, 250ms, ease-out-expo
           │
t=400      Verdict icon springs into center
           │  scale 0→1 with ease-spring, 600ms
           │  Icon: ⚗️ with verdict-colored glow
           │
t=700      Verdict word appears
           │  letter-spacing contracts from 0.5em to normal, 600ms, ease-out-expo
           │  opacity 0→1 simultaneously
           │  Font: text-6xl font-black (desktop), text-5xl (mobile)
           │
t=1100     Subtitle fades in
           │  "Your idea has market signal." / "Save your resources."
           │  fade-in, 250ms, ease-out-expo
           │
t=1500     Scorecard bars begin filling
           │  Each bar: scaleX 0→final, 600ms, ease-out-quart
           │  Stagger: 200ms between dimensions
           │  Color transition at 1.0x threshold (bar crosses from red zone to green)
           │  4 bars = completes at t=1500 + 600 + 600 = t=2700
           │
t=2400     ROI summary section fades up
           │  fade-up, 400ms, ease-out-expo
           │  "$47 spent → 3.2x signal"
           │
t=2800     Recommendation text fades up
           │  fade-up, 400ms, ease-out-expo
           │
t=3200     Action buttons appear
           │  fade-up with 60ms stagger, 400ms, ease-out-expo
           │
t=3600     Primary CTA gains subtle glow
           │  glow animation begins (ambient, ongoing)
           │  Sequence complete — user takes action
```

**Per-verdict emotional modulation:**

| Verdict | Modification | Emotional Intent |
|---------|-------------|-----------------|
| **SCALE** | Confetti particle burst at t=400 (desktop only). Standard pacing. | Celebration — "You found gold!" |
| **KILL** | All timings 15% slower. No particles. Amber underline on "You saved 3 months" appears at t=1100. | Respectful gravity — the answer is valuable, even if negative |
| **REFINE** | Bottleneck dimension bar pulses once after filling (pulse-glow, 1 cycle). | Attention-directing — "Here's what to fix" |
| **PIVOT** | Verdict icon oscillates horizontally ±5px at t=400 before settling. All timings 5% faster. | Energy, redirection — "Same energy, different direction" |

#### Sequence C: Scorecard Bar Update (~1200ms total)

When scorecard data refreshes (new metrics arrive), bars animate from their **previous value** to the new value — never from zero.

```
Timeline:

t=0        Bar begins transition
           │  scaleX: previousValue → newValue
           │  Duration: 600ms
           │  Easing: ease-out-quart
           │
           │  Color: transitions if crossing 1.0x threshold
           │  e.g., 0.9x (amber) → 1.1x (green): color shifts mid-fill
           │
t=600      Bar settles at new value
           │
t=600      If status badge changed (e.g., "!" → "✓"):
           │  Old badge: scale-out, 150ms, ease-in-expo
           │  New badge: scale-in, 150ms, ease-out-back (starts at t=750)
           │
t=900      Badge transition complete
           │
t=1200     Ratio number updates
           │  Counter animation from old → new value, 300ms, ease-out-quart
```

### Reduced Motion Strategy

Users with `prefers-reduced-motion: reduce` (or users on mobile where animations are already reduced) get a carefully considered alternative — not just "turn everything off."

**REMOVE entirely:**
- `pulse-glow` (ambient pulse)
- `float` (ambient float)
- Canvas particles and confetti
- Letter-spacing contraction (verdict word)
- Stagger delays (all items appear simultaneously)

**REPLACE with instant:**
- All entrances/exits → `opacity: 0→1` in 1ms (element appears, no motion)
- Scorecard bars → jump to final `scaleX` value immediately (no fill animation)
- Counter animations → display final number immediately (no roll)
- Skeleton → content swap is instant (no crossfade)

**KEEP (modified):**
- Hover color changes (instant, no motion involved)
- Shimmer loading animation (slowed to 3s cycle, subtle)
- Focus rings (accessibility requirement — never remove)
- Color transitions for state changes (250ms, no spatial movement)

**Implementation:**

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }

  /* Exception: keep color transitions for state feedback */
  .state-transition {
    transition-duration: 250ms !important;
    transition-property: color, background-color, border-color !important;
  }

  /* Exception: keep shimmer but slow it down */
  .skeleton-shimmer {
    animation-duration: 3s !important;
    animation-iteration-count: infinite !important;
  }
}
```

**JavaScript:** `useRevealOnScroll` hook checks `window.matchMedia('(prefers-reduced-motion: reduce)')`. If true, skips IntersectionObserver setup and sets `visible = true` immediately.

### Performance Budget

| Constraint | Limit | Reason |
|-----------|-------|--------|
| Max simultaneous animations | **12** | Beyond 12, frame drops become noticeable on mid-range devices |
| GPU-promoted properties only | `transform` + `opacity` | `width`, `height`, `top`, `left` trigger layout recalculation |
| Scorecard bars | `transform: scaleX()` | Never animate `width` — scaleX is GPU-composited |
| `will-change` lifecycle | Set on trigger → remove on `animationend` | Static `will-change` creates permanent GPU layers |
| Static `will-change` elements | **≤ 5** | More than 5 permanent GPU layers = memory pressure |
| Skeleton shimmer | Paint-only (`background-position`) | OK on up to 20 elements simultaneously |
| Choreography queue | Sequential, not parallel | Verdict sequence runs steps in order — no parallel composition |
| Mobile animation cap | See Mobile Performance table | Reduced distances, durations, and stagger on `< md` |

**Monitoring:** If any animation drops below 30fps on a mid-range device (e.g., Pixel 6a, iPhone SE 3), it must be simplified or removed. Performance > aesthetics, always.

### Emotional Timing Map

This table maps every interaction context to its appropriate timing feel. When designing a new animation, find its context here first.

| Context | Duration Band | Easing | Character | Examples |
|---------|--------------|--------|-----------|----------|
| **Utility** | `instant`–`normal` (50–250ms) | `ease-out-expo` | Efficient, invisible | Tab switches, dropdown open, tooltip |
| **Content reveals** | `emphasis` (400ms) | `ease-out-expo` | Smooth, confident | Card entrance, section fade-up, scroll reveal |
| **AI generation** | `emphasis` (400ms) + stagger | `ease-out-back` | Playful, building | Spec materializing, pre-flight checks popping |
| **Scorecard data** | `dramatic` (600ms) | `ease-out-quart` | Fast attack, precise | Bar fills, counter rolls, metric updates |
| **Verdict ceremony** | `ceremony` (900ms) | `ease-spring` | Gravity, deliberation | Icon spring, word reveal, the "moment" |
| **Error/alert** | `normal` enter / `fast` dismiss (250ms/150ms) | `ease-out-expo` | Quick, non-blocking | Error banner slide-in, toast appear/dismiss |
| **Hover/focus** | `instant`–`fast` (50–150ms) | `ease-out-expo` | Perceptually instant | Card lift, button color, focus ring |

**Rule:** The emotional weight of the interaction determines the duration. Verdicts are ceremonies (900ms). Button hovers are utilities (50ms). Nothing in between should feel like a ceremony, and no ceremony should feel like a utility.

---

## Design Principles Summary

| # | Principle | Rationale |
|---|-----------|-----------|
| 1 | One question per screen | Every screen answers exactly one question |
| 2 | The experiment is the hero | Not the dashboard. Dashboard is navigation, not destination |
| 3 | Show the process | AI working, data collecting, verdict forming -- all engagement moments |
| 4 | Celebrate clarity, even KILL | A KILL that saves 3 months is a victory |
| 5 | Portfolio thinking | Real value isn't one experiment -- it's comparing 3-5 in parallel |
| 6 | Ambient awareness | Users should know experiment status without opening the app |
| 7 | Scorecard is THE page | Not a tab inside a page. The primary information |
| 8 | Traffic is visible | Per-channel performance above the funnel. Users see where traffic comes from |
| 9 | Value before commitment | No signup to start. AI performs first. Free tier gives a real experiment |
| 10 | Automation is visible | Distribution loop must be seen, not hidden |
| 11 | Design for rain | Error states get equal design attention as happy paths |
| 12 | Ambient scorecard | Every notification contains a mini scorecard, not just a link |
| 13 | Spec is the control surface | Users control what to test, never how to build |
| 14 | Level-appropriate verification | L1 gets speed. L2/L3 get confidence. The flow adapts |
| 15 | Zero-code interaction | Users describe problems in words. AI translates to code changes |
| 16 | Mobile is a different context, not a smaller screen | Glance mode (status check) vs Work mode (deep analysis) require different information hierarchies |
| 17 | Animation serves cognition, not decoration | Every animation communicates spatial, temporal, or causal information — nothing is purely ornamental |
| 18 | Timing is personality | Consistent duration/easing vocabulary creates a coherent feel — the "Assayer signature" |

---

## Alignment with Product Design Doc

This UX design and `docs/assayer-product-design.md` are fully aligned. The product design doc is the technical specification for implementing this UX. Key implementation decisions:

| UX Concept | Technical Implementation |
|-----------|------------------------|
| Spec materializing on Assay page | `>>>EVENT:` text markers -> SSE stream -> `specReducer` progressive rendering |
| No signup to start | Anonymous spec via direct Anthropic API call (not Cloud Run), `anonymous_specs` table with 24h TTL |
| No follow-up questions on web | Inference mode: AI fills missing dimensions with `[inferred]` markers |
| Build preview + variant carousel | Local template preview during build, iframe after deploy |
| Content Check (L1) hot text update | Variant text stored in `variants` table; landing pages load content from API, not baked into static HTML |
| Quality Gate (L2/L3) | `/verify` skill with auto-fix loop (max 3 retries); behavior `tests[]` array drives test coverage |
| Walkthrough (L2/L3) | Golden_path steps from experiment.yaml rendered as interactive checklist; flagged issues trigger micro-`/change` |
| Change Request | Natural language -> AI impact analysis -> `/change` -> `/verify` -> redeploy; active experiments force new Round |
| Runtime auto-fix | Metrics sync cron detects anomalies (0.0x ratio with sufficient traffic) -> auto-diagnosis -> `/change` -> redeploy |
| Distribution approval gate | Cloud Run Job pauses -> polls Supabase -> user approves via web UI |
| Scorecard ratios | 15-minute Vercel Cron syncs PostHog + ad platforms -> `experiment_metric_snapshots` |
| Alert banners | `experiment_alerts` table, 7 alert types (incl. `bug_auto_fixed`), non-blocking |
| REFINE return flow | `experiment_rounds` table (same experiment, new round) |
| UPGRADE return flow (L1→L2→L3) | [Upgrade to L2] navigates to `/assay?...&level={L+1}&upgrade_from={id}`, `POST /api/spec/claim { upgrade_from }` sets `parent_experiment_id`, original marked `completed` (graduated) |
| Portfolio grouping | `experiments.status` with `verdict_ready` state between `active` and `completed` |
| Ambient notifications | `notifications` table, 7 triggers (incl. `bug_auto_fixed`), Resend emails with mini scorecards |
| Pricing plans | PAYG + subscription hybrid; `user_billing` table tracks plan, pool counters, PAYG balance; `operation_ledger` gates every billable execution; overage at PAYG rates |
| Plan-gated channels | `distribution_campaigns` creation checks user plan; paid channels require Pro+ |
| Bottom tab bar (mobile) | `MobileTabBar` component, auth-conditional rendering in `layout.tsx` |
| Scrollable tab strips (mobile) | `ScrollableTabStrip` component for mobile tab navigation |
| Timing tokens | CSS custom properties (`--dur-*`, `--ease-*`) defined in `globals.css` `:root` |
| Reduced motion | `@media (prefers-reduced-motion: reduce)` in CSS + JS `matchMedia` check in `useRevealOnScroll` |
| Scorecard bar fill animation | `transform: scaleX()` choreography (GPU-composited), never `width` animation |

When this UX design and the product design doc conflict, this document wins.
